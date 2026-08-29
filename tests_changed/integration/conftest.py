"""Shared fixtures for integration tests."""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from emerald.api.app import create_app
from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.conversation import ConversationChunker
from emerald.pipeline.chunking.markdown import MarkdownChunker
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor


@pytest.fixture
def docker_available():
    """Return True if Docker daemon is reachable."""
    import shutil
    return shutil.which("docker") is not None


@pytest.fixture
def engine():
    """In-memory engine with all built-in extractors/chunkers for integration tests."""
    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    extractors.register("conversation", TextExtractor())
    extractors.register("markdown", TextExtractor())

    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    chunkers.register("conversation", ConversationChunker())
    chunkers.register("markdown", MarkdownChunker())

    embedder = MockEmbeddingProvider(dimension=128)
    graph = GraphStore(use_db=False)
    vector = VectorStore(use_db=False)

    return MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=embedder,
        graph=graph,
        vector=vector,
        use_db=False,
    )


@pytest.fixture
def client(engine):
    """FastAPI TestClient with in-memory engine + bypassed auth/rate-limit."""
    from emerald.api.dependencies import api_key_auth, require_write_permission, rate_limit

    async def _bypass_auth(request: Request):
        # Use a UUID-format entity_id for connector routes that still cast to uuid.UUID
        request.state.entity_id = "550e8400-e29b-41d4-a716-446655440000"
        return "authenticated"

    async def _bypass_write(request: Request):
        return "authorized"

    async def _bypass_rate(request: Request):
        return None

    app = create_app(engine=engine)
    app.dependency_overrides[api_key_auth] = _bypass_auth
    app.dependency_overrides[require_write_permission] = _bypass_write
    app.dependency_overrides[rate_limit] = _bypass_rate
    return TestClient(app, headers={"Authorization": "Bearer em_test"})


@pytest.fixture
def mock_db_session():
    """Yield a reusable AsyncMock session + patch helper for session_factory."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    # Context manager protocol
    mock_factory = MagicMock()
    mock_factory.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.session.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("emerald.api.routes.connectors.session_factory", mock_factory):
        yield mock_session, mock_factory
