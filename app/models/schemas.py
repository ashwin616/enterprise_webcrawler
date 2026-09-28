"""
app/models/schemas.py
──────────────────────
All Pydantic request and response models used across APIs.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, HttpUrl, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────

class ScheduleFrequency(str, Enum):
    MANUAL  = "manual"    # 0  min — trigger only via API
    TEN_MIN = "10m"       # 10 min
    THIRTY  = "30m"       # 30 min
    ONE_HR  = "1h"        # 60 min
    THREE_HR= "3h"        # 180 min
    SIX_HR  = "6h"        # 360 min
    TEN_HR  = "10h"       # 600 min
    ONE_DAY = "1d"        # 1440 min

    def to_minutes(self) -> int:
        return {
            "manual": 0,
            "10m":    10,
            "30m":    30,
            "1h":     60,
            "3h":     180,
            "6h":     360,
            "10h":    600,
            "1d":     1440,
        }[self.value]


class ContentType(str, Enum):
    HTML = "html"
    PDF  = "pdf"
    DOCX = "docx"
    FILE = "file"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE    = "done"
    ERROR   = "error"


# ── Crawl job request ─────────────────────────────────────────────────────

# class CrawlJobCreate(BaseModel):
#     url:       str
#     label:     Optional[str]              = ""
#     frequency: Optional[ScheduleFrequency] = ScheduleFrequency.MANUAL

#     @field_validator("url")
#     @classmethod
#     def normalise_url(cls, v: str) -> str:
#         if not v.startswith("http"):
#             v = "https://" + v
#         return v.rstrip("/")
    
class CrawlJobCreate(BaseModel):
    url:       str
    label:     Optional[str]               = ""
    frequency: Optional[ScheduleFrequency] = ScheduleFrequency.MANUAL
    max_depth: Optional[int]               = 3   # ← add this (default 3)
    max_url:   Optional[int]               = None  # ← add this (None = auto)


    @field_validator("url")
    @classmethod
    def normalise_url(cls, v: str) -> str:
        if not v.startswith("http"):
            v = "https://" + v
        return v.rstrip("/")


class CrawlJobUpdate(BaseModel):
    label:     Optional[str]               = None
    frequency: Optional[ScheduleFrequency] = None
    max_url:   Optional[int]               = None  # ← add this (allow updating limit)



class CrawlJobResponse(BaseModel):
    id:             int
    url:            str
    label:          str
    frequency:      str
    status:         str
    max_depth:      int
    max_url:        Optional[int]          
    run_count:      int
    last_crawled_at: Optional[datetime]
    next_crawl_at:  Optional[datetime]
    created_at:     datetime
    last_error:     Optional[str]




# ── File upload request ───────────────────────────────────────────────────

class FileUploadResponse(BaseModel):
    filename:   str
    saved_path: str
    size_kb:    int
    message:    str


# ── Chat ──────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    top_k:   Optional[int] = 5


class ChatResponse(BaseModel):
    session_id:     str
    answer:         str
    sources:        list[str]
    chunks_used:    int
    search_query:   str
    history_length: int
    model:          str


class SessionResponse(BaseModel):
    session_id: str
    message:    str


# ── Generic ───────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str

class HealthResponse(BaseModel):
    status:  str
    service: str
    env:     str
