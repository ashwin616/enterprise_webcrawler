# """
# scheduler.py  —  Automatic crawl scheduler
# ───────────────────────────────────────────
# Stores crawl jobs in PostgreSQL (crawlerdb.crawl_jobs).
# Checks every SCHEDULER_INTERVAL_MINUTES for due jobs and triggers crawler.

# Endpoints:
#   POST /jobs                   → add a URL with schedule frequency
#   GET  /jobs                   → list all jobs + next run time
#   GET  /jobs/{id}              → get one job
#   PUT  /jobs/{id}              → update label or frequency
#   DELETE /jobs/{id}            → remove a job
#   POST /jobs/{id}/run          → trigger immediate crawl (non-blocking)
#   GET  /health                 → scheduler status + due job count

# Frequency options (from ScheduleFrequency enum):
#   manual | 10m | 30m | 1h | 3h | 6h | 10h | 1d

# Usage:
#   python scheduler.py
#   or:
#   uvicorn scheduler:app --host 0.0.0.0 --port 8001 --reload
# """
# from __future__ import annotations

# import subprocess
# import sys
# import threading
# from pathlib import Path
# from typing import Optional

# from apscheduler.schedulers.background import BackgroundScheduler
# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel

# # Project root on path so config/settings resolves
# sys.path.insert(0, str(Path(__file__).parent))

# from app.models.schemas import ScheduleFrequency
# from app.services.database import (
#     init_schema,
#     job_create, job_get, job_list,
#     job_update, job_delete,
#     job_set_running, job_set_done, job_set_error,
#     job_get_due,
# )
# from app.utils.logger import get_logger
# from config.settings import settings

# log = get_logger(__name__)

# # Path to crawler_service.py
# CRAWLER_SCRIPT = Path(__file__).parent / "app" / "services" / "crawler_service.py"

# # How often the scheduler checks for due jobs
# SCHEDULER_INTERVAL_MINUTES = 1


# # ── Crawl trigger ─────────────────────────────────────────────────────────

# def _trigger_crawl(job_id: int, url: str, max_depth: int = 3, max_url: int = None):

#     """
#     Launch crawler_service.py as a subprocess.
#     URL is piped to stdin (matches the if __name__ == '__main__' block).
#     Runs synchronously — call from a thread for non-blocking behaviour.
#     """
#     log.info(f"Triggering crawl — job_id={job_id} url={url} max_depth={max_depth} max_url={max_url or 'auto'}")

#     job_set_running(job_id)
#     try:
#         input_data = f"{url}\n{job_id}\n{max_depth}\n{max_url or ''}\n"  # ← updated

#         result = subprocess.run(
#             [sys.executable, str(CRAWLER_SCRIPT)],
#             input=url,
#             capture_output=True,
#             text=True,
#             timeout=600,          # 10 min max per crawl
#         )
#         if result.returncode == 0:
#             log.info(f"Crawl done — job_id={job_id}")
#             log.debug(f"crawler stdout:\n{result.stdout[-2000:]}")
#             job_set_done(job_id)
#         else:
#             err = (result.stderr or "non-zero exit")[-500:]
#             log.error(f"Crawl failed — job_id={job_id}: {err}")
#             job_set_error(job_id, err)
#     except subprocess.TimeoutExpired:
#         log.error(f"Crawl timeout — job_id={job_id}")
#         job_set_error(job_id, "timeout after 600s")
#     except Exception as e:
#         log.error(f"Crawl exception — job_id={job_id}: {e}", exc_info=True)
#         job_set_error(job_id, str(e))


# # def _trigger_crawl_async(job_id: int, url: str):
# #     """Run crawl in a background thread so the API call returns immediately."""
# #     t = threading.Thread(target=_trigger_crawl, args=(job_id, url), daemon=True)
# #     t.start()

# def _trigger_crawl_async(job_id: int, url: str, max_depth: int = 3, max_url: int = None):
#     t = threading.Thread(
#         target=_trigger_crawl,
#         args=(job_id, url, max_depth, max_url),  # ← updated
#         daemon=True,
#     )
#     t.start()


