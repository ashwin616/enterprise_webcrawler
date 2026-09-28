# """
# crawl_dashboard.py  —  Streamlit Crawl Summary & Coverage Dashboard
# ─────────────────────────────────────────────────────────────────────
# Two tabs:

#   1. Crawl Summary
#      - Pick a crawl job
#      - See: sitemap URL count, scraped count, failed count (with reasons),
#        attachments downloaded (with source page), images saved (with
#        resolution + source page)
#      - Everything shown in plain tables — no jargon, designed so a
#        non-technical user can see at a glance "what happened" for a job.

#   2. Coverage Score
#      - For each job: scraped URLs / total sitemap URLs = coverage %
#      - Simple bar/metric view across all jobs, plus a breakdown for
#        the selected job.

# Usage:
#     streamlit run crawl_dashboard.py --server.port 8502
# """
# from __future__ import annotations

# import sys
# from pathlib import Path

# sys.path.insert(0, str(Path(__file__).parent))

# import pandas as pd
# import streamlit as st

# from app.services import database as db


# # ── Page setup ──────────────────────────────────────────────────────────────

# st.set_page_config(
#     page_title="Crawl Dashboard",
#     page_icon="🕸️",
#     layout="wide",
# )

# st.title("🕸️ Crawl Dashboard")
# st.caption(
#     "See which pages were scraped, which failed (and why), and what "
#     "attachments/images were saved for each crawl."
# )


# # ── Data loading helpers ─────────────────────────────────────────────────────

# @st.cache_data(ttl=15)
# def load_jobs() -> list[dict]:
#     try:
#         return db.job_list()
#     except Exception as e:
#         st.error(f"Could not connect to the database: {e}")
#         return []


# @st.cache_data(ttl=15)
# def load_crawl_urls(job_id: int) -> list[dict]:
#     return db.crawl_urls_for_job(job_id)


# @st.cache_data(ttl=15)
# def load_attachments(job_id: int) -> list[dict]:
#     return db.attachments_for_job(job_id)


# @st.cache_data(ttl=15)
# def load_images(job_id: int) -> list[dict]:
#     return db.images_for_job(job_id)


# @st.cache_data(ttl=15)
# def load_summary(job_id: int) -> dict:
#     return db.crawl_urls_summary(job_id)


# def job_label(job: dict) -> str:
#     label = job.get("label") or ""
#     url = job.get("url", "")
#     status = job.get("status", "")
#     suffix = f" — {label}" if label else ""
#     return f"#{job['id']}  {url}{suffix}  [{status}]"


# def human_size(num_bytes) -> str:
#     if num_bytes is None:
#         return "-"
#     num_bytes = float(num_bytes)
#     for unit in ["B", "KB", "MB", "GB"]:
#         if num_bytes < 1024:
#             return f"{num_bytes:.0f} {unit}"
#         num_bytes /= 1024
#     return f"{num_bytes:.1f} TB"


# # ── Job picker (shared across tabs) ─────────────────────────────────────────

# jobs = load_jobs()

# if not jobs:
#     st.warning(
#         "No crawl jobs found yet. Start a crawl from the Crawler API "
#         "( /crawl/url ) and come back here."
#     )
#     st.stop()

# job_options = {job_label(j): j["id"] for j in jobs}
# selected_label = st.selectbox("Select a crawl job", list(job_options.keys()))
# job_id = job_options[selected_label]
# job = next(j for j in jobs if j["id"] == job_id)

# with st.expander("Job details", expanded=False):
#     st.json({
#         "id": job["id"],
#         "url": job["url"],
#         "label": job.get("label"),
#         "status": job.get("status"),
#         "last_crawled_at": str(job.get("last_crawled_at")),
#         "run_count": job.get("run_count"),
#         "last_error": job.get("last_error"),
#     })


# # ── Tabs ──────────────────────────────────────────────────────────────────

# tab_summary, tab_coverage = st.tabs(["📋 Crawl Summary", "🎯 Coverage Score"])


# # ═══════════════════════════════════════════════════════════════════════════
# # TAB 1 — Crawl Summary
# # ═══════════════════════════════════════════════════════════════════════════

# with tab_summary:
#     crawl_urls = load_crawl_urls(job_id)
#     attachments = load_attachments(job_id)
#     images = load_images(job_id)

#     if not crawl_urls:
#         st.info(
#             "No sitemap URLs recorded for this job yet — either the crawl "
#             "hasn't run, the site has no sitemap, or it's still in progress."
#         )
#     else:
#         scraped = [u for u in crawl_urls if u["status"] == "scraped"]
#         failed = [u for u in crawl_urls if u["status"] == "failed"]
#         pending = [u for u in crawl_urls if u["status"] == "pending"]

#         # ── Top metrics ──────────────────────────────────────────────────
#         c1, c2, c3, c4, c5 = st.columns(5)
#         c1.metric("URLs in sitemap", len(crawl_urls))
#         c2.metric("✅ Scraped", len(scraped))
#         c3.metric("❌ Failed", len(failed))
#         c4.metric("⏳ Pending", len(pending))
#         c5.metric("📎 Attachments / 🖼️ Images", f"{len(attachments)} / {len(images)}")

#         st.divider()

#         # ── Scraped URLs ─────────────────────────────────────────────────
#         st.subheader("✅ Successfully scraped pages")
#         if scraped:
#             df_scraped = pd.DataFrame([
#                 {
#                     "URL": u["url"],
#                     "Saved to folder": u.get("local_path") or "-",
#                     "Scraped at": u.get("scraped_at"),
#                 }
#                 for u in scraped
#             ])
#             st.dataframe(df_scraped, use_container_width=True, hide_index=True)
#         else:
#             st.caption("No pages scraped successfully yet.")

