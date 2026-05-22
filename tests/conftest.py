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