# # ── Scheduler tick ────────────────────────────────────────────────────────

# def scheduler_tick():
#     """
#     Called every SCHEDULER_INTERVAL_MINUTES.
#     Finds all jobs where next_crawl_at <= NOW() and triggers them.
#     """
#     log.debug("Scheduler tick — checking for due jobs...")
#     due = job_get_due()
#     if not due:
#         return

#     log.info(f"Found {len(due)} due job(s)")
#     for job in due:
#         log.info(
#             f"  Running job id={job['id']} "
#             f"url={job['url']} "
#             f"frequency={job['frequency']}m "
#             f"run_count={job['run_count']}"
#         )
#         # _trigger_crawl(job["id"], job["url"])
#         _trigger_crawl(
#                 job["id"], job["url"],
#                 max_depth=job.get("max_depth", 3),
#                 max_url=job.get("max_url"),
#             )   # sequential — one at a time


# # ── FastAPI ───────────────────────────────────────────────────────────────

# app = FastAPI(
#     title="Crawl Scheduler API",
#     description="Schedule URLs for automatic recurring crawls",
#     version="1.0.0",
#     docs_url="/docs",
#     redoc_url="/redoc",
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# _scheduler = BackgroundScheduler()


# @app.on_event("startup")
# def startup():
#     log.info("─" * 60)
#     log.info("  Scheduler API starting")
#     log.info("─" * 60)

#     # Ensure crawl_jobs table exists
#     init_schema()

#     # Register periodic tick
#     _scheduler.add_job(
#         scheduler_tick,
#         trigger="interval",
#         minutes=SCHEDULER_INTERVAL_MINUTES,
#         id="crawl_tick",
#         max_instances=1,       # never overlap ticks
#         replace_existing=True,
#     )
#     _scheduler.start()
#     log.info(f"Scheduler running — checking every {SCHEDULER_INTERVAL_MINUTES} minute(s)")

#     # Run once on startup to catch any overdue jobs immediately
#     scheduler_tick()


# @app.on_event("shutdown")
# def shutdown():
#     _scheduler.shutdown(wait=False)
#     log.info("Scheduler stopped")


# # ── Request / Response models ─────────────────────────────────────────────

# class JobCreate(BaseModel):
#     url:       str
#     label:     Optional[str]               = ""
#     frequency: Optional[ScheduleFrequency] = ScheduleFrequency.MANUAL
#     max_depth: Optional[int]               = 3    
#     max_url:   Optional[int]               = None 

#     class Config:
#         use_enum_values = False


# class JobUpdate(BaseModel):
#     label:     Optional[str]               = None
#     frequency: Optional[ScheduleFrequency] = None
#     max_url:   Optional[int]               = None

# # ── Endpoints ─────────────────────────────────────────────────────────────

# @app.post("/jobs", status_code=201)
# def create_job(req: JobCreate):
#     """
#     Add a URL to the crawl schedule.

#     frequency values: manual | 10m | 30m | 1h | 3h | 6h | 10h | 1d
#     """
#     url = req.url.strip()
#     if not url.startswith("http"):
#         url = "https://" + url

#     freq_minutes = req.frequency.to_minutes() if req.frequency else 0
#     job = job_create(
#         url=url,
#         label=req.label or "",
#         frequency=freq_minutes,
#         max_depth=req.max_depth or 3,  
#         max_url=req.max_url, )

#     log.info(f"Job created id={job['id']} freq={freq_minutes}m url={url}")

#     # Trigger immediately on creation
#     # _trigger_crawl_async(job["id"], url)
#     _trigger_crawl_async(job["id"], url, max_depth=req.max_depth or 3, max_url=req.max_url)

#     return {
#         "message":   "Job created and crawl started",
#         "job":       job,
#         "frequency": req.frequency.value if req.frequency else "manual",
#     }


# @app.get("/jobs")
# def list_jobs():
#     """List all crawl jobs with status and next scheduled run."""
#     return {"jobs": job_list()}