#         # ── Failed URLs ──────────────────────────────────────────────────
#         st.subheader("❌ Pages that failed (with reason)")
#         if failed:
#             df_failed = pd.DataFrame([
#                 {
#                     "URL": u["url"],
#                     "Why it failed": u.get("fail_reason") or "Unknown error",
#                 }
#                 for u in failed
#             ])
#             st.dataframe(df_failed, use_container_width=True, hide_index=True)
#         else:
#             st.caption("No failed pages 🎉")

#         # ── Pending (not yet attempted) ─────────────────────────────────
#         if pending:
#             with st.expander(f"⏳ {len(pending)} URL(s) not yet attempted"):
#                 st.dataframe(
#                     pd.DataFrame({"URL": [u["url"] for u in pending]}),
#                     use_container_width=True, hide_index=True,
#                 )

#         st.divider()

#         # ── Attachments ──────────────────────────────────────────────────
#         st.subheader("📎 Attachments downloaded (PDF / DOC / XLSX / ...)")
#         if attachments:
#             df_att = pd.DataFrame([
#                 {
#                     "File": Path(a["file_path"]).name,
#                     "Type": (a.get("file_type") or "").upper(),
#                     "Size": human_size(a.get("file_size")),
#                     "Found on page": a["page_url"],
#                     "Saved at": a["file_path"],
#                 }
#                 for a in attachments
#             ])
#             st.dataframe(df_att, use_container_width=True, hide_index=True)
#         else:
#             st.caption("No attachments found on this site.")

#         # ── Images ───────────────────────────────────────────────────────
#         st.subheader(
#             "🖼️ Important images saved "
#             "(≥ 800x600 — flowcharts/diagrams; logos & icons skipped)"
#         )
#         if images:
#             df_img = pd.DataFrame([
#                 {
#                     "File": Path(i["file_path"]).name,
#                     "Resolution": f"{i['width']} x {i['height']}",
#                     "Size": human_size(i.get("file_size")),
#                     "Found on page": i["page_url"],
#                     "Saved at": i["file_path"],
#                 }
#                 for i in images
#             ])
#             st.dataframe(df_img, use_container_width=True, hide_index=True)

#             # Quick preview gallery for the first few images
#             with st.expander("Preview images"):
#                 cols = st.columns(4)
#                 for idx, i in enumerate(images[:12]):
#                     p = Path(i["file_path"])
#                     if p.exists():
#                         with cols[idx % 4]:
#                             st.image(str(p), caption=f"{i['width']}x{i['height']}")
#         else:
#             st.caption("No large images (≥800x600) found — likely a text/PDF-heavy site.")


# # ═══════════════════════════════════════════════════════════════════════════
# # TAB 2 — Coverage Score
# # ═══════════════════════════════════════════════════════════════════════════

# with tab_coverage:
#     st.subheader("How much of the site was actually scraped?")
#     st.caption(
#         "Coverage score = (pages successfully scraped) ÷ (total pages "
#         "found in the site's sitemap) × 100. A higher score means more "
#         "of the real site content made it into the system."
#     )

#     summary = load_summary(job_id)
#     total = summary["total"]
#     scraped_n = summary["scraped"]
#     failed_n = summary["failed"]
#     pending_n = summary["pending"]

#     coverage_pct = (scraped_n / total * 100) if total else 0.0

#     c1, c2, c3 = st.columns(3)
#     c1.metric("Coverage score", f"{coverage_pct:.1f}%")
#     c2.metric("Scraped / Total", f"{scraped_n} / {total}")
#     c3.metric("Failed", failed_n)

#     st.progress(min(coverage_pct / 100, 1.0))

#     if coverage_pct >= 90:
#         st.success("Excellent coverage — almost the entire sitemap was scraped.")
#     elif coverage_pct >= 60:
#         st.info("Good coverage — most of the site was scraped, some pages failed.")
#     elif coverage_pct >= 30:
#         st.warning("Partial coverage — a significant portion of the site was missed.")
#     else:
#         st.error("Low coverage — most of the site was not scraped. Check failure reasons in the Crawl Summary tab.")

#     st.divider()

#     # ── Coverage across all jobs ───────────────────────────────────────────
#     st.subheader("Coverage across all crawl jobs")
#     rows = []
#     for j in jobs:
#         s = load_summary(j["id"])
#         t = s["total"]
#         pct = (s["scraped"] / t * 100) if t else 0.0
#         rows.append({
#             "Job": job_label(j),
#             "Sitemap URLs": t,
#             "Scraped": s["scraped"],
#             "Failed": s["failed"],
#             "Pending": s["pending"],
#             "Coverage %": round(pct, 1),
#         })

#     if rows:
#         df_all = pd.DataFrame(rows)
#         st.dataframe(
#             df_all, use_container_width=True, hide_index=True,
#             column_config={
#                 "Coverage %": st.column_config.ProgressColumn(
#                     "Coverage %", min_value=0, max_value=100, format="%.1f%%"
#                 )
#             },
#         )

# """
# crawl_dashboard.py  —  Streamlit Crawl Summary, Coverage & Validation Dashboard
# ─────────────────────────────────────────────────────────────────────────────────
# Three tabs:

#   1. Crawl Summary
#      - Pick a crawl job
#      - See: sitemap URL count, scraped count, failed count (with reasons),
#        retry-scheduled URLs, attachments downloaded, images saved

