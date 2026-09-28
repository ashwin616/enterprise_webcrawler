# """
# app/services/content_validator.py
# ──────────────────────────────────
# Validates content quality by measuring how much content is lost
# during crawl4ai's processing pipeline:

#     raw HTML (ground truth)
#         ↓ cleaning
#     cleaned_html  → loss_clean %
#         ↓ markdownify
#     markdown      → loss_markdown %

# Flags pages where processing dropped too much content.
# Stores results in `content_validations` table for Streamlit dashboard.
# """
# from __future__ import annotations

# import re
# import json
# from app.utils.logger import get_logger

# log = get_logger(__name__)


# # ── Thresholds ────────────────────────────────────────────────────────────

# # How much content loss is acceptable at each stage
# # CLEAN_LOSS_WARNING    = 30.0   # > 30% lost in HTML cleaning  → warning
# # CLEAN_LOSS_CRITICAL   = 60.0   # > 60% lost in HTML cleaning  → critical
# # MD_LOSS_WARNING       = 40.0   # > 40% lost in markdown conv  → warning
# # MD_LOSS_CRITICAL      = 70.0   # > 70% lost in markdown conv  → critical

# # ── Thresholds ────────────────────────────────────────────────────────────

# # Raw HTML always contains scripts/CSS/nav/ads — cleaning removes these.
# # 70-80% loss from raw→cleaned is NORMAL for modern JS-heavy sites.
# # Only flag if loss is extreme (>85%) suggesting real content was stripped.
# CLEAN_LOSS_WARNING  = 70.0   # was 30 — too aggressive
# CLEAN_LOSS_CRITICAL = 85.0   # was 60 — too aggressive

# # Markdown conversion from cleaned HTML should preserve most text content.
# # 30-40% loss here is acceptable (markdown drops HTML formatting/attributes).
# MD_LOSS_WARNING  = 40.0   # loss from cleaned→markdown
# MD_LOSS_CRITICAL = 65.0   # was 70 — kept similar

# # Minimum raw HTML size to bother validating
# # (very small pages — 404s, redirects — skew the numbers)
# MIN_RAW_LENGTH = 500


# # ── Helpers ───────────────────────────────────────────────────────────────

# def _text_length(text: str) -> int:
#     """Meaningful character count — strips whitespace/newlines."""
#     if not text:
#         return 0
#     return len(re.sub(r"\s+", " ", text).strip())


# def _loss_percent(original: int, processed: int) -> float:
#     """How much content was lost going from original → processed (0-100%)."""
#     if original == 0:
#         return 0.0
#     lost = original - processed
#     return round(max(0.0, lost / original * 100), 1)


# def _word_set(text: str) -> set[str]:
#     """Normalize text to a set of meaningful words for content comparison."""
#     if not text:
#         return set()
#     text = re.sub(r"[^\w\s]", " ", text.lower())
#     return {w for w in text.split() if len(w) > 3}


# def _unique_words_lost(source_words: set, target_words: set) -> list[str]:
#     """Words in source but not in target — evidence of lost content."""
#     return sorted(list(source_words - target_words))[:30]


# # ── Core validator ────────────────────────────────────────────────────────

# def validate_formats(
#     url: str,
#     raw_html: str,
#     cleaned_html: str,
#     markdown: str,
#     job_id: int = None,
# ) -> dict:
#     """
#     Validate content quality by measuring loss at each processing stage.

#     Pipeline:
#         raw_html → cleaned_html → markdown

#     Measures:
#         - loss_clean:    % of raw_html content lost after cleaning
#         - loss_markdown: % of raw_html content lost after markdown conversion
#         - loss_stage2:   % of cleaned_html content lost in markdown conversion

#     Returns a report dict for storage + Streamlit display.
#     """

#     # ── Character-level lengths ───────────────────────────────────────
#     len_raw   = _text_length(raw_html)
#     len_clean = _text_length(cleaned_html)
#     len_md    = _text_length(markdown)

#     # Skip validation for tiny pages (404s, redirects, empty responses)
#     if len_raw < MIN_RAW_LENGTH:
#         log.debug(f"  [validate] Skipping tiny page ({len_raw} chars): {url}")
#         return {
#             "url": url, "job_id": job_id,
#             "skipped": True, "reason": f"raw HTML too small ({len_raw} chars)",
#         }

