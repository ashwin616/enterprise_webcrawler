
# """
# app/services/database.py
# ─────────────────────────
# All PostgreSQL operations.
# Import: from app.services.database import db
# """
# from __future__ import annotations
# import psycopg2
# import psycopg2.extras
# from contextlib import contextmanager
# from config.settings import settings
# from app.utils.logger import get_logger

# log = get_logger(__name__)


# @contextmanager
# def get_cursor(cursor_factory=psycopg2.extras.RealDictCursor):
#     conn = psycopg2.connect(settings.pg_dsn)
#     try:
#         with conn.cursor(cursor_factory=cursor_factory) as cur:
#             yield cur
#         conn.commit()
#     except Exception:
#         conn.rollback()
#         raise
#     finally:
#         conn.close()


# def init_schema():
#     """Create all tables. Safe to run on every startup."""
#     sql = """    
#     CREATE TABLE IF NOT EXISTS content_validations (
#         id              SERIAL PRIMARY KEY,
#         job_id          INTEGER REFERENCES crawl_jobs(id) ON DELETE CASCADE,
#         url             TEXT NOT NULL,
#         skipped         BOOLEAN DEFAULT FALSE,
#         skip_reason     TEXT,
#         overall_score   FLOAT,
#         loss_clean      FLOAT,        -- % lost raw→cleaned
#         loss_markdown   FLOAT,        -- % lost raw→markdown (end-to-end)
#         loss_stage2     FLOAT,        -- % lost cleaned→markdown
#         status          TEXT,         -- consistent | partial | inconsistent
#         char_raw        INTEGER,
#         char_clean      INTEGER,
#         char_md         INTEGER,
#         conflicts       JSONB DEFAULT '[]',
#         lost_in_cleaning JSONB DEFAULT '[]',
#         lost_in_markdown JSONB DEFAULT '[]',
#         recovered_in_md  JSONB DEFAULT '[]',
#         validated_at    TIMESTAMPTZ DEFAULT NOW()
#     );

#     CREATE INDEX IF NOT EXISTS validations_job_idx    ON content_validations(job_id);
#     CREATE INDEX IF NOT EXISTS validations_status_idx ON content_validations(status);

#     CREATE EXTENSION IF NOT EXISTS vector;

#     CREATE TABLE IF NOT EXISTS crawl_jobs (
#         id              SERIAL PRIMARY KEY,
#         url             TEXT NOT NULL,
#         label           TEXT DEFAULT '',
#         frequency       INTEGER DEFAULT 0,
#         max_depth       INTEGER DEFAULT 3,
#         max_pages       INTEGER DEFAULT NULL,
#         status          TEXT DEFAULT 'pending',
#         last_crawled_at TIMESTAMPTZ,
#         next_crawl_at   TIMESTAMPTZ,
#         created_at      TIMESTAMPTZ DEFAULT NOW(),
#         run_count       INTEGER DEFAULT 0,
#         last_error      TEXT
#     );

#     CREATE TABLE IF NOT EXISTS raw_pages (
#         id           SERIAL PRIMARY KEY,
#         job_id       INTEGER REFERENCES crawl_jobs(id) ON DELETE SET NULL,
#         url          TEXT NOT NULL,
#         title        TEXT,
#         content_type TEXT DEFAULT 'html',
#         raw_content  TEXT,
#         fetched_at   TIMESTAMPTZ DEFAULT NOW(),
#         UNIQUE (job_id, url, content_type)
#     );

#     CREATE TABLE IF NOT EXISTS chunks (
#         id          SERIAL PRIMARY KEY,
#         page_id     INTEGER REFERENCES raw_pages(id) ON DELETE CASCADE,
#         chunk_index INTEGER,
#         content     TEXT NOT NULL,
#         token_count INTEGER,
#         embedding   vector(384),
#         metadata    JSONB DEFAULT '{}',
#         created_at  TIMESTAMPTZ DEFAULT NOW()
#     );

#     CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);

#     CREATE INDEX IF NOT EXISTS chunks_page_id_idx ON chunks(page_id);
#     CREATE INDEX IF NOT EXISTS raw_pages_url_idx  ON raw_pages(url);
#     CREATE INDEX IF NOT EXISTS crawl_jobs_status_idx ON crawl_jobs(status);

#     -- ── Sitemap URL tracking — every URL discovered for a job, with status ──
#     CREATE TABLE IF NOT EXISTS crawl_urls (
#         id          SERIAL PRIMARY KEY,
#         job_id      INTEGER REFERENCES crawl_jobs(id) ON DELETE CASCADE,
#         url         TEXT NOT NULL,
#         source      TEXT DEFAULT 'sitemap',   -- 'sitemap' | 'seed'
#         status      TEXT DEFAULT 'pending',   -- pending | scraped | failed
#         fail_reason TEXT,
#         page_id     INTEGER REFERENCES raw_pages(id) ON DELETE SET NULL,
#         local_path  TEXT,                     -- folder on disk for this page
#         scraped_at  TIMESTAMPTZ,
#         created_at  TIMESTAMPTZ DEFAULT NOW(),
#         UNIQUE (job_id, url)
#     );

#     CREATE INDEX IF NOT EXISTS crawl_urls_job_idx    ON crawl_urls(job_id);
#     CREATE INDEX IF NOT EXISTS crawl_urls_status_idx ON crawl_urls(job_id, status);

#     -- ── Downloaded attachments (PDF/DOC/XLSX/...) ──────────────────────────
#     CREATE TABLE IF NOT EXISTS attachments (
#         id          SERIAL PRIMARY KEY,
#         job_id      INTEGER REFERENCES crawl_jobs(id) ON DELETE CASCADE,
#         page_url    TEXT NOT NULL,            -- page the attachment was found on
#         source_url  TEXT NOT NULL,            -- direct download URL
#         file_path   TEXT NOT NULL,            -- local path on disk
#         file_type   TEXT,
#         file_size   INTEGER,
#         page_id     INTEGER REFERENCES raw_pages(id) ON DELETE SET NULL,
#         downloaded_at TIMESTAMPTZ DEFAULT NOW(),
#         UNIQUE (job_id, source_url)
#     );

#     CREATE INDEX IF NOT EXISTS attachments_job_idx ON attachments(job_id);

#     -- ── Saved images (>= min resolution, logos/icons filtered out) ─────────
#     CREATE TABLE IF NOT EXISTS images (
#         id          SERIAL PRIMARY KEY,
#         job_id      INTEGER REFERENCES crawl_jobs(id) ON DELETE CASCADE,
#         page_url    TEXT NOT NULL,
#         source_url  TEXT NOT NULL,
#         file_path   TEXT NOT NULL,
#         width       INTEGER,
#         height      INTEGER,
#         file_size   INTEGER,
#         downloaded_at TIMESTAMPTZ DEFAULT NOW(),
#          UNIQUE (job_id, source_url)
#     );

#     CREATE INDEX IF NOT EXISTS images_job_idx ON images(job_id);

#     """
#     with get_cursor() as cur:
#         cur.execute(sql)
#     log.info("Database schema initialised")


# # ── Crawl jobs ────────────────────────────────────────────────────────────

# # def job_create(url: str, label: str, frequency: int) -> dict:
# #     with get_cursor() as cur:
# #         cur.execute(
# #             """INSERT INTO crawl_jobs (url, label, frequency)
# #                VALUES (%s, %s, %s) RETURNING *""",
# #             (url, label, frequency),
# #         )
# #         return dict(cur.fetchone())
# # DB functions:

