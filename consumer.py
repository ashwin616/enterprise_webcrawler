# """
# consumer.py  —  Kafka consumer pipeline (LangChain edition)
# ────────────────────────────────────────────────────────────
# Reads from two Kafka topics:
#   crawler.raw_pages   → LangChain chunk → embed → pgvector
#   crawler.attachments → doc_parser → LangChain chunk → embed → pgvector

# Chunking uses LangChain text splitters (strategy from .env).
# Embeddings use FastEmbed AllMiniLM (local, no API key).

# Usage:
#     python consumer.py
# """
# from __future__ import annotations

# import json
# import logging
# import signal
# import sys
# from pathlib import Path

# # Add project root to path
# sys.path.insert(0, str(Path(__file__).parent))

# from config.settings import settings
# from app.services.database import init_schema, page_save, chunks_save
# from app.services.doc_parser import parse_to_single_text
# from app.services.chunker_service import chunk_text
# from app.utils.logger import get_logger
# from app.services import database as db


# log = get_logger(__name__)

# # Per-job stats tracker: { job_id: {"pages": 0, "chunks": 0} }
# _job_stats: dict = {}

# # ── Embedding model ───────────────────────────────────────────────────────

# _embed_model = None


# def _get_embed_model():
#     global _embed_model
#     if _embed_model is None:
#         from fastembed import TextEmbedding
#         log.info(f"Loading FastEmbed: {settings.fastembed_model}")
#         _embed_model = TextEmbedding(model_name=settings.fastembed_model)
#         log.info("FastEmbed ready")
#     return _embed_model


# def embed_texts(texts: list[str]) -> list[list[float]]:
#     model = _get_embed_model()
#     return [emb.tolist() for emb in model.embed(texts)]

# def embed_texts_with_progress(texts: list[str]) -> list[list[float]]:
#     from tqdm import tqdm
#     model = _get_embed_model()
#     embeddings = []
#     for emb in tqdm(model.embed(texts), total=len(texts), desc="Embedding chunks", unit="chunk"):
#         embeddings.append(emb.tolist())
#     return embeddings


# def embed_and_save_chunks(chunks: list[dict], page_id: int, batch_size: int = 50):
#     """
#     Embed and save chunks in batches of batch_size.
#     Prints progress every batch so large documents show activity.
#     """
#     total = len(chunks)
#     saved = 0

#     for i in range(0, total, batch_size):
#         batch = chunks[i:i + batch_size]
#         texts = [c["content"] for c in batch]

#         embeddings = embed_texts(texts)

#         for c, emb in zip(batch, embeddings):
#             c["page_id"]   = page_id
#             c["embedding"] = emb

#         chunks_save(batch)
#         saved += len(batch)
#         print(f"  [chunks] processed {saved}/{total}", flush=True)

#     log.info(f"  Saved {total} chunks to DB")

# # ── Processors ────────────────────────────────────────────────────────────

# def process_raw_page(payload: dict):
#     """
#     Handle crawler.raw_pages message.
#     Payload: { url, title, text, metadata }
#     """
#     url    = payload.get("url", "")
#     title  = payload.get("title", "")
#     text   = payload.get("text", "")
#     meta   = payload.get("metadata", {})
#     job_id = meta.get("job_id")

#     if not url or not text:
#         log.warning("Skipping — missing url or text")
#         return

#     log.info(f"Processing HTML page: {url} ({len(text)} chars)")

#     # 1. Save raw text
#     page_id = page_save(url=url, title=title, content=text,
#                         content_type="html", job_id=job_id)

#     # 2. LangChain chunking
#     chunk_meta = {"url": url, "title": title, "source": "html", **meta}
#     chunks = chunk_text(text, metadata=chunk_meta)
#     if not chunks:
#         log.warning(f"No chunks produced for {url}")
#         return

#     # 3. Embed
#     # embeddings = embed_texts([c["content"] for c in chunks])
#     embeddings = embed_texts_with_progress([c["content"] for c in chunks])


#     # 4. Save to pgvector
#     for c, emb in zip(chunks, embeddings):
#         c["page_id"]   = page_id
#         c["embedding"] = emb
#     chunks_save(chunks)

#     log.info(f"  ✓ page_id={page_id} chunks={len(chunks)} url={url}")

