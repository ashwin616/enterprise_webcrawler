
"""
app/api/crawler_api.py
───────────────────────
Crawler FastAPI — production grade.

Endpoints:
  POST /crawl/url          → submit URL with schedule
  POST /crawl/file         → upload PDF/DOCX directly
  GET  /crawl/jobs         → list all jobs
  GET  /crawl/jobs/{id}    → get one job
  PUT  /crawl/jobs/{id}    → update label / frequency
  DELETE /crawl/jobs/{id}  → delete job
  POST /crawl/jobs/{id}/run → trigger immediate crawl
  GET  /crawl/frequencies  → list available schedule options
  GET  /health             → health check
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import (
    APIRouter, BackgroundTasks, FastAPI,
    HTTPException, UploadFile, File, Form
)
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from app.models.schemas import (
    CrawlJobCreate, CrawlJobUpdate, CrawlJobResponse,
    FileUploadResponse, HealthResponse, MessageResponse,
    ScheduleFrequency,
)
from app.services import database as db
from app.services.database import get_cursor

from app.services.kafka_producer import publish_attachment, flush
from app.utils.logger import get_logger
from config.settings import settings

log = get_logger(__name__)

# ── FastAPI app ───────────────────────────────────────────────────────────

app = FastAPI(
    title="Web Crawler API",
    description="Crawl URLs and upload files into the RAG pipeline",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(prefix="/crawl", tags=["Crawler"])

OUTPUT_DIR = Path(settings.crawler_output_dir)
OUTPUT_DIR.mkdir(exist_ok=True)

# CRAWLER_SCRIPT = Path(__file__).parent.parent.parent / "services" / "crawler_service.py"
# CRAWLER_SCRIPT = Path(__file__).parent.parent.parent / "app" / "services" / "crawler_service.py"
CRAWLER_SCRIPT = Path(__file__).parent.parent / "services" / "crawler_service.py"




# Allowed upload extensions
ALLOWED_UPLOAD_EXTS = {".pdf", ".doc", ".docx", ".txt", ".csv", ".xlsx", ".pptx"}


# ── Helpers ───────────────────────────────────────────────────────────────

# def _trigger_crawl(job_id: int, url: str):
# def _trigger_crawl(job_id: int, url: str, max_depth: int = 3):
def _trigger_crawl(job_id: int, url: str, max_depth: int = 3, max_url: int = None):


    """Run crawler_service.py as subprocess, pipe URL to stdin.
    stdout/stderr are streamed live so crawler logs appear in real-time.
    """
    log.info(f"Triggering crawl job_id={job_id} url={url}")
    db.job_set_running(job_id)
    stderr_lines: list[str] = []

    # Prefixes crawl4ai writes to stderr that are actually just progress/info
    _INFO_PREFIXES = (
        "[FETCH]", "[SCRAPE]", "[COMPLETE]",
        "[green]", "[yellow]", "[red]",
        "INFO ", "DEBUG ",
    )
    _WARN_PREFIXES = ("WARNING ", "WARN ")

    def _stream(pipe, is_stderr: bool):
        """Read lines from pipe and forward them to the logger in real-time.

        crawl4ai writes ALL its output (progress bars, INFO, errors) to stderr.
        We parse each line's severity instead of blindly marking everything ERROR.
        """
        for raw in iter(pipe.readline, ""):
            line = raw.rstrip("\n")
            if not line:
                continue
            if is_stderr:
                stripped = line.lstrip()
                # Real errors — only collect these for the failure summary
                if "ERROR" in stripped or "Traceback" in stripped or "Exception" in stripped:
                    stderr_lines.append(line)
                    log.error(f"[crawler] {line}")
                elif stripped.startswith(_WARN_PREFIXES) or "UserWarning" in stripped:
                    log.warning(f"[crawler] {line}")
                else:
                    # Everything else from crawl4ai stderr is normal progress output
                    log.info(f"[crawler] {line}")
            else:
                log.info(f"[crawler] {line}")
        pipe.close()

    try:
        import os
        crawler_env = os.environ.copy()
        # Force UTF-8 everywhere so rich/crawl4ai can print unicode arrows/symbols
        # without hitting Windows cp1252 UnicodeEncodeError in the pipe
        crawler_env["PYTHONIOENCODING"] = "utf-8"
        crawler_env["PYTHONUTF8"] = "1"          # Python 3.7+ UTF-8 mode
        crawler_env["CRAWL4AI_VERBOSE"] = "false"

        proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", str(CRAWLER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",   # read subprocess output as UTF-8
            errors="replace",   # replace undecodable bytes instead of crashing
            bufsize=1,
            env=crawler_env,
        )

        # Write URL/job_id/max_depth to stdin then close it
        # proc.stdin.write(f"{url}\n{job_id}\n{max_depth}\n")
        proc.stdin.write(
        f"{url}\n"
        f"{job_id}\n"
        f"{max_depth}\n"
        f"{max_url if max_url is not None else ''}\n")
        proc.stdin.flush()
        proc.stdin.close()

        # Stream stdout and stderr concurrently in background threads
        t_out = threading.Thread(target=_stream, args=(proc.stdout, False), daemon=True)
        t_err = threading.Thread(target=_stream, args=(proc.stderr, True),  daemon=True)
        t_out.start()
        t_err.start()

        # Wait with timeout — 1 hour. With max_pages up to 500 and 3
        # concurrent workers, large sites (or sites with several pages
        # that each eat the full 30s page_timeout due to anti-bot
        # blocks) can take well over 10 minutes. Pages are published to
        # Kafka / saved to disk incrementally as each completes, so even
        # if this timeout is hit, already-processed pages are not lost.
        try:
            proc.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            proc.kill()
            db.job_set_error(job_id, "timeout after 3600s")
            return

        t_out.join()
        t_err.join()

        if proc.returncode == 0:
            log.info(f"Crawl done job_id={job_id}")
            db.job_set_done(job_id)
        else:
            err = "\n".join(stderr_lines[-20:]) or "non-zero exit"
            log.error(f"Crawl failed job_id={job_id}: {err[-500:]}")
            db.job_set_error(job_id, err[-500:])

    except Exception as e:
        db.job_set_error(job_id, str(e))
        log.error(f"Crawl exception job_id={job_id}: {e}", exc_info=True)


# ── Schedule options endpoint ─────────────────────────────────────────────

@router.get("/frequencies")
def get_frequencies():
    """List all available schedule frequency options."""
    return {
        "frequencies": [
            {"value": f.value, "label": _freq_label(f), "minutes": f.to_minutes()}
            for f in ScheduleFrequency
        ]
    }


def _freq_label(f: ScheduleFrequency) -> str:
    return {
        ScheduleFrequency.MANUAL:   "Manual only",
        ScheduleFrequency.TEN_MIN:  "Every 10 minutes",
        ScheduleFrequency.THIRTY:   "Every 30 minutes",
        ScheduleFrequency.ONE_HR:   "Every 1 hour",
        ScheduleFrequency.THREE_HR: "Every 3 hours",
        ScheduleFrequency.SIX_HR:   "Every 6 hours",
        ScheduleFrequency.TEN_HR:   "Every 10 hours",
        ScheduleFrequency.ONE_DAY:  "Every 24 hours",
    }[f]


# ── URL crawl endpoint ────────────────────────────────────────────────────

@router.post("/url", status_code=202)
def crawl_url(req: CrawlJobCreate, background_tasks: BackgroundTasks):
    """
    Submit a URL to crawl.

    - url       : page to crawl (http/https)
    - label     : friendly name for this job
    - frequency : schedule — manual | 10m | 30m | 1h | 3h | 6h | 10h | 1d
    """
    freq_minutes = req.frequency.to_minutes() if req.frequency else 0
    job = db.job_create(
        url=req.url,
        label=req.label or "",
        frequency=freq_minutes,
        max_depth=req.max_depth or 3,  
        max_url=req.max_url,            
    )
    # background_tasks.add_task(_trigger_crawl, job["id"], req.url)
    background_tasks.add_task(_trigger_crawl, job["id"], req.url, req.max_depth, req.max_url,)

    # log.info(f"URL job created id={job['id']} freq={req.frequency}")
    log.info(f"URL job created id={job['id']} freq={req.frequency} "
             f"max_depth={req.max_depth} max_url={req.max_url}")
    return {
        "message":   "Crawl job accepted",
        "job_id":    job["id"],
        "url":       req.url,
        "frequency": req.frequency,
        "status":    "running",
    }


# ── File upload endpoint ──────────────────────────────────────────────────

@router.post("/file", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(..., description="PDF, DOCX, TXT, CSV, XLSX, PPTX"),
    label: Optional[str] = Form(default=""),
):
    """
    Upload a file directly into the pipeline.
    File is saved to crawl_output/ and published to Kafka for the consumer to parse.
    """
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{suffix}' not supported. Allowed: {', '.join(ALLOWED_UPLOAD_EXTS)}",
        )

    # Save file
    safe_name = Path(file.filename).stem[:60].replace(" ", "_")
    out_path  = OUTPUT_DIR / f"{safe_name}{suffix}"
    with open(out_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    size_kb = out_path.stat().st_size // 1024
    log.info(f"File uploaded: {out_path.name} ({size_kb} KB)")

    # Create a job record for tracking
    source_url = f"file://upload/{file.filename}"
    job = db.job_create(url=source_url, label=label or file.filename, frequency=0)
    db.job_set_running(job["id"])

    # Publish to Kafka — consumer will parse and chunk it
    publish_attachment(
        file_path=out_path,
        source_url=source_url,
        file_type=suffix,
        job_id=job["id"],
    )
    flush()
    db.job_set_done(job["id"])

    return FileUploadResponse(
        filename=file.filename,
        saved_path=str(out_path.resolve()),
        size_kb=size_kb,
        message=f"File uploaded and queued for processing (job_id={job['id']})",
    )


# ── Job management endpoints ──────────────────────────────────────────────

@router.get("/jobs")
def list_jobs():
    """List all crawl jobs."""
    return {"jobs": db.job_list()}


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    """Get a specific job by ID."""
    job = db.job_get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.put("/jobs/{job_id}")
def update_job(job_id: int, req: CrawlJobUpdate):
    """Update a job's label or frequency."""
    freq = req.frequency.to_minutes() if req.frequency else None
    job  = db.job_update(job_id, label=req.label, frequency=freq)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"message": "Job updated", "job": job}