# import json
# def validation_save(report: dict) -> int:
#     if report.get("skipped"):
#         return None
#     with get_cursor() as cur:
#         cur.execute(
#             """INSERT INTO content_validations
#                (job_id, url, skipped, overall_score,
#                 loss_clean, loss_markdown, loss_stage2,
#                 status, char_raw, char_clean, char_md,
#                 conflicts, lost_in_cleaning, lost_in_markdown, recovered_in_md)
#                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
#                RETURNING id""",
#             (
#                 report["job_id"], report["url"], False,
#                 report["overall_score"],
#                 report["loss_clean"],
#                 report["loss_markdown"],
#                 report["loss_stage2"],
#                 report["status"],
#                 report["char_counts"]["raw_html"],
#                 report["char_counts"]["cleaned_html"],
#                 report["char_counts"]["markdown"],
#                 json.dumps(report["conflicts"]),
#                 json.dumps(report["lost_in_cleaning"]),
#                 json.dumps(report["lost_in_markdown"]),
#                 json.dumps(report["recovered_in_md"]),
#             ),
#         )
#         return cur.fetchone()["id"]


# def validations_for_job(job_id: int) -> list[dict]:
#     with get_cursor() as cur:
#         cur.execute(
#             """SELECT * FROM content_validations
#                WHERE job_id=%s ORDER BY overall_score ASC""",
#             (job_id,)
#         )
#         return [dict(r) for r in cur.fetchall()]


# def validations_summary(job_id: int) -> dict:
#     with get_cursor() as cur:
#         cur.execute(
#             """SELECT
#                 COUNT(*)                                            AS total,
#                 ROUND(AVG(overall_score)::numeric, 1)              AS avg_score,
#                 ROUND(AVG(loss_clean)::numeric, 1)                 AS avg_loss_clean,
#                 ROUND(AVG(loss_markdown)::numeric, 1)              AS avg_loss_md,
#                 ROUND(AVG(loss_stage2)::numeric,   1)              AS avg_loss_stage2,
#                 SUM(CASE WHEN status='consistent'   THEN 1 ELSE 0 END) AS consistent,
#                 SUM(CASE WHEN status='partial'       THEN 1 ELSE 0 END) AS partial,
#                 SUM(CASE WHEN status='inconsistent'  THEN 1 ELSE 0 END) AS inconsistent
#                FROM content_validations
#                WHERE job_id=%s AND skipped=FALSE""",
#             (job_id,)
#         )
#         return dict(cur.fetchone())



# # def job_create(url: str, label: str, frequency: int, max_depth: int = 3, max_url: int = None) -> dict:
# #     with get_cursor() as cur:
# #         cur.execute(
# #             """INSERT INTO crawl_jobs (url, label, frequency, max_depth, max_url, status)
# #                VALUES (%s, %s, %s, %s, %s, 'pending') RETURNING *""",
# #             (url, label, frequency, max_depth, max_url),
# #         )
# #         return dict(cur.fetchone())

# def job_create(url: str, label: str, frequency: int,
#                max_depth: int = 3, max_url: int = None) -> dict:
#     with get_cursor() as cur:
#         cur.execute(
#             """INSERT INTO crawl_jobs (url, label, frequency, max_depth, max_url)
#                VALUES (%s, %s, %s, %s, %s) RETURNING *""",
#             (url, label, frequency, max_depth, max_url),
#         )
#         return dict(cur.fetchone())


# def job_get(job_id: int) -> dict | None:
#     with get_cursor() as cur:
#         cur.execute("SELECT * FROM crawl_jobs WHERE id=%s", (job_id,))
#         row = cur.fetchone()
#         return dict(row) if row else None


# def job_list() -> list[dict]:
#     with get_cursor() as cur:
#         cur.execute("SELECT * FROM crawl_jobs ORDER BY created_at DESC")
#         return [dict(r) for r in cur.fetchall()]


# def job_update(job_id: int, label: str = None, frequency: int = None) -> dict | None:
#     fields, vals = [], []
#     if label is not None:
#         fields.append("label=%s");     vals.append(label)
#     if frequency is not None:
#         fields.append("frequency=%s"); vals.append(frequency)
#     if not fields:
#         return job_get(job_id)
#     vals.append(job_id)
#     with get_cursor() as cur:
#         cur.execute(
#             f"UPDATE crawl_jobs SET {', '.join(fields)} WHERE id=%s RETURNING *",
#             vals,
#         )
#         row = cur.fetchone()
#         return dict(row) if row else None


# # def job_delete(job_id: int) -> bool:
# #     with get_cursor() as cur:
# #         cur.execute("DELETE FROM crawl_jobs WHERE id=%s RETURNING id", (job_id,))
# #         return cur.fetchone() is not None

# def job_delete(job_id: int) -> bool:
#     with get_cursor() as cur:
#         # Delete chunks first (via raw_pages)
#         cur.execute("""
#             DELETE FROM chunks 
#             WHERE page_id IN (
#                 SELECT id FROM raw_pages WHERE job_id = %s
#             )
#         """, (job_id,))
#         # Delete raw_pages
#         cur.execute("DELETE FROM raw_pages WHERE job_id = %s", (job_id,))
#         # Delete the job
#         cur.execute("DELETE FROM crawl_jobs WHERE id=%s RETURNING id", (job_id,))
#         return cur.fetchone() is not None


# def job_set_running(job_id: int):
#     with get_cursor() as cur:
#         cur.execute(
#             "UPDATE crawl_jobs SET status='running', last_crawled_at=NOW() WHERE id=%s",
#             (job_id,),
#         )


# def job_set_done(job_id: int):
#     with get_cursor() as cur:
#         cur.execute("SELECT frequency FROM crawl_jobs WHERE id=%s", (job_id,))
#         row = cur.fetchone()
#         freq = row["frequency"] if row else 0
#         next_run = f"NOW() + INTERVAL '{freq} minutes'" if freq > 0 else "NULL"
#         cur.execute(
#             f"""UPDATE crawl_jobs
#                 SET status='done', run_count=run_count+1,
#                     last_error=NULL, next_crawl_at={next_run}
#                 WHERE id=%s""",
#             (job_id,),
#         )


# def job_set_error(job_id: int, error: str):
#     with get_cursor() as cur:
#         cur.execute(
#             """UPDATE crawl_jobs
#                SET status='error', run_count=run_count+1, last_error=%s
#                WHERE id=%s""",
#             (error[:500], job_id),
#         )


# def job_get_due() -> list[dict]:
#     with get_cursor() as cur:
#         cur.execute(
#             """SELECT * FROM crawl_jobs
#                WHERE frequency > 0 AND status != 'running'
#                AND (next_crawl_at IS NULL OR next_crawl_at <= NOW())
#                ORDER BY next_crawl_at ASC NULLS FIRST"""
#         )
#         return [dict(r) for r in cur.fetchall()]


# # ── Raw pages ─────────────────────────────────────────────────────────────

# # def page_save(url: str, title: str, content: str,
# #               content_type: str = "html", job_id: int = None) -> int:
# #     with get_cursor() as cur:
# #         cur.execute(
# #             """INSERT INTO raw_pages (job_id, url, title, content_type, raw_content)
# #                VALUES (%s, %s, %s, %s, %s) RETURNING id""",
# #             (job_id, url, title, content_type, content),
# #         )
# #         return cur.fetchone()["id"]