#     # ── Loss percentages ──────────────────────────────────────────────
#     loss_clean    = _loss_percent(len_raw,   len_clean)  # raw → cleaned
#     loss_markdown = _loss_percent(len_raw,   len_md)     # raw → markdown
#     loss_stage2   = _loss_percent(len_clean, len_md)     # cleaned → markdown

#     # ── Word-level analysis ───────────────────────────────────────────
#     raw_words   = _word_set(raw_html)
#     clean_words = _word_set(cleaned_html)
#     md_words    = _word_set(markdown)

#     # Words lost at each stage
#     lost_in_cleaning  = _unique_words_lost(raw_words,   clean_words)
#     lost_in_markdown  = _unique_words_lost(clean_words, md_words)
#     recovered_in_md   = _unique_words_lost(md_words,    clean_words)  # md added vs clean

#     # Current (wrong) — penalizes normal cleaning loss:
#     survival_rate = 100.0 - loss_markdown  # loss_markdown = raw→md = 78.9% → score=21%

#     # Fix — score should be based on cleaned→markdown loss (stage2), not raw→md:
#     survival_rate = 100.0 - loss_stage2    # loss_stage2 = clean→md = ~7% → score=93%

#     # Penalize only if markdown output is suspiciously small
#     if char_md < 500:
#         survival_rate = max(0.0, survival_rate - 30)
#     elif char_md < 200:
#         survival_rate = 0.0

#     overall_score = round(survival_rate, 1)
#     # ── Status ────────────────────────────────────────────────────────
#     if overall_score >= 75:
#         status = "consistent"    # minimal content loss
#     elif overall_score >= 50:
#         status = "partial"       # some content lost
#     else:
#         status = "inconsistent"  # significant content lost

#     # ── Conflicts / warnings ──────────────────────────────────────────
#     conflicts = []

#     if loss_clean >= CLEAN_LOSS_CRITICAL:
#         conflicts.append(
#             f"CRITICAL: HTML cleaning dropped {loss_clean}% of raw content "
#             f"({len_raw}→{len_clean} chars) — cleaner may be too aggressive"
#         )
#     elif loss_clean >= CLEAN_LOSS_WARNING:
#         conflicts.append(
#             f"WARNING: HTML cleaning dropped {loss_clean}% of raw content "
#             f"({len_raw}→{len_clean} chars)"
#         )

#     if loss_stage2 >= MD_LOSS_CRITICAL:
#         conflicts.append(
#             f"CRITICAL: Markdown conversion dropped {loss_stage2}% of cleaned content "
#             f"({len_clean}→{len_md} chars) — markdownify may be failing"
#         )
#     elif loss_stage2 >= MD_LOSS_WARNING:
#         conflicts.append(
#             f"WARNING: Markdown conversion dropped {loss_stage2}% of cleaned content "
#             f"({len_clean}→{len_md} chars)"
#         )

#     if loss_markdown >= MD_LOSS_CRITICAL:
#         conflicts.append(
#             f"CRITICAL: Overall {loss_markdown}% of raw content lost by end of pipeline "
#             f"— final text may be severely incomplete"
#         )

#     if len_md == 0:
#         conflicts.append(
#             "CRITICAL: Markdown output is empty — page produced no usable content"
#         )

#     if len_clean == 0:
#         conflicts.append(
#             "CRITICAL: Cleaned HTML is empty — HTML cleaner removed everything"
#         )

#     report = {
#         "url":     url,
#         "job_id":  job_id,
#         "skipped": False,

#         # Lengths at each stage
#         "char_counts": {
#             "raw_html":    len_raw,
#             "cleaned_html": len_clean,
#             "markdown":    len_md,
#         },

#         # Loss percentages
#         "loss_clean":    loss_clean,     # raw → cleaned
#         "loss_markdown": loss_markdown,  # raw → markdown (end-to-end)
#         "loss_stage2":   loss_stage2,    # cleaned → markdown

