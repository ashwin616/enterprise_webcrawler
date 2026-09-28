
"""
app/services/doc_parser.py
───────────────────────────
Multi-format document parser.
Extracts text + tables from PDF, DOCX, TXT, CSV, XLSX, PPTX, JSON.

No LLM calls — pure extraction only.
Tables extracted as JSON rows { header: value } — ready for chunking.

Supported formats: .pdf .docx .doc .txt .csv .xlsx .xls .pptx .json

Based on table_extract2.py approach.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List

from app.utils.logger import get_logger

log = get_logger(__name__)


# ── PDF ───────────────────────────────────────────────────────────────────
from tqdm import tqdm



# ── PDF: full extraction (text + images + page-numbered txt) ─────────────
# ── PDF: full extraction (text + images + page-numbered txt) ─────────────

MIN_PDF_IMAGE_WIDTH = 200
MIN_PDF_IMAGE_HEIGHT = 200


def extract_pdf_full(file_path: str) -> dict:
    """
    Extract from PDF and organize everything into a per-document folder:

        <attachments>/<stem>/
            <stem>.pdf          ← original file (moved here)
            <stem>_pages.txt    ← page-numbered text (text + JSON tables)
            images/
                <stem>_p3_img1.png
                ...

    Returns:
        {
            "blocks": List[str],
            "txt_path": Path | None,
            "images": List[dict],
            "pdf_path": Path,     # new location of the PDF
            "doc_dir": Path,      # the per-document folder
        }
    """
    import fitz  # PyMuPDF
    import pdfplumber
    import shutil

    src = Path(file_path)
    stem = src.stem
    doc_dir = src.parent / stem
    images_dir = doc_dir / "images"
    doc_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"Parsing PDF (full): {file_path}")
    log.info(f"  Output folder: {doc_dir}")

    blocks: List[str] = []
    page_texts: List[str] = []
    images_out: List[dict] = []

    # ── Text + tables via pdfplumber ───────────────────────────────────
    devnull = open(os.devnull, "w")
    old_stderr = sys.stderr
    sys.stderr = devnull
    try:
        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            log.info(f"  PDF has {total_pages} pages — extracting text...")

            for page_num, page in enumerate(pdf.pages, start=1):
                if page_num % 10 == 0 or page_num == total_pages:
                    print(f"  [text] page {page_num}/{total_pages}", flush=True)

                page_content_parts = []

                text = page.extract_text() or ""
                if text.strip():
                    page_content_parts.append(text.strip())
                    blocks.append(f"\n--- PDF Page {page_num} ---\n")
                    blocks.append(text.strip())

                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    headers = table[0]
                    table_header = f"\n[Table on PDF Page {page_num}]\n"
                    blocks.append(table_header)
                    page_content_parts.append(table_header)

                    for row in table[1:]:
                        row_dict = {
                            headers[i]: row[i] if i < len(row) else None
                            for i in range(len(headers))
                            if headers[i]
                        }
                        row_json = json.dumps(row_dict, ensure_ascii=False)
                        blocks.append(row_json)
                        page_content_parts.append(row_json)

                # page_texts now mirrors blocks for this page (text + JSON tables)
                page_texts.append("\n".join(page_content_parts))
    finally:
        sys.stderr = old_stderr
        devnull.close()

    log.info(f"  Extracted text from {len(page_texts)} pages")

    # ── Images via PyMuPDF ──────────────────────────────────────────────
    try:
        doc = fitz.open(file_path)
        total_pages_img = len(doc)
        log.info(f"  Extracting images from {total_pages_img} pages...")

        for page_num in range(total_pages_img):
            if (page_num + 1) % 10 == 0 or (page_num + 1) == total_pages_img:
                print(f"  [images] page {page_num+1}/{total_pages_img}", flush=True)

            page = doc[page_num]
            for img_index, img in enumerate(page.get_images(full=True), start=1):
                xref = img[0]
                try:
                    base_image = doc.extract_image(xref)
                    img_bytes = base_image["image"]
                    ext = base_image.get("ext", "png")
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)

                    if width < MIN_PDF_IMAGE_WIDTH or height < MIN_PDF_IMAGE_HEIGHT:
                        continue

                    images_dir.mkdir(parents=True, exist_ok=True)
                    img_name = f"{stem}_p{page_num+1}_img{img_index}.{ext}"
                    img_path = images_dir / img_name
                    img_path.write_bytes(img_bytes)

                    images_out.append({
                        "path": img_path,
                        "width": width,
                        "height": height,
                        "page": page_num + 1,
                        "size": len(img_bytes),
                    })
                except Exception as e:
                    log.debug(f"  Skipping image xref={xref} on page {page_num+1}: {e}")
        doc.close()
        log.info(f"  Extracted {len(images_out)} image(s) >= {MIN_PDF_IMAGE_WIDTH}x{MIN_PDF_IMAGE_HEIGHT}")
    except Exception as e:
        log.warning(f"  Image extraction failed: {e}")

    # ── Page-numbered text file ────────────────────────────────────────
    txt_path = doc_dir / f"{stem}_pages.txt"
    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            for i, text in enumerate(page_texts, start=1):
                f.write(f"--- Page {i} ---\n")
                f.write(text + "\n\n")
        log.info(f"  Page-numbered text saved: {txt_path.name}")
    except Exception as e:
        log.warning(f"  Failed to write page-numbered txt: {e}")
        txt_path = None

    # ── Move original PDF into its own folder ──────────────────────────
    pdf_path = doc_dir / src.name
    try:
        shutil.move(str(src), str(pdf_path))
        log.info(f"  Moved PDF into: {pdf_path}")
    except Exception as e:
        log.warning(f"  Failed to move PDF into folder: {e}")
        pdf_path = src

    return {
        "blocks": blocks,
        "txt_path": txt_path,
        "images": images_out,
        "pdf_path": pdf_path,
        "doc_dir": doc_dir,
    }

def extract_pdf(file_path: str) -> List[str]:
    """
    Extract text + tables from PDF using pdfplumber.
    - Text extracted per page with page header
    - Tables extracted as JSON rows { header: value }
    - stderr suppressed to avoid Windows reentrant BufferedWriter error
    """
    import pdfplumber

    log.info(f"Parsing PDF: {file_path}")
    content = []

    devnull = open(os.devnull, "w")
    old_stderr = sys.stderr
    sys.stderr = devnull

    try:
        with pdfplumber.open(file_path) as pdf:
            log.debug(f"  PDF pages: {len(pdf.pages)}")
            # for page_num, page in enumerate(pdf.pages, start=1):
            for page_num, page in enumerate(tqdm(pdf.pages, desc="Parsing PDF pages", unit="page"), start=1):


                # Text
                text = page.extract_text()
                if text and text.strip():
                    content.append(f"\n--- PDF Page {page_num} ---\n")
                    content.append(text.strip())

                # Tables → JSON rows
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    headers = table[0]
                    content.append(f"\n[Table on PDF Page {page_num}]\n")
                    for row in table[1:]:
                        row_dict = {
                            headers[i]: row[i] if i < len(row) else None
                            for i in range(len(headers))
                            if headers[i]
                        }
                        content.append(json.dumps(row_dict, ensure_ascii=False))
    finally:
        sys.stderr = old_stderr
        devnull.close()

    log.info(f"  Extracted {len(content)} text blocks from PDF")
    return content



# ── DOCX ──────────────────────────────────────────────────────────────────
def extract_docx_full(file_path: str) -> dict:
    """
    Extract from DOCX and organize into a per-document folder:

        <attachments>/<stem>/
            <stem>.docx
            <stem>_text.txt
            images/
                <stem>_<media_name>
    """
    from docx import Document
    import zipfile
    import shutil

    src = Path(file_path)
    stem = src.stem
    doc_dir = src.parent / stem
    images_dir = doc_dir / "images"
    doc_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"Parsing DOCX (full): {file_path}")
    log.info(f"  Output folder: {doc_dir}")

    doc = Document(file_path)
    blocks = []
    total_paras = len(doc.paragraphs)
    log.info(f"  DOCX has {total_paras} paragraphs — extracting text...")

    for i, para in enumerate(doc.paragraphs, start=1):
        if i % 50 == 0 or i == total_paras:
            print(f"  [text] paragraph {i}/{total_paras}", flush=True)
        if para.text.strip():
            blocks.append(para.text.strip())

    images_out = []
    try:
        with zipfile.ZipFile(file_path) as z:
            media_files = [n for n in z.namelist() if n.startswith("word/media/")]
            total_imgs = len(media_files)
            if total_imgs:
                log.info(f"  Extracting {total_imgs} embedded image(s)...")

            for idx, name in enumerate(media_files, start=1):
                print(f"  [images] {idx}/{total_imgs}", flush=True)
                data = z.read(name)
                if len(data) < 5000:
                    continue
                images_dir.mkdir(parents=True, exist_ok=True)
                out_name = f"{stem}_{Path(name).name}"
                out_path = images_dir / out_name
                out_path.write_bytes(data)

                try:
                    from PIL import Image
                    import io as _io
                    with Image.open(_io.BytesIO(data)) as im:
                        w, h = im.size
                except Exception:
                    w, h = 0, 0

                images_out.append({
                    "path": out_path, "width": w, "height": h,
                    "page": None, "size": len(data),
                })
    except Exception as e:
        log.warning(f"  DOCX image extraction failed: {e}")

    log.info(f"  Extracted {len(blocks)} paragraphs, {len(images_out)} image(s)")

    txt_path = doc_dir / f"{stem}_text.txt"
    try:
        txt_path.write_text("\n\n".join(blocks), encoding="utf-8")
        log.info(f"  Text file saved: {txt_path.name}")
    except Exception as e:
        log.warning(f"  Failed to write text file: {e}")
        txt_path = None

    docx_path = doc_dir / src.name
    try:
        shutil.move(str(src), str(docx_path))
        log.info(f"  Moved DOCX into: {docx_path}")
    except Exception as e:
        log.warning(f"  Failed to move DOCX into folder: {e}")
        docx_path = src

    return {
        "blocks": blocks,
        "txt_path": txt_path,
        "images": images_out,
        "pdf_path": docx_path,  # reuse same key name for consumer compatibility
        "doc_dir": doc_dir,
    }


def extract_docx(file_path: str) -> List[str]:
    """Extract paragraphs from Word documents."""
    from docx import Document

    log.info(f"Parsing DOCX: {file_path}")
    doc = Document(file_path)
    content = []

    # for para in doc.paragraphs:
    for para in tqdm(doc.paragraphs, desc="Parsing DOCX paragraphs", unit="para"):

        if para.text.strip():
            content.append(para.text.strip())

    log.info(f"  Extracted {len(content)} paragraphs from DOCX")
    return content


# ── TXT ───────────────────────────────────────────────────────────────────

def extract_txt(file_path: str) -> List[str]:
    """Read plain text file as-is."""
    log.info(f"Parsing TXT: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return [f.read()]


# ── CSV ───────────────────────────────────────────────────────────────────

def extract_csv(file_path: str) -> List[str]:
    """Extract CSV rows as JSON records using pandas."""
    import pandas as pd

    log.info(f"Parsing CSV: {file_path}")
    df = pd.read_csv(file_path)
    log.info(f"  Extracted {len(df)} rows from CSV")
    return [df.to_json(orient="records", force_ascii=False, indent=2)]


# ── XLSX ──────────────────────────────────────────────────────────────────

def extract_excel(file_path: str) -> List[str]:
    """Extract each Excel sheet as JSON records using pandas."""
    import pandas as pd

    log.info(f"Parsing XLSX: {file_path}")
    sheets = pd.read_excel(file_path, sheet_name=None)
    content = []

    for sheet_name, df in sheets.items():
        content.append(f"\n--- Sheet: {sheet_name} ---\n")
        content.append(df.to_json(orient="records", force_ascii=False, indent=2))

    log.info(f"  Extracted {len(sheets)} sheets from Excel")
    return content


# ── JSON ──────────────────────────────────────────────────────────────────

def extract_json(file_path: str) -> List[str]:
    """Read and return formatted JSON file content."""
    log.info(f"Parsing JSON: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [json.dumps(data, ensure_ascii=False, indent=2)]


# ── PPTX ──────────────────────────────────────────────────────────────────

def extract_pptx(file_path: str) -> List[str]:
    """Extract text per slide from PowerPoint."""
    from pptx import Presentation

    log.info(f"Parsing PPTX: {file_path}")
    prs = Presentation(file_path)
    content = []

    for slide_num, slide in enumerate(prs.slides, start=1):
        content.append(f"\n--- Slide {slide_num} ---\n")
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                content.append(shape.text.strip())

    log.info(f"  Extracted {len(prs.slides)} slides from PPTX")
    return content


# ── Router ────────────────────────────────────────────────────────────────

PARSERS = {
    ".pdf":  extract_pdf,
    ".docx": extract_docx,
    ".doc":  extract_docx,
    ".txt":  extract_txt,
    ".csv":  extract_csv,
    ".xlsx": extract_excel,
    ".xls":  extract_excel,
    ".json": extract_json,
    ".pptx": extract_pptx,
}


def parse_document(file_path: str) -> List[str]:
    """
    Auto-detect file type and extract text content.
    Returns list of text strings ready for chunking.
    """
    ext = Path(file_path).suffix.lower()
    parser = PARSERS.get(ext)
    if not parser:
        raise ValueError(
            f"Unsupported file type: {ext}. Supported: {list(PARSERS.keys())}"
        )
    return parser(file_path)


def parse_to_single_text(file_path: str) -> str:
    """Parse document and join all content into one string."""
    blocks = parse_document(file_path)
    return "\n".join(blocks)