"""
app/services/kafka_producer.py
───────────────────────────────
Kafka producer — used by crawler API to publish messages.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from config.settings import settings
from app.utils.logger import get_logger

log = get_logger(__name__)
_producer = None


def _get_producer():
    global _producer
    if _producer is not None:
        return _producer
    try:
        from confluent_kafka import Producer
        _producer = Producer({
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "acks": "all",
            "retries": 3,
            "retry.backoff.ms": 500,
        })
        log.info(f"Kafka producer connected → {settings.kafka_bootstrap_servers}")
    except Exception as e:
        log.error(f"Kafka producer init failed: {e}")
        raise
    return _producer


def _on_delivery(err, msg):
    if err:
        log.error(f"Kafka delivery failed [{msg.topic()}]: {err}")
    else:
        log.debug(f"Kafka ✓ {msg.topic()} offset={msg.offset()}")


def publish_page(url: str, title: str, text: str,
                 depth: int = 0, job_id: int = None):
    """Publish crawled HTML page text to crawler.raw_pages."""
    _publish(
        topic=settings.kafka_topic_raw_pages,
        key=url,
        payload={
            "url": url, "title": title, "text": text,
            "metadata": {
                "source": "html", "depth": depth,
                "job_id": job_id,
                "crawled_at": datetime.now().isoformat(),
            },
        },
    )


def publish_attachment(file_path: Path, source_url: str,
                       file_type: str, job_id: int = None):
    """Publish downloaded attachment path to crawler.attachments."""
    _publish(
        topic=settings.kafka_topic_attachments,
        key=source_url,
        payload={
            "file_path": str(file_path.resolve()),
            "source_url": source_url,
            "file_type": file_type.lstrip(".").lower(),
            "metadata": {
                "job_id": job_id,
                "downloaded_at": datetime.now().isoformat(),
            },
        },
    )

def publish_job_complete(job_id: int, total_pages: int, total_attachments: int):
    """Publish a sentinel message to signal crawler is done for this job."""
    _publish(
        topic=settings.kafka_topic_raw_pages,
        key=f"job_complete_{job_id}",
        payload={
            "event":      "job_complete",
            "job_id":     job_id,
            "total_pages": total_pages,
            "total_attachments": total_attachments,
            "completed_at": datetime.now().isoformat(),
        },
    )

def flush():
    if _producer:
        remaining = _producer.flush(timeout=10)
        if remaining:
            log.warning(f"Kafka flush: {remaining} message(s) undelivered")


def _publish(topic: str, key: str, payload: dict):
    try:
        p = _get_producer()
        p.produce(
            topic=topic,
            key=key.encode("utf-8"),
            value=json.dumps(payload).encode("utf-8"),
            callback=_on_delivery,
        )
        p.poll(0)
        log.info(f"Kafka → {topic} | {key[:80]}")
    except Exception as e:
        log.error(f"Kafka publish failed: {e}", exc_info=True)
