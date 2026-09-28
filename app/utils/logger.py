# """
# app/utils/logger.py
# ───────────────────
# Single logging setup for all services.
# Call get_logger(__name__) in every module.
# """
# from __future__ import annotations
# import logging
# import logging.handlers
# from datetime import datetime
# from pathlib import Path

# LOG_DIR = Path("logs")
# LOG_DIR.mkdir(exist_ok=True)

# CONSOLE_FMT = "%(asctime)s  %(levelname)-8s  %(message)s"
# FILE_FMT    = "%(asctime)s  %(levelname)-8s  [%(name)s:%(lineno)d]  %(message)s"
# DATE_FMT    = "%H:%M:%S"

# _configured = False


# def _setup():
#     global _configured
#     if _configured:
#         return
#     log_file = LOG_DIR / f"app_{datetime.now().strftime('%Y%m%d')}.log"

#     console = logging.StreamHandler()
#     console.setLevel(logging.INFO)
#     console.setFormatter(logging.Formatter(CONSOLE_FMT, datefmt=DATE_FMT))

#     # rotating = logging.handlers.RotatingFileHandler(
#     #     log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
#     # )

#     rotating = logging.handlers.TimedRotatingFileHandler(
#     log_file,
#     when="midnight",
#     backupCount=5,
#     encoding="utf-8",
#     delay=True,
#     )
#     rotating.setLevel(logging.DEBUG)
#     rotating.setFormatter(logging.Formatter(FILE_FMT, datefmt=DATE_FMT))

#     logging.basicConfig(level=logging.DEBUG, handlers=[console, rotating])
#     _configured = True


# def get_logger(name: str) -> logging.Logger:
#     _setup()
#     return logging.getLogger(name)


"""
app/utils/logger.py
───────────────────
Single logging setup for all services.
Call get_logger(__name__) in every module.
"""
from __future__ import annotations
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

CONSOLE_FMT = "%(asctime)s  %(levelname)-8s  %(message)s"
FILE_FMT    = "%(asctime)s  %(levelname)-8s  [%(name)s:%(lineno)d]  %(message)s"
DATE_FMT    = "%H:%M:%S"

_configured = False


def _process_tag() -> str:
    """
    Unique tag per running process — used in the log filename so that
    multiple services (consumer, scheduler, chatbot, crawler_api,
    streamlit, crawler subprocess, ...) each write to their own file.

    TimedRotatingFileHandler tries to os.rename() the log file at
    midnight. On Windows, rename fails with PermissionError if any
    other process still has the same file open. Giving each process
    its own file avoids the shared-handle conflict entirely.
    """
    script = Path(sys.argv[0]).stem or "app"
    return f"{script}_{os.getpid()}"


def _setup():
    global _configured
    if _configured:
        return
    log_file = LOG_DIR / f"app_{datetime.now().strftime('%Y%m%d')}_{_process_tag()}.log"

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(CONSOLE_FMT, datefmt=DATE_FMT))

    # Plain FileHandler — no rotation. Each process writes to its own
    # per-PID file, so the multi-process Windows rename conflict that
    # TimedRotatingFileHandler hit (PermissionError: WinError 32) cannot
    # occur. Old log files just accumulate in logs/ and can be cleaned
    # up periodically (e.g. by date) outside the app.
    file_handler = logging.FileHandler(log_file, encoding="utf-8", delay=True)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(FILE_FMT, datefmt=DATE_FMT))

    logging.basicConfig(level=logging.DEBUG, handlers=[console, file_handler])
    _configured = True


def get_logger(name: str) -> logging.Logger:
    _setup()
    return logging.getLogger(name)