#     # Accumulate stats for final summary
#     if job_id:
#         if job_id not in _job_stats:
#             _job_stats[job_id] = {"pages": 0, "chunks": 0}
#         _job_stats[job_id]["pages"]  += 1
#         _job_stats[job_id]["chunks"] += len(chunks)

# def process_attachment(payload: dict):
#     file_path  = payload.get("file_path", "")
#     source_url = payload.get("source_url", "")
#     file_type  = payload.get("file_type", "").lower()
#     meta       = payload.get("metadata", {})
#     job_id     = meta.get("job_id")

#     if not file_path or not source_url:
#         log.warning("Skipping — missing file_path or source_url")
#         return

#     fp = Path(file_path)
#     if not fp.exists():
#         log.error(f"File not found: {file_path}")
#         return

#     log.info(f"Processing attachment [{file_type}]: {file_path}")

#     images_dir = fp.parent / "extracted_images"

#     # 1. Full extraction (text blocks + images + page-numbered txt)
#     try:
#         if file_type == "pdf":
#             from app.services.doc_parser import extract_pdf_full
#             result = extract_pdf_full(file_path)
#         elif file_type in ("doc", "docx"):
#             from app.services.doc_parser import extract_docx_full
#             result = extract_docx_full(file_path)
#         else:
#             text = parse_to_single_text(file_path)
#             result = {"blocks": [text], "txt_path": None, "images": [], "pdf_path": Path(file_path)}
#     except Exception as e:
#         log.error(f"doc_parser failed for {file_path}: {e}", exc_info=True)
#         return

#     blocks = result["blocks"]
#     text = "\n".join(blocks)

#     if not text.strip():
#         log.warning(f"No text extracted from {file_path}")
#         return

#     # 2. Save extracted images to DB
#     for img in result.get("images", []):
#         try:
#             db.image_save(
#                 job_id=job_id,
#                 page_url=source_url,
#                 source_url=f"{source_url}#page={img.get('page', 'na')}",
#                 file_path=str(img["path"].resolve()),
#                 width=img["width"], height=img["height"],
#                 file_size=img["size"],
#             )
#         except Exception as e:
#             log.warning(f"  image_save failed for {img['path']}: {e}")

#     if result.get("images"):
#         log.info(f"  Saved {len(result['images'])} image(s) to {result['doc_dir']}/images/")

#     # 3. Save raw content (use updated pdf_path for record-keeping)
#     page_id = page_save(
#         url=source_url, title=Path(file_path).stem,
#         content=text, content_type=file_type, job_id=job_id,
#     )

#     # 4. Chunking
#     chunk_meta = {
#         "url": source_url, "source": file_type,
#         "file_path": str(result["pdf_path"]),
#         "page_text_file": str(result["txt_path"]) if result.get("txt_path") else None,
#         **meta
#     }
#     chunks = chunk_text(text, metadata=chunk_meta)
#     if not chunks:
#         log.warning(f"No chunks from {file_path}")
#         return

#     # 5. Embed + store
#     embeddings = embed_texts([c["content"] for c in chunks])
#     for c, emb in zip(chunks, embeddings):
#         c["page_id"]   = page_id
#         c["embedding"] = emb
#     chunks_save(chunks)

#     log.info(f"  ✓ page_id={page_id} chunks={len(chunks)} file={Path(file_path).name}")

#     if job_id:
#         if job_id not in _job_stats:
#             _job_stats[job_id] = {"pages": 0, "chunks": 0}
#         _job_stats[job_id]["pages"]  += 1
#         _job_stats[job_id]["chunks"] += len(chunks)


# def process_job_complete(payload: dict):
#     """
#     Handle job_complete sentinel message published by crawler after flush().
#     Prints final summary of everything stored for this job.
#     """
#     job_id        = payload.get("job_id")
#     total_crawled = payload.get("total_pages", 0)
#     total_attach  = payload.get("total_attachments", 0)
#     stats         = _job_stats.pop(job_id, {"pages": 0, "chunks": 0})

#     log.info("─" * 60)
#     log.info(f"  ✅ Job {job_id} — ALL DONE")
#     log.info(f"     Pages crawled      : {total_crawled}")
#     log.info(f"     Attachments found  : {total_attach}")
#     log.info(f"     Pages stored in DB : {stats['pages']}")
#     log.info(f"     Chunks in pgvector : {stats['chunks']}")
#     log.info("─" * 60)


# # ── Kafka consumer loop ───────────────────────────────────────────────────

