import asyncio
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig


# =====================================================
# CONFIGURATION
# =====================================================

URL = "https://www.kratosolutions.com/"

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

ATTACHMENT_EXTS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".csv",
}


# =====================================================
# HELPERS
# =====================================================

def same_domain(url, base):
    return urlparse(url).netloc == urlparse(base).netloc


def is_attachment(url):
    return any(
        urlparse(url).path.lower().endswith(ext)
        for ext in ATTACHMENT_EXTS
    )


def clean_text(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def save_page(url, content):
    parsed = urlparse(url)

    filename = parsed.path.strip("/")

    if not filename:
        filename = "index"

    filename = filename.replace("/", "_")

    filepath = OUTPUT_DIR / f"{filename}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Saved: {filepath}")


def download_attachment(url):
    try:
        response = requests.get(url, timeout=30)

        response.raise_for_status()

        filename = url.split("/")[-1]

        filepath = OUTPUT_DIR / filename

        with open(filepath, "wb") as f:
            f.write(response.content)

        print(f"Downloaded attachment: {filename}")

    except Exception as e:
        print(f"Failed attachment download: {url}")
        print(e)


# =====================================================
# CRAWLER
# =====================================================

visited = set()


async def crawl_page(crawler, url, seed_url):

    if url in visited:
        return

    visited.add(url)

    print(f"\nCrawling: {url}")

    try:

        result = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(
                page_timeout=60000,
                wait_until="domcontentloaded",
            ),
        )

        if not result.success:
            print("Failed")
            return

        content = clean_text(
            result.markdown
            or result.cleaned_html
            or ""
        )

        save_page(url, content)

        links = set()

        if result.html:
            soup = BeautifulSoup(
                result.html,
                "html.parser"
            )

            for tag in soup.find_all("a", href=True):

                href = tag["href"]

                absolute = urljoin(url, href)

                links.add(absolute)

        for link in links:

            if is_attachment(link):
                download_attachment(link)

            elif (
                same_domain(link, seed_url)
                and link not in visited
            ):
                await crawl_page(
                    crawler,
                    link,
                    seed_url,
                )

    except Exception as e:
        print(e)


# =====================================================
# MAIN
# =====================================================

async def main():

    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
    )

    async with AsyncWebCrawler(
        config=browser_config
    ) as crawler:

        await crawl_page(
            crawler,
            URL,
            URL,
        )


if __name__ == "__main__":
    asyncio.run(main())