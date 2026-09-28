"""
app/services/crawler_service.py
─────────────────────────────────
Core crawl logic — called by crawler_api.py as a subprocess.
Reads URL + job_id + max_depth from stdin, crawls, publishes to Kafka.

Uses crawl4ai 0.5+ built-in BFSDeepCrawlStrategy — no custom DFS logic.
"""
from __future__ import annotations

import re
import sys
import asyncio
import mimetypes
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin, urldefrag

import requests
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from PIL import Image
import io as _io

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings
from app.services.kafka_producer import publish_page, publish_attachment, flush, publish_job_complete
from app.services import database as db
from app.utils.logger import get_logger
from crawl4ai import AsyncWebCrawler, CacheMode
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher

from usp.tree import sitemap_tree_for_homepage
from usp.web_client.requests_client import RequestsWebClient


try:
    import io
    from rich.console import Console as _RichConsole
    from crawl4ai import async_logger as _c4ai_logger
    _safe_console = _RichConsole(
        file=io.TextIOWrapper(open(2, "wb", closefd=False), encoding="utf-8"),
        highlight=False,
        markup=False,
        force_terminal=False,
        force_jupyter=False,
    )

    def _noop(self, *a, **kw):
        pass

    _SILENCED_METHODS = (
        "error", "warning", "info", "debug",
        "success", "url_status", "error_status",
        "alert", "critical", "exception", "fatal", "notice",
    )

    for _cls_name in ("AsyncLogger", "AsyncFileLogger", "AsyncLoggerBase"):
        _cls = getattr(_c4ai_logger, _cls_name, None)
        if _cls is None:
            continue

        if _cls_name == "AsyncLogger":
            _orig_init = _cls.__init__
            def _patched_init(self, *a, _orig=_orig_init, **kw):
                _orig(self, *a, **kw)
                self.console = _safe_console
                self.verbose = False
            _cls.__init__ = _patched_init

        for _m in _SILENCED_METHODS:
            if hasattr(_cls, _m):
                setattr(_cls, _m, _noop)
except Exception:
    pass


log = get_logger(__name__)

OUTPUT_DIR = Path(settings.crawler_output_dir)
OUTPUT_DIR.mkdir(exist_ok=True)

ATTACHMENT_EXTS = {".pdf", ".doc", ".docx", ".csv", ".xls", ".xlsx", ".ppt", ".pptx"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}

# Minimum resolution for an image to be considered "important" (e.g. a
# flowchart/diagram) rather than a logo, icon, or decorative low-res image.
MIN_IMAGE_WIDTH = 800
MIN_IMAGE_HEIGHT = 600


def page_folder(seed_url: str, page_url: str) -> Path:
    """
    Build the parent-child storage folder for a crawled page:

        crawl_output/<domain>/<page-path>/

    e.g. https://www.google.com/about/contact-us
         -> crawl_output/www.google.com/about/contact-us/

    Root page (path "/" or "") -> crawl_output/<domain>/_root/
    """
    p = urlparse(page_url)
    domain = p.netloc or urlparse(seed_url).netloc
    path = p.path.strip("/")
    if not path:
        path = "_root"
    # sanitise path segments (avoid weird chars / path traversal)
    safe_segments = [
        re.sub(r"[^\w\-.]", "_", seg)[:80] for seg in path.split("/") if seg
    ]
    folder = OUTPUT_DIR / domain / Path(*safe_segments)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ── Helpers ───────────────────────────────────────────────────────────────

def safe_filename(text: str, ext: str = ".pdf") -> str:
    slug = re.sub(r"[^\w\-]", "_", text)[:80].strip("_")
    return f"{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"


def is_attachment_url(url: str) -> bool:
    return any(urlparse(url).path.lower().endswith(e) for e in ATTACHMENT_EXTS)


def same_domain(url: str, base: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc

def _same_domain_relaxed(url1: str, url2: str) -> bool:
    """
    Compare domains ignoring www. prefix.
    kratosolutions.com == www.kratosolutions.com → True
    """
    def strip_www(netloc: str) -> str:
        return netloc.lower().removeprefix("www.")

    return strip_www(urlparse(url1).netloc) == strip_www(urlparse(url2).netloc)


def normalise_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/') or '/'}"


def is_drive_url(url: str) -> bool:
    return any(h in urlparse(url).netloc for h in ["drive.google.com", "docs.google.com"])


_UNICODE_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "--", "\u2026": "...", "\u00a0": " ", "\u2022": "*",
})


def sanitise(text: str) -> str:
    return text.translate(_UNICODE_MAP)


# ── Sitemap parser ────────────────────────────────────────────────────────

# def fetch_sitemap_urls(seed_url: str) -> list[str]:
#     """
#     Use ultimate-sitemap-parser (usp) to robustly discover all sitemap URLs.

#     usp handles:
#       - robots.txt sitemap discovery
#       - sitemap index files (nested sitemaps, recursive)
#       - gzip-compressed sitemaps (.xml.gz)
#       - common known sitemap paths (sitemap.xml, sitemap_index.xml, etc.)
#       - news/video/image sitemap variants

#     Falls back to [] (BFS-only crawl) if no sitemap is found or usp errors out.
#     """
#     try:
#         session = requests.Session()
#         session.headers.update({"User-Agent": settings.crawler_user_agent})
#         client = RequestsWebClient(session=session)

#         base = f"{urlparse(seed_url).scheme}://{urlparse(seed_url).netloc}/"
#         tree = sitemap_tree_for_homepage(base, web_client=client)

#         urls = []
#         for page in tree.all_pages():
#             loc = (page.url or "").strip()
#             if not loc:
#                 continue
#             if same_domain(loc, seed_url) and not is_attachment_url(loc):
#                 urls.append(normalise_url(loc))

#         urls = list(dict.fromkeys(urls))
#         if urls:
#             log.info(f"  Sitemap (usp) provided {len(urls)} URLs")
#             return urls

#     except Exception as e:
#         log.debug(f"  usp sitemap fetch failed: {e}")

#     log.info("  No sitemap found — using BFS crawl only")
#     return []


"""
Replace fetch_sitemap_urls in crawler_service.py with this version.

Root cause of the tickbig.com failure:
  The site returns an HTML page (Cloudflare / bot-protection) for every
  sitemap URL.  usp tries to gunzip it → fails ("Not a gzipped file (b'<!')").
  Then tries to parse as XML → "syntax error: line 1, column 0".
  Marks every sitemap invalid → 0 URLs returned.

Fix strategy (three layers):
  1. Content sniff before handing to usp — if the response is HTML, skip usp
     and fall back immediately rather than letting usp log noisy errors.
  2. ScraperAPI bypass — if direct fetch is blocked, retry through ScraperAPI.
  3. robots.txt manual parse — read Sitemap: directives directly as a last resort
     so we still get the sitemap URL list even if usp can't reach them.
"""




