# """
# config/settings.py
# ──────────────────
# Single source of truth for all configuration.
# Reads from .env file — works in development and production.
# Import anywhere: from config.settings import settings
# """
# from __future__ import annotations
# from functools import lru_cache
# from pathlib import Path
# from pydantic_settings import BaseSettings, SettingsConfigDict


# class Settings(BaseSettings):
#     model_config = SettingsConfigDict(
#         env_file=Path(__file__).parent.parent / ".env",
#         env_file_encoding="utf-8",
#         case_sensitive=False,
#         extra="ignore",
#     )

#     # ── Application ───────────────────────────────────
#     app_env:              str = "development"
#     app_host:             str = "0.0.0.0"
#     crawler_api_port:     int = 8000
#     scheduler_api_port:   int = 8001
#     chatbot_api_port:     int = 8002
#     streamlit_port:       int = 8501

#     # ── PostgreSQL ────────────────────────────────────
#     pg_host:     str = "localhost"
#     pg_port:     int = 5432
#     pg_db:       str = "crawlerdb"
#     pg_user:     str = "postgres"
#     pg_password: str = ""

#     @property
#     def pg_dsn(self) -> str:
#         return (
#             f"host={self.pg_host} port={self.pg_port} "
#             f"dbname={self.pg_db} user={self.pg_user} "
#             f"password={self.pg_password}"
#         )

#     # ── Kafka ─────────────────────────────────────────
#     kafka_bootstrap_servers:  str = "localhost:9092"
#     kafka_topic_raw_pages:    str = "crawler.raw_pages"
#     kafka_topic_attachments:  str = "crawler.attachments"
#     kafka_consumer_group:     str = "crawler_consumer_group"

#     # ── LLM ───────────────────────────────────────────
#     groq_api_key: str = ""
#     groq_model:   str = "openai/gpt-oss-20b"

#     # ── Embeddings ────────────────────────────────────
#     fastembed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

#     # ── Crawler ───────────────────────────────────────
#     crawler_output_dir:      str = "crawl_output"
#     crawler_user_agent: str = "WebCrawlerBot/1.0"
#     crawler_request_timeout: int = 30
#     crawler_max_retries:     int = 3

#     # ── Chunking ──────────────────────────────────────
#     chunk_strategy: str = "recursive"
#     chunk_size:     int = 512
#     chunk_overlap:  int = 64
#     chunk_min_size: int = 50

#     # ── Retrieval ─────────────────────────────────────
#     retrieval_top_k:          int   = 10
#     retrieval_min_similarity: float = 0.25
#     retrieval_rerank:         bool  = False   
#     retrieval_hybrid:         bool  = True


#     # ── Chatbot ───────────────────────────────────────
#     chatbot_max_history: int = 20

#     @property
#     def is_production(self) -> bool:
#         return self.app_env == "production"


# @lru_cache(maxsize=1)
# def get_settings() -> Settings:
#     return Settings()


# # Convenience singleton — import this everywhere
# settings = get_settings()
"""
config/settings.py
──────────────────
Single source of truth for all configuration.
Reads from .env file — works in development and production.
Import anywhere: from config.settings import settings
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────
    app_env:              str = "development"
    app_host:             str = "0.0.0.0"
    crawler_api_port:     int = 8000
    scheduler_api_port:   int = 8001
    chatbot_api_port:     int = 8002
    streamlit_port:       int = 8501
    crawl_dashboard_port: int = 8502

    # ── PostgreSQL ────────────────────────────────────
    pg_host:     str = "localhost"
    pg_port:     int = 5432
    pg_db:       str = "crawlerdb"
    pg_user:     str = "postgres"
    pg_password: str = ""

    @property
    def pg_dsn(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} "
            f"dbname={self.pg_db} user={self.pg_user} "
            f"password={self.pg_password}"
        )

    # ── Kafka ─────────────────────────────────────────
    kafka_bootstrap_servers:  str = "localhost:9092"
    kafka_topic_raw_pages:    str = "crawler.raw_pages"
    kafka_topic_attachments:  str = "crawler.attachments"
    kafka_consumer_group:     str = "crawler_consumer_group"

    # ── LLM ───────────────────────────────────────────
    groq_api_key: str = ""
    groq_model:   str = "openai/gpt-oss-20b"

    # ── Embeddings ────────────────────────────────────
    fastembed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # ── Crawler ───────────────────────────────────────
    crawler_output_dir:      str = "crawl_output"
    crawler_user_agent: str = "WebCrawlerBot/1.0"
    crawler_request_timeout: int = 30
    crawler_max_retries:     int = 3

    # ── Chunking ──────────────────────────────────────
    chunk_strategy: str = "recursive"
    chunk_size:     int = 512
    chunk_overlap:  int = 64
    chunk_min_size: int = 50

    # ── Retrieval ─────────────────────────────────────
    retrieval_top_k:          int   = 10
    retrieval_min_similarity: float = 0.25
    retrieval_rerank:         bool  = False   
    retrieval_hybrid:         bool  = True


    # ── Chatbot ───────────────────────────────────────
    chatbot_max_history: int = 20

    scraperapi_key: str = "cacefad4b56578e1fb798576704eb03b"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Convenience singleton — import this everywhere
settings = get_settings()