# class CrawlerConsumer:
#     def __init__(self):
#         from confluent_kafka import Consumer, KafkaError
#         self._KafkaError = KafkaError
#         self.consumer = Consumer({
#             "bootstrap.servers":  settings.kafka_bootstrap_servers,
#             "group.id":           settings.kafka_consumer_group,
#             "auto.offset.reset":  "earliest",
#             "enable.auto.commit": True,
#             "max.poll.interval.ms": 600000,
#         })
#         self.running = True

#     def start(self):
#         topics = [settings.kafka_topic_raw_pages, settings.kafka_topic_attachments]
#         self.consumer.subscribe(topics)
#         log.info(f"Subscribed to: {topics}")
#         log.info("─" * 60)
#         log.info("  Consumer started — waiting for messages")
#         log.info("─" * 60)

#         signal.signal(signal.SIGINT,  self._shutdown)
#         signal.signal(signal.SIGTERM, self._shutdown)

#         while self.running:
#             msg = self.consumer.poll(timeout=1.0)
#             if msg is None:
#                 continue
#             if msg.error():
#                 if msg.error().code() != self._KafkaError._PARTITION_EOF:
#                     log.error(f"Kafka error: {msg.error()}")
#                 continue
#             try:
#                 payload = json.loads(msg.value().decode("utf-8"))
#                 topic   = msg.topic()

#                 if topic == settings.kafka_topic_raw_pages:
#                     # Check for sentinel job_complete message first
#                     if payload.get("event") == "job_complete":
#                         process_job_complete(payload)
#                     else:
#                         process_raw_page(payload)

#                 elif topic == settings.kafka_topic_attachments:
#                     process_attachment(payload)

#             except Exception as e:
#                 log.error(f"Message processing error: {e}", exc_info=True)

#         self.consumer.close()
#         log.info("Consumer stopped")

#     def _shutdown(self, *_):
#         log.info("Shutting down consumer...")
#         self.running = False


# if __name__ == "__main__":
#     log.info("─" * 60)
#     log.info("  Consumer startup")
#     log.info("─" * 60)
#     init_schema()
#     _get_embed_model()  # ← pre-load FastEmbed before consuming
#     CrawlerConsumer().start()
    

"""
consumer.py  —  Kafka consumer pipeline (LangChain edition)
────────────────────────────────────────────────────────────
Reads from two Kafka topics:
  crawler.raw_pages   → LangChain chunk → embed → pgvector
  crawler.attachments → doc_parser → LangChain chunk → embed → pgvector

Chunking uses LangChain text splitters (strategy from .env).
Embeddings use FastEmbed AllMiniLM (local, no API key).

Usage:
    python consumer.py
"""
from __future__ import annotations

import json
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from app.services.database import init_schema, page_save, chunks_save
from app.services.doc_parser import parse_to_single_text
from app.services.chunker_service import chunk_text
from app.utils.logger import get_logger
from app.services import database as db

log = get_logger(__name__)

# Per-job stats tracker: { job_id: {"pages": 0, "chunks": 0} }
_job_stats: dict = {}

# ── Kafka topic auto-creation ─────────────────────────────────────────────

def ensure_topics():
    """Create Kafka topics if they don't exist — safe to call on every startup."""
    try:
        from confluent_kafka.admin import AdminClient, NewTopic
        admin = AdminClient({"bootstrap.servers": settings.kafka_bootstrap_servers})

        topics_to_create = [
            NewTopic(settings.kafka_topic_raw_pages,   num_partitions=1, replication_factor=1),
            NewTopic(settings.kafka_topic_attachments, num_partitions=1, replication_factor=1),
        ]

        existing = admin.list_topics(timeout=10).topics.keys()
        to_create = [t for t in topics_to_create if t.topic not in existing]

        if not to_create:
            log.info("Kafka topics already exist")
            return

        results = admin.create_topics(to_create)
        for topic, future in results.items():
            try:
                future.result()
                log.info(f"  Created Kafka topic: {topic}")
            except Exception as e:
                log.warning(f"  Topic {topic} creation skipped: {e}")
    except Exception as e:
        log.warning(f"ensure_topics failed: {e}")


# ── Embedding model ───────────────────────────────────────────────────────

_embed_model = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from fastembed import TextEmbedding
        log.info(f"Loading FastEmbed: {settings.fastembed_model}")
        _embed_model = TextEmbedding(model_name=settings.fastembed_model)
        log.info("FastEmbed ready")
    return _embed_model


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = _get_embed_model()
    return [emb.tolist() for emb in model.embed(texts)]


