"""Unified configuration via pydantic-settings.

All environment variables are loaded from .env and validated here.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    development = "development"
    production = "production"


class EmbeddingProvider(str, Enum):
    openai = "openai"
    bge = "bge"
    text2vec = "text2vec"
    local = "local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # .env 提供默认值，.env.local 覆盖真实密钥（不提交到 git）
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Core ----
    emerald_env: Environment = Environment.development
    emerald_log_level: str = "INFO"

    # ---- API Key ----
    api_key_secret: str = "change-me"
    encryption_key: str = "0" * 64  # 64 hex chars = 32 bytes

    # ---- PostgreSQL ----
    database_url: str = "postgresql+asyncpg://emerald:emerald_dev@localhost:5432/emerald"
    database_url_sync: str = "postgresql://emerald:emerald_dev@localhost:5432/emerald"

    # ---- Neo4j ----
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "emerald_dev"

    # ---- Redis ----
    redis_url: str = "redis://:emerald_dev@localhost:6379/0"

    # ---- Celery ----
    celery_broker_url: str = "redis://:emerald_dev@localhost:6379/1"
    celery_result_backend: str = "redis://:emerald_dev@localhost:6379/2"

    # ---- MinIO ----
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "emerald_admin"
    minio_secret_key: str = "emerald_dev123"
    minio_bucket: str = "emerald-documents"
    minio_secure: bool = False

    # ---- Embedding ----
    embedding_provider: EmbeddingProvider = EmbeddingProvider.openai
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    bge_model_path: str = "/models/bge-large-zh-v1.5"

    # ---- OCR / Speech ----
    tesseract_lang: str = "chi_sim+eng"
    whisper_model_size: str = "small"

    # ---- OAuth ----
    google_client_id: str = ""
    google_client_secret: str = ""
    notion_client_id: str = ""
    notion_client_secret: str = ""
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    github_webhook_secret: str = ""

    # ---- CORS ----
    cors_allowed_origins: str = "*"

    # ---- Rate Limiting ----
    rate_limit_memories: int = 60
    rate_limit_search: int = 120
    rate_limit_profiles: int = 300
    rate_limit_upload: int = 10

    # ---- OpenTelemetry ----
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "emerald"
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = 1.0

    # ---- DeepSeek / Fact Extraction ----
    deepseek_api_key: str = ""

    fact_extraction_model: str = "deepseek-v4-flash"
    fact_extraction_base_url: str = "https://api.deepseek.com"
    fact_extraction_max_facts: int = 20
    fact_extraction_timeout: float = 15.0
    fact_extraction_temperature: float = 0.1
    fact_extraction_max_tokens: int = 2000


@lru_cache
def get_settings() -> Settings:
    return Settings()
