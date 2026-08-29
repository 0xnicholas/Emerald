"""Shared test fixtures and configuration."""

from __future__ import annotations

import pytest


@pytest.fixture
def settings():
    """Provide test settings with default values (no .env required)."""
    from emerald.config import Settings

    return Settings(
        emerald_env="development",
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        neo4j_password="test",
        redis_url="redis://localhost:6379/0",
        encryption_key="0" * 64,
    )


@pytest.fixture
def clean_settings(monkeypatch):
    """Settings instance that ignores all .env files (N7).

    Why: ``Settings(_env_file=None)`` is the right way to test defaults
    and the ``CORS_ALLOWED_ORIGINS=*`` production-rejection logic without
    picking up values from the developer's local .env.  Encapsulating
    this in a fixture makes the intent obvious at the call site.
    """
    from emerald.config import Settings

    # Strip every environment variable pydantic-settings would read so the
    # returned Settings reflects ONLY the model defaults + explicit kwargs.
    for env_key in (
        "EMERALD_ENV", "EMERALD_LOG_LEVEL", "API_KEY_SECRET", "ENCRYPTION_KEY",
        "DATABASE_URL", "DATABASE_URL_SYNC", "NEO4J_URI", "NEO4J_USER",
        "NEO4J_PASSWORD", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
        "MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET",
        "MINIO_SECURE", "EMBEDDING_PROVIDER", "OPENAI_API_KEY",
        "OPENAI_EMBEDDING_MODEL", "BGE_MODEL_PATH", "TESSERACT_LANG",
        "WHISPER_MODEL_SIZE", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
        "NOTION_CLIENT_ID", "NOTION_CLIENT_SECRET", "GITHUB_APP_ID",
        "GITHUB_APP_PRIVATE_KEY", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET",
        "GITHUB_WEBHOOK_SECRET", "CORS_ALLOWED_ORIGINS", "RATE_LIMIT_MEMORIES",
        "RATE_LIMIT_SEARCH", "RATE_LIMIT_PROFILES", "RATE_LIMIT_UPLOAD",
        "OAUTH_STATE_TTL_SECONDS",
    ):
        monkeypatch.delenv(env_key, raising=False)
    return Settings(_env_file=None)


@pytest.fixture
def engine():
    """A fully in-memory MemoryEngine for tests (N1).

    The same construction is repeated in 5+ test files; centralising
    here keeps tests focused on behaviour, not engine plumbing.
    """
    from emerald.core.chunker import ChunkerRegistry
    from emerald.core.embedder import MockEmbeddingProvider
    from emerald.core.engine import MemoryEngine
    from emerald.core.extractor import ExtractorRegistry
    from emerald.core.graph import GraphStore
    from emerald.core.vector import VectorStore
    from emerald.pipeline.chunking.text import TextChunker
    from emerald.pipeline.extraction.text import TextExtractor

    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    return MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=MockEmbeddingProvider(dimension=128),
        graph=GraphStore(use_db=False),
        vector=VectorStore(use_db=False),
        use_db=False,
    )