def embed_and_save_chunks(
    chunks: list[dict],
    page_id: int,
    batch_size: int = 50,
    consumer=None,
):
    """
    Embed and save chunks in batches of batch_size.
    - Prints progress every batch so large documents show activity.
    - Polls Kafka between batches to prevent MAXPOLL/rebalance.
    """
    total = len(chunks)
    saved = 0

    for i in range(0, total, batch_size):
        batch = chunks[i:i + batch_size]
        texts = [c["content"] for c in batch]

        embeddings = embed_texts(texts)

        for c, emb in zip(batch, embeddings):
            c["page_id"]   = page_id
            c["embedding"] = emb

        chunks_save(batch)
        saved += len(batch)
        print(f"  [chunks] processed {saved}/{total}", flush=True)

        # ── Keep Kafka consumer group alive between batches ──────────
        if consumer is not None:
            try:
                consumer.poll(0)  # non-blocking heartbeat
            except Exception:
                pass

    log.info(f"  Saved {total} chunks to DB")


# ── Processors ────────────────────────────────────────────────────────────

def process_raw_page(payload: dict, consumer=None):
    """
    Handle crawler.raw_pages message.
    Payload: { url, title, text, metadata }
    """
    url    = payload.get("url", "")
    title  = payload.get("title", "")
    text   = payload.get("text", "")
    meta   = payload.get("metadata", {})
    job_id = meta.get("job_id")

    if not url or not text:
        log.warning("Skipping — missing url or text")
        return

    log.info(f"Processing HTML page: {url} ({len(text)} chars)")

    # 1. Save raw text
    page_id = page_save(
        url=url, title=title, content=text,
        content_type="html", job_id=job_id,
    )

    # 2. LangChain chunking
    chunk_meta = {"url": url, "title": title, "source": "html", **meta}
    chunks = chunk_text(text, metadata=chunk_meta)
    if not chunks:
        log.warning(f"No chunks produced for {url}")
        return

    log.info(f"  Chunking → {len(chunks)} chunks")

    # 3. Embed + save in batches with progress + Kafka heartbeat
    embed_and_save_chunks(chunks, page_id=page_id, batch_size=50, consumer=consumer)

    log.info(f"  ✓ page_id={page_id} chunks={len(chunks)} url={url}")

    if job_id:
        if job_id not in _job_stats:
            _job_stats[job_id] = {"pages": 0, "chunks": 0}
        _job_stats[job_id]["pages"]  += 1
        _job_stats[job_id]["chunks"] += len(chunks)


def process_attachment(payload: dict, consumer=None):
    file_path  = payload.get("file_path", "")
    source_url = payload.get("source_url", "")
    file_type  = payload.get("file_type", "").lower()
    meta       = payload.get("metadata", {})
    job_id     = meta.get("job_id")

    if not file_path or not source_url:
        log.warning("Skipping — missing file_path or source_url")
        return

    fp = Path(file_path)
    if not fp.exists():
        log.error(f"File not found: {file_path}")
        return

    log.info(f"Processing attachment [{file_type}]: {file_path}")

    # 1. Full extraction (text blocks + images + page-numbered txt)
    try:
        if file_type == "pdf":
            from app.services.doc_parser import extract_pdf_full
            result = extract_pdf_full(file_path)
        elif file_type in ("doc", "docx"):
            from app.services.doc_parser import extract_docx_full
            result = extract_docx_full(file_path)
        else:
            text = parse_to_single_text(file_path)
            result = {
                "blocks": [text], "txt_path": None,
                "images": [], "pdf_path": Path(file_path),
                "doc_dir": Path(file_path).parent,
            }
    except Exception as e:
        log.error(f"doc_parser failed for {file_path}: {e}", exc_info=True)
        return

    blocks = result["blocks"]
    text   = "\n".join(blocks)

    if not text.strip():
        log.warning(f"No text extracted from {file_path}")
        return

    # 2. Save extracted images to DB
    for img in result.get("images", []):
        try:
            db.image_save(
                job_id=job_id,
                page_url=source_url,
                source_url=f"{source_url}#page={img.get('page', 'na')}",
                file_path=str(img["path"].resolve()),
                width=img["width"], height=img["height"],
                file_size=img["size"],
            )
        except Exception as e:
            log.warning(f"  image_save failed for {img['path']}: {e}")

    if result.get("images"):
        log.info(f"  Saved {len(result['images'])} image(s) to images/")

    # 3. Save raw content
    page_id = page_save(
        url=source_url, title=Path(file_path).stem,
        content=text, content_type=file_type, job_id=job_id,
    )

    # 4. Chunking
    chunk_meta = {
        "url": source_url, "source": file_type,
        "file_path": str(result.get("pdf_path", file_path)),
        "page_text_file": str(result["txt_path"]) if result.get("txt_path") else None,
        **meta,
    }
    chunks = chunk_text(text, metadata=chunk_meta)
    if not chunks:
        log.warning(f"No chunks from {file_path}")
        return

    log.info(f"  Chunking → {len(chunks)} chunks")

    # 5. Embed + save in batches with progress + Kafka heartbeat
    embed_and_save_chunks(chunks, page_id=page_id, batch_size=50, consumer=consumer)

    log.info(f"  ✓ page_id={page_id} chunks={len(chunks)} file={Path(file_path).name}")

    if job_id:
        if job_id not in _job_stats:
            _job_stats[job_id] = {"pages": 0, "chunks": 0}
        _job_stats[job_id]["pages"]  += 1
        _job_stats[job_id]["chunks"] += len(chunks)