# @app.get("/jobs/{job_id}")
# def get_job(job_id: int):
#     """Get a specific job by ID."""
#     job = job_get(job_id)
#     if not job:
#         raise HTTPException(404, "Job not found")
#     return job


# @app.put("/jobs/{job_id}")
# def update_job(job_id: int, req: JobUpdate):
#     """Update a job's label or frequency."""
#     freq = req.frequency.to_minutes() if req.frequency else None
#     job  = job_update(job_id, label=req.label, frequency=freq)
#     if not job:
#         raise HTTPException(404, "Job not found")
#     log.info(f"Job updated id={job_id}")
#     return {"message": "Job updated", "job": job}


# @app.delete("/jobs/{job_id}")
# def delete_job(job_id: int):
#     """Delete a job from the schedule."""
#     if not job_delete(job_id):
#         raise HTTPException(404, "Job not found")
#     log.info(f"Job deleted id={job_id}")
#     return {"message": f"Job {job_id} deleted"}


# @app.post("/jobs/{job_id}/run")
# def run_job_now(job_id: int):
#     """Trigger an immediate crawl outside the normal schedule."""
#     job = job_get(job_id)
#     if not job:
#         raise HTTPException(404, "Job not found")
#     if job["status"] == "running":
#         raise HTTPException(409, "Job is already running")

#     _trigger_crawl_async(job_id, job["url"])
#     log.info(f"Immediate crawl triggered job_id={job_id}")
#     return {"message": f"Crawl triggered for job {job_id}", "url": job["url"]}


# @app.get("/health")
# def health():
#     """Scheduler health — returns running state and count of due jobs."""
#     due_count = len(job_get_due())
#     return {
#         "status":            "ok",
#         "service":           "scheduler",
#         "env":               settings.app_env,
#         "scheduler_running": _scheduler.running,
#         "check_interval_m":  SCHEDULER_INTERVAL_MINUTES,
#         "due_jobs":          due_count,
#     }


# # ── Entry point ───────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     import uvicorn
#     log.info(f"Scheduler API  port={settings.scheduler_api_port}")
#     log.info(f"Crawler script: {CRAWLER_SCRIPT}")
#     uvicorn.run(
#         "scheduler:app",
#         host=settings.app_host,
#         port=settings.scheduler_api_port,
#         reload=settings.app_env == "development",
#     )

