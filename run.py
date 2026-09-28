"""
run_all.py
──────────
Starts all 5 services in the correct order with one command.

Usage:
    python run_all.py

Prerequisite:
    Kafka must be running on localhost:9092 before running this script.
    Start Kafka: Z:\kafka\bin\windows\kafka-server-start.bat Z:\kafka\config\kraft\server.properties

Services started:
    1. consumer.py          — Kafka consumer (must start first)
    2. scheduler.py         — Auto re-crawl scheduler
    3. chatbot.py           — RAG chatbot API  :8002
    4. crawler_api.py       — Crawler API      :8000
    5. chatbot_ui.py        — Streamlit UI     :8501

Stop all:  Ctrl+C  (shuts down all services cleanly)
"""
from __future__ import annotations

import subprocess
import sys
import time
import signal
import socket
from pathlib import Path

BASE_DIR = Path(__file__).parent
PYTHON   = sys.executable

# ── Service definitions ───────────────────────────────────────────────────
# (name, command, startup_wait_seconds)

SERVICES = [
    (
        "Consumer",
        [PYTHON, str(BASE_DIR / "consumer.py")],
        4,   # wait 4s — must be ready before any crawl
    ),
    (
        "Scheduler",
        [PYTHON, str(BASE_DIR / "scheduler.py")],
        2,
    ),
    (
        "Chatbot API",
        [PYTHON, str(BASE_DIR / "chatbot.py")],
        2,
    ),
    (
        "Crawler API",
        [PYTHON, "-m", "uvicorn",
         "app.api.crawler_api:app",
         "--host", "0.0.0.0",
         "--port", "8000",
         "--reload"],
        2,
    ),
    (
        "Streamlit UI",
        [PYTHON, "-m", "streamlit", "run",
         str(BASE_DIR / "chatbot_ui.py"),
         "--server.port", "8501",
         "--server.headless", "true"],
        15,
    ),
    (
    "Crawl Dashboard",                        # ← add this
    [PYTHON, "-m", "streamlit", "run",
     str(BASE_DIR / "crawl_dashboard.py"),
     "--server.port", "8502",
     "--server.headless", "true"],
    15,
    ),
]

# ── Kafka check ───────────────────────────────────────────────────────────

def check_kafka():
    print("\n" + "=" * 60)
    print("  Checking Kafka on localhost:9092...")
    try:
        s = socket.create_connection(("localhost", 9092), timeout=3)
        s.close()
        print("  Kafka is running")
        print("=" * 60)
    except OSError:
        print("\n  ERROR: Kafka is not running!")
        print("=" * 60)
        print("\n  Start Kafka first using this command:\n")
        print("  Z:\\kafka\\bin\\windows\\kafka-server-start.bat"
              " Z:\\kafka\\config\\kraft\\server.properties\n")
        print("  Then run this script again: python run_all.py\n")
        sys.exit(1)


# ── Startup ───────────────────────────────────────────────────────────────

processes = []


def start_all():
    print("\n" + "=" * 60)
    print("  Starting all services...")
    print("=" * 60 + "\n")

    for name, cmd, wait in SERVICES:
        print(f"  Starting {name}...")
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=None,
            stderr=None,
        )
        processes.append((name, proc))
        print(f"  {name} started (pid={proc.pid})")
        time.sleep(wait)

    print("\n" + "=" * 60)
    print("  All services running")
    print("  Crawler API  →  http://localhost:8000/docs")
    print("  Chatbot UI   →  http://localhost:8501")
    print("  Press Ctrl+C to stop all")
    print("=" * 60 + "\n")


# ── Shutdown ──────────────────────────────────────────────────────────────

def stop_all(signum=None, frame=None):
    print("\n" + "=" * 60)
    print("  Stopping all services...")
    print("=" * 60)

    for name, proc in reversed(processes):
        if proc.poll() is None:
            print(f"  Stopping {name} (pid={proc.pid})...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            print(f"  {name} stopped")

    print("\n  All services stopped.")
    sys.exit(0)


# ── Health monitor ────────────────────────────────────────────────────────

def monitor():
    """Watch for any crashed service and report it."""
    while True:
        time.sleep(5)
        for name, proc in processes:
            if proc.poll() is not None:
                print(f"\n  [WARNING] {name} stopped unexpectedly "
                      f"(exit code={proc.returncode})")
                print(f"  Run 'python run_all.py' to restart all services\n")


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    signal.signal(signal.SIGINT,  stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    check_kafka()   # exits with clear message if Kafka not running
    start_all()

    try:
        monitor()
    except KeyboardInterrupt:
        stop_all()