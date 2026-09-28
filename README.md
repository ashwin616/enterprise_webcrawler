# Web Crawler RAG Pipeline

Production-grade pipeline: crawl URLs → Kafka → parse → chunk → pgvector → chatbot.

## Folder structure

```
project/
├── .env                        ← config (copy from .env.example)                
├── requirements.txt
├── README.md
│
├── app/
│   ├── api/
│   │   └── crawler_api.py      ← FastAPI: URL input, file upload, schedule
│   ├── models/
│   │   └── schemas.py          ← Pydantic request/response models
│   ├── services/
│   │   ├── crawler_service.py  ← crawl4ai DFS crawler (called as subprocess)
│   │   ├── kafka_producer.py   ← publishes to Kafka
│   │   └── database.py         ← all PostgreSQL operations
│   └── utils/
│       └── logger.py           ← centralised logging
│
├── config/
│   └── settings.py             ← single settings object (reads .env)
│
├── consumer.py                 ← Kafka consumer → chunk → embed → store
├── chatbot.py                  ← RAG chatbot FastAPI (:8002)
├── scheduler.py                ← auto re-crawl scheduler (:8001)
├── chatbot_ui.py               ← Streamlit UI (:8501)
│
├── crawl_output/               ← downloaded PDFs and files
├── logs/                       ← rotating log files
└── tests/
```

## Setup

### 1. Prerequisites
- Python 3.10+
- PostgreSQL 18 with pgvector extension
- Kafka binary (local, no Docker)

### 2. Configure
```bat
copy .env.example .env
notepad .env
```
Fill in:
- `PG_PASSWORD` — your PostgreSQL password
- `GROQ_API_KEY` 

### 3. Install dependencies
```bat
pip install -r requirements.txt
```

### 4. Database setup
In pgAdmin → crawlerdb → Query Tool:
```sql
CREATE DATABASE crawlerdb;
-- then connect to crawlerdb:
CREATE EXTENSION IF NOT EXISTS vector;
```

### 5. Start Kafka
```bat
subst Z: C:\path\to\project subst Z: C:\workplace\Genai_task_demo\
cd Z:\kafka

:: One-time format (KRaft)
<!-- bin\windows\kafka-storage.bat format -t "MkU3OEVBNTcwNTJENDM2Qg" -c config\kraft\server.properties  -->
bin\windows\kafka-storage.bat format -t "9mA1iYehRQWIEp4UmjAknA" -c config\kraft\server.properties

:: Start broker (keep this terminal open)
bin\windows\kafka-server-start.bat config\kraft\server.properties
```

### 6. Create Kafka topics
```bat
Z:\kafka\bin\windows\kafka-topics.bat --create --bootstrap-server localhost:9092 --topic crawler.raw_pages --partitions 1 --replication-factor 1
Z:\kafka\bin\windows\kafka-topics.bat --create --bootstrap-server localhost:9092 --topic crawler.attachments --partitions 1 --replication-factor 1
```

## Running all services

Open 5 terminals in the project folder:

| Terminal | Command | Port |
|----------|---------|------|
| 1 | Kafka (already running) | 9092 | https://worktual.in/
| 2 | `python consumer.py` | — | 
| 3 | `python scheduler.py` | 8001 |
| 4 | `python chatbot.py` | 8002 |
| 5 | `python -m uvicorn app.api.crawler_api:app --host 0.0.0.0 --port 8000 --reload` | 8000 |
| 6 | `streamlit run chatbot_ui.py` | 8501 |

## API docs (Swagger UI)

| Service | URL |
|---------|-----|
| Crawler API | http://localhost:8000/docs |
| Scheduler API | http://localhost:8001/docs |
| Chatbot API | http://localhost:8002/docs |
| Streamlit UI | http://localhost:8501 |

## Moving to other server

1. Copy the entire `project/` folder to the server
2. Install Python 3.10+ on the server
3. Install PostgreSQL 18 + pgvector on the server
4. Install Kafka binary on the server
5. Copy `.env` and update `PG_HOST`, `KAFKA_BOOTSTRAP_SERVERS` if needed
6. Run `pip install -r requirements.txt`
7. Start all services as above

Everything is driven by `.env` — no hardcoded values anywhere.
Changing server = change `.env` only.

## Schedule frequency options

| Value | Frequency |
|-------|-----------|
| `manual` | Manual trigger only |
| `10m` | Every 10 minutes |
| `30m` | Every 30 minutes |
| `1h` | Every 1 hour |
| `3h` | Every 3 hours |
| `6h` | Every 6 hours |
| `10h` | Every 10 hours |
| `1d` | Every 24 hours |