def _is_html_not_xml(content: bytes) -> bool:
    """Return True if content looks like an HTML page rather than XML."""
    sniff = content[:200].lower()
    return (
        sniff.startswith(b"<!doctype") or
        b"<html" in sniff or
        b"<head" in sniff or
        b"just a moment" in sniff or
        b"cloudflare" in sniff
    )


def _parse_robots_for_sitemaps(base_url: str, user_agent: str) -> list[str]:
    """
    Manually read robots.txt and extract every 'Sitemap:' directive.
    Returns a list of sitemap URLs (may be empty).
    """
    try:
        resp = requests.get(
            f"{base_url}robots.txt",
            headers={"User-Agent": user_agent},
            timeout=15,
        )
        if resp.status_code == 200:
            return re.findall(r"(?i)^sitemap:\s*(\S+)", resp.text, re.MULTILINE)
    except Exception:
        pass
    return []


def _fetch_sitemap_xml(url: str, user_agent: str, scraperapi_key: str = None) -> bytes | None:
    """
    Fetch a sitemap URL.  If the direct response is an HTML block page,
    retry through ScraperAPI (if a key is configured).
    Returns raw bytes or None.
    """
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/xml,text/xml,*/*",
    }
    content = None

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        content = resp.content
    except Exception:
        pass

    # If blocked (HTML response) and ScraperAPI is available, bypass it
    if (content is None or _is_html_not_xml(content)) and scraperapi_key:
        try:
            resp = requests.get(
                "https://api.scraperapi.com/",
                params={"api_key": scraperapi_key, "url": url},
                timeout=40,
            )
            resp.raise_for_status()
            content = resp.content
        except Exception:
            pass

    if content and _is_html_not_xml(content):
        return None   # still blocked after all retries

    return content


def _extract_locs(xml_bytes: bytes) -> list[str]:
    """
    Pull every <loc>...</loc> value from sitemap XML.
    Uses regex instead of a full XML parser so it tolerates minor
    namespace issues and malformed XML that lxml would reject.
    """
    locs = re.findall(rb"<loc>\s*(.+?)\s*</loc>", xml_bytes, re.IGNORECASE)
    return [loc.decode("utf-8", errors="replace").strip() for loc in locs]


# def fetch_sitemap_urls(seed_url: str) -> list[str]:
#     """
#     Robustly discover all sitemap URLs for seed_url.

#     Strategy:
#       1. Try usp (handles robots.txt, nested indexes, gzip, news/video sitemaps).
#       2. If usp returns nothing (or the site blocks it with HTML), fall back to:
#          a. Manual robots.txt parse to find sitemap URLs.
#          b. Direct fetch of each sitemap URL (with ScraperAPI bypass if needed).
#          c. Common sitemap path probing as a last resort.

#     Returns deduplicated, same-domain, non-attachment URLs.
#     Falls back to [] (BFS-only crawl) if nothing works.
#     """
#     from config.settings import settings
#     from app.utils.logger import get_logger
#     log = get_logger(__name__)

#     user_agent = settings.crawler_user_agent
#     scraperapi_key = getattr(settings, "scraperapi_key", None)

#     base = f"{urlparse(seed_url).scheme}://{urlparse(seed_url).netloc}/"

#     def same_domain(url):
#         return urlparse(url).netloc == urlparse(seed_url).netloc

#     def normalise(url):
#         from urllib.parse import urldefrag
#         url, _ = urldefrag(url)
#         p = urlparse(url)
#         return f"{p.scheme}://{p.netloc}{p.path.rstrip('/') or '/'}"

#     def is_attachment(url):
#         return any(urlparse(url).path.lower().endswith(e) for e in ATTACHMENT_EXTS)

#     def filter_and_dedup(urls):
#         out = []
#         seen = set()
#         for u in urls:
#             u = u.strip()
#             if not u:
#                 continue
#             n = normalise(u)
#             if n in seen:
#                 continue
#             seen.add(n)
#             if same_domain(u) and not is_attachment(u):
#                 out.append(n)
#         return out

#     # ── Layer 1: usp ──────────────────────────────────────────────────────────
#     try:
#         from usp.tree import sitemap_tree_for_homepage
#         from usp.web_client.requests_client import RequestsWebClient

#         session = requests.Session()
#         session.headers.update({"User-Agent": user_agent})
#         client = RequestsWebClient(session=session)

#         tree = sitemap_tree_for_homepage(base, web_client=client)
#         usp_urls = []
#         for page in tree.all_pages():
#             loc = (page.url or "").strip()
#             if loc and same_domain(loc) and not is_attachment(loc):
#                 usp_urls.append(normalise(loc))
#         usp_urls = list(dict.fromkeys(usp_urls))

#         if usp_urls:
#             log.info(f"Sitemap (usp) provided {len(usp_urls)} URLs")
#             return usp_urls

#         log.info("usp returned 0 URLs — trying fallback sitemap fetch")

#     except Exception as e:
#         log.warning(f"usp sitemap fetch failed: {e} — trying fallback")

#     # ── Layer 2: manual robots.txt + direct sitemap fetch ─────────────────────
#     #
#     # This layer handles the case where usp gets blocked by bot protection
#     # (it receives HTML instead of XML, logs "syntax error: line 1, column 0",
#     # and returns nothing).  We fetch the sitemap bytes ourselves, optionally
#     # bypassing bot protection via ScraperAPI, then parse <loc> tags directly.

#     sitemap_urls_to_try: list[str] = []

#     # 2a. Read Sitemap: directives from robots.txt
#     robot_sitemaps = _parse_robots_for_sitemaps(base, user_agent)
#     if robot_sitemaps:
#         log.info(f"robots.txt listed {len(robot_sitemaps)} sitemap(s): {robot_sitemaps}")
#         sitemap_urls_to_try.extend(robot_sitemaps)

#     # 2b. Also probe common sitemap paths that usp tries but may have been blocked
#     common_paths = [
#         "sitemap.xml",
#         "sitemap_index.xml",
#         "sitemap-index.xml",
#         "sitemap-news.xml",
#     ]
#     sitemap_urls_to_try.extend(base.rstrip("/") + "/" + p for p in common_paths)

#     # Deduplicate the list of sitemap URLs to fetch
#     sitemap_urls_to_try = list(dict.fromkeys(sitemap_urls_to_try))

#     all_page_urls: list[str] = []

#     for sitemap_url in sitemap_urls_to_try:
#         log.info(f"  Fallback fetch: {sitemap_url}")
#         xml_bytes = _fetch_sitemap_xml(sitemap_url, user_agent, scraperapi_key)
#         if not xml_bytes:
#             log.debug(f"  Blocked or empty: {sitemap_url}")
#             continue

#         locs = _extract_locs(xml_bytes)
#         log.info(f"  Found {len(locs)} <loc> entries in {sitemap_url}")

#         # A sitemap index contains <loc> pointing to other sitemaps — recurse one level
#         child_sitemaps = [
#             l for l in locs
#             if any(l.endswith(ext) for ext in (".xml", ".xml.gz"))
#         ]
#         page_locs = [l for l in locs if l not in child_sitemaps]

#         all_page_urls.extend(page_locs)

#         for child_url in child_sitemaps:
#             log.info(f"    Fetching child sitemap: {child_url}")
#             child_bytes = _fetch_sitemap_xml(child_url, user_agent, scraperapi_key)
#             if child_bytes:
#                 child_locs = _extract_locs(child_bytes)
#                 log.info(f"    Found {len(child_locs)} URLs in child sitemap")
#                 all_page_urls.extend(child_locs)

#     filtered = filter_and_dedup(all_page_urls)

#     if filtered:
#         log.info(f"Sitemap fallback provided {len(filtered)} URLs")
#         return filtered

#     log.info("No sitemap found after all fallback attempts — using BFS crawl only")
#     return []


def fetch_sitemap_urls(seed_url: str, retries: int = 2) -> list[str]:
    """
    Robustly discover all sitemap URLs for seed_url.

    Strategy:
      1. Try usp (handles robots.txt, nested indexes, gzip, news/video sitemaps).
         Retries up to `retries` times on 0-URL result or exception (network
         timeouts cause intermittent 0-URL returns).
      2. If usp returns nothing after all retries, fall back to:
         a. Manual robots.txt parse to find sitemap URLs.
         b. Direct fetch of each sitemap URL (with ScraperAPI bypass if needed).
         c. Common sitemap path probing as a last resort.

    Returns deduplicated, same-domain, non-attachment URLs.
    Falls back to [] (BFS-only crawl) if nothing works.
    """
    import time
    from config.settings import settings
    from app.utils.logger import get_logger
    log = get_logger(__name__)

    user_agent     = settings.crawler_user_agent
    scraperapi_key = getattr(settings, "scraperapi_key", None)

    base = f"{urlparse(seed_url).scheme}://{urlparse(seed_url).netloc}/"

    # ── Local helpers ─────────────────────────────────────────────────────────

    def _same_domain(url):
        return urlparse(url).netloc == urlparse(seed_url).netloc

    def _normalise(url):
        from urllib.parse import urldefrag
        url, _ = urldefrag(url)
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{p.path.rstrip('/') or '/'}"

    def _is_attachment(url):
        return any(urlparse(url).path.lower().endswith(e) for e in ATTACHMENT_EXTS)

    def _filter_and_dedup(urls):
        out, seen = [], set()
        for u in urls:
            u = u.strip()
            if not u:
                continue
            n = _normalise(u)
            if n in seen:
                continue
            seen.add(n)
            # if _same_domain(u) and not _is_attachment(u):
            if _same_domain_relaxed(u) and not _is_attachment(u):            
                out.append(n)
        return out

    # ── Layer 1: usp with retry ───────────────────────────────────────────────
    #
    # usp can return 0 URLs intermittently due to network timeouts or transient
    # bot-protection responses — retry a few times before giving up.

    for attempt in range(1, retries + 2):   # attempts: 1, 2, 3 (if retries=2)
        try:
            from usp.tree import sitemap_tree_for_homepage
            from usp.web_client.requests_client import RequestsWebClient

            session = requests.Session()
            session.headers.update({"User-Agent": user_agent})
            client = RequestsWebClient(session=session)

            tree = sitemap_tree_for_homepage(base, web_client=client)
            usp_urls = []
            for page in tree.all_pages():
                loc = (page.url or "").strip()
                # if loc and _same_domain(loc) and not _is_attachment(loc):
                if loc and _same_domain_relaxed(loc, seed_url) and not _is_attachment(loc):

                    usp_urls.append(_normalise(loc))
            usp_urls = list(dict.fromkeys(usp_urls))

            if usp_urls:
                log.info(f"Sitemap (usp) provided {len(usp_urls)} URLs "
                         f"(attempt {attempt})")
                return usp_urls

            # Got 0 URLs — retry unless this was the last attempt
            if attempt <= retries:
                log.info(
                    f"usp returned 0 URLs (attempt {attempt}/{retries + 1}) "
                    f"— retrying in 2s..."
                )
                time.sleep(2)
            else:
                log.info(
                    f"usp returned 0 URLs after {retries + 1} attempts "
                    f"— trying fallback sitemap fetch"
                )

        except Exception as e:
            if attempt <= retries:
                log.warning(
                    f"usp attempt {attempt}/{retries + 1} failed: {e} "
                    f"— retrying in 2s..."
                )
                time.sleep(2)
            else:
                log.warning(
                    f"usp failed after {retries + 1} attempts: {e} "
                    f"— trying fallback"
                )

    # ── Layer 2: manual robots.txt + direct sitemap fetch ─────────────────────
    #
    # Handles the case where usp is blocked by bot protection
    # (receives HTML instead of XML → "syntax error: line 1, column 0" → 0 URLs).
    # We fetch sitemap bytes ourselves, bypass via ScraperAPI if needed,
    # then parse <loc> tags directly.

    sitemap_urls_to_try: list[str] = []

    # 2a. Read Sitemap: directives from robots.txt
    robot_sitemaps = _parse_robots_for_sitemaps(base, user_agent)
    if robot_sitemaps:
        log.info(f"robots.txt listed {len(robot_sitemaps)} sitemap(s): {robot_sitemaps}")
        sitemap_urls_to_try.extend(robot_sitemaps)

    # 2b. Probe common sitemap paths
    common_paths = [
        "sitemap.xml",
        "sitemap_index.xml",
        "sitemap-index.xml",
        "sitemap-news.xml",
    ]
    sitemap_urls_to_try.extend(
        base.rstrip("/") + "/" + p for p in common_paths
    )

    # Deduplicate
    sitemap_urls_to_try = list(dict.fromkeys(sitemap_urls_to_try))

    all_page_urls: list[str] = []

    for sitemap_url in sitemap_urls_to_try:
        log.info(f"  Fallback fetch: {sitemap_url}")
        xml_bytes = _fetch_sitemap_xml(sitemap_url, user_agent, scraperapi_key)
        if not xml_bytes:
            log.debug(f"  Blocked or empty: {sitemap_url}")
            continue

        locs = _extract_locs(xml_bytes)
        log.info(f"  Found {len(locs)} <loc> entries in {sitemap_url}")

        # Sitemap index — <loc> entries pointing to child sitemaps → recurse one level
        child_sitemaps = [
            l for l in locs
            if any(l.endswith(ext) for ext in (".xml", ".xml.gz"))
        ]
        page_locs = [l for l in locs if l not in child_sitemaps]

        log.info(f"  → {len(page_locs)} page URLs, {len(child_sitemaps)} child sitemaps")

        all_page_urls.extend(page_locs)

        for child_url in child_sitemaps:
            log.info(f"    Fetching child sitemap: {child_url}")
            child_bytes = _fetch_sitemap_xml(child_url, user_agent, scraperapi_key)
            if child_bytes:
                child_locs = _extract_locs(child_bytes)
                log.info(f"    Found {len(child_locs)} URLs in child sitemap")
                all_page_urls.extend(child_locs)

    filtered = _filter_and_dedup(all_page_urls)

    if filtered:
        log.info(f"Sitemap fallback provided {len(filtered)} URLs")
        return filtered

    log.info("No sitemap found after all fallback attempts — using BFS crawl only")
    return []

# ── Crawl4AI config ───────────────────────────────────────────────────────

# CONSENT_JS = """
# (async () => {
#   const s = ms => new Promise(r => setTimeout(r, ms));
#   const selectors = [
#     'button[id*="accept"]', 'button[class*="accept"]',
#     'button[id*="consent"]', 'button[class*="consent"]',
#     'button[id*="agree"]',  'button[class*="agree"]',
#     'button[id*="cookie"]', 'button[class*="cookie"]',
#     'a[id*="accept"]', 'a[class*="accept"]',
#     '[data-testid*="accept"]', '[data-testid*="consent"]',
#     '.cookie-accept', '.consent-accept', '.accept-cookies',
#     '#onetrust-accept-btn-handler', '.cc-accept', '.cc-btn.cc-allow',
#   ];
#   for (const sel of selectors) {
#     try {
#       const el = document.querySelector(sel);
#       if (el && el.offsetParent !== null) { el.click(); await s(300); }
#     } catch(e) {}
#   }
#   let l = 0;
#   for (let i = 0; i < 8; i++) {
#     window.scrollTo(0, document.body.scrollHeight);
#     await s(500);
#     if (document.body.scrollHeight === l) break;
#     l = document.body.scrollHeight;
#   }
#   window.scrollTo(0, 0);
#   await s(800);
# })();
# """
CONSENT_JS = """
(async () => {
  const s = ms => new Promise(r => setTimeout(r, ms));

  // ── 1. Cookie consent / overlays ────────────────────────────────────
  const consentSelectors = [
    'button[id*="accept"]', 'button[class*="accept"]',
    'button[id*="consent"]', 'button[class*="consent"]',
    'button[id*="agree"]',  'button[class*="agree"]',
    'button[id*="cookie"]', 'button[class*="cookie"]',
    'a[id*="accept"]', 'a[class*="accept"]',
    '[data-testid*="accept"]', '[data-testid*="consent"]',
    '.cookie-accept', '.consent-accept', '.accept-cookies',
    '#onetrust-accept-btn-handler', '.cc-accept', '.cc-btn.cc-allow',
  ];
  for (const sel of consentSelectors) {
    try {
      const el = document.querySelector(sel);
      if (el && el.offsetParent !== null) { el.click(); await s(300); }
    } catch(e) {}
  }

  // ── 2. Expand accordions, tabs, show-more buttons ────────────────────
  const expandSelectors = [
    '[aria-expanded="false"]',
    '.accordion-button.collapsed',
    '[data-toggle="collapse"]',
    '[data-bs-toggle="collapse"]',
    '[role="tab"]:not([aria-selected="true"])',
    '.nav-link:not(.active)',
    'button[class*="show-more"]',
    'button[class*="load-more"]',
    'button[class*="read-more"]',
    'a[class*="show-more"]',
    '[class*="expand"]',
    'details:not([open]) summary',
  ];
  for (const sel of expandSelectors) {
    const els = document.querySelectorAll(sel);
    for (const el of els) {
      try {
        if (el.offsetParent !== null) { el.click(); await s(200); }
      } catch(e) {}
    }
  }
  // Open all <details> elements
  document.querySelectorAll('details:not([open])')
    .forEach(d => { try { d.open = true; } catch(e) {} });

  await s(500);

  // ── 3. Shadow DOM extraction ──────────────────────────────────────────
  function extractShadowText(root) {
    let text = '';
    try {
      root.querySelectorAll('*').forEach(el => {
        if (el.shadowRoot) text += extractShadowText(el.shadowRoot);
      });
      root.querySelectorAll(
        'p,h1,h2,h3,h4,h5,h6,li,span,div,article,section,main'
      ).forEach(el => {
        if (el.shadowRoot) return;
        const t = (el.innerText || el.textContent || '').trim();
        if (t) text += t + '\\n';
      });
    } catch(e) {}
    return text;
  }
  const shadowText = extractShadowText(document);
  if (shadowText.trim()) {
    const div = document.createElement('div');
    div.id = '__shadow_extracted__';
    div.style.cssText = 'display:block;position:relative;z-index:0;';
    div.innerText = shadowText;
    document.body.appendChild(div);
  }

  // ── 4. Same-origin iframe content injection ───────────────────────────
  document.querySelectorAll('iframe').forEach((iframe, idx) => {
    try {
      const doc = iframe.contentDocument || iframe.contentWindow?.document;
      if (!doc || !doc.body) return;
      const text = (doc.body.innerText || doc.body.textContent || '').trim();
      if (!text) return;
      const div = document.createElement('div');
      div.id = `__iframe_${idx}__`;
      div.style.display = 'block';
      div.innerText = '[Embedded content]:\\n' + text;
      document.body.appendChild(div);
    } catch(e) {} // cross-origin — skip silently
  });

  // ── 5. Scroll to trigger lazy-loaded content ──────────────────────────
  let lastH = 0;
  for (let i = 0; i < 8; i++) {
    window.scrollTo(0, document.body.scrollHeight);
    await s(500);
    if (document.body.scrollHeight === lastH) break;
    lastH = document.body.scrollHeight;
  }
  window.scrollTo(0, 0);
  await s(800);
})();
"""

def make_browser_config() -> BrowserConfig:
    return BrowserConfig(
        headless=True,
        verbose=False,
        user_agent=settings.crawler_user_agent,
        use_managed_browser=True,   
        browser_mode="dedicated",   
        extra_args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--window-size=1920,1080",
            "--disable-gpu",
            "--disable-extensions", 
            "--disable-background-networking",
            "--js-flags=--max-old-space-size=512",
        ],
    )


def make_run_config(max_depth: int = 3, max_pages: int = 500) -> CrawlerRunConfig:
    return CrawlerRunConfig(
        # ── Built-in BFS deep crawl — replaces all custom DFS logic ──────
        # BFSDeepCrawlStrategy handles:
        #   - depth tracking (max_depth)
        #   - deduplication (visited set)
        #   - domain restriction (include_external=False)
        #   - link discovery from each crawled page
        # No more visited sets, CrawlNode trees, or sitemap injection bugs.
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=max_depth,
            include_external=False,
            max_pages=max_pages,
        ),
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=0,
        excluded_tags=["script", "style","noscript"],
        remove_overlay_elements=False,
        wait_until="domcontentloaded",
        page_timeout=300000,
        delay_before_return_html=3.0,
        simulate_user=True,
        override_navigator=True,
        magic=True,
        js_code=CONSENT_JS,
        stream=True,
    )


def make_page_config() -> CrawlerRunConfig:
    """
    Single-page fetch config — NO deep_crawl_strategy.
    Used for arun_many() over sitemap URLs, where each URL is already
    a known target and we don't want crawl4ai to spider further.

    page_timeout is reduced to 30s here: with arun_many() crawling
    hundreds/thousands of URLs, a handful of genuinely-blocked pages
    each eating 60s adds up fast and isn't worth the wait — they're
    logged as failures and the rest of the crawl continues.
    """
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=0,
        excluded_tags=["script", "style","noscript"],
        remove_overlay_elements=False,
        wait_until="domcontentloaded",
        page_timeout=300000, #5 min
        delay_before_return_html=2.0,
        simulate_user=True,
        override_navigator=True,
        magic=True,
        js_code=CONSENT_JS,
        wait_for="css:body",
        mean_delay=0.5,        # small jitter between requests per worker
        max_range=1.0,
        stream=True,
    )


from bs4 import BeautifulSoup
def fetch_via_scraperapi(target_url: str) -> str | None:
    try:
        resp = requests.get(
            "https://api.scraperapi.com/",
            params={"api_key": settings.scraperapi_key, "url": target_url, "render": "true"},
            timeout=90,
        )
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        log.warning(f"  ScraperAPI fallback failed for {target_url}: {e}")
        return None

def process_page_content(
    page_url: str,
    html: str,
    text: str,
    title: str,
    depth: int,
    job_id: int,
    seed_url: str,
    attach_seen: set,
    attach_saved: list,
    img_saved: list,
) -> Path:
    folder = page_folder(seed_url, page_url)

    if text:
        (folder / "page.txt").write_text(text, encoding="utf-8")
        publish_page(url=page_url, title=title, text=text, depth=depth, job_id=job_id)

    if job_id is not None:
        try:
            db.crawl_url_mark_scraped(
                job_id, normalise_url(page_url), page_id=None, local_path=str(folder.resolve())
            )
        except Exception as e:
            log.warning(f"  crawl_url_mark_scraped failed: {e}")

    if html:
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup.find_all("a", href=True):
            href = urljoin(page_url, tag["href"].strip())
            href, _ = urldefrag(href)
            if href and is_attachment_url(href) and href not in attach_seen:
                attach_seen.add(href)
                path = download_file(
                    href, job_id=job_id,
                    dest_folder=folder / "attachments",
                    page_url=page_url,
                )
                if path:
                    attach_saved.append(path)

        seen_imgs = set()
        for tag in soup.find_all("img"):
            src = tag.get("src") or tag.get("data-src") or ""
            src = src.strip()
            if not src or src.startswith("data:"):
                continue
            img_href = urljoin(page_url, src)
            img_href, _ = urldefrag(img_href)
            if img_href in seen_imgs:
                continue
            seen_imgs.add(img_href)
            img_path = download_image(
                img_href, job_id=job_id,
                dest_folder=folder / "images",
                page_url=page_url,
            )
            if img_path:
                img_saved.append(img_path)

    return folder



# ── Text cleaner ──────────────────────────────────────────────────────────

def clean_text(raw: str) -> str:
    if not raw:
        return ""

    def tag_h(m):
        return f"\n[H{len(m.group(1))}]{m.group(2).strip()}\n"

    raw = re.sub(r"^(#{1,6})\s+(.+)$", tag_h, raw, flags=re.MULTILINE)
    raw = re.sub(r"!\[.*?\]\(.*?\)", "", raw)
    raw = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", raw)
    raw = re.sub(r"`{1,3}[^`]*`{1,3}", "", raw)
    raw = re.sub(r"\*{1,2}(.*?)\*{1,2}", r"\1", raw)
    raw = re.sub(r"_{1,2}(.*?)_{1,2}", r"\1", raw)
    raw = re.sub(r"^[-*+]\s+", "• ", raw, flags=re.MULTILINE)
    raw = re.sub(r"^\d+\.\s+", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\|.*?\|", "", raw)
    raw = re.sub(r"^[-=]{3,}$", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"&[a-z]+;", " ", raw)
    raw = re.sub(r"<[^>]+>", "", raw)

    lines, paragraphs, current = raw.splitlines(), [], []
    for line in lines:
        s = line.strip()
        if not s:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append("")
        elif s.startswith("[H") or s.startswith("•"):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append(s)
        else:
            current.append(s)
    if current:
        paragraphs.append(" ".join(current))

    return re.sub(r"\n{3,}", "\n\n", "\n".join(paragraphs)).strip()


# ── File downloader ───────────────────────────────────────────────────────

def download_file(url: str, job_id: int = None,
                   dest_folder: Path = None, page_url: str = "") -> Path | None:
    """
    Download an attachment (PDF/DOC/XLSX/...) into dest_folder
    (defaults to OUTPUT_DIR for backwards compatibility), publish to
    Kafka for parsing/chunking, and record metadata in the
    `attachments` DB table.
    """
    folder = dest_folder or OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": settings.crawler_user_agent},
            stream=True,
            timeout=settings.crawler_request_timeout,
        )
        resp.raise_for_status()
        from urllib.parse import unquote
        cd = resp.headers.get("Content-Disposition", "")
        fname = re.search(r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\n]+)', cd)
        fname = (
            fname.group(1).strip('"').strip()
            if fname
            else unquote(urlparse(url).path).split("/")[-1] or "file"
        )
        stem = Path(fname).stem
        ext = Path(fname).suffix.lower() or \
              mimetypes.guess_extension(
                  resp.headers.get("Content-Type", "").split(";")[0].strip()
              ) or ".bin"
        out = folder / safe_filename(stem, ext)
        with open(out, "wb") as f:
            for chunk in resp.iter_content(32768):
                if chunk:
                    f.write(chunk)
        size = out.stat().st_size
        log.info(f"  ↓ {out.name}  ({size // 1024} KB)")

        if ext.lower() in {".pdf", ".doc", ".docx"}:
            publish_attachment(out, url, ext, job_id=job_id)

        if job_id is not None:
            try:
                db.attachment_save(
                    job_id=job_id, page_url=page_url, source_url=url,
                    file_path=str(out.resolve()), file_type=ext.lstrip("."),
                    file_size=size,
                )
            except Exception as e:
                log.warning(f"  attachment_save failed for {url}: {e}")

        return out
    except Exception as e:
        log.error(f"Download failed {url}: {e}")
        return None


def download_image(url: str, job_id: int = None,
                    dest_folder: Path = None, page_url: str = "") -> Path | None:
    """
    Download an image, check its resolution against MIN_IMAGE_WIDTH /
    MIN_IMAGE_HEIGHT, and only KEEP it (saved to disk + recorded in DB)
    if it meets the threshold — this filters out logos, icons, social
    badges, and other small decorative images, keeping likely
    flowcharts/diagrams/screenshots.

    Returns the saved Path if kept, or None if skipped/filtered/failed.
    """
    folder = dest_folder or OUTPUT_DIR
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": settings.crawler_user_agent},
            stream=True,
            timeout=settings.crawler_request_timeout,
        )
        resp.raise_for_status()
        content = resp.content

        # Determine dimensions
        try:
            with Image.open(_io.BytesIO(content)) as im:
                width, height = im.size
        except Exception:
            # Not a readable raster image (e.g. SVG) — skip resolution check
            log.debug(f"  Skipping non-raster image (cannot read dims): {url}")
            return None

        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            log.debug(f"  Skipping small image {width}x{height}: {url}")
            return None

        from urllib.parse import unquote
        fname = unquote(urlparse(url).path).split("/")[-1] or "image"
        stem = Path(fname).stem or "image"
        ext = Path(fname).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
            ext = mimetypes.guess_extension(
                resp.headers.get("Content-Type", "").split(";")[0].strip()
            ) or ".jpg"

        folder.mkdir(parents=True, exist_ok=True)
        out = folder / safe_filename(stem, ext)
        with open(out, "wb") as f:
            f.write(content)

        size = len(content)
        log.info(f"  🖼  {out.name}  {width}x{height}  ({size // 1024} KB)")

        if job_id is not None:
            try:
                db.image_save(
                    job_id=job_id, page_url=page_url, source_url=url,
                    file_path=str(out.resolve()), width=width, height=height,
                    file_size=size,
                )
            except Exception as e:
                log.warning(f"  image_save failed for {url}: {e}")

        return out
    except Exception as e:
        log.debug(f"  Image download failed {url}: {e}")
        return None


# ── BFS crawler ───────────────────────────────────────────────────────────



async def bfs_crawl(
    seed_url: str,
    job_id: int = None,
    max_depth: int = 3,
    max_url: int = None,   
) -> tuple[list, list[Path]]:
    """
    Crawl strategy:

      1. Fetch the full sitemap via usp (handles robots.txt, nested
         sitemap indexes, gzip, etc.) -- used ONLY for validation /
         seeding the crawl_urls coverage table (job_id is not None).
         The sitemap is NOT used to drive the crawl itself.

      2. Crawl via BFSDeepCrawlStrategy (link-discovery crawl) starting
         from the seed URL, with stream=True so each page is processed
         as soon as it's crawled (live progress) instead of waiting for
         the entire BFS to finish.
    """
    flat = []
    attach_saved = []
    img_saved = []
    attach_seen = set()

    # -- Step 1: Fetch sitemap URLs (usp) — validation/seeding only ---------
    sitemap_urls = fetch_sitemap_urls(seed_url)
    log.info(f"Sitemap discovered {len(sitemap_urls)} URLs (used for validation only)")

    # -- Step 2: Seed DB coverage table (independent of max_url) -------------
    # Always seed with whatever sitemap returned — this is for coverage
    # tracking only, not for controlling the crawl limit.
    if job_id is not None and sitemap_urls:
        # try:
        #     db.crawl_urls_seed(job_id, sitemap_urls, source="sitemap")

        # try:
        # # Include seed URL in seeding so dashboard count matches crawl count
        #     all_urls_to_seed = list(dict.fromkeys(
        #         [normalise_url(seed_url)] + sitemap_urls
        #     ))

        #     all_seed_urls = list(dict.fromkeys(sitemap_urls))
        #     log.info(f"Seeding {len(all_seed_urls)} sitemap URLs")

        #     # For crawling, add seed URL separately but don't seed it as 'sitemap':
        #     urls_to_crawl = list(dict.fromkeys(
        #         [normalise_url(seed_url)] + sitemap_urls
        #     ))[:effective_max_pages]
        #     db.crawl_urls_seed(job_id, all_urls_to_seed, source="sitemap")
        # except Exception as e:
        #     log.warning(f"crawl_urls_seed failed: {e}")

        try:
            # Seed only sitemap URLs (37) — without adding seed URL
            all_seed_urls = list(dict.fromkeys(sitemap_urls))
            log.info(f"Seeding {len(all_seed_urls)} sitemap URLs")
            db.crawl_urls_seed(job_id, all_seed_urls, source="sitemap")  # ← all_seed_urls not all_urls_to_seed

            # For crawling, add seed URL separately (may differ by www.)
            urls_to_crawl = list(dict.fromkeys(
                [normalise_url(seed_url)] + sitemap_urls
            ))[:effective_max_pages]

        except Exception as e:
            log.warning(f"crawl_urls_seed failed: {e}")


    # Determine effective URL limit
    # if max_url is not None:
    #     effective_max_pages = max_url
    #     log.info(f"max_url: user-defined = {effective_max_pages}")
    # elif sitemap_urls:
    #     effective_max_pages = len(sitemap_urls)
    #     log.info(f"max_url: auto from sitemap = {effective_max_pages}")
    # else:
    #     effective_max_pages = 99999
    #     log.info(f"max_url: auto no-sitemap = {effective_max_pages} (unlimited)")

    if max_url is not None and max_url > 0:
        effective_max_pages = max_url
        log.info(f"max_url: user-defined = {effective_max_pages}")
    elif sitemap_urls:
        effective_max_pages = len(sitemap_urls)
        log.info(f"max_url: auto from sitemap = {effective_max_pages}")
    else:
        effective_max_pages = 99999
        log.info(f"max_url: auto no-sitemap = {effective_max_pages} (unlimited)")


    async with AsyncWebCrawler(config=make_browser_config()) as crawler:
        log.info(f"Starting BFS deep crawl (streaming, max_pages={effective_max_pages})")

        # log.info("Starting BFS deep crawl (streaming)")
        config = make_run_config(max_depth=max_depth, max_pages=effective_max_pages+1)

        page_num = 0
        async for result in await crawler.arun(normalise_url(seed_url), config=config):
            page_num += 1
            page_url = normalise_url(result.url)

            # if not result.success:
            #     status = getattr(result, "status_code", "?")
            #     reason = (result.error_message or f"HTTP {status}")[:300]
            #     log.warning(f"  [{page_num}] X FAILED [{status}] {result.url}")
            #     log.warning(f"     reason: {reason}")

            #     recovered = False
            #     if any(k in reason for k in ("ANTIBOT", "Cloudflare", "Timeout", "ACS-GOTO")):
            #         html = fetch_via_scraperapi(result.url)
            #         if html:
            #             title = urlparse(result.url).netloc
            #             text = clean_text(BeautifulSoup(html, "html.parser").get_text("\n"))
            #             depth = result.metadata.get("depth", 0) if result.metadata else 0
            #             process_page_content(
            #                 page_url=result.url,
            #                 html=html,
            #                 text=text,
            #                 title=title,
            #                 depth=depth,
            #                 job_id=job_id,
            #                 seed_url=seed_url,
            #                 attach_seen=attach_seen,
            #                 attach_saved=attach_saved,
            #                 img_saved=img_saved,
            #             )
            #             flat.append(result)
            #             log.info(f"  [{page_num}] OK Recovered via ScraperAPI: {result.url} ({len(text)} chars)")
            #             recovered = True

            #     if not recovered and job_id is not None:
            #         try:
            #             db.crawl_url_mark_failed(job_id, page_url, reason)
            #         except Exception as e:
            #             log.warning(f"  crawl_url_mark_failed failed: {e}")
            #     continue

            if not result.success:
                status = getattr(result, "status_code", "?")
                reason = (result.error_message or f"HTTP {status}")[:300]
                reason_lower = reason.lower()
                log.warning(f"  [{page_num}] X FAILED [{status}] {result.url}")
                log.warning(f"     reason: {reason}")

                # Transient Playwright race conditions + real anti-bot blocks
                # both go through ScraperAPI immediately — no waiting
                SCRAPER_TRIGGERS = (
                    "antibot", "cloudflare", "timeout", "acs-goto",
                    "anti-bot", "blocked", "403", "net::err",
                    "unable to retrieve content",      # ← Playwright race condition
                    "page is navigating",              # ← Playwright race condition
                    "unexpected error in _crawl_web",  # ← Playwright internal error
                    "page.content",                    # ← Playwright content grab fail
                )

                recovered = False
                if any(k in reason_lower for k in SCRAPER_TRIGGERS):
                    html = fetch_via_scraperapi(result.url)
                    if html:
                        title = urlparse(result.url).netloc
                        text = clean_text(BeautifulSoup(html, "html.parser").get_text("\n"))
                        depth = result.metadata.get("depth", 0) if result.metadata else 0
                        process_page_content(
                            page_url=result.url,
                            html=html,
                            text=text,
                            title=title,
                            depth=depth,
                            job_id=job_id,
                            seed_url=seed_url,
                            attach_seen=attach_seen,
                            attach_saved=attach_saved,
                            img_saved=img_saved,
                        )
                        flat.append(result)
                        log.info(f"  [{page_num}] OK Recovered via ScraperAPI: {result.url} ({len(text)} chars)")
                        recovered = True

                if not recovered and job_id is not None:
                    try:
                        db.crawl_url_mark_failed(job_id, page_url, reason)
                    except Exception as e:
                        log.warning(f"  crawl_url_mark_failed failed: {e}")
                continue

            depth = result.metadata.get("depth", 0)
            from app.services.content_validator import validate_formats

            # ── Content validation (raw→clean→md pipeline quality check) ───────
            try:
                val_report = validate_formats(
                    url=result.url,
                    raw_html=result.html or "",
                    cleaned_html=result.cleaned_html or "",
                    markdown=result.markdown or "",
                    job_id=job_id,
                )
                if job_id is not None and not val_report.get("skipped"):
                    db.validation_save(val_report)
            except Exception as e:
                log.warning(f"  validation failed for {result.url}: {e}")
            # ────────────────────────────────────────────────────────────────────
            text = clean_text(result.markdown or result.cleaned_html or "")
            title = result.metadata.get("title", "") or urlparse(result.url).netloc

            # ── Cloudflare JS challenge can return success=True with a
            # near-empty "Just a moment..." challenge page as content ──────
            cf_markers = ("just a moment", "checking your browser", "cloudflare")
            is_cf_challenge = (
                len(text) < 500 and any(m in text.lower() for m in cf_markers)
            )

            if is_cf_challenge:
                log.warning(f"  [{page_num}] Cloudflare challenge page detected: {result.url}")
                html = fetch_via_scraperapi(result.url)
                if html:
                    text = clean_text(BeautifulSoup(html, "html.parser").get_text("\n"))
                    process_page_content(
                        page_url=result.url, html=html, text=text, title=title,
                        depth=depth, job_id=job_id, seed_url=seed_url,
                        attach_seen=attach_seen, attach_saved=attach_saved, img_saved=img_saved,
                    )
                    flat.append(result)
                    log.info(f"  [{page_num}] OK Recovered via ScraperAPI: {result.url} ({len(text)} chars)")
                else:
                    if job_id is not None:
                        try:
                            db.crawl_url_mark_failed(job_id, page_url, "Cloudflare JS challenge")
                        except Exception as e:
                            log.warning(f"  crawl_url_mark_failed failed: {e}")
                continue

            log.info(f"[{page_num}] [depth={depth}/{max_depth}] OK [{title[:40]}] {len(text)} chars — {result.url}")

            process_page_content(
                page_url=result.url,
                html=result.html or "",
                text=text,
                title=title,
                depth=depth,
                job_id=job_id,
                seed_url=seed_url,
                attach_seen=attach_seen,
                attach_saved=attach_saved,
                img_saved=img_saved,
            )

            flat.append(result)
    if job_id is not None:
        try:
            skipped = db.crawl_urls_mark_uncrawled(job_id)
            if skipped:
                log.info(f"  {skipped} sitemap URL(s) not reached → not_crawled")
        except Exception as e:
            log.warning(f"  crawl_urls_mark_uncrawled failed: {e}")

    flush()

    publish_job_complete(
        job_id=job_id,
        total_pages=len(flat),
        total_attachments=len(attach_saved),
    )

    log.info(
        f"Crawl complete — {len(flat)} pages, "
        f"{len(attach_saved)} attachments, {len(img_saved)} images saved"
    )
    return flat, attach_saved


# ── PDF builder ───────────────────────────────────────────────────────────

def _find_font() -> str | None:
    for p in [
        Path(__file__).parent / "DejaVuSans.ttf",
        Path("DejaVuSans.ttf"),
        Path(r"C:/Windows/Fonts/DejaVuSans.ttf"),
    ]:
        if p.exists():
            return str(p)
    return None


def build_pdf(results: list, seed_url: str, out_path: Path):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    fp = _find_font()
    uni = False
    if fp:
        pdf.add_font("DejaVu", "", fp)
        pdf.add_font("DejaVu", "B", fp)
        uni = True

    for result in results:
        text = clean_text(result.markdown or result.cleaned_html or "")
        if not text:
            continue
        title = sanitise(result.metadata.get("title", "") or urlparse(result.url).netloc)
        pdf.add_page()
        pdf.set_font("DejaVu" if uni else "Helvetica", "B", 13)
        pdf.set_text_color(20, 20, 20)
        if not uni:
            title = title.encode("latin-1", errors="replace").decode("latin-1")
        pdf.multi_cell(0, 8, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
        pdf.set_font("DejaVu" if uni else "Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        for para in text.split("\n"):
            para = sanitise(para.strip())
            if not para:
                pdf.ln(3)
                continue
            if not uni:
                para = para.encode("latin-1", errors="replace").decode("latin-1")
            pdf.multi_cell(0, 6, para, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1)

    pdf.output(str(out_path))
    log.info(f"PDF saved: {out_path.name} ({out_path.stat().st_size // 1024} KB)")

# drive link handler
def extract_drive_file_id(url: str) -> str | None:
    """Extract file ID from various Google Drive URL formats."""
    # https://drive.google.com/file/d/<ID>/view?usp=sharing
    m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    # https://drive.google.com/open?id=<ID>
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None


def download_drive_file(url: str, job_id: int = None) -> Path | None:
    """
    Download a publicly-shared Google Drive file and publish it as
    an attachment for the consumer to parse/chunk/store.
    """
    file_id = extract_drive_file_id(url)
    if not file_id:
        log.error(f"Could not extract file ID from Drive URL: {url}")
        return None

    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    try:
        session = requests.Session()
        resp = session.get(download_url, stream=True, timeout=settings.crawler_request_timeout)

        # Handle Drive's "confirm download" page for large files
        if "text/html" in resp.headers.get("Content-Type", ""):
            # Look for confirm token
            m = re.search(r"confirm=([0-9A-Za-z_-]+)", resp.text)
            if m:
                token = m.group(1)
                download_url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm={token}"
                resp = session.get(download_url, stream=True, timeout=settings.crawler_request_timeout)

        resp.raise_for_status()

        # Determine filename/extension from headers
        cd = resp.headers.get("Content-Disposition", "")
        m = re.search(r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\n]+)', cd)
        fname = m.group(1).strip('"').strip() if m else f"drive_{file_id}"
        stem = Path(fname).stem
        ext = Path(fname).suffix.lower() or \
              mimetypes.guess_extension(
                  resp.headers.get("Content-Type", "").split(";")[0].strip()
              ) or ".bin"

        out = OUTPUT_DIR / safe_filename(stem, ext)
        with open(out, "wb") as f:
            for chunk in resp.iter_content(32768):
                if chunk:
                    f.write(chunk)

        size = out.stat().st_size
        log.info(f"  ↓ {out.name}  ({size // 1024} KB)")

        if ext.lower() in {".pdf", ".doc", ".docx"}:
            publish_attachment(out, url, ext, job_id=job_id)

        if job_id is not None:
            try:
                db.attachment_save(
                    job_id=job_id, page_url=url, source_url=url,
                    file_path=str(out.resolve()), file_type=ext.lstrip("."),
                    file_size=size,
                )
            except Exception as e:
                log.warning(f"  attachment_save failed for {url}: {e}")

        return out

    except Exception as e:
        log.error(f"Drive download failed {url}: {e}")
        return None
    
# ── Entry point ───────────────────────────────────────────────────────────

# def run(url: str, job_id: int = None, max_depth: int = 3):
def run(url: str, job_id: int = None, max_depth: int = 3, max_url: int = None):

    log.info("─" * 60)
    log.info(f"Crawl started: {url}  job_id={job_id}  max_depth={max_depth}")
    log.info("─" * 60)
    log.info(f"Crawl started: {url}  job_id={job_id}  max_depth={max_depth}  max_url={max_url or 'auto'}")

    if is_drive_url(url):
        log.info("Mode: Google Drive")
        download_drive_file(url, job_id=job_id)
    elif is_attachment_url(url):
        log.info("Mode: Direct file download")
        download_file(url, job_id=job_id)
    else:
        log.info("Mode: Website BFS crawl (crawl4ai BFSDeepCrawlStrategy)")
        flat, _ = asyncio.run(
            bfs_crawl(seed_url=url, job_id=job_id, max_depth=max_depth, max_url=max_url)
        )
        seed_title = (
            flat[0].metadata.get("title", "") if flat else ""
        ) or urlparse(url).netloc
        pdf_path = OUTPUT_DIR / safe_filename(seed_title)
        build_pdf(flat, url, pdf_path)
        log.info(f"Crawl complete — {len(flat)} pages crawled, PDF: {pdf_path.name}")


if __name__ == "__main__":
    # Reconfigure stdout/stderr for UTF-8 + line buffering (safe on Windows pipes)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

    url        = sys.stdin.readline().strip()
    job_id_raw = sys.stdin.readline().strip()
    depth_raw  = sys.stdin.readline().strip()
    pages_raw  = sys.stdin.readline().strip()   


    job_id    = int(job_id_raw) if job_id_raw.isdigit() else None
    max_depth = int(depth_raw)  if depth_raw.isdigit()  else 3
    max_url = int(pages_raw) if pages_raw.isdigit() and int(pages_raw) > 0 else None


    if not url.startswith("http"):
        url = "https://" + url

    run(url, job_id=job_id, max_depth=max_depth,max_url=max_url)