# def page_save(url: str, title: str, content: str,
#               content_type: str = "html", job_id: int = None) -> int:
#     """
#     Upsert a crawled page.
 
#     Dedup key: (job_id, url, content_type)
#     On re-crawl of the same URL in the same job:
#       - raw_content, title are updated to the latest version
#       - old chunks for this page are deleted before new ones are saved
#         (chunks_save is called separately in consumer, so we just clean up here)
#       - fetched_at is refreshed
 
#     Returns the page id (existing or new).
#     """
#     with get_cursor() as cur:
#         cur.execute(
#             """INSERT INTO raw_pages (job_id, url, title, content_type, raw_content, fetched_at)
#                VALUES (%s, %s, %s, %s, %s, NOW())
#                ON CONFLICT (job_id, url, content_type)
#                DO UPDATE SET
#                    title       = EXCLUDED.title,
#                    raw_content = EXCLUDED.raw_content,
#                    fetched_at  = NOW()
#                RETURNING id""",
#             (job_id, url, title, content_type, content),
#         )
#         page_id = cur.fetchone()["id"]
 
#         # Delete old chunks for this page so re-crawl doesn't accumulate
#         # stale/duplicate embeddings in the vector store
#         cur.execute("DELETE FROM chunks WHERE page_id = %s", (page_id,))
 
#         return page_id
 


# # ── Crawl URLs (sitemap coverage tracking) ────────────────────────────────

# # def crawl_urls_seed(job_id: int, urls: list[str], source: str = "sitemap"):
# #     """
# #     Bulk-insert the discovered URL list for a job as 'pending'.
# #     Called once at the start of a crawl, before any page is fetched.
# #     Safe to call multiple times — duplicates are ignored.
# #     """
# #     # if not urls:
# #     #     return
# #     with get_cursor() as cur:
# #         psycopg2.extras.execute_values(
# #             cur,
# #             """INSERT INTO crawl_urls (job_id, url, source, status)
# #                VALUES %s
# #                ON CONFLICT (job_id, url) DO NOTHING""",
# #             [(job_id, u, source, "pending") for u in urls],
# #         )

# # In database.py, update crawl_urls_seed():
# def crawl_urls_seed(job_id: int, urls: list[str], source: str = "sitemap"):
#     with get_cursor() as cur:
#         # Clear existing pending rows for this job before re-seeding
#         # (keeps scraped/failed rows intact for continuity)
#         cur.execute(
#             "DELETE FROM crawl_urls WHERE job_id=%s AND status='pending'",
#             (job_id,)
#         )
#         for url in urls:
#             cur.execute(
#                 """INSERT INTO crawl_urls (job_id, url, source, status)
#                    VALUES (%s, %s, %s, 'pending')
#                    ON CONFLICT (job_id, url) DO NOTHING""",
#                 (job_id, url, source),
#             )


# def crawl_url_mark_scraped(job_id: int, url: str, page_id: int, local_path: str):
#     with get_cursor() as cur:
#         cur.execute(
#             """INSERT INTO crawl_urls (job_id, url, source, status, page_id, local_path, scraped_at)
#                VALUES (%s, %s, 'sitemap', 'scraped', %s, %s, NOW())
#                ON CONFLICT (job_id, url) DO UPDATE
#                    SET status='scraped', page_id=%s, local_path=%s, scraped_at=NOW(), fail_reason=NULL""",
#             (job_id, url, page_id, local_path, page_id, local_path),
#         )


# def crawl_url_mark_failed(job_id: int, url: str, reason: str):
#     with get_cursor() as cur:
#         cur.execute(
#             """INSERT INTO crawl_urls (job_id, url, source, status, fail_reason)
#                VALUES (%s, %s, 'sitemap', 'failed', %s)
#                ON CONFLICT (job_id, url) DO UPDATE
#                    SET status='failed', fail_reason=%s""",
#             (job_id, url, (reason or "")[:500], (reason or "")[:500]),
#         )


# def crawl_urls_for_job(job_id: int) -> list[dict]:
#     with get_cursor() as cur:
#         cur.execute(
#             "SELECT * FROM crawl_urls WHERE job_id=%s ORDER BY id", (job_id,)
#         )
#         return [dict(r) for r in cur.fetchall()]


# # def crawl_urls_summary(job_id: int) -> dict:
# #     """Counts of total / scraped / failed / pending URLs for a job."""
# #     with get_cursor() as cur:
# #         cur.execute(
# #             """SELECT status, COUNT(*) AS n FROM crawl_urls
# #                WHERE job_id=%s GROUP BY status""",
# #             (job_id,),
# #         )
# #         counts = {r["status"]: r["n"] for r in cur.fetchall()}
# #     total = sum(counts.values())
# #     return {
# #         "total":   total,
# #         "scraped": counts.get("scraped", 0),
# #         "failed":  counts.get("failed", 0),
# #         "pending": counts.get("pending", 0),
# #     }
# def crawl_urls_summary(job_id: int) -> dict:
#     with get_cursor() as cur:
#         cur.execute(
#             """SELECT status, COUNT(*) AS n FROM crawl_urls
#                WHERE job_id=%s GROUP BY status""",
#             (job_id,),
#         )
#         counts = {r["status"]: r["n"] for r in cur.fetchall()}
#     total = sum(counts.values())
#     return {
#         "total":       total,
#         "scraped":     counts.get("scraped",     0),
#         "failed":      counts.get("failed",      0),
#         "pending":     counts.get("pending",     0),
#         "retry":       counts.get("retry",       0),
#         "not_crawled": counts.get("not_crawled", 0),
#     }


# # ── Attachments ───────────────────────────────────────────────────────────

# # def attachment_save(job_id: int, page_url: str, source_url: str,
# #                      file_path: str, file_type: str, file_size: int,
# #                      page_id: int = None) -> int:
# #     with get_cursor() as cur:
# #         cur.execute(
# #             """INSERT INTO attachments
# #                (job_id, page_url, source_url, file_path, file_type, file_size, page_id)
# #                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
# #             (job_id, page_url, source_url, file_path, file_type, file_size, page_id),
# #         )
# #         return cur.fetchone()["id"]

# def attachment_save(job_id: int, page_url: str, source_url: str,
#                      file_path: str, file_type: str, file_size: int,
#                      page_id: int = None) -> int:
#     """
#     Upsert an attachment record.
 
#     Dedup key: (job_id, source_url)
#     On re-crawl of the same attachment URL in the same job:
#       - file_path, file_size, page_id updated to latest version
#       - downloaded_at refreshed
 
#     Returns the attachment id (existing or new).
#     """
#     with get_cursor() as cur:
#         cur.execute(
#             """INSERT INTO attachments
#                (job_id, page_url, source_url, file_path, file_type, file_size,
#                 page_id, downloaded_at)
#                VALUES (%s,%s,%s,%s,%s,%s,%s, NOW())
#                ON CONFLICT (job_id, source_url)
#                DO UPDATE SET
#                    file_path     = EXCLUDED.file_path,
#                    file_size     = EXCLUDED.file_size,
#                    page_id       = EXCLUDED.page_id,
#                    downloaded_at = NOW()
#                RETURNING id""",
#             (job_id, page_url, source_url, file_path, file_type, file_size, page_id),
#         )
#         return cur.fetchone()["id"]
 