"""
scheduler.py  —  Automatic crawl scheduler
───────────────────────────────────────────
Stores crawl jobs in PostgreSQL (crawlerdb.crawl_jobs).
Checks every SCHEDULER_INTERVAL_MINUTES for due jobs and triggers crawler.

Endpoints:
  POST /jobs                   → add a URL with schedule frequency
  GET  /jobs                   → list all jobs + next run time
  GET  /jobs/{id}              → get one job
  PUT  /jobs/{id}              → update label or frequency
  DELETE /jobs/{id}            → remove a job
  POST /jobs/{id}/run          → trigger immediate crawl (non-blocking)
  GET  /health                 → scheduler status + due job count

Frequency options (from ScheduleFrequency enum):
  manual | 10m | 30m | 1h | 3h | 6h | 10h | 1d

Usage:
  python scheduler.py
  or:
  uvicorn scheduler:app --host 0.0.0.0 --port 8001 --reload
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Project root on path so config/settings resolves
sys.path.insert(0, str(Path(__file__).parent))

from app.models.schemas import ScheduleFrequency
from app.services.database import (
    init_schema,
    job_create, job_get, job_list,
    job_update, job_delete,
    job_set_running, job_set_done, job_set_error,
    job_get_due,
)
from app.utils.logger import get_logger
from config.settings import settings

log = get_logger(__name__)

# Path to crawler_service.py
CRAWLER_SCRIPT = Path(__file__).parent / "app" / "services" / "crawler_service.py"

# How often the scheduler checks for due jobs
SCHEDULER_INTERVAL_MINUTES = 1


# ── Crawl trigger ─────────────────────────────────────────────────────────

def _trigger_crawl(job_id: int, url: str, max_depth: int = 3, max_url: int = None):
    """
    Launch crawler_service.py as a subprocess.
    4 lines piped to stdin match crawler_service.py __main__ readline order:
      line 1: url
      line 2: job_id
      line 3: max_depth
      line 4: max_url (empty string = auto-determine from sitemap)
    Runs synchronously — call from a thread for non-blocking behaviour.
    """
    log.info(
        f"Triggering crawl — job_id={job_id} url={url} "
        f"max_depth={max_depth} max_url={max_url or 'auto'}"
    )
    job_set_running(job_id)

    # Build stdin — 4 lines matching crawler_service.py __main__ readline order
    # input_data = "\n".join([
    #     url,
    #     str(job_id),
    #     str(max_depth),
    #     str(max_url) if max_url is not None else "",
    # ]) + "\n"

    input_data = "\n".join([
    url,
    str(job_id),
    str(max_depth),
    str(max_url) if max_url is not None and max_url > 0 else "",]) + "\n"

    try:
        result = subprocess.run(
            [sys.executable, str(CRAWLER_SCRIPT)],
            input=input_data,          # ← was `input=url` (bug — only sent url)
            capture_output=True,
            text=True,
            timeout=600,               # 10 min max per crawl
        )
        if result.returncode == 0:
            log.info(f"Crawl done — job_id={job_id}")
            log.debug(f"crawler stdout:\n{result.stdout[-2000:]}")
            job_set_done(job_id)
        else:
            err = (result.stderr or "non-zero exit")[-500:]
            log.error(f"Crawl failed — job_id={job_id}: {err}")
            job_set_error(job_id, err)
    except subprocess.TimeoutExpired:
        log.error(f"Crawl timeout — job_id={job_id}")
        job_set_error(job_id, "timeout after 600s")
    except Exception as e:
        log.error(f"Crawl exception — job_id={job_id}: {e}", exc_info=True)
        job_set_error(job_id, str(e))


def _trigger_crawl_async(job_id: int, url: str, max_depth: int = 3, max_url: int = None):
    """Run crawl in a background thread so the API call returns immediately."""
    t = threading.Thread(
        target=_trigger_crawl,
        args=(job_id, url, max_depth, max_url),
        daemon=True,
    )
    t.start()


# ── Scheduler tick ────────────────────────────────────────────────────────

def scheduler_tick():
    """
    Called every SCHEDULER_INTERVAL_MINUTES.
    Finds all jobs where next_crawl_at <= NOW() and triggers them.
    """
    log.debug("Scheduler tick — checking for due jobs...")
    due = job_get_due()
    if not due:
        return

    log.info(f"Found {len(due)} due job(s)")
    for job in due:
        log.info(
            f"  Running job id={job['id']} "
            f"url={job['url']} "
            f"frequency={job['frequency']}m "
            f"run_count={job['run_count']}"
        )
        _trigger_crawl(
            job["id"],
            job["url"],
            max_depth=job.get("max_depth", 3),
            max_url=job.get("max_url"),
        )   # sequential — one at a time


# ── FastAPI ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Crawl Scheduler API",
    description="Schedule URLs for automatic recurring crawls",
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

_scheduler = BackgroundScheduler()


@app.on_event("startup")
def startup():
    log.info("─" * 60)
    log.info("  Scheduler API starting")
    log.info("─" * 60)

    # Ensure crawl_jobs table exists
    init_schema()

    # Register periodic tick
    _scheduler.add_job(
        scheduler_tick,
        trigger="interval",
        minutes=SCHEDULER_INTERVAL_MINUTES,
        id="crawl_tick",
        max_instances=1,        # never overlap ticks
        replace_existing=True,
    )
    _scheduler.start()
    log.info(f"Scheduler running — checking every {SCHEDULER_INTERVAL_MINUTES} minute(s)")

    # Run once on startup to catch any overdue jobs immediately
    scheduler_tick()


@app.on_event("shutdown")
def shutdown():
    _scheduler.shutdown(wait=False)
    log.info("Scheduler stopped")


# ── Request / Response models ─────────────────────────────────────────────

class JobCreate(BaseModel):
    url:       str
    label:     Optional[str]               = ""
    frequency: Optional[ScheduleFrequency] = ScheduleFrequency.MANUAL
    max_depth: Optional[int]               = 3
    max_url:   Optional[int]               = None   # None = auto (sitemap length or 99999)

    class Config:
        use_enum_values = False


class JobUpdate(BaseModel):
    label:     Optional[str]               = None
    frequency: Optional[ScheduleFrequency] = None
    max_url:   Optional[int]               = None


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.post("/jobs", status_code=201)
def create_job(req: JobCreate):
    """
    Add a URL to the crawl schedule.

    frequency values: manual | 10m | 30m | 1h | 3h | 6h | 10h | 1d
    max_depth: how many link-hops deep to crawl (default 3)
    max_url: max pages to crawl (default: auto from sitemap length, or 99999)
    """
    url = req.url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    freq_minutes = req.frequency.to_minutes() if req.frequency else 0
    # job = job_create(
    #     url=url,
    #     label=req.label or "",
    #     frequency=freq_minutes,
    #     max_depth=req.max_depth or 3,
    #     max_url=req.max_url,
    # )
    job = job_create(
    url=url,
    label=req.label or "",
    frequency=freq_minutes,
    max_depth=req.max_depth or 3,
    max_url=req.max_url if req.max_url and req.max_url > 0 else None,)

    log.info(
        f"Job created id={job['id']} freq={freq_minutes}m url={url} "
        f"max_depth={req.max_depth} max_url={req.max_url}"
    )

    # Trigger immediately on creation
    _trigger_crawl_async(
        job["id"], url,
        max_depth=req.max_depth or 3,
        max_url=req.max_url,
    )

    return {
        "message":   "Job created and crawl started",
        "job":       job,
        "frequency": req.frequency.value if req.frequency else "manual",
    }


@app.get("/jobs")
def list_jobs():
    """List all crawl jobs with status and next scheduled run."""
    return {"jobs": job_list()}


@app.get("/jobs/{job_id}")
def get_job(job_id: int):
    """Get a specific job by ID."""
    job = job_get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.put("/jobs/{job_id}")
def update_job(job_id: int, req: JobUpdate):
    """Update a job's label, frequency or max_url."""
    freq = req.frequency.to_minutes() if req.frequency else None
    job  = job_update(job_id, label=req.label, frequency=freq, max_url=req.max_url)
    if not job:
        raise HTTPException(404, "Job not found")
    log.info(f"Job updated id={job_id}")
    return {"message": "Job updated", "job": job}


