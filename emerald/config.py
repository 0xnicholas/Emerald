"""Unified configuration via pydantic-settings.

All environment variables are loaded from .env and validated here.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import model_validator
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

    # ---- Session JWT ----
    # Must be >= 32 bytes in production. Falls back to api_key_secret if not set,
    # but a dedicated secret is strongly recommended.
    session_jwt_secret: str = "change-me-change-me-change-me-change-me"

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
    # P2.2: default is empty (most restrictive) so production is safe by
    # accident.  A bare ``*`` is rejected in production via the validator
    # below.  In development, ``*`` is permitted for local browser testing.
    cors_allowed_origins: str = ""

    @model_validator(mode="after")
    def _reject_wildcard_cors_in_production(self) -> Settings:
        """Refuse to start with ``CORS_ALLOWED_ORIGINS=*`` in production.

        A wildcard origin allows ANY site in the user's browser to call
        the API on their behalf, which combined with a leaked API key is
        a full account takeover vector.  Production must list specific
        origins; development gets a free pass for local testing.
        """
        if (
            self.emerald_env == Environment.production
            and self.cors_allowed_origins.strip() == "*"
        ):
            raise ValueError(
                "CORS_ALLOWED_ORIGINS='*' is not allowed in production. "
                "List specific origins (comma-separated) or leave empty "
                "to disable browser CORS entirely."
            )
        return self

    # ---- Rate Limiting ----
    rate_limit_memories: int = 60
    rate_limit_search: int = 120
    rate_limit_profiles: int = 300
    rate_limit_upload: int = 10

    # ---- OAuth ----
    # I8: TTL for OAuth state tokens. Should be at least the typical
    # round-trip time for a human to complete the provider's consent
    # screen.  10 minutes is conservative; reduce for tighter security.
    oauth_state_ttl_seconds: int = 600

    # ---- Connection Hub (ADR-0004) ----
    # Emerald never talks to providers directly; all external data flows
    # through a connection hub. The hub is swappable: `hub_provider` picks
    # the implementation (stackone is the first; others plug in behind the
    # same ConnectionHub interface in emerald/sources/hub.py).
    hub_provider: str = "stackone"
    stackone_api_base_url: str = "https://api.stackone.com"
    stackone_api_key_id: str = ""
    stackone_api_key_secret: str = ""
    # Signing secret for verifying inbound webhook deliveries
    # (x-stackone-signature, HMAC-SHA256 over the raw body).
    stackone_webhook_secret: str = ""
    # Base URL of this Emerald instance, used to build the webhook
    # endpoint that the hub delivers events to.
    public_base_url: str = "http://localhost:8000"

    # ---- OpenTelemetry ----
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "emerald"
    otel_traces_sampler: str = "parentbased_traceidratio"
    otel_traces_sampler_arg: float = 1.0

    # ---- OTEL Auto-instrumentation ----
    # NOTE: FastAPI is hardcoded in emerald/api/app.py.
    #       Neo4j has no PyPI instrumentation package (uses manual spans).
    otel_instrument_httpx: bool = True
    otel_instrument_asyncpg: bool = True
    otel_instrument_redis: bool = True
    otel_instrument_celery: bool = True
    otel_console_exporter: bool = False
    otel_service_namespace: str = "memory-infrastructure"
    otel_service_version: str = "0.4.0"

    # ---- Search / Recall ----
    search_default_top_k: int = 30
    search_max_top_k: int = 100
    search_dynamic_truncation_enabled: bool = True
    search_score_gap_threshold: float = 0.15
    search_min_confidence_default: float | None = None
    search_relationship_expansion_factor: float = 0.85

    # ---- Fast Lane ----
    fast_lane_enabled: bool = True
    fast_lane_max_age_hours: float = 24.0
    fast_lane_score_discount: float = 0.9
    fast_lane_max_chars_per_chunk: int = 1024

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