# def attachments_for_job(job_id: int) -> list[dict]:
#     with get_cursor() as cur:
#         cur.execute("SELECT * FROM attachments WHERE job_id=%s ORDER BY id", (job_id,))
#         return [dict(r) for r in cur.fetchall()]


# # ── Images ────────────────────────────────────────────────────────────────

# # def image_save(job_id: int, page_url: str, source_url: str, file_path: str,
# #                width: int, height: int, file_size: int) -> int:
# #     with get_cursor() as cur:
# #         cur.execute(
# #             """INSERT INTO images
# #                (job_id, page_url, source_url, file_path, width, height, file_size)
# #                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
# #             (job_id, page_url, source_url, file_path, width, height, file_size),
# #         )
# #         return cur.fetchone()["id"]

# def image_save(job_id: int, page_url: str, source_url: str, file_path: str,
#                width: int, height: int, file_size: int) -> int:
#     """
#     Upsert an image record.
 
#     Dedup key: (job_id, source_url)
#     On re-crawl of the same image URL in the same job:
#       - file_path, dimensions, file_size updated
#       - downloaded_at refreshed
 
#     Returns the image id (existing or new).
#     """
#     with get_cursor() as cur:
#         cur.execute(
#             """INSERT INTO images
#                (job_id, page_url, source_url, file_path, width, height,
#                 file_size, downloaded_at)
#                VALUES (%s,%s,%s,%s,%s,%s,%s, NOW())
#                ON CONFLICT (job_id, source_url)
#                DO UPDATE SET
#                    file_path     = EXCLUDED.file_path,
#                    width         = EXCLUDED.width,
#                    height        = EXCLUDED.height,
#                    file_size     = EXCLUDED.file_size,
#                    downloaded_at = NOW()
#                RETURNING id""",
#             (job_id, page_url, source_url, file_path, width, height, file_size),
#         )
#         return cur.fetchone()["id"]
 


# def images_for_job(job_id: int) -> list[dict]:
#     with get_cursor() as cur:
#         cur.execute("SELECT * FROM images WHERE job_id=%s ORDER BY id", (job_id,))
#         return [dict(r) for r in cur.fetchall()]


# # ── Chunks ────────────────────────────────────────────────────────────────

# # def chunks_save(chunks: list[dict]):
# #     if not chunks:
# #         return
# #     with get_cursor(cursor_factory=None) as cur:
# #         for c in chunks:
# #             emb = c.get("embedding")
# #             vec = "[" + ",".join(str(round(v, 6)) for v in emb) + "]" if emb else None
# #             cur.execute(
# #                 """INSERT INTO chunks
# #                    (page_id, chunk_index, content, token_count, embedding, metadata)
# #                    VALUES (%s,%s,%s,%s,%s::vector,%s)""",
# #                 (
# #                     c["page_id"], c["chunk_index"], c["content"],
# #                     c["token_count"], vec,
# #                     psycopg2.extras.Json(c.get("metadata", {})),
# #                 ),
# #             )

# def chunks_save(chunks: list[dict]):
#     """
#     Insert chunks for a page.
 
#     Note: page_save() already deletes old chunks for the page before
#     this is called, so no ON CONFLICT needed here — we always insert fresh.
#     chunks_save is only called after page_save, so there are no stale
#     rows to conflict with.
#     """
#     if not chunks:
#         return
#     with get_cursor(cursor_factory=None) as cur:
#         for c in chunks:
#             emb = c.get("embedding")
#             vec = "[" + ",".join(str(round(v, 6)) for v in emb) + "]" if emb else None
#             cur.execute(
#                 """INSERT INTO chunks
#                    (page_id, chunk_index, content, token_count, embedding, metadata)
#                    VALUES (%s,%s,%s,%s,%s::vector,%s)""",
#                 (
#                     c["page_id"], c["chunk_index"], c["content"],
#                     c["token_count"], vec,
#                     psycopg2.extras.Json(c.get("metadata", {})),
#                 ),
#             )
 

# def chunks_search(query_vec: list[float], top_k: int,
#                   min_similarity: float) -> list[dict]:
#     vec_str = "[" + ",".join(str(round(v, 6)) for v in query_vec) + "]"
#     sql = """
#         SELECT c.id AS chunk_id, c.page_id, c.content, c.metadata,
#                r.url, r.title,
#                1 - (c.embedding <=> %s::vector) AS similarity
#         FROM   chunks c
#         JOIN   raw_pages r ON r.id = c.page_id
#         WHERE  1 - (c.embedding <=> %s::vector) >= %s
#         ORDER  BY c.embedding <=> %s::vector
#         LIMIT  %s
#     """
#     with get_cursor() as cur:
#         cur.execute(sql, (vec_str, vec_str, min_similarity, vec_str, top_k))
#         return [dict(r) for r in cur.fetchall()]


# # def chunks_keyword_search(query: str, top_k: int) -> list[dict]:
# #     """
# #     Full-text keyword search using PostgreSQL tsvector.
# #     Ranks by ts_rank — how many query words match and how often.
# #     Handles partial words using prefix matching (:*).
# #     """
# #     # Build tsquery — each word becomes a prefix match term joined with OR
# #     words   = [w.strip() for w in query.split() if w.strip()]
# #     tsquery = " | ".join(f"{w}:*" for w in words)

# #     sql = """
# #         SELECT c.id AS chunk_id, c.page_id, c.content, c.metadata,
# #                r.url, r.title,
# #                ts_rank(to_tsvector('english', c.content),
# #                        to_tsquery('english', %s)) AS similarity
# #         FROM   chunks c
# #         JOIN   raw_pages r ON r.id = c.page_id
# #         WHERE  to_tsvector('english', c.content)
# #                @@ to_tsquery('english', %s)
# #         ORDER  BY similarity DESC
# #         LIMIT  %s
# #     """
# #     with get_cursor() as cur:
# #         cur.execute(sql, (tsquery, tsquery, top_k))
# #         return [dict(r) for r in cur.fetchall()]

# def chunks_keyword_search(query: str, top_k: int) -> list[dict]:
#     """
#     Full-text keyword search using PostgreSQL tsvector.
#     """
#     import re

#     # Clean query — remove special chars that break tsquery
#     # Keep only letters, numbers and spaces
#     clean_query = re.sub(r"[^\w\s]", " ", query)
#     clean_query = re.sub(r"\s+", " ", clean_query).strip()

#     if not clean_query:
#         return []

#     # Build tsquery — each word becomes a prefix match joined with OR
#     words   = [w for w in clean_query.split() if len(w) > 2]  # skip tiny words
#     if not words:
#         return []

#     tsquery = " | ".join(f"{w}:*" for w in words)

#     sql = """
#         SELECT c.id AS chunk_id, c.page_id, c.content, c.metadata,
#                r.url, r.title,
#                ts_rank(to_tsvector('english', c.content),
#                        to_tsquery('english', %s)) AS similarity
#         FROM   chunks c
#         JOIN   raw_pages r ON r.id = c.page_id
#         WHERE  to_tsvector('english', c.content)
#                @@ to_tsquery('english', %s)
#         ORDER  BY similarity DESC
#         LIMIT  %s
#     """
#     try:
#         with get_cursor() as cur:
#             cur.execute(sql, (tsquery, tsquery, top_k))
#             return [dict(r) for r in cur.fetchall()]
#     except Exception as e:
#         log.warning(f"Keyword search failed ({e}) — returning empty")
#         return []