#   2. Coverage Score
#      - For each job: scraped URLs / total sitemap URLs = coverage %
#      - Simple bar/metric view across all jobs, plus a breakdown for
#        the selected job.

#   3. Content Validation
#      - Per-page content pipeline quality check
#      - Measures content loss: raw HTML → cleaned HTML → markdown
#      - Score based on char_md + loss_stage2 (clean→md)
#      - 60-80% raw→clean loss is NORMAL — scripts/CSS/ads stripped
#      - Focus metric: cleaned→markdown loss (should be < 30%)

# Usage:
#     streamlit run crawl_dashboard.py --server.port 8502
# """
# from __future__ import annotations

# import sys
# from pathlib import Path

# sys.path.insert(0, str(Path(__file__).parent))

# import pandas as pd
# import streamlit as st

# from app.services import database as db


# # ── Page setup ────────────────────────────────────────────────────────────

# st.set_page_config(
#     page_title="Crawl Dashboard",
#     page_icon="🕸️",
#     layout="wide",
# )

# st.title("🕸️ Crawl Dashboard")
# st.caption(
#     "See which pages were scraped, which failed (and why), what "
#     "attachments/images were saved, and content pipeline quality for each crawl."
# )


# # ── Data loading helpers ──────────────────────────────────────────────────

# @st.cache_data(ttl=15)
# def load_jobs() -> list[dict]:
#     try:
#         return db.job_list()
#     except Exception as e:
#         st.error(f"Could not connect to the database: {e}")
#         return []


# @st.cache_data(ttl=15)
# def load_crawl_urls(job_id: int) -> list[dict]:
#     return db.crawl_urls_for_job(job_id)


# @st.cache_data(ttl=15)
# def load_attachments(job_id: int) -> list[dict]:
#     return db.attachments_for_job(job_id)


# @st.cache_data(ttl=15)
# def load_images(job_id: int) -> list[dict]:
#     return db.images_for_job(job_id)


# @st.cache_data(ttl=15)
# def load_summary(job_id: int) -> dict:
#     return db.crawl_urls_summary(job_id)


# @st.cache_data(ttl=15)
# def load_validations(job_id: int) -> list[dict]:
#     try:
#         return db.validations_for_job(job_id)
#     except Exception:
#         return []


# @st.cache_data(ttl=15)
# def load_validations_summary(job_id: int) -> dict:
#     try:
#         return db.validations_summary(job_id)
#     except Exception:
#         return {}


# def job_label(job: dict) -> str:
#     label  = job.get("label") or ""
#     url    = job.get("url", "")
#     status = job.get("status", "")
#     suffix = f" — {label}" if label else ""
#     return f"#{job['id']}  {url}{suffix}  [{status}]"


# def human_size(num_bytes) -> str:
#     if num_bytes is None:
#         return "-"
#     num_bytes = float(num_bytes)
#     for unit in ["B", "KB", "MB", "GB"]:
#         if num_bytes < 1024:
#             return f"{num_bytes:.0f} {unit}"
#         num_bytes /= 1024
#     return f"{num_bytes:.1f} TB"


# # ── Job picker (shared across tabs) ──────────────────────────────────────

# jobs = load_jobs()

# if not jobs:
#     st.warning(
#         "No crawl jobs found yet. Start a crawl from the Crawler API "
#         "( /crawl/url ) and come back here."
#     )
#     st.stop()

# job_options    = {job_label(j): j["id"] for j in jobs}
# selected_label = st.selectbox("Select a crawl job", list(job_options.keys()))
# job_id = job_options[selected_label]
# job    = next(j for j in jobs if j["id"] == job_id)

# with st.expander("Job details", expanded=False):
#     st.json({
#         "id":              job["id"],
#         "url":             job["url"],
#         "label":           job.get("label"),
#         "status":          job.get("status"),
#         "max_depth":       job.get("max_depth"),
#         "max_url":         job.get("max_url"),
#         "last_crawled_at": str(job.get("last_crawled_at")),
#         "run_count":       job.get("run_count"),
#         "last_error":      job.get("last_error"),
#     })


# # ── Tabs ──────────────────────────────────────────────────────────────────

# tab_summary, tab_coverage, tab_validation = st.tabs([
#     "📋 Crawl Summary",
#     "🎯 Coverage Score",
#     "🔍 Content Validation",
# ])


# # ═══════════════════════════════════════════════════════════════════════════
# # TAB 1 — Crawl Summary
# # ═══════════════════════════════════════════════════════════════════════════

# with tab_summary:
#     crawl_urls  = load_crawl_urls(job_id)
#     attachments = load_attachments(job_id)
#     images      = load_images(job_id)

#     if not crawl_urls:
#         st.info(
#             "No sitemap URLs recorded for this job yet — either the crawl "
#             "hasn't run, the site has no sitemap, or it's still in progress."
#         )
#     else:
#         scraped = [u for u in crawl_urls if u["status"] == "scraped"]
#         failed  = [u for u in crawl_urls if u["status"] == "failed"]
#         pending = [u for u in crawl_urls if u["status"] == "pending"]
#         retry   = [u for u in crawl_urls if u["status"] == "retry"]

#         # ── Top metrics ──────────────────────────────────────────────────
#         c1, c2, c3, c4, c5, c6 = st.columns(6)
#         c1.metric("URLs in sitemap",            len(crawl_urls))
#         c2.metric("✅ Scraped",                 len(scraped))
#         c3.metric("❌ Failed",                  len(failed))
#         c4.metric("⏳ Pending",                 len(pending))
#         c5.metric("🔄 Retry scheduled",         len(retry))
#         c6.metric("📎 Attachments / 🖼️ Images", f"{len(attachments)} / {len(images)}")