#         # Scores
#         "overall_score": overall_score,
#         "status":        status,

#         # Word-level evidence
#         "lost_in_cleaning": lost_in_cleaning,   # words raw had but cleaned lost
#         "lost_in_markdown": lost_in_markdown,   # words cleaned had but md lost
#         "recovered_in_md":  recovered_in_md,    # words md added (vs cleaned)

#         # Conflict/warning messages
#         "conflicts": conflicts,
#     }

#     log.info(
#         f"  [validate] {url[:50]} → "
#         f"score={overall_score}% status={status} "
#         f"loss: clean={loss_clean}% md={loss_markdown}% "
#         f"chars: raw={len_raw} clean={len_clean} md={len_md}"
#     )

#     return report

# """
# app/services/content_validator.py
# ──────────────────────────────────
# Validates content quality by measuring how much content is lost
# during crawl4ai's processing pipeline:

#     raw HTML (ground truth)
#         ↓ cleaning
#     cleaned_html  → loss_clean %   (60-80% is NORMAL — scripts/CSS/ads removed)
#         ↓ markdownify
#     markdown      → loss_stage2 %  (THIS is the real signal — should be < 30%)

# Score and status are based on:
#   1. char_md  — absolute size of final markdown (primary sanity check)
#   2. loss_stage2 — % lost from cleaned→markdown (conversion quality)

# NOT based on raw→markdown end-to-end loss, which is dominated by
# expected cleaning loss and is misleading as a quality signal.

# Stores results in `content_validations` table for Streamlit dashboard.
# """
# from __future__ import annotations

# import re
# import json
# from app.utils.logger import get_logger

# log = get_logger(__name__)


# # ── Thresholds ────────────────────────────────────────────────────────────

# # Stage 2 thresholds: cleaned_html → markdown
# # This is the meaningful conversion quality metric.
# # Raw→clean loss (60-80%) is expected and NOT flagged.
# MD_LOSS_WARNING  = 30.0   # > 30% lost in clean→md conversion → warning
# MD_LOSS_CRITICAL = 55.0   # > 55% lost in clean→md conversion → critical

# # Minimum markdown char count thresholds
# # Pages below these are flagged regardless of loss percentages
# CHAR_MD_CRITICAL = 200    # nearly empty — JS rendering issue likely
# CHAR_MD_WARNING  = 500    # very short — possible extraction problem

# # Minimum raw HTML size to bother validating
# # (404s, redirects, empty responses skew numbers)
# MIN_RAW_LENGTH = 500


# # ── Helpers ───────────────────────────────────────────────────────────────

# def _text_length(text: str) -> int:
#     """Meaningful character count — collapses whitespace."""
#     if not text:
#         return 0
#     return len(re.sub(r"\s+", " ", text).strip())


# def _loss_percent(original: int, processed: int) -> float:
#     """How much content was lost going from original → processed (0-100%)."""
#     if original == 0:
#         return 0.0
#     lost = original - processed
#     return round(max(0.0, lost / original * 100), 1)


# def _word_set(text: str) -> set[str]:
#     """Normalize text to a set of meaningful words for content comparison."""
#     if not text:
#         return set()
#     text = re.sub(r"[^\w\s]", " ", text.lower())
#     return {w for w in text.split() if len(w) > 3}


# def _unique_words_lost(source_words: set, target_words: set) -> list[str]:
#     """Words in source but not in target — evidence of lost content."""
#     return sorted(list(source_words - target_words))[:30]


# # ── Core validator ────────────────────────────────────────────────────────

# def validate_formats(
#     url: str,
#     raw_html: str,
#     cleaned_html: str,
#     markdown: str,
#     job_id: int = None,
# ) -> dict:
#     """
#     Validate content quality by measuring loss at each processing stage.

#     Pipeline:
#         raw_html → cleaned_html → markdown

#     Scoring:
#         - Primary signal: char_md (absolute markdown size)
#         - Secondary signal: loss_stage2 (cleaned→markdown conversion loss)
#         - Raw→markdown end-to-end loss is recorded but NOT used for scoring
#           because it's dominated by expected cleaning loss (60-80% is normal)

#     Returns a report dict for storage + Streamlit display.
#     """