@app.delete("/jobs/{job_id}")
def delete_job(job_id: int):
    """Delete a job from the schedule."""
    if not job_delete(job_id):
        raise HTTPException(404, "Job not found")
    log.info(f"Job deleted id={job_id}")
    return {"message": f"Job {job_id} deleted"}


@app.post("/jobs/{job_id}/run")
def run_job_now(job_id: int):
    """Trigger an immediate crawl outside the normal schedule."""
    job = job_get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] == "running":
        raise HTTPException(409, "Job is already running")

    _trigger_crawl_async(
        job_id,
        job["url"],
        max_depth=job.get("max_depth", 3),
        max_url=job.get("max_url"),
    )
    log.info(f"Immediate crawl triggered job_id={job_id}")
    return {"message": f"Crawl triggered for job {job_id}", "url": job["url"]}


@app.get("/health")
def health():
    """Scheduler health — returns running state and count of due jobs."""
    due_count = len(job_get_due())
    return {
        "status":            "ok",
        "service":           "scheduler",
        "env":               settings.app_env,
        "scheduler_running": _scheduler.running,
        "check_interval_m":  SCHEDULER_INTERVAL_MINUTES,
        "due_jobs":          due_count,
    }


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    log.info(f"Scheduler API  port={settings.scheduler_api_port}")
    log.info(f"Crawler script: {CRAWLER_SCRIPT}")
    uvicorn.run(
        "scheduler:app",
        host=settings.app_host,
        port=settings.scheduler_api_port,
        reload=settings.app_env == "development",
    )