#         st.divider()

#         # ── Scraped URLs ─────────────────────────────────────────────────
#         st.subheader("✅ Successfully scraped pages")
#         if scraped:
#             df_scraped = pd.DataFrame([
#                 {
#                     "URL":             u["url"],
#                     "Saved to folder": u.get("local_path") or "-",
#                     "Scraped at":      u.get("scraped_at"),
#                 }
#                 for u in scraped
#             ])
#             st.dataframe(df_scraped, use_container_width=True, hide_index=True)
#         else:
#             st.caption("No pages scraped successfully yet.")

#         # ── Failed URLs ──────────────────────────────────────────────────
#         st.subheader("❌ Pages that failed (with reason)")
#         if failed:
#             df_failed = pd.DataFrame([
#                 {
#                     "URL":           u["url"],
#                     "Why it failed": u.get("fail_reason") or "Unknown error",
#                     "Retries":       u.get("retry_count", 0),
#                 }
#                 for u in failed
#             ])
#             st.dataframe(df_failed, use_container_width=True, hide_index=True)
#         else:
#             st.caption("No failed pages 🎉")

#         # ── Retry scheduled ──────────────────────────────────────────────
#         if retry:
#             with st.expander(f"🔄 {len(retry)} URL(s) scheduled for retry"):
#                 df_retry = pd.DataFrame([
#                     {
#                         "URL":           u["url"],
#                         "Retry #":       u.get("retry_count", 0),
#                         "Next retry at": u.get("next_retry_at"),
#                         "Last error":    u.get("fail_reason") or "-",
#                     }
#                     for u in retry
#                 ])
#                 st.dataframe(df_retry, use_container_width=True, hide_index=True)

#         # ── Pending ──────────────────────────────────────────────────────
#         if pending:
#             with st.expander(f"⏳ {len(pending)} URL(s) not yet attempted"):
#                 st.dataframe(
#                     pd.DataFrame({"URL": [u["url"] for u in pending]}),
#                     use_container_width=True,
#                     hide_index=True,
#                 )

#         st.divider()

#         # ── Attachments ──────────────────────────────────────────────────
#         st.subheader("📎 Attachments downloaded (PDF / DOC / XLSX / ...)")
#         if attachments:
#             df_att = pd.DataFrame([
#                 {
#                     "File":          Path(a["file_path"]).name,
#                     "Type":          (a.get("file_type") or "").upper(),
#                     "Size":          human_size(a.get("file_size")),
#                     "Found on page": a["page_url"],
#                     "Saved at":      a["file_path"],
#                 }
#                 for a in attachments
#             ])
#             st.dataframe(df_att, use_container_width=True, hide_index=True)
#         else:
#             st.caption("No attachments found on this site.")

#         # ── Images ───────────────────────────────────────────────────────
#         st.subheader(
#             "🖼️ Important images saved "
#             "(≥ 800×600 — flowcharts/diagrams; logos & icons skipped)"
#         )
#         if images:
#             df_img = pd.DataFrame([
#                 {
#                     "File":          Path(i["file_path"]).name,
#                     "Resolution":    f"{i['width']} × {i['height']}",
#                     "Size":          human_size(i.get("file_size")),
#                     "Found on page": i["page_url"],
#                     "Saved at":      i["file_path"],
#                 }
#                 for i in images
#             ])
#             st.dataframe(df_img, use_container_width=True, hide_index=True)

#             with st.expander("Preview images"):
#                 cols = st.columns(4)
#                 for idx, i in enumerate(images[:12]):
#                     p = Path(i["file_path"])
#                     if p.exists():
#                         with cols[idx % 4]:
#                             st.image(str(p), caption=f"{i['width']}×{i['height']}")
#         else:
#             st.caption("No large images (≥800×600) found — likely a text/PDF-heavy site.")


# # ═══════════════════════════════════════════════════════════════════════════
# # TAB 2 — Coverage Score
# # ═══════════════════════════════════════════════════════════════════════════

# with tab_coverage:
#     st.subheader("How much of the site was actually scraped?")
#     st.caption(
#         "Coverage score = (pages successfully scraped) ÷ (total pages "
#         "found in the site's sitemap) × 100. A higher score means more "
#         "of the real site content made it into the system."
#     )

#     summary   = load_summary(job_id)
#     total     = summary["total"]
#     scraped_n = summary["scraped"]
#     failed_n  = summary["failed"]
#     pending_n = summary["pending"]

#     coverage_pct = (scraped_n / total * 100) if total else 0.0

#     c1, c2, c3 = st.columns(3)
#     c1.metric("Coverage score",  f"{coverage_pct:.1f}%")
#     c2.metric("Scraped / Total", f"{scraped_n} / {total}")
#     c3.metric("Failed",          failed_n)

#     st.progress(min(coverage_pct / 100, 1.0))

#     if coverage_pct >= 90:
#         st.success("Excellent coverage — almost the entire sitemap was scraped.")
#     elif coverage_pct >= 60:
#         st.info("Good coverage — most of the site was scraped, some pages failed.")
#     elif coverage_pct >= 30:
#         st.warning("Partial coverage — a significant portion of the site was missed.")
#     else:
#         st.error(
#             "Low coverage — most of the site was not scraped. "
#             "Check failure reasons in the Crawl Summary tab."
#         )

#     st.divider()