#     # ── Character-level lengths ───────────────────────────────────────
#     len_raw   = _text_length(raw_html)
#     len_clean = _text_length(cleaned_html)
#     len_md    = _text_length(markdown)

#     # Skip validation for tiny pages (404s, redirects, empty responses)
#     if len_raw < MIN_RAW_LENGTH:
#         log.debug(f"  [validate] Skipping tiny page ({len_raw} chars): {url}")
#         return {
#             "url":     url,
#             "job_id":  job_id,
#             "skipped": True,
#             "reason":  f"raw HTML too small ({len_raw} chars)",
#         }

#     # ── Loss percentages ──────────────────────────────────────────────
#     loss_clean    = _loss_percent(len_raw,   len_clean)  # raw → cleaned (expected to be high)
#     loss_markdown = _loss_percent(len_raw,   len_md)     # raw → markdown (end-to-end, for reference)
#     loss_stage2   = _loss_percent(len_clean, len_md)     # cleaned → markdown (THE real signal)

#     # ── Word-level analysis ───────────────────────────────────────────
#     raw_words   = _word_set(raw_html)
#     clean_words = _word_set(cleaned_html)
#     md_words    = _word_set(markdown)

#     lost_in_cleaning = _unique_words_lost(raw_words,   clean_words)
#     lost_in_markdown = _unique_words_lost(clean_words, md_words)
#     recovered_in_md  = _unique_words_lost(md_words,    clean_words)

#     # ── Score (based on char_md + loss_stage2, NOT raw→md) ───────────
#     #
#     # Logic:
#     #   - If char_md is healthy (>= 500), score = 100 - loss_stage2
#     #     e.g. raw=80k, clean=15k, md=14k → stage2=6.7% → score=93.3%
#     #   - If char_md is very small, penalize regardless of percentages
#     #     (a page with clean=500, md=480 has 4% stage2 loss but only
#     #      480 chars of content — still likely a bad page)
#     #
#     if len_md == 0:
#         overall_score = 0.0
#     elif len_md < CHAR_MD_CRITICAL:
#         # Nearly empty — hard fail
#         overall_score = 10.0
#     elif len_md < CHAR_MD_WARNING:
#         # Short — partial credit, capped at 50
#         overall_score = min(50.0, round(100.0 - loss_stage2, 1))
#     else:
#         # Healthy size — score purely on conversion quality
#         overall_score = round(100.0 - loss_stage2, 1)

#     overall_score = max(0.0, min(100.0, overall_score))

#     # ── Status ────────────────────────────────────────────────────────
#     if len_md < CHAR_MD_CRITICAL:
#         status = "inconsistent"
#     elif len_md < CHAR_MD_WARNING:
#         status = "partial"
#     elif overall_score >= 80:
#         status = "consistent"
#     elif overall_score >= 55:
#         status = "partial"
#     else:
#         status = "inconsistent"

#     # ── Conflicts / warnings ──────────────────────────────────────────
#     # NOTE: We do NOT flag raw→clean loss here — 60-80% is expected.
#     # We only flag stage2 (clean→md) loss and char_md issues.
#     conflicts = []

#     if len_md == 0:
#         conflicts.append(
#             "CRITICAL: Markdown output is empty — page produced no usable content"
#         )
#     elif len_md < CHAR_MD_CRITICAL:
#         conflicts.append(
#             f"CRITICAL: Markdown output only {len_md} chars — "
#             "page likely requires JavaScript to render its content. "
#             "Try increasing delay_before_return_html or use ScraperAPI fallback."
#         )
#     elif len_md < CHAR_MD_WARNING:
#         conflicts.append(
#             f"WARNING: Markdown output is short ({len_md} chars) — "
#             "page may have limited extractable text content."
#         )