def process_job_complete(payload: dict):
    """
    Handle job_complete sentinel message published by crawler after flush().
    Prints final summary of everything stored for this job.
    """
    job_id        = payload.get("job_id")
    total_crawled = payload.get("total_pages", 0)
    total_attach  = payload.get("total_attachments", 0)
    stats         = _job_stats.pop(job_id, {"pages": 0, "chunks": 0})

    log.info("─" * 60)
    log.info(f"  ✅ Job {job_id} — ALL DONE")
    log.info(f"     Pages crawled      : {total_crawled}")
    log.info(f"     Attachments found  : {total_attach}")
    log.info(f"     Pages stored in DB : {stats['pages']}")
    log.info(f"     Chunks in pgvector : {stats['chunks']}")
    log.info("─" * 60)


# ── Kafka consumer loop ───────────────────────────────────────────────────

class CrawlerConsumer:
    def __init__(self):
        from confluent_kafka import Consumer, KafkaError
        self._KafkaError = KafkaError
        self.consumer = Consumer({
            "bootstrap.servers":   settings.kafka_bootstrap_servers,
            "group.id":            settings.kafka_consumer_group,
            "auto.offset.reset":   "earliest",
            "enable.auto.commit":  False,        # manual commit after success
            "max.poll.interval.ms": 1800000,     # 30 min — enough for large PDFs
            "session.timeout.ms":   60000,        # 60 sec
            "heartbeat.interval.ms": 20000,       # 20 sec
        })
        self.running = True

    def start(self):
        topics = [settings.kafka_topic_raw_pages, settings.kafka_topic_attachments]
        self.consumer.subscribe(topics)
        log.info(f"Subscribed to: {topics}")
        log.info("─" * 60)
        log.info("  Consumer started — waiting for messages")
        log.info("─" * 60)

        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        while self.running:
            msg = self.consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != self._KafkaError._PARTITION_EOF:
                    log.error(f"Kafka error: {msg.error()}")
                continue
            try:
                payload = json.loads(msg.value().decode("utf-8"))
                topic   = msg.topic()

                if topic == settings.kafka_topic_raw_pages:
                    if payload.get("event") == "job_complete":
                        process_job_complete(payload)
                    else:
                        process_raw_page(payload, consumer=self.consumer)

                elif topic == settings.kafka_topic_attachments:
                    process_attachment(payload, consumer=self.consumer)

                # ── Commit offset only after successful processing ──────
                self.consumer.commit(asynchronous=False)

            except Exception as e:
                log.error(f"Message processing error: {e}", exc_info=True)
                # Don't commit — message will be redelivered on restart

        self.consumer.close()
        log.info("Consumer stopped")

    def _shutdown(self, *_):
        log.info("Shutting down consumer...")
        self.running = False


if __name__ == "__main__":
    log.info("─" * 60)
    log.info("  Consumer startup")
    log.info("─" * 60)
    ensure_topics()         # auto-create topics if missing
    init_schema()
    _get_embed_model()      # pre-load FastEmbed before consuming
    CrawlerConsumer().start()