#     # ── Coverage across all jobs ──────────────────────────────────────────
#     st.subheader("Coverage across all crawl jobs")
#     rows = []
#     for j in jobs:
#         s   = load_summary(j["id"])
#         t   = s["total"]
#         pct = (s["scraped"] / t * 100) if t else 0.0
#         rows.append({
#             "Job":          job_label(j),
#             "Sitemap URLs": t,
#             "Scraped":      s["scraped"],
#             "Failed":       s["failed"],
#             "Pending":      s["pending"],
#             "Coverage %":   round(pct, 1),
#         })

#     if rows:
#         df_all = pd.DataFrame(rows)
#         st.dataframe(
#             df_all,
#             use_container_width=True,
#             hide_index=True,
#             column_config={
#                 "Coverage %": st.column_config.ProgressColumn(
#                     "Coverage %", min_value=0, max_value=100, format="%.1f%%"
#                 )
#             },
#         )


# # ═══════════════════════════════════════════════════════════════════════════
# # TAB 3 — Content Validation
# # ═══════════════════════════════════════════════════════════════════════════

# with tab_validation:
#     st.subheader("Content Pipeline Quality")
#     st.caption(
#         "Measures content loss across crawl4ai's processing pipeline: "
#         "**raw HTML → cleaned HTML → markdown**. "
#         "The quality score is based on **char_md** (markdown size) and "
#         "**cleaned→markdown loss** — NOT raw→markdown end-to-end loss, "
#         "which is dominated by expected cleaning (60-80% normal)."
#     )

#     val_summary = load_validations_summary(job_id)

#     if not val_summary or not val_summary.get("total"):
#         st.info(
#             "No validation data yet for this job. "
#             "Validation runs automatically during crawling — "
#             "make sure `content_validator.py` is hooked into `bfs_crawl()`."
#         )
#     else:
#         total_val   = val_summary.get("total")          or 0
#         avg_score   = val_summary.get("avg_score")      or 0
#         avg_loss_c  = val_summary.get("avg_loss_clean") or 0
#         avg_loss_m  = val_summary.get("avg_loss_md")    or 0
#         avg_loss_s2 = val_summary.get("avg_loss_stage2") or 0
#         consistent  = val_summary.get("consistent")     or 0
#         partial     = val_summary.get("partial")        or 0
#         inconsist   = val_summary.get("inconsistent")   or 0

#         # ── Summary metrics ───────────────────────────────────────────────
#         c1, c2, c3, c4, c5 = st.columns(5)
#         c1.metric("Pages Validated",   total_val)
#         c2.metric("Avg Quality Score", f"{avg_score}%")
#         c3.metric("✅ Consistent",     consistent)
#         c4.metric("⚠️ Partial",        partial)
#         c5.metric("❌ Inconsistent",   inconsist)

#         st.progress(int(avg_score) / 100)

#         # ── Pipeline loss metrics (3 columns) ────────────────────────────
#         st.divider()
#         st.write("**Average content loss per pipeline stage:**")
#         col1, col2, col3 = st.columns(3)

#         col1.metric(
#             "① Raw → Cleaned HTML",
#             f"{avg_loss_c}% lost",
#             help=(
#                 "How much the HTML cleaner removed — scripts, CSS, ads, nav. "
#                 "60-80% loss here is completely NORMAL and expected. "
#                 "Only investigate if consistently above 85%."
#             ),
#         )
#         col2.metric(
#             "② Cleaned → Markdown  ⭐",
#             f"{avg_loss_s2}% lost",
#             help=(
#                 "The KEY metric — how much real content is lost during "
#                 "markdown conversion. Should be < 30%. "
#                 "This drives the quality score."
#             ),
#         )
#         col3.metric(
#             "③ Raw → Markdown (end-to-end)",
#             f"{avg_loss_m}% lost",
#             help=(
#                 "Combines ① + ② — dominated by cleaning loss so looks high. "
#                 "Focus on ② Cleaned→Markdown instead."
#             ),
#         )

#         # ── Overall pipeline interpretation (based on stage2, not end-to-end) ──
#         if avg_loss_s2 <= 20:
#             st.success(
#                 f"✅ Pipeline is performing well — markdown conversion only lost "
#                 f"{avg_loss_s2}% of already-cleaned content. "
#                 f"The higher raw→markdown number ({avg_loss_m}%) is expected cleaning loss."
#             )
#         elif avg_loss_s2 <= 45:
#             st.warning(
#                 f"⚠️ Markdown conversion is losing {avg_loss_s2}% of cleaned content — "
#                 "some pages may have incomplete text in the vector DB. "
#                 "Check problem pages below."
#             )
#         else:
#             st.error(
#                 f"❌ Markdown conversion is losing {avg_loss_s2}% of cleaned content — "
#                 "markdownify may be failing on some page types. "
#                 "Review inconsistent pages below."
#             )

#         st.divider()

#         # ── Per-page table ────────────────────────────────────────────────
#         st.subheader("Per-page breakdown")
#         rows = load_validations(job_id)

#         if rows:
#             df_val = pd.DataFrame(rows)[[
#                 "url", "overall_score", "status",
#                 "loss_clean", "loss_stage2", "loss_markdown",
#                 "char_raw", "char_clean", "char_md",
#             ]].copy()
#             df_val["url"] = df_val["url"].str[:70]
#             df_val.columns = [
#                 "URL", "Score %", "Status",
#                 "① Raw→Clean %", "② Clean→MD % ⭐", "③ Raw→MD %",
#                 "Raw chars", "Clean chars", "MD chars",
#             ]

#             def color_status(val):
#                 return {
#                     "consistent":   "background-color: #d4edda; color: #155724",
#                     "partial":      "background-color: #fff3cd; color: #856404",
#                     "inconsistent": "background-color: #f8d7da; color: #721c24",
#                 }.get(val, "")