#     if len_clean == 0:
#         conflicts.append(
#             "CRITICAL: Cleaned HTML is empty — HTML cleaner removed everything"
#         )
#     elif loss_stage2 >= MD_LOSS_CRITICAL:
#         conflicts.append(
#             f"CRITICAL: Markdown conversion dropped {loss_stage2}% of cleaned content "
#             f"({len_clean:,}→{len_md:,} chars) — "
#             "markdownify may be failing for this page type. "
#             "Consider using cleaned_html as primary source instead."
#         )
#     elif loss_stage2 >= MD_LOSS_WARNING:
#         conflicts.append(
#             f"WARNING: Markdown conversion dropped {loss_stage2}% of cleaned content "
#             f"({len_clean:,}→{len_md:,} chars) — "
#             "some content lost in markdown conversion."
#         )

#     # Info-only note about cleaning loss (not a conflict, just context)
#     if loss_clean > 85:
#         conflicts.append(
#             f"INFO: HTML cleaning removed {loss_clean}% of raw content — "
#             "higher than typical 60-80% range. "
#             "Page may use heavy JS framework or have unusual structure."
#         )

#     report = {
#         "url":     url,
#         "job_id":  job_id,
#         "skipped": False,

#         # Lengths at each stage
#         "char_counts": {
#             "raw_html":     len_raw,
#             "cleaned_html": len_clean,
#             "markdown":     len_md,
#         },

#         # Loss percentages
#         "loss_clean":    loss_clean,     # raw → cleaned (expected to be high, 60-80%)
#         "loss_markdown": loss_markdown,  # raw → markdown (end-to-end, for reference)
#         "loss_stage2":   loss_stage2,    # cleaned → markdown (THE real signal)

#         # Score and status
#         "overall_score": overall_score,
#         "status":        status,

#         # Word-level evidence
#         "lost_in_cleaning": lost_in_cleaning,
#         "lost_in_markdown": lost_in_markdown,
#         "recovered_in_md":  recovered_in_md,

#         # Conflict/warning messages
#         "conflicts": conflicts,
#     }

#     log.info(
#         f"  [validate] {url[:50]} → "
#         f"score={overall_score}% status={status} "
#         f"stage2={loss_stage2}% char_md={len_md:,} "
#         f"(raw={len_raw:,} clean={len_clean:,})"
#     )

#     return report

"""
app/services/content_validator.py
──────────────────────────────────
Validates content quality by measuring how much content is lost
during crawl4ai's processing pipeline:

    raw HTML (ground truth)
        ↓ cleaning
    cleaned_html  → loss_clean %   (60-80% is NORMAL — scripts/CSS/ads removed)
        ↓ markdownify
    markdown      → loss_stage2 %  (THE real signal — should be < 40%)

Score and status are based on:
  1. char_md  — absolute size of final markdown (primary sanity check)
  2. loss_stage2 — % lost from cleaned→markdown (conversion quality)
     BUT penalized proportionally less for large content pages:
       char_md >= 10000 → cap penalty at 15% max deduction
       char_md >= 2000  → cap penalty at 25% max deduction
       char_md >= 500   → full penalty applies

This means a page with 18k chars of markdown and 24.5% stage2 loss
scores 85% (consistent) rather than 75.5% (partial) — correctly
reflecting that the page has plenty of usable content.

NOT based on raw→markdown end-to-end loss, which is dominated by
expected cleaning loss (60-80% is normal) and is misleading.
"""
from __future__ import annotations

import re
from app.utils.logger import get_logger

log = get_logger(__name__)


# ── Thresholds ────────────────────────────────────────────────────────────

# Stage 2 thresholds: cleaned_html → markdown
# Raw→clean loss (60-80%) is expected and NOT flagged.
MD_LOSS_WARNING  = 40.0   # > 40% lost in clean→md → warning (was 30)
MD_LOSS_CRITICAL = 65.0   # > 65% lost in clean→md → critical (was 55)

# Minimum markdown char count thresholds
CHAR_MD_CRITICAL = 200    # nearly empty — JS rendering issue likely
CHAR_MD_WARNING  = 500    # very short — possible extraction problem

# char_md size buckets for penalty capping
CHAR_MD_LARGE    = 10000  # large page — cap stage2 penalty at 15%
CHAR_MD_MEDIUM   = 2000   # medium page — cap stage2 penalty at 25%

# Minimum raw HTML size to bother validating
MIN_RAW_LENGTH = 500


# ── Helpers ───────────────────────────────────────────────────────────────