# def chunks_hybrid_search(
#     query_vec: list[float],
#     query_text: str,
#     top_k: int,
#     min_similarity: float,
#     rrf_k: int = 60,
# ) -> list[dict]:
#     """
#     Hybrid search using Reciprocal Rank Fusion (RRF).

#     RRF formula: score = 1/(rank + k)
#       - Each result ranked by vector search gets a score
#       - Each result ranked by keyword search gets a score
#       - Scores are summed — results appearing in both lists rank highest

#     Args:
#         query_vec      : embedded query vector
#         query_text     : raw query string for keyword search
#         top_k          : final number of results
#         min_similarity : minimum cosine score for vector search
#         rrf_k          : RRF constant (60 is standard)

#     Returns merged, RRF-ranked list of chunk dicts with rrf_score field.
#     """
#     fetch_k = top_k * 3  # fetch more from each source before merging

#     # Run both searches
#     vector_results  = chunks_search(query_vec, top_k=fetch_k,
#                                     min_similarity=min_similarity)
#     keyword_results = chunks_keyword_search(query_text, top_k=fetch_k)

#     # Build RRF score map keyed by chunk_id
#     rrf_scores: dict[int, float] = {}
#     chunk_map:  dict[int, dict]  = {}

#     # Score vector results
#     for rank, chunk in enumerate(vector_results, start=1):
#         cid = chunk["chunk_id"]
#         rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (rank + rrf_k)
#         chunk_map[cid]  = chunk

#     # Score keyword results
#     for rank, chunk in enumerate(keyword_results, start=1):
#         cid = chunk["chunk_id"]
#         rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (rank + rrf_k)
#         if cid not in chunk_map:
#             chunk_map[cid] = chunk

#     # Sort by RRF score descending
#     sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)

#     results = []
#     for cid in sorted_ids[:top_k]:
#         chunk = chunk_map[cid]
#         chunk["rrf_score"] = round(rrf_scores[cid], 6)
#         results.append(chunk)

#     return results

"""
app/services/database.py
─────────────────────────
All PostgreSQL operations.
"""
from __future__ import annotations
import json
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from config.settings import settings
from app.utils.logger import get_logger

log = get_logger(__name__)


@contextmanager
def get_cursor(cursor_factory=psycopg2.extras.RealDictCursor):
    conn = psycopg2.connect(settings.pg_dsn)
    try:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema():
    """Create all tables. Safe to run on every startup."""
    sql = """
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS crawl_jobs (
        id              SERIAL PRIMARY KEY,
        url             TEXT NOT NULL,
        label           TEXT DEFAULT '',
        frequency       INTEGER DEFAULT 0,
        max_depth       INTEGER DEFAULT 3,
        max_url         INTEGER DEFAULT NULL,
        status          TEXT DEFAULT 'pending',
        last_crawled_at TIMESTAMPTZ,
        next_crawl_at   TIMESTAMPTZ,
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        run_count       INTEGER DEFAULT 0,
        last_error      TEXT
    );

    CREATE TABLE IF NOT EXISTS raw_pages (
        id           SERIAL PRIMARY KEY,
        job_id       INTEGER REFERENCES crawl_jobs(id) ON DELETE SET NULL,
        url          TEXT NOT NULL,
        title        TEXT,
        content_type TEXT DEFAULT 'html',
        raw_content  TEXT,
        fetched_at   TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE (url, content_type)
    );

    CREATE TABLE IF NOT EXISTS chunks (
        id          SERIAL PRIMARY KEY,
        page_id     INTEGER REFERENCES raw_pages(id) ON DELETE CASCADE,
        chunk_index INTEGER,
        content     TEXT NOT NULL,
        token_count INTEGER,
        embedding   vector(384),
        metadata    JSONB DEFAULT '{}',
        created_at  TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS chunks_embedding_idx  ON chunks USING hnsw (embedding vector_cosine_ops);
    CREATE INDEX IF NOT EXISTS chunks_page_id_idx    ON chunks(page_id);
    CREATE INDEX IF NOT EXISTS raw_pages_url_idx     ON raw_pages(url);
    CREATE INDEX IF NOT EXISTS crawl_jobs_status_idx ON crawl_jobs(status);

    CREATE TABLE IF NOT EXISTS crawl_urls (
        id          SERIAL PRIMARY KEY,
        job_id      INTEGER REFERENCES crawl_jobs(id) ON DELETE CASCADE,
        url         TEXT NOT NULL,
        source      TEXT DEFAULT 'sitemap',
        status      TEXT DEFAULT 'pending',
        fail_reason TEXT,
        retry_count INTEGER DEFAULT 0,
        next_retry_at TIMESTAMPTZ,
        page_id     INTEGER REFERENCES raw_pages(id) ON DELETE SET NULL,
        local_path  TEXT,
        scraped_at  TIMESTAMPTZ,
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE (url)
    );

    CREATE INDEX IF NOT EXISTS crawl_urls_job_idx    ON crawl_urls(job_id);
    CREATE INDEX IF NOT EXISTS crawl_urls_status_idx ON crawl_urls(job_id, status);
    CREATE INDEX IF NOT EXISTS crawl_urls_retry_idx  ON crawl_urls(status, next_retry_at)
        WHERE status = 'retry';

    CREATE TABLE IF NOT EXISTS attachments (
        id            SERIAL PRIMARY KEY,
        job_id        INTEGER REFERENCES crawl_jobs(id) ON DELETE CASCADE,
        page_url      TEXT NOT NULL,
        source_url    TEXT NOT NULL,
        file_path     TEXT NOT NULL,
        file_type     TEXT,
        file_size     INTEGER,
        page_id       INTEGER REFERENCES raw_pages(id) ON DELETE SET NULL,
        downloaded_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE (source_url)
    );

    CREATE INDEX IF NOT EXISTS attachments_job_idx ON attachments(job_id);

    CREATE TABLE IF NOT EXISTS images (
        id            SERIAL PRIMARY KEY,
        job_id        INTEGER REFERENCES crawl_jobs(id) ON DELETE CASCADE,
        page_url      TEXT NOT NULL,
        source_url    TEXT NOT NULL,
        file_path     TEXT NOT NULL,
        width         INTEGER,
        height        INTEGER,
        file_size     INTEGER,
        downloaded_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE (source_url)
    );

    CREATE INDEX IF NOT EXISTS images_job_idx ON images(job_id);

    CREATE TABLE IF NOT EXISTS content_validations (
        id               SERIAL PRIMARY KEY,
        job_id           INTEGER REFERENCES crawl_jobs(id) ON DELETE CASCADE,
        url              TEXT NOT NULL,
        skipped          BOOLEAN DEFAULT FALSE,
        skip_reason      TEXT,
        overall_score    FLOAT,
        loss_clean       FLOAT,
        loss_markdown    FLOAT,
        loss_stage2      FLOAT,
        status           TEXT,
        char_raw         INTEGER,
        char_clean       INTEGER,
        char_md          INTEGER,
        conflicts        JSONB DEFAULT '[]',
        lost_in_cleaning JSONB DEFAULT '[]',
        lost_in_markdown JSONB DEFAULT '[]',
        recovered_in_md  JSONB DEFAULT '[]',
        validated_at     TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS validations_job_idx    ON content_validations(job_id);
    CREATE INDEX IF NOT EXISTS validations_status_idx ON content_validations(status);
    """
    with get_cursor() as cur:
        cur.execute(sql)

    # ── Column migrations — safe to run on every startup ─────────────────
    _migrate("""
        ALTER TABLE crawl_jobs  ADD COLUMN IF NOT EXISTS max_depth INTEGER DEFAULT 3;
        ALTER TABLE crawl_jobs  ADD COLUMN IF NOT EXISTS max_url   INTEGER DEFAULT NULL;
        ALTER TABLE crawl_urls  ADD COLUMN IF NOT EXISTS retry_count   INTEGER DEFAULT 0;
        ALTER TABLE crawl_urls  ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
    """)

    log.info("Database schema initialised")