#             st.dataframe(
#                 df_val.style.applymap(color_status, subset=["Status"]),
#                 use_container_width=True,
#                 height=400,
#                 hide_index=True,
#             )

#         st.divider()

#         # ── Problem page drill-down ───────────────────────────────────────
#         problem_rows = [r for r in rows if r.get("status") != "consistent"]

#         if not problem_rows:
#             st.success("✅ All pages passed consistency validation — no issues found.")
#         else:
#             st.subheader(f"🔎 Problem Pages ({len(problem_rows)} pages need attention)")

#             selected_url = st.selectbox(
#                 "Select a page to inspect",
#                 options=[r["url"] for r in problem_rows],
#                 key="val_page_select",
#             )

#             if selected_url:
#                 row = next(r for r in problem_rows if r["url"] == selected_url)

#                 st.write(f"**URL:** {row['url']}")
#                 st.write(
#                     f"**Score:** `{row['overall_score']}%`  —  "
#                     f"**Status:** `{row['status']}`"
#                 )

#                 # ── Pipeline flow ─────────────────────────────────────────
#                 st.write("**Content size at each pipeline stage:**")
#                 col1, col2, col3 = st.columns(3)

#                 col1.metric(
#                     "① Raw HTML",
#                     f"{row['char_raw']:,} chars",
#                     help="Ground truth — full HTML from the browser (includes scripts/CSS/ads)",
#                 )
#                 col2.metric(
#                     "② Cleaned HTML",
#                     f"{row['char_clean']:,} chars",
#                     delta=f"-{row['loss_clean']}% vs raw",
#                     delta_color="off",   # neutral — cleaning loss is expected
#                     help=(
#                         "After HTML cleaner removed scripts/CSS/ads/nav. "
#                         "60-80% loss here is normal and expected — not a problem."
#                     ),
#                 )
#                 col3.metric(
#                     "③ Markdown  ⭐",
#                     f"{row['char_md']:,} chars",
#                     delta=f"-{row['loss_stage2']}% vs cleaned",
#                     delta_color="inverse",
#                     help=(
#                         "Final output — what goes into the vector DB. "
#                         "This is the number that matters most."
#                     ),
#                 )

#                 # ── Bar chart ─────────────────────────────────────────────
#                 chart_data = pd.DataFrame({
#                     "Stage":      ["① Raw HTML", "② Cleaned HTML", "③ Markdown"],
#                     "Characters": [row["char_raw"], row["char_clean"], row["char_md"]],
#                 })
#                 st.bar_chart(chart_data.set_index("Stage"))

#                 # ── Conflicts ─────────────────────────────────────────────
#                 conflicts = row.get("conflicts") or []
#                 if conflicts:
#                     st.write("**Issues detected:**")
#                     for c in conflicts:
#                         if c.startswith("CRITICAL"):
#                             st.error(f"🔴 {c}")
#                         elif c.startswith("WARNING"):
#                             st.warning(f"🟡 {c}")
#                         else:
#                             st.info(f"ℹ️ {c}")
#                 else:
#                     st.success("No specific conflicts detected.")

#                 # ── Word-level evidence ───────────────────────────────────
#                 st.write("**Word-level evidence:**")
#                 col1, col2, col3 = st.columns(3)

#                 lost_cleaning = row.get("lost_in_cleaning") or []
#                 lost_markdown = row.get("lost_in_markdown") or []
#                 recovered_md  = row.get("recovered_in_md")  or []

#                 with col1:
#                     st.write("**Lost in cleaning** (raw→clean):")
#                     if lost_cleaning:
#                         st.code(", ".join(lost_cleaning[:20]))
#                         st.caption(
#                             f"{len(lost_cleaning)} words — "
#                             "mostly JS/CSS tokens, expected ✅"
#                         )
#                     else:
#                         st.caption("none ✅")

#                 with col2:
#                     st.write("**Lost in markdown ⭐** (clean→md):")
#                     if lost_markdown:
#                         st.code(", ".join(lost_markdown[:20]))
#                         st.caption(
#                             f"{len(lost_markdown)} words — "
#                             "check if these look like real content"
#                         )
#                     else:
#                         st.caption("none — markdown preserved everything ✅")

#                 with col3:
#                     st.write("**Added by markdown** (vs cleaned):")
#                     if recovered_md:
#                         st.code(", ".join(recovered_md[:20]))
#                         st.caption(f"{len(recovered_md)} words added/transformed")
#                     else:
#                         st.caption("none")

#                 # ── Recommendation ────────────────────────────────────────
#                 st.divider()
#                 st.write("**Recommendation:**")

#                 loss_s2  = row.get("loss_stage2", 0)
#                 loss_cl  = row.get("loss_clean", 0)
#                 char_md  = row.get("char_md", 0)

