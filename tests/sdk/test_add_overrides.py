"""Tests for SDK add() override parameters (P1.2a fix).

P1.2a fix: SDK docs claimed `add(memory_type=..., confidence=...,
valid_until=...)` parameters existed, but they were never implemented
in the schema, route, or engine. This test pins down the contract:

- The SDK `add()` method MUST accept these keyword arguments.
- They MUST be forwarded as the body fields of the same names to POST /v1/memories.
- The engine MUST store the value (verified via the test engine).

Existing `metadata` dict overrides are kept for backward compatibility.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------- Schema & SDK signature ----------

def test_add_memory_request_schema_has_override_fields():
    """The Pydantic AddMemoryRequest must accept memory_type, confidence, valid_until."""
    from emerald.api.schemas.memories import AddMemoryRequest

    fields = AddMemoryRequest.model_fields
    assert "memory_type" in fields, (
        "AddMemoryRequest must accept `memory_type` (per docs/api/rest-guide.md)"
    )
    assert "confidence" in fields, (
        "AddMemoryRequest must accept `confidence` (per docs)"
    )
    assert "valid_until" in fields, (
        "AddMemoryRequest must accept `valid_until` (per docs)"
    )


def test_sdk_add_signature_has_override_params():
    """EmeraldClient.add() must accept memory_type, confidence, valid_until."""
    from emerald.sdk import EmeraldClient

    sig = inspect.signature(EmeraldClient.add)
    params = sig.parameters
    for name in ("memory_type", "confidence", "valid_until"):
        assert name in params, (
            f"EmeraldClient.add() must accept `{name}=` keyword argument "
            f"(per docs/api/sdk-guide.md). Existing params: {list(params)}"
        )


def test_sdk_add_forwards_overrides_in_request_body():
    """When the user passes memory_type/confidence/valid_until, the SDK must
    include them as top-level keys in the JSON body — NOT inside metadata.
    """
    from emerald.sdk import EmeraldClient

    client = EmeraldClient(api_key="em_test", base_url="http://test")

    # Capture the actual request body via a mocked httpx client.
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {"memory_ids": ["mem_1"], "pipeline_status": "done", "extracted_count": 1},
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(client, "_get_client") as get_client:
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_response)
        mock_http.headers = client._headers
        get_client.return_value = mock_http

        valid_until_dt = datetime(2027, 1, 1, tzinfo=UTC)
        import asyncio
        asyncio.run(client.add(
            content="用户偏好 TypeScript",
            entity_id="user_123",
            memory_type="preference",
            confidence=0.95,
            valid_until=valid_until_dt,
        ))

    # Find the call to /v1/memories and inspect the body.
    call = mock_http.request.call_args
    body = call.kwargs.get("json") or (call.args[2] if len(call.args) > 2 else None)
    assert body is not None, f"Request body missing in call: {call}"
    assert body["memory_type"] == "preference", (
        f"memory_type not in body or wrong: {body}"
    )
    assert body["confidence"] == 0.95, f"confidence not in body: {body}"
    assert "valid_until" in body, f"valid_until not in body: {body}"


# ---------- Engine accepts and applies overrides ----------

@pytest.mark.asyncio
async def test_engine_add_accepts_memory_type_override():
    """engine.add() must accept memory_type and apply it via the indexer."""
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

    # Patch graph.create_memory to record what overrides were passed in.
    captured = {}
    original_create = engine.graph.create_memory

    async def _capture(**kwargs):
        captured.update(kwargs)
        return await original_create(**kwargs)

    engine.graph.create_memory = _capture

    await engine.add(
        content="用户偏好 TypeScript",
        entity_id="user_123",
        memory_type="preference",
        confidence=0.92,
    )

    assert captured.get("memory_type") == "preference", (
        f"Engine did not forward memory_type to graph: {captured}"
    )
    assert captured.get("confidence") == 0.92, (
        f"Engine did not forward confidence to graph: {captured}"
    )


@pytest.mark.asyncio
async def test_engine_add_accepts_valid_until_override():
    """engine.add() must accept valid_until (datetime or ISO string)."""
    from datetime import datetime

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

    captured = {}
    original_create = engine.graph.create_memory

    async def _capture(**kwargs):
        captured.update(kwargs)
        return await original_create(**kwargs)

    engine.graph.create_memory = _capture

    expiry = datetime(2027, 6, 30, tzinfo=UTC)
    await engine.add(
        content="Alex 明天有考试",
        entity_id="user_alex",
        valid_until=expiry,
    )

    # engine normalises to either a datetime or a string depending on graph impl
    vu = captured.get("valid_until")
    assert vu is not None, f"valid_until not forwarded to graph: {captured}"
    if isinstance(vu, datetime):
        # Must be timezone-aware
        assert vu.tzinfo is not None
        assert vu == expiry
    elif isinstance(vu, str):
        # ISO string should round-trip
        parsed = datetime.fromisoformat(vu.replace("Z", "+00:00"))
        assert parsed == expiry
    else:
        pytest.fail(f"Unexpected valid_until type from graph: {type(vu)}: {vu!r}")


# ---------- I5: precedence invariants (explicit > metadata > chunker) ----------
#
# These tests pin the override resolution rules.  If someone changes the
# precedence in _resolve_override() (e.g. swaps explicit and metadata),
# the test_engine_precedence_explicit_over_metadata test will fail.

@pytest.mark.asyncio
async def test_engine_precedence_explicit_over_metadata():
    """Explicit add() arg must win over metadata dict (P1.2a contract)."""
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
    engine = MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=MockEmbeddingProvider(dimension=128),
        graph=GraphStore(use_db=False),
        vector=VectorStore(use_db=False),
        use_db=False,
    )

    captured = {}
    original_create = engine.graph.create_memory

    async def _capture(**kwargs):
        captured.update(kwargs)
        return await original_create(**kwargs)

    engine.graph.create_memory = _capture

    # Pass BOTH explicit arg AND metadata override — explicit must win.
    await engine.add(
        content="用户偏好 TypeScript",
        entity_id="user_123",
        memory_type="preference",  # explicit
        metadata={"memory_type": "fact"},  # metadata (should lose)
    )

    assert captured.get("memory_type") == "preference", (
        f"explicit add() arg must win over metadata: {captured}"
    )


@pytest.mark.asyncio
async def test_engine_precedence_metadata_over_chunker():
    """When explicit is None, metadata must win over the chunker default."""
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
    engine = MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=MockEmbeddingProvider(dimension=128),
        graph=GraphStore(use_db=False),
        vector=VectorStore(use_db=False),
        use_db=False,
    )

    captured = {}
    original_create = engine.graph.create_memory

    async def _capture(**kwargs):
        captured.update(kwargs)
        return await original_create(**kwargs)

    engine.graph.create_memory = _capture

    # No explicit override; metadata provides one; chunker default loses.
    await engine.add(
        content="用户偏好 TypeScript",
        entity_id="user_123",
        metadata={"memory_type": "episodic"},
    )

    assert captured.get("memory_type") == "episodic", (
        f"metadata override must win when no explicit arg: {captured}"
    )
