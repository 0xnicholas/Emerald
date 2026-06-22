"""Tests for GET /v1/files list endpoint.

Strategy: Direct function tests (bypass FastAPI request validation layer).

Why not TestClient: With the OpenTelemetry FastAPI instrumentator active
in test environments, FastAPI's dependency-overrides mechanism produces
spurious 422 "missing query: request" errors for routes that have no
`request` query parameter (verified: the dependant tree contains only
entity_id, status_filter, page, page_size). The endpoint function itself
is correct — verified by calling it directly with mock session_factory.

These tests invoke the endpoint function directly with a mocked session
to verify its behavior. The route registration and signature are
verified separately by the OpenAPI schema in test_api.py.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------- Helpers ----------


def _make_doc(
    doc_id=None,
    title="doc.pdf",
    status="done",
    content_type="application/pdf",
    size=1024,
    chunk_count=5,
    created_at=None,
):
    if doc_id is None:
        doc_id = uuid.uuid4()
    if created_at is None:
        created_at = datetime(2026, 6, 21, 10, 0, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=doc_id,
        title=title,
        content_type=content_type,
        status=status,
        file_size_bytes=size,
        chunk_count=chunk_count,
        created_at=created_at,
    )


def _build_session_mock(documents, entity_exists=True):
    """Build a mock session that mimics Document/Entity queries."""
    entity_id_uuid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    entity = (
        SimpleNamespace(id=entity_id_uuid, external_id="user_123")
        if entity_exists
        else None
    )

    # scalar_one_or_none() returns the entity (sync)
    entity_result = MagicMock()
    entity_result.scalar_one_or_none = MagicMock(return_value=entity)

    # scalar() returns count (sync)
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=len(documents))

    # .scalars().all() returns documents (sync)
    docs_result = MagicMock()
    docs_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=documents))
    )

    # session.execute() is ASYNC (called with await)
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[entity_result, count_result, docs_result]
    )

    class FakeCM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return None

    factory = MagicMock()
    factory.session = MagicMock(return_value=FakeCM())
    return factory


async def _call_list_files(entity_id, status_filter="done", page=1, page_size=20):
    """Call list_files() directly with patched session_factory."""
    from emerald.api.routes.v1 import upload

    factory = _build_session_mock(documents=[])
    original = upload.session_factory if hasattr(upload, "session_factory") else None

    # list_files does `from emerald.db.session import session_factory` inside the
    # function body, so we patch the source module's attribute.
    import emerald.db.session as db_session

    db_session.session_factory = factory
    try:
        from unittest.mock import patch
        # Mock request.state.request_id for the new request_id line
        mock_request = MagicMock()
        mock_request.state.request_id = "test_id"
        result = await upload.list_files(
            request=mock_request,
            entity_id=entity_id,
            status_filter=status_filter,
            page=page,
            page_size=page_size,
        )
    finally:
        if original is not None:
            db_session.session_factory = original
    return result


# ---------- Tests ----------


@pytest.mark.asyncio
async def test_list_files_empty_entity_returns_empty():
    """Entity with no documents returns empty list (not error)."""
    # Rebuild mock for THIS call (empty documents)
    factory = _build_session_mock(documents=[])

    import emerald.db.session as db_session
    original = db_session.session_factory
    db_session.session_factory = factory
    try:
        from emerald.api.routes.v1 import upload
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.state.request_id = "test_id"
        result = await upload.list_files(
            request=mock_request,
            entity_id="user_123",
            status_filter="done",
            page=1,
            page_size=20,
        )
    finally:
        db_session.session_factory = original

    assert result["data"]["items"] == []
    assert result["data"]["total"] == 0
    assert result["data"]["page"] == 1
    assert result["data"]["page_size"] == 20
    assert "meta" in result
    assert "took_ms" in result["meta"]
    assert "request_id" in result["meta"]


@pytest.mark.asyncio
async def test_list_files_unknown_entity_returns_empty():
    """Unknown entity_id (not in DB) returns empty list, not 404."""
    factory = _build_session_mock(documents=[], entity_exists=False)

    import emerald.db.session as db_session
    original = db_session.session_factory
    db_session.session_factory = factory
    try:
        from emerald.api.routes.v1 import upload
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.state.request_id = "test_id"
        result = await upload.list_files(
            request=mock_request,
            entity_id="nonexistent_user",
            status_filter="done",
        )
    finally:
        db_session.session_factory = original

    assert result["data"]["items"] == []
    assert result["data"]["total"] == 0


@pytest.mark.asyncio
async def test_list_files_returns_documents():
    """Entity with documents returns paginated list."""
    docs = [
        _make_doc(title="report.pdf", size=1024 * 100, chunk_count=12),
        _make_doc(title="image.png", size=1024 * 50, chunk_count=0),
    ]
    factory = _build_session_mock(documents=docs)

    import emerald.db.session as db_session
    original = db_session.session_factory
    db_session.session_factory = factory
    try:
        from emerald.api.routes.v1 import upload
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.state.request_id = "test_id"
        result = await upload.list_files(
            request=mock_request,
            entity_id="user_123",
            status_filter="done",
        )
    finally:
        db_session.session_factory = original

    assert result["data"]["total"] == 2
    assert len(result["data"]["items"]) == 2
    titles = {item["title"] for item in result["data"]["items"]}
    assert titles == {"report.pdf", "image.png"}

    item = result["data"]["items"][0]
    # All required fields present
    for field in ["id", "title", "content_type", "status", "file_size_bytes", "chunk_count", "created_at"]:
        assert field in item, f"Missing field: {field}"
    assert item["content_type"] == "application/pdf"
    assert item["status"] == "done"


@pytest.mark.asyncio
async def test_list_files_handles_null_size():
    """Documents with NULL file_size_bytes are serialized as None."""
    doc = SimpleNamespace(
        id=uuid.uuid4(),
        title="pending.pdf",
        content_type="application/pdf",
        status="processing",
        file_size_bytes=None,
        chunk_count=0,
        created_at=datetime(2026, 6, 21, 10, 0, 0, tzinfo=timezone.utc),
    )
    factory = _build_session_mock(documents=[doc])

    import emerald.db.session as db_session
    original = db_session.session_factory
    db_session.session_factory = factory
    try:
        from emerald.api.routes.v1 import upload
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.state.request_id = "test_id"
        result = await upload.list_files(
            request=mock_request,
            entity_id="user_123",
            status_filter="processing",
        )
    finally:
        db_session.session_factory = original

    assert result["data"]["total"] == 1
    item = result["data"]["items"][0]
    assert item["file_size_bytes"] is None
    assert item["title"] == "pending.pdf"


@pytest.mark.asyncio
async def test_list_files_pagination_params():
    """page and page_size are reflected in response.data."""
    factory = _build_session_mock(documents=[])

    import emerald.db.session as db_session
    original = db_session.session_factory
    db_session.session_factory = factory
    try:
        from emerald.api.routes.v1 import upload
        from unittest.mock import MagicMock

        mock_request = MagicMock()
        mock_request.state.request_id = "test_id"
        result = await upload.list_files(
            request=mock_request,
            entity_id="user_123",
            status_filter="done",
            page=3,
            page_size=10,
        )
    finally:
        db_session.session_factory = original

    assert result["data"]["page"] == 3
    assert result["data"]["page_size"] == 10


# ---------- Signature verification ----------


def test_list_files_signature():
    """Endpoint signature has correct parameters (no spurious 'request' query param)."""
    from emerald.api.routes.v1 import upload

    sig = inspect.signature(upload.list_files)
    params = sig.parameters

    # First param must be request: Request (FastAPI standard)
    first_name = next(iter(params))
    assert first_name == "request", (
        f"First param should be 'request', got '{first_name}'"
    )

    # Should have these query params
    assert "entity_id" in params
    assert "status_filter" in params
    assert "page" in params
    assert "page_size" in params

    # Required: entity_id (no default)
    assert params["entity_id"].default is inspect.Parameter.empty
    # Optional: others have defaults
    assert params["status_filter"].default == "done"
    assert params["page"].default == 1
    assert params["page_size"].default == 20


def test_list_files_route_registered():
    """Endpoint is registered with correct signature in OpenAPI."""
    from fastapi.testclient import TestClient
    from emerald.api.app import create_app
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
    embedder = MockEmbeddingProvider(dimension=128)
    engine = MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=embedder,
        graph=GraphStore(use_db=False),
        vector=VectorStore(use_db=False),
        use_db=False,
    )
    app = create_app(engine=engine)
    schema = app.openapi()

    # Find /v1/files GET endpoint in schema
    files_path = schema["paths"].get("/v1/files")
    assert files_path is not None, "/v1/files not in OpenAPI"
    get_op = files_path.get("get")
    assert get_op is not None, "GET /v1/files not in OpenAPI"

    # Verify parameters
    params = {p["name"]: p for p in get_op.get("parameters", [])}
    assert "entity_id" in params
    assert params["entity_id"]["required"] is True
    assert "status_filter" in params
    assert "page" in params
    assert "page_size" in params
    # NO 'request' query parameter
    assert "request" not in params, (
        "Spurious 'request' query parameter in OpenAPI schema"
    )