def _migrate(sql: str):
    """Run ALTER TABLE migrations safely — each statement independently."""
    statements = [s.strip() for s in sql.strip().split(";") if s.strip()]
    with get_cursor() as cur:
        for stmt in statements:
            try:
                cur.execute(stmt)
                log.debug(f"Migration OK: {stmt[:80]}")
            except Exception as e:
                log.debug(f"Migration skipped ({e}): {stmt[:80]}")


# ── Content validations ───────────────────────────────────────────────────

def validation_save(report: dict) -> int | None:
    if report.get("skipped"):
        return None
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO content_validations
               (job_id, url, skipped, overall_score,
                loss_clean, loss_markdown, loss_stage2,
                status, char_raw, char_clean, char_md,
                conflicts, lost_in_cleaning, lost_in_markdown, recovered_in_md)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (
                report["job_id"], report["url"], False,
                report["overall_score"],
                report["loss_clean"],
                report["loss_markdown"],
                report["loss_stage2"],
                report["status"],
                report["char_counts"]["raw_html"],
                report["char_counts"]["cleaned_html"],
                report["char_counts"]["markdown"],
                json.dumps(report["conflicts"]),
                json.dumps(report["lost_in_cleaning"]),
                json.dumps(report["lost_in_markdown"]),
                json.dumps(report["recovered_in_md"]),
            ),
        )
        return cur.fetchone()["id"]


def validations_for_job(job_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM content_validations WHERE job_id=%s ORDER BY overall_score ASC",
            (job_id,)
        )
        return [dict(r) for r in cur.fetchall()]


def validations_summary(job_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute(
            """SELECT
                COUNT(*)                                               AS total,
                ROUND(AVG(overall_score)::numeric, 1)                 AS avg_score,
                ROUND(AVG(loss_clean)::numeric,    1)                 AS avg_loss_clean,
                ROUND(AVG(loss_markdown)::numeric, 1)                 AS avg_loss_md,
                ROUND(AVG(loss_stage2)::numeric,   1)                 AS avg_loss_stage2,
                SUM(CASE WHEN status='consistent'   THEN 1 ELSE 0 END) AS consistent,
                SUM(CASE WHEN status='partial'       THEN 1 ELSE 0 END) AS partial,
                SUM(CASE WHEN status='inconsistent'  THEN 1 ELSE 0 END) AS inconsistent
               FROM content_validations
               WHERE job_id=%s AND skipped=FALSE""",
            (job_id,)
        )
        return dict(cur.fetchone())


# ── Crawl jobs ────────────────────────────────────────────────────────────

def job_create(url: str, label: str, frequency: int,
               max_depth: int = 3, max_url: int = None) -> dict:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO crawl_jobs (url, label, frequency, max_depth, max_url)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (url, label, frequency, max_depth, max_url),
        )
        return dict(cur.fetchone())


def job_get(job_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM crawl_jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def job_list() -> list[dict]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM crawl_jobs ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]


def job_update(job_id: int, label: str = None,
               frequency: int = None, max_url: int = None) -> dict | None:
    """Update job label, frequency and/or max_url."""
    fields, vals = [], []
    if label is not None:
        fields.append("label=%s");     vals.append(label)
    if frequency is not None:
        fields.append("frequency=%s"); vals.append(frequency)
    if max_url is not None:
        fields.append("max_url=%s");   vals.append(max_url)
    if not fields:
        return job_get(job_id)
    vals.append(job_id)
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE crawl_jobs SET {', '.join(fields)} WHERE id=%s RETURNING *",
            vals,
        )
        row = cur.fetchone()
        return dict(row) if row else None


def job_delete(job_id: int) -> bool:
    with get_cursor() as cur:
        # Cascade via FK — chunks deleted via raw_pages cascade
        cur.execute(
            "DELETE FROM chunks WHERE page_id IN "
            "(SELECT id FROM raw_pages WHERE job_id=%s)", (job_id,)
        )
        cur.execute("DELETE FROM raw_pages WHERE job_id=%s", (job_id,))
        cur.execute("DELETE FROM crawl_jobs WHERE id=%s RETURNING id", (job_id,))
        return cur.fetchone() is not None


def job_set_running(job_id: int):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE crawl_jobs SET status='running', last_crawled_at=NOW() WHERE id=%s",
            (job_id,),
        )


def job_set_done(job_id: int):
    with get_cursor() as cur:
        cur.execute("SELECT frequency FROM crawl_jobs WHERE id=%s", (job_id,))
        row  = cur.fetchone()
        freq = row["frequency"] if row else 0
        next_run = f"NOW() + INTERVAL '{freq} minutes'" if freq > 0 else "NULL"
        cur.execute(
            f"""UPDATE crawl_jobs
                SET status='done', run_count=run_count+1,
                    last_error=NULL, next_crawl_at={next_run}
                WHERE id=%s""",
            (job_id,),
        )


def job_set_error(job_id: int, error: str):
    with get_cursor() as cur:
        cur.execute(
            """UPDATE crawl_jobs
               SET status='error', run_count=run_count+1, last_error=%s
               WHERE id=%s""",
            (error[:500], job_id),
        )


def job_get_due() -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT * FROM crawl_jobs
               WHERE frequency > 0 AND status != 'running'
               AND (next_crawl_at IS NULL OR next_crawl_at <= NOW())
               ORDER BY next_crawl_at ASC NULLS FIRST"""
        )
        return [dict(r) for r in cur.fetchall()]


# ── Raw pages ─────────────────────────────────────────────────────────────

def page_save(url: str, title: str, content: str,
              content_type: str = "html", job_id: int = None) -> int:
    """
    Upsert a crawled page.
    Dedup key: (job_id, url, content_type)
    On re-crawl: updates content + deletes old chunks so embeddings stay fresh.
    """
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO raw_pages
               (job_id, url, title, content_type, raw_content, fetched_at)
               VALUES (%s, %s, %s, %s, %s, NOW())
               ON CONFLICT (url, content_type)
               DO UPDATE SET
                    job_id     = EXCLUDED.job_id,
                   title       = EXCLUDED.title,
                   raw_content = EXCLUDED.raw_content,
                   fetched_at  = NOW()
               RETURNING id""",
            (job_id, url, title, content_type, content),
        )
        page_id = cur.fetchone()["id"]
        # Delete stale chunks — consumer will re-insert fresh ones
        cur.execute("DELETE FROM chunks WHERE page_id = %s", (page_id,))
        return page_id


# ── Crawl URLs (sitemap coverage tracking) ────────────────────────────────