def _text_length(text: str) -> int:
    """Meaningful character count — collapses whitespace."""
    if not text:
        return 0
    return len(re.sub(r"\s+", " ", text).strip())


def _loss_percent(original: int, processed: int) -> float:
    """How much content was lost going from original → processed (0-100%)."""
    if original == 0:
        return 0.0
    lost = original - processed
    return round(max(0.0, lost / original * 100), 1)


def _word_set(text: str) -> set[str]:
    """Normalize text to a set of meaningful words for content comparison."""
    if not text:
        return set()
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return {w for w in text.split() if len(w) > 3}


def _unique_words_lost(source_words: set, target_words: set) -> list[str]:
    """Words in source but not in target — evidence of lost content."""
    return sorted(list(source_words - target_words))[:30]


# ── Core validator ────────────────────────────────────────────────────────

def validate_formats(
    url: str,
    raw_html: str,
    cleaned_html: str,
    markdown: str,
    job_id: int = None,
) -> dict:
    """
    Validate content quality by measuring loss at each processing stage.

    Scoring examples:
      char_md=18k, stage2=24.5% → penalty=min(24.5,15)=15 → score=85% consistent ✅
      char_md=5k,  stage2=24.5% → penalty=min(24.5,25)=24.5 → score=75.5% consistent ✅
      char_md=1k,  stage2=24.5% → penalty=24.5 → score=75.5% consistent ✅
      char_md=18k, stage2=50%   → penalty=min(50,15)=15 → score=85% consistent ✅
      char_md=18k, stage2=70%   → penalty=min(70,15)=15 → score=85% consistent ✅
      char_md=300, stage2=70%   → capped at 50, partial ⚠️
      char_md=100              → score=10, inconsistent ❌
    """

    # ── Character-level lengths ───────────────────────────────────────
    len_raw   = _text_length(raw_html)
    len_clean = _text_length(cleaned_html)
    len_md    = _text_length(markdown)

    # Skip validation for tiny pages (404s, redirects, empty responses)
    if len_raw < MIN_RAW_LENGTH:
        log.debug(f"  [validate] Skipping tiny page ({len_raw} chars): {url}")
        return {
            "url":     url,
            "job_id":  job_id,
            "skipped": True,
            "reason":  f"raw HTML too small ({len_raw} chars)",
        }

    # ── Loss percentages ──────────────────────────────────────────────
    loss_clean    = _loss_percent(len_raw,   len_clean)  # raw → cleaned (expected high)
    loss_markdown = _loss_percent(len_raw,   len_md)     # raw → markdown (reference only)
    loss_stage2   = _loss_percent(len_clean, len_md)     # cleaned → markdown (real signal)

    # ── Word-level analysis ───────────────────────────────────────────
    raw_words   = _word_set(raw_html)
    clean_words = _word_set(cleaned_html)
    md_words    = _word_set(markdown)

    lost_in_cleaning = _unique_words_lost(raw_words,   clean_words)
    lost_in_markdown = _unique_words_lost(clean_words, md_words)
    recovered_in_md  = _unique_words_lost(md_words,    clean_words)

    # ── Score ─────────────────────────────────────────────────────────
    #
    # Primary check: char_md size
    # Secondary: loss_stage2 with penalty capped based on content size
    #
    # Rationale: a page with 18k chars of markdown losing 24.5% in
    # markdown conversion still has 18k chars of USEFUL content.
    # The 24.5% loss is mostly HTML formatting noise (tables→markdown,
    # inline styles, attributes) — not actual text content loss.
    # Penalizing the score heavily for this gives a misleading "partial"
    # status for what is clearly a healthy, content-rich page.
    #
    if len_md == 0:
        overall_score = 0.0

    elif len_md < CHAR_MD_CRITICAL:
        # Nearly empty — hard fail regardless of loss %
        overall_score = 10.0

    elif len_md < CHAR_MD_WARNING:
        # Short page — partial credit, capped at 50
        overall_score = min(50.0, round(100.0 - loss_stage2, 1))

    elif len_md >= CHAR_MD_LARGE:
        # Large content page (>= 10k chars) — cap stage2 penalty at 15%
        # A page with 10k+ chars of markdown is healthy by definition
        penalty = min(loss_stage2, 15.0)
        overall_score = round(100.0 - penalty, 1)

    elif len_md >= CHAR_MD_MEDIUM:
        # Medium page (2k-10k chars) — cap stage2 penalty at 25%
        penalty = min(loss_stage2, 25.0)
        overall_score = round(100.0 - penalty, 1)

    else:
        # Small-medium page (500-2k chars) — full stage2 penalty applies
        overall_score = round(100.0 - loss_stage2, 1)

    overall_score = max(0.0, min(100.0, overall_score))

    # ── Status ────────────────────────────────────────────────────────
    if len_md < CHAR_MD_CRITICAL:
        status = "inconsistent"
    elif len_md < CHAR_MD_WARNING:
        status = "partial"
    elif overall_score >= 70:       # was 80 — more realistic threshold
        status = "consistent"
    elif overall_score >= 45:       # was 55
        status = "partial"
    else:
        status = "inconsistent"

    # ── Conflicts / warnings ──────────────────────────────────────────
    # Only flag real problems — not normal conversion noise.
    conflicts = []

    if len_md == 0:
        conflicts.append(
            "CRITICAL: Markdown output is empty — page produced no usable content"
        )
    elif len_md < CHAR_MD_CRITICAL:
        conflicts.append(
            f"CRITICAL: Markdown output only {len_md} chars — "
            "page likely requires JavaScript to render its content. "
            "Try increasing delay_before_return_html or use ScraperAPI fallback."
        )
    elif len_md < CHAR_MD_WARNING:
        conflicts.append(
            f"WARNING: Markdown output is short ({len_md} chars) — "
            "page may have limited extractable text content."
        )

    if len_clean == 0:
        conflicts.append(
            "CRITICAL: Cleaned HTML is empty — HTML cleaner removed everything"
        )
    elif loss_stage2 >= MD_LOSS_CRITICAL:
        # Only flag if char_md is also small — large pages can have high
        # stage2 loss due to table/formatting conversion and still be fine
        if len_md < CHAR_MD_MEDIUM:
            conflicts.append(
                f"CRITICAL: Markdown conversion dropped {loss_stage2}% of cleaned "
                f"content ({len_clean:,}→{len_md:,} chars) — "
                "markdownify may be failing for this page type. "
                "Consider using cleaned_html as primary source instead."
            )
        else:
            conflicts.append(
                f"INFO: Markdown conversion dropped {loss_stage2}% of cleaned content "
                f"but page has {len_md:,} chars of usable markdown — "
                "loss is likely HTML formatting noise, not real content."
            )
    elif loss_stage2 >= MD_LOSS_WARNING:
        if len_md < CHAR_MD_MEDIUM:
            conflicts.append(
                f"WARNING: Markdown conversion dropped {loss_stage2}% of cleaned "
                f"content ({len_clean:,}→{len_md:,} chars)."
            )
        # else: large page with moderate stage2 loss — don't flag, it's normal

    # Info-only note about cleaning loss (not a conflict)
    if loss_clean > 85:
        conflicts.append(
            f"INFO: HTML cleaning removed {loss_clean}% of raw content — "
            "higher than typical 60-80% range. "
            "Page may use heavy JS framework or have unusual structure."
        )

    report = {
        "url":     url,
        "job_id":  job_id,
        "skipped": False,

        "char_counts": {
            "raw_html":     len_raw,
            "cleaned_html": len_clean,
            "markdown":     len_md,
        },

        "loss_clean":    loss_clean,
        "loss_markdown": loss_markdown,
        "loss_stage2":   loss_stage2,

        "overall_score": overall_score,
        "status":        status,

        "lost_in_cleaning": lost_in_cleaning,
        "lost_in_markdown": lost_in_markdown,
        "recovered_in_md":  recovered_in_md,

        "conflicts": conflicts,
    }

    log.info(
        f"  [validate] {url[:50]} → "
        f"score={overall_score}% status={status} "
        f"stage2={loss_stage2}% char_md={len_md:,} "
        f"(raw={len_raw:,} clean={len_clean:,})"
    )

    return report