@router.delete("/jobs/{job_id}", response_model=MessageResponse)
def delete_job(job_id: int):
    """Delete a job."""
    if not db.job_delete(job_id):
        raise HTTPException(404, "Job not found")
    return MessageResponse(message=f"Job {job_id} deleted")



#reseting the table############
# @app.delete("/admin/reset-db", tags=["admin"])
# def reset_database():
#     """Wipe all data for a fresh demo start."""
#     with get_cursor() as cur:
#         cur.execute("""
#             TRUNCATE TABLE chunks     RESTART IDENTITY CASCADE;
#             TRUNCATE TABLE raw_pages  RESTART IDENTITY CASCADE;
#             TRUNCATE TABLE crawl_jobs RESTART IDENTITY CASCADE;
#         """)
#     return {"status": "ok", "message": "Database reset successfully"}

@app.delete("/admin/reset-db", tags=["admin"])
def reset_database():
    """
    Wipe ALL data across every table for a fresh demo start.
    Resets sequences (auto-increment IDs) back to 1.
    Order matters — child tables truncated before parents to avoid FK conflicts.
    """
    with get_cursor() as cur:
        cur.execute("""
            TRUNCATE TABLE
                content_validations,
                images,
                attachments,
                crawl_urls,
                chunks,
                raw_pages,
                crawl_jobs
            RESTART IDENTITY CASCADE;
        """)
    return {
        "status":  "ok",
        "message": "All tables cleared — database reset successfully",
        "tables_cleared": [
            "content_validations",
            "images",
            "attachments",
            "crawl_urls",
            "chunks",
            "raw_pages",
            "crawl_jobs",
        ],
    }

@router.post("/jobs/{job_id}/run")
def run_job_now(job_id: int):
    """Trigger an immediate crawl for an existing job."""
    job = db.job_get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] == "running":
        raise HTTPException(409, "Job is already running")
    t = threading.Thread(
        target=_trigger_crawl, args=(job_id, job["url"]), daemon=True
    )
    t.start()
    return {"message": f"Crawl triggered for job {job_id}", "url": job["url"]}



# ── Health ────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
def health():
    return HealthResponse(
        status="ok", service="crawler-api", env=settings.app_env
    )


# ── Mount router ──────────────────────────────────────────────────────────

app.include_router(router)


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    db.init_schema()
    log.info(f"Crawler API starting on port {settings.crawler_api_port}")
    uvicorn.run(
        "app.api.crawler_api:app",
        host=settings.app_host,
        port=settings.crawler_api_port,
        reload=settings.app_env == "development",
    )