def crawl_urls_seed(job_id: int, urls: list[str], source: str = "sitemap"):
    """
    Seed crawl_urls for a job.
    - Clears stale 'pending' rows from previous run before re-seeding
    - Resets previously scraped/failed rows back to 'pending' for re-crawl
    """
    if not urls:
        return
    with get_cursor() as cur:
        # Remove stale pending rows from previous run
        cur.execute(
            "DELETE FROM crawl_urls WHERE job_id=%s AND status='pending'",
            (job_id,)
        )
        # Upsert all URLs — reset status to pending for re-crawl
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO crawl_urls (job_id, url, source, status)
               VALUES %s
               ON CONFLICT (url) DO UPDATE
                   SET job_id        = EXCLUDED.job_id,
                       status      = 'pending',
                       fail_reason = NULL,
                       scraped_at  = NULL,
                       local_path  = NULL,
                       retry_count = 0,
                       next_retry_at = NULL""",
            [(job_id, u, source, "pending") for u in urls],
        )


def crawl_url_mark_scraped(job_id: int, url: str,
                            page_id: int = None, local_path: str = None):
    """
    Mark a URL as scraped.
    Upserts so it works for both seeded and BFS-discovered URLs.
    """
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO crawl_urls
               (job_id, url, source, status, page_id, local_path, scraped_at)
               VALUES (%s, %s, 'bfs', 'scraped', %s, %s, NOW())
               ON CONFLICT (url) DO UPDATE
                   SET job_id      = EXCLUDED.job_id,
                       status      = 'scraped',
                       page_id     = COALESCE(EXCLUDED.page_id,    crawl_urls.page_id),
                       local_path  = COALESCE(EXCLUDED.local_path, crawl_urls.local_path),
                       scraped_at  = NOW(),
                       fail_reason = NULL,
                       retry_count = 0""",
            (job_id, url, page_id, local_path),
        )


# def crawl_url_mark_failed(job_id: int, url: str, reason: str):
#     """
#     Mark a URL as failed with exponential backoff retry scheduling.
#     Max 3 retries: 2min → 10min → 30min → permanent fail.
#     """
#     BACKOFF_MINUTES = [2, 10, 30]
#     MAX_RETRIES = 3

#     with get_cursor() as cur:
#         # Get current retry count
#         cur.execute(
#             "SELECT retry_count FROM crawl_urls WHERE url=%s",
#             (url,)
#         )
#         row = cur.fetchone()
#         current_retries = row["retry_count"] if row else 0
#         new_retries = current_retries + 1

#         if new_retries >= MAX_RETRIES:
#             # Permanent failure
#             cur.execute(
#                 """INSERT INTO crawl_urls
#                    (job_id, url, source, status, fail_reason, retry_count)
#                    VALUES (%s, %s, 'bfs', 'failed', %s, %s)
#                    ON CONFLICT (url) DO UPDATE
#                        SET status        = 'failed',
#                            fail_reason   = EXCLUDED.fail_reason,
#                            retry_count   = EXCLUDED.retry_count,
#                            next_retry_at = NULL""",
#                 (job_id, url, (reason or "")[:500], new_retries),
#             )
#             log.warning(f"  Permanently failed after {new_retries} retries: {url}")
#         else:
#             # Schedule retry with backoff
#             backoff = BACKOFF_MINUTES[new_retries - 1]
#             cur.execute(
#                 """INSERT INTO crawl_urls
#                    (job_id, url, source, status, fail_reason, retry_count, next_retry_at)
#                    VALUES (%s, %s, 'bfs', 'retry', %s, %s,
#                            NOW() + INTERVAL '1 minute' * %s)
#                    ON CONFLICT (url) DO UPDATE
#                        SET status        = 'retry',
#                            fail_reason   = EXCLUDED.fail_reason,
#                            retry_count   = EXCLUDED.retry_count,
#                            next_retry_at = EXCLUDED.next_retry_at""",
#                 (job_id, url, (reason or "")[:500], new_retries, backoff),
#             )
#             log.info(f"  Retry {new_retries}/{MAX_RETRIES} in {backoff}min: {url}")
def crawl_url_mark_failed(job_id: int, url: str, reason: str):
    """
    Mark URL as failed with smart backoff:
    - Transient Playwright errors: 10s → 30s → 2min
    - Real blocks (antibot/CF/403): 2min → 10min → 30min
    """
    TRANSIENT_ERRORS = (
        "unable to retrieve content",
        "page is navigating",
        "unexpected error in _crawl_web",
        "page.content",
        "net::err_aborted",
    )
    reason_lower = (reason or "").lower()
    is_transient = any(k in reason_lower for k in TRANSIENT_ERRORS)

    # transient: 10s → 30s → 2min (in minutes: 0.17, 0.5, 2)
    # real block: 2min → 10min → 30min
    BACKOFF_MINUTES = [0.17, 0.5, 2] if is_transient else [2, 10, 30]
    MAX_RETRIES = 3

    with get_cursor() as cur:
        cur.execute(
            "SELECT retry_count FROM crawl_urls WHERE url=%s",
            (url,)
        )
        row = cur.fetchone()
        current_retries = row["retry_count"] if row else 0
        new_retries = current_retries + 1

        if new_retries >= MAX_RETRIES:
            cur.execute(
                """INSERT INTO crawl_urls
                   (job_id, url, source, status, fail_reason, retry_count)
                   VALUES (%s,%s,'bfs','failed',%s,%s)
                   ON CONFLICT (url) DO UPDATE SET
                       status        = 'failed',
                       fail_reason   = EXCLUDED.fail_reason,
                       retry_count   = EXCLUDED.retry_count,
                       next_retry_at = NULL""",
                (job_id, url, (reason or "")[:500], new_retries),
            )
            log.warning(f"  Permanently failed after {new_retries} retries: {url}")
        else:
            backoff = BACKOFF_MINUTES[new_retries - 1]
            cur.execute(
                """INSERT INTO crawl_urls
                   (job_id, url, source, status, fail_reason,
                    retry_count, next_retry_at)
                   VALUES (%s,%s,'bfs','retry',%s,%s,
                           NOW() + INTERVAL '1 minute' * %s)
                   ON CONFLICT (url) DO UPDATE SET
                       status        = 'retry',
                       fail_reason   = EXCLUDED.fail_reason,
                       retry_count   = EXCLUDED.retry_count,
                       next_retry_at = EXCLUDED.next_retry_at""",
                (job_id, url, (reason or "")[:500], new_retries, backoff),
            )
            label = "Transient" if is_transient else "Block"
            secs  = int(backoff * 60)
            log.info(f"  [{label}] retry {new_retries}/{MAX_RETRIES} in {secs}s: {url}")

def crawl_urls_due_retry(job_id: int) -> list[str]:
    """Return URLs due for retry (status='retry', next_retry_at <= NOW())."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT url FROM crawl_urls
               WHERE job_id=%s AND status='retry'
               AND next_retry_at <= NOW()
               ORDER BY next_retry_at ASC""",
            (job_id,)
        )
        return [r["url"] for r in cur.fetchall()]


def crawl_urls_mark_uncrawled(job_id: int) -> int:
    """
    After BFS completes, mark any URL still 'pending' as 'not_crawled'.
    These are sitemap URLs that BFS never discovered/visited.
    Returns count of URLs marked.
    """
    with get_cursor() as cur:
        cur.execute(
            """UPDATE crawl_urls
               SET status='not_crawled'
               WHERE job_id=%s AND status='pending'""",
            (job_id,)
        )
        return cur.rowcount


def crawl_urls_for_job(job_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM crawl_urls WHERE job_id=%s ORDER BY id",
            (job_id,)
        )
        return [dict(r) for r in cur.fetchall()]


# def crawl_urls_summary(job_id: int) -> dict:
#     """Counts by status for a job."""
#     with get_cursor() as cur:
#         cur.execute(
#             "SELECT status, COUNT(*) AS n FROM crawl_urls WHERE job_id=%s GROUP BY status",
#             (job_id,),
#         )
#         counts = {r["status"]: r["n"] for r in cur.fetchall()}
#     total = sum(counts.values())
#     return {
#         "total":       total,
#         "scraped":     counts.get("scraped",     0),
#         "failed":      counts.get("failed",      0),
#         "pending":     counts.get("pending",     0),
#         "retry":       counts.get("retry",       0),
#         "not_crawled": counts.get("not_crawled", 0),
#     }
def crawl_urls_summary(job_id: int) -> dict:
    with get_cursor() as cur:
        # Total = sitemap-seeded URLs only (37)
        cur.execute(
            """SELECT COUNT(*) AS n FROM crawl_urls
               WHERE job_id=%s AND source='sitemap'""",
            (job_id,)
        )
        sitemap_total = cur.fetchone()["n"]   # → 37 ✅

        # Status breakdown — all URLs including BFS-discovered
        cur.execute(
            """SELECT status, COUNT(*) AS n FROM crawl_urls
               WHERE job_id=%s GROUP BY status""",
            (job_id,)
        )
        counts = {r["status"]: r["n"] for r in cur.fetchall()}

    return {
        "total":       sitemap_total,
        "scraped":     counts.get("scraped",     0),
        "failed":      counts.get("failed",      0),
        "pending":     counts.get("pending",     0),
        "retry":       counts.get("retry",       0),
        "not_crawled": counts.get("not_crawled", 0),
    }

# ── Attachments ───────────────────────────────────────────────────────────

def attachment_save(job_id: int, page_url: str, source_url: str,
                     file_path: str, file_type: str, file_size: int,
                     page_id: int = None) -> int:
    """Upsert attachment. Dedup key: (job_id, source_url)."""
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO attachments
               (job_id, page_url, source_url, file_path, file_type,
                file_size, page_id, downloaded_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s, NOW())
               ON CONFLICT (source_url) DO UPDATE SET
                   job_id        = EXCLUDED.job_id,
                   file_path     = EXCLUDED.file_path,
                   file_size     = EXCLUDED.file_size,
                   page_id       = EXCLUDED.page_id,
                   downloaded_at = NOW()
               RETURNING id""",
            (job_id, page_url, source_url, file_path, file_type, file_size, page_id),
        )
        return cur.fetchone()["id"]


def attachments_for_job(job_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM attachments WHERE job_id=%s ORDER BY id", (job_id,))
        return [dict(r) for r in cur.fetchall()]


# ── Images ────────────────────────────────────────────────────────────────

def image_save(job_id: int, page_url: str, source_url: str, file_path: str,
               width: int, height: int, file_size: int) -> int:
    """Upsert image. Dedup key: (job_id, source_url)."""
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO images
               (job_id, page_url, source_url, file_path, width, height,
                file_size, downloaded_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s, NOW())
               ON CONFLICT (source_url) DO UPDATE SET
                   job_id        = EXCLUDED.job_id,
                   file_path     = EXCLUDED.file_path,
                   width         = EXCLUDED.width,
                   height        = EXCLUDED.height,
                   file_size     = EXCLUDED.file_size,
                   downloaded_at = NOW()
               RETURNING id""",
            (job_id, page_url, source_url, file_path, width, height, file_size),
        )
        return cur.fetchone()["id"]


def images_for_job(job_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM images WHERE job_id=%s ORDER BY id", (job_id,))
        return [dict(r) for r in cur.fetchall()]


# ── Chunks ────────────────────────────────────────────────────────────────

def chunks_save(chunks: list[dict]):
    """
    Insert chunks. page_save() deletes old chunks first so no conflict needed.
    """
    if not chunks:
        return
    with get_cursor(cursor_factory=None) as cur:
        for c in chunks:
            emb = c.get("embedding")
            vec = "[" + ",".join(str(round(v, 6)) for v in emb) + "]" if emb else None
            cur.execute(
                """INSERT INTO chunks
                   (page_id, chunk_index, content, token_count, embedding, metadata)
                   VALUES (%s,%s,%s,%s,%s::vector,%s)""",
                (
                    c["page_id"], c["chunk_index"], c["content"],
                    c["token_count"], vec,
                    psycopg2.extras.Json(c.get("metadata", {})),
                ),
            )


def chunks_search(query_vec: list[float], top_k: int,
                  min_similarity: float) -> list[dict]:
    vec_str = "[" + ",".join(str(round(v, 6)) for v in query_vec) + "]"
    sql = """
        SELECT c.id AS chunk_id, c.page_id, c.content, c.metadata,
               r.url, r.title,
               1 - (c.embedding <=> %s::vector) AS similarity
        FROM   chunks c
        JOIN   raw_pages r ON r.id = c.page_id
        WHERE  1 - (c.embedding <=> %s::vector) >= %s
        ORDER  BY c.embedding <=> %s::vector
        LIMIT  %s
    """
    with get_cursor() as cur:
        cur.execute(sql, (vec_str, vec_str, min_similarity, vec_str, top_k))
        return [dict(r) for r in cur.fetchall()]


def chunks_keyword_search(query: str, top_k: int) -> list[dict]:
    """Full-text keyword search using PostgreSQL tsvector."""
    import re
    clean_query = re.sub(r"[^\w\s]", " ", query)
    clean_query = re.sub(r"\s+", " ", clean_query).strip()
    if not clean_query:
        return []
    words = [w for w in clean_query.split() if len(w) > 2]
    if not words:
        return []
    tsquery = " | ".join(f"{w}:*" for w in words)
    sql = """
        SELECT c.id AS chunk_id, c.page_id, c.content, c.metadata,
               r.url, r.title,
               ts_rank(to_tsvector('english', c.content),
                       to_tsquery('english', %s)) AS similarity
        FROM   chunks c
        JOIN   raw_pages r ON r.id = c.page_id
        WHERE  to_tsvector('english', c.content)
               @@ to_tsquery('english', %s)
        ORDER  BY similarity DESC
        LIMIT  %s
    """
    try:
        with get_cursor() as cur:
            cur.execute(sql, (tsquery, tsquery, top_k))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        log.warning(f"Keyword search failed ({e}) — returning empty")
        return []


def chunks_hybrid_search(
    query_vec: list[float],
    query_text: str,
    top_k: int,
    min_similarity: float,
    rrf_k: int = 60,
) -> list[dict]:
    """Hybrid search using Reciprocal Rank Fusion (RRF)."""
    fetch_k = top_k * 3
    vector_results  = chunks_search(query_vec, top_k=fetch_k, min_similarity=min_similarity)
    keyword_results = chunks_keyword_search(query_text, top_k=fetch_k)

    rrf_scores: dict[int, float] = {}
    chunk_map:  dict[int, dict]  = {}

    for rank, chunk in enumerate(vector_results, start=1):
        cid = chunk["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (rank + rrf_k)
        chunk_map[cid]  = chunk

    for rank, chunk in enumerate(keyword_results, start=1):
        cid = chunk["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (rank + rrf_k)
        if cid not in chunk_map:
            chunk_map[cid] = chunk

    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
    results = []
    for cid in sorted_ids[:top_k]:
        chunk = chunk_map[cid]
        chunk["rrf_score"] = round(rrf_scores[cid], 6)
        results.append(chunk)
    return results