#                 if char_md < 200:
#                     st.error(
#                         "⛔ Final markdown is nearly empty — this page likely requires "
#                         "JavaScript to render its content. "
#                         "Try increasing `delay_before_return_html` in `make_run_config()` "
#                         "or enable the ScraperAPI fallback for this domain."
#                     )
#                 elif char_md < 500:
#                     st.warning(
#                         f"🟡 Markdown output is short ({char_md} chars). "
#                         "This page may have limited text content, or content may be "
#                         "loaded dynamically via JavaScript."
#                     )
#                 elif loss_s2 > 55:
#                     st.warning(
#                         f"🟡 Markdown conversion dropped {loss_s2}% of already-cleaned content. "
#                         "Consider using `result.cleaned_html` instead of `result.markdown` "
#                         "as the primary text source for this page type in `bfs_crawl()`."
#                     )
#                 elif loss_s2 > 30:
#                     st.info(
#                         f"ℹ️ Markdown conversion lost {loss_s2}% of cleaned content — "
#                         "moderate concern. Check if the lost words (above) are real content "
#                         "or HTML artifacts. If real content, consider using cleaned_html."
#                     )
#                 elif loss_cl > 85:
#                     st.info(
#                         f"ℹ️ HTML cleaning removed {loss_cl}% of raw content — "
#                         "slightly above the normal 60-80% range. "
#                         "The markdown output looks healthy ({char_md:,} chars) so this "
#                         "is likely a JS-heavy page where most raw HTML was framework code."
#                     )
#                 else:
#                     st.success(
#                         f"✅ Content loss is within acceptable range. "
#                         f"The markdown output has {char_md:,} chars of usable content. "
#                         "Raw→clean loss is normal (scripts/CSS/ads removed). "
#                         "Core page content is preserved."
#                     )

"""
crawl_dashboard.py  —  Streamlit Crawl Summary & Coverage Dashboard
─────────────────────────────────────────────────────────────────────
Two tabs:

  1. Crawl Summary
     - Pick a crawl job
     - See: sitemap URL count, scraped count, failed count (with reasons),
       retry-scheduled URLs, attachments downloaded, images saved

  2. Coverage Score
     - For each job: scraped URLs / total sitemap URLs = coverage %
     - Simple bar/metric view across all jobs, plus a breakdown for
       the selected job.

Usage:
    streamlit run crawl_dashboard.py --server.port 8502
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import streamlit as st

from app.services import database as db


# ── Page setup ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Crawl Dashboard",
    page_icon="🕸️",
    layout="wide",
)

st.title("🕸️ Crawl Dashboard")
st.caption(
    "See which pages were scraped, which failed (and why), what "
    "attachments/images were saved for each crawl job."
)


# ── Data loading helpers ──────────────────────────────────────────────────

@st.cache_data(ttl=15)
def load_jobs() -> list[dict]:
    try:
        return db.job_list()
    except Exception as e:
        st.error(f"Could not connect to the database: {e}")
        return []


@st.cache_data(ttl=15)
def load_crawl_urls(job_id: int) -> list[dict]:
    return db.crawl_urls_for_job(job_id)


@st.cache_data(ttl=15)
def load_attachments(job_id: int) -> list[dict]:
    return db.attachments_for_job(job_id)


@st.cache_data(ttl=15)
def load_images(job_id: int) -> list[dict]:
    return db.images_for_job(job_id)


@st.cache_data(ttl=0)
def load_summary(job_id: int) -> dict:
    return db.crawl_urls_summary(job_id)


def job_label(job: dict) -> str:
    label  = job.get("label") or ""
    url    = job.get("url", "")
    status = job.get("status", "")
    suffix = f" — {label}" if label else ""
    return f"#{job['id']}  {url}{suffix}  [{status}]"


def human_size(num_bytes) -> str:
    if num_bytes is None:
        return "-"
    num_bytes = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.0f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


# ── Job picker (shared across tabs) ──────────────────────────────────────

jobs = load_jobs()

if not jobs:
    st.warning(
        "No crawl jobs found yet. Start a crawl from the Crawler API "
        "( /crawl/url ) and come back here."
    )
    st.stop()

job_options    = {job_label(j): j["id"] for j in jobs}
selected_label = st.selectbox("Select a crawl job", list(job_options.keys()))
job_id = job_options[selected_label]
job    = next(j for j in jobs if j["id"] == job_id)

with st.expander("Job details", expanded=False):
    st.json({
        "id":              job["id"],
        "url":             job["url"],
        "label":           job.get("label"),
        "status":          job.get("status"),
        "max_depth":       job.get("max_depth"),
        "max_url":         job.get("max_url"),
        "last_crawled_at": str(job.get("last_crawled_at")),
        "run_count":       job.get("run_count"),
        "last_error":      job.get("last_error"),
    })


# ── Tabs ──────────────────────────────────────────────────────────────────

tab_summary, tab_coverage = st.tabs([
    "📋 Crawl Summary",
    "🎯 Coverage Score",
])


# ═══════════════════════════════════════════════════════════════════════════
# TAB 1 — Crawl Summary
# ═══════════════════════════════════════════════════════════════════════════

with tab_summary:
    crawl_urls  = load_crawl_urls(job_id)
    attachments = load_attachments(job_id)
    images      = load_images(job_id)

    if not crawl_urls:
        st.info(
            "No sitemap URLs recorded for this job yet — either the crawl "
            "hasn't run, the site has no sitemap, or it's still in progress."
        )
    else:
        scraped = [u for u in crawl_urls if u["status"] == "scraped"]
        failed  = [u for u in crawl_urls if u["status"] == "failed"]
        pending = [u for u in crawl_urls if u["status"] == "pending"]
        retry   = [u for u in crawl_urls if u["status"] == "retry"]

        # ── Top metrics ──────────────────────────────────────────────────
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("URLs in sitemap",            len(crawl_urls))
        c2.metric("✅ Scraped",                 len(scraped))
        c3.metric("❌ Failed",                  len(failed))
        c4.metric("⏳ Pending",                 len(pending))
        c5.metric("🔄 Retry scheduled",         len(retry))
        c6.metric("📎 Attachments / 🖼️ Images", f"{len(attachments)} / {len(images)}")

        st.divider()

        # ── Scraped URLs ─────────────────────────────────────────────────
        st.subheader("✅ Successfully scraped pages")
        if scraped:
            df_scraped = pd.DataFrame([
                {
                    "URL":             u["url"],
                    "Saved to folder": u.get("local_path") or "-",
                    "Scraped at":      u.get("scraped_at"),
                }
                for u in scraped
            ])
            st.dataframe(df_scraped, use_container_width=True, hide_index=True)
        else:
            st.caption("No pages scraped successfully yet.")

        # ── Failed URLs ──────────────────────────────────────────────────
        st.subheader("❌ Pages that failed (with reason)")
        if failed:
            df_failed = pd.DataFrame([
                {
                    "URL":           u["url"],
                    "Why it failed": u.get("fail_reason") or "Unknown error",
                    "Retries":       u.get("retry_count", 0),
                }
                for u in failed
            ])
            st.dataframe(df_failed, use_container_width=True, hide_index=True)
        else:
            st.caption("No failed pages 🎉")

        # ── Retry scheduled ──────────────────────────────────────────────
        if retry:
            with st.expander(f"🔄 {len(retry)} URL(s) scheduled for retry"):
                df_retry = pd.DataFrame([
                    {
                        "URL":           u["url"],
                        "Retry #":       u.get("retry_count", 0),
                        "Next retry at": u.get("next_retry_at"),
                        "Last error":    u.get("fail_reason") or "-",
                    }
                    for u in retry
                ])
                st.dataframe(df_retry, use_container_width=True, hide_index=True)

        # ── Pending ──────────────────────────────────────────────────────
        if pending:
            with st.expander(f"⏳ {len(pending)} URL(s) not yet attempted"):
                st.dataframe(
                    pd.DataFrame({"URL": [u["url"] for u in pending]}),
                    use_container_width=True,
                    hide_index=True,
                )

        st.divider()

        # ── Attachments ──────────────────────────────────────────────────
        st.subheader("📎 Attachments downloaded (PDF / DOC / XLSX / ...)")
        if attachments:
            df_att = pd.DataFrame([
                {
                    "File":          Path(a["file_path"]).name,
                    "Type":          (a.get("file_type") or "").upper(),
                    "Size":          human_size(a.get("file_size")),
                    "Found on page": a["page_url"],
                    "Saved at":      a["file_path"],
                }
                for a in attachments
            ])
            st.dataframe(df_att, use_container_width=True, hide_index=True)
        else:
            st.caption("No attachments found on this site.")

        # ── Images ───────────────────────────────────────────────────────
        st.subheader(
            "🖼️ Important images saved "
            "(≥ 800×600 — flowcharts/diagrams; logos & icons skipped)"
        )
        if images:
            df_img = pd.DataFrame([
                {
                    "File":          Path(i["file_path"]).name,
                    "Resolution":    f"{i['width']} × {i['height']}",
                    "Size":          human_size(i.get("file_size")),
                    "Found on page": i["page_url"],
                    "Saved at":      i["file_path"],
                }
                for i in images
            ])
            st.dataframe(df_img, use_container_width=True, hide_index=True)

            with st.expander("Preview images"):
                cols = st.columns(4)
                for idx, i in enumerate(images[:12]):
                    p = Path(i["file_path"])
                    if p.exists():
                        with cols[idx % 4]:
                            st.image(str(p), caption=f"{i['width']}×{i['height']}")
        else:
            st.caption("No large images (≥800×600) found — likely a text/PDF-heavy site.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2 — Coverage Score
# ═══════════════════════════════════════════════════════════════════════════

with tab_coverage:
    st.subheader("How much of the site was actually scraped?")
    st.caption(
        "Coverage score = (pages successfully scraped) ÷ (total pages "
        "found in the site's sitemap) × 100. A higher score means more "
        "of the real site content made it into the system."
    )

    summary   = load_summary(job_id)
    total     = summary["total"]
    scraped_n = summary["scraped"]
    failed_n  = summary["failed"]
    pending_n = summary["pending"]

    coverage_pct = (scraped_n / total * 100) if total else 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("Coverage score",  f"{coverage_pct:.1f}%")
    c2.metric("Scraped / Total", f"{scraped_n} / {total}")
    c3.metric("Failed",          failed_n)

    st.progress(min(coverage_pct / 100, 1.0))

    if coverage_pct >= 90:
        st.success("Excellent coverage — almost the entire sitemap was scraped.")
    elif coverage_pct >= 60:
        st.info("Good coverage — most of the site was scraped, some pages failed.")
    elif coverage_pct >= 30:
        st.warning("Partial coverage — a significant portion of the site was missed.")
    else:
        st.error(
            "Low coverage — most of the site was not scraped. "
            "Check failure reasons in the Crawl Summary tab."
        )

    st.divider()

    # ── Coverage across all jobs ──────────────────────────────────────────
    st.subheader("Coverage across all crawl jobs")
    rows = []
    for j in jobs:
        s   = load_summary(j["id"])
        t   = s["total"]
        pct = (s["scraped"] / t * 100) if t else 0.0
        rows.append({
            "Job":          job_label(j),
            "Sitemap URLs": t,
            "Scraped":      s["scraped"],
            "Failed":       s["failed"],
            "Pending":      s["pending"],
            "Coverage %":   round(pct, 1),
        })

    if rows:
        df_all = pd.DataFrame(rows)
        st.dataframe(
            df_all,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Coverage %": st.column_config.ProgressColumn(
                    "Coverage %", min_value=0, max_value=100, format="%.1f%%"
                )
            },
        )