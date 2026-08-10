"""Tests for Celery pipeline task helpers."""

import json
from datetime import UTC, datetime

import pytest

from emerald.pipeline.chunking.base import Chunk
from emerald.pipeline.tasks import _chunk_to_dict, _deserialize_valid_until, _run_index


class _FakeRedis:
    def __init__(self, chunks_data, embeddings):
        self._chunks = json.dumps(chunks_data)
        self._embeddings = json.dumps(embeddings)

    async def get(self, key):
        if "chunks" in key:
            return self._chunks
        if "embeddings" in key:
            return self._embeddings
        return None


class _FakeGraphStore:
    def __init__(self, use_db=True):
        self.calls = []

    async def create_memory(self, **kwargs):
        self.calls.append(kwargs)
        return f"memory-{len(self.calls)}"


class _FakeVectorStore:
    def __init__(self, use_db=True):
        pass

    async def store(self, **kwargs):
        pass


async def _async_noop(*args, **kwargs):
    pass


def test_chunk_to_dict_serializes_valid_until_to_iso():
    valid_until = datetime(2026, 6, 24, 23, 59, 59, tzinfo=UTC)
    chunk = Chunk(text="我明天有考试", index=0, valid_until=valid_until)

    data = _chunk_to_dict(chunk)

    assert data["valid_until"] == "2026-06-24T23:59:59+00:00"


def test_chunk_to_dict_serializes_none_valid_until():
    chunk = Chunk(text="persist forever", index=1, valid_until=None)

    data = _chunk_to_dict(chunk)

    assert data["valid_until"] is None


def test_deserialize_valid_until_parses_iso_string():
    result = _deserialize_valid_until("2026-06-24T23:59:59+00:00")

    assert result == datetime(2026, 6, 24, 23, 59, 59, tzinfo=UTC)


def test_deserialize_valid_until_parses_z_suffix():
    result = _deserialize_valid_until("2026-06-24T23:59:59Z")

    assert result == datetime(2026, 6, 24, 23, 59, 59, tzinfo=UTC)


def test_deserialize_valid_until_returns_none_for_missing():
    assert _deserialize_valid_until(None) is None


def test_deserialize_valid_until_returns_none_for_invalid():
    assert _deserialize_valid_until("not-a-date") is None


@pytest.mark.asyncio
async def test_run_index_passes_valid_until_to_graph_store(monkeypatch):
    chunks_data = [
        {
            "text": "我明天有考试",
            "memory_type": "fact",
            "confidence": 0.9,
            "summary": "exam tomorrow",
            "valid_until": "2026-06-24T23:59:59+00:00",
        },
        {
            "text": "persistent fact",
            "memory_type": "fact",
            "confidence": 0.8,
            "summary": None,
            "valid_until": None,
        },
    ]
    embeddings = [[0.1, 0.2], [0.3, 0.4]]

    fake_graph = _FakeGraphStore(use_db=False)
    redis_client = _FakeRedis(chunks_data, embeddings)
    monkeypatch.setattr("emerald.core.graph.GraphStore", lambda **_: fake_graph)
    monkeypatch.setattr("emerald.core.vector.VectorStore", lambda **_: _FakeVectorStore())
    async def _ensure_redis():
        return redis_client

    monkeypatch.setattr("emerald.db.redis.ensure_redis_for_loop", _ensure_redis)
    monkeypatch.setattr("emerald.pipeline.tasks._update_status", _async_noop)
    monkeypatch.setattr("emerald.db.neo4j.init_neo4j", _async_noop)
    monkeypatch.setattr("emerald.db.neo4j.close_neo4j", _async_noop)

    result = await _run_index(None, {"pipeline_id": "p-123"}, "entity-1")

    assert result["memory_ids"] == ["memory-1", "memory-2"]
    assert fake_graph.calls[0]["valid_until"] == datetime(2026, 6, 24, 23, 59, 59, tzinfo=UTC)
    assert fake_graph.calls[1]["valid_until"] is None


@pytest.mark.asyncio
async def test_run_index_ignores_invalid_valid_until(monkeypatch):
    chunks_data = [
        {
            "text": "broken date",
            "memory_type": "fact",
            "confidence": 0.8,
            "summary": None,
            "valid_until": "garbage",
        },
    ]
    embeddings = [[0.1]]

    fake_graph = _FakeGraphStore(use_db=False)
    redis_client = _FakeRedis(chunks_data, embeddings)
    monkeypatch.setattr("emerald.core.graph.GraphStore", lambda **_: fake_graph)
    monkeypatch.setattr("emerald.core.vector.VectorStore", lambda **_: _FakeVectorStore())
    async def _ensure_redis():
        return redis_client

    monkeypatch.setattr("emerald.db.redis.ensure_redis_for_loop", _ensure_redis)
    monkeypatch.setattr("emerald.pipeline.tasks._update_status", _async_noop)
    monkeypatch.setattr("emerald.db.neo4j.init_neo4j", _async_noop)
    monkeypatch.setattr("emerald.db.neo4j.close_neo4j", _async_noop)

    await _run_index(None, {"pipeline_id": "p-456"}, "entity-1")

    assert fake_graph.calls[0]["valid_until"] is None


# ---- Task wrapper execution (P0-1: helpers must not receive the task as self) ----


class _RecorderRedis:
    """Minimal fake Redis: setex/get round-trip into a dict."""

    def __init__(self):
        self.data = {}

    async def setex(self, key, ttl, value):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)


class _CallRecorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, *args):
        self.calls.append(args)


def test_extract_task_executes_full_helper(monkeypatch):
    """extract_task runs _run_extract without passing the task as self.

    Regression for P0-1: the wrapper used to call
    ``run_async(_run_extract)(self, ...)`` while ``_run_extract`` takes no
    ``self``, raising TypeError on every async ingest.
    """
    import types

    from emerald.pipeline import tasks as tasks_mod

    status = _CallRecorder()
    errors = _CallRecorder()
    monkeypatch.setattr(tasks_mod, "_update_status", status)
    monkeypatch.setattr(tasks_mod, "_update_error", errors)
    monkeypatch.setattr(tasks_mod, "get_traceparent", lambda: None)

    class _Extractor:
        async def extract(self, content):
            assert content == b"raw content"
            return types.SimpleNamespace(text="extracted")

    registry = types.SimpleNamespace(get=lambda t: _Extractor())
    monkeypatch.setattr("emerald.pipeline.extraction.get_default_registry", lambda: registry)

    redis = _RecorderRedis()
    async def _ensure_redis():
        return redis

    monkeypatch.setattr("emerald.db.redis.ensure_redis_for_loop", _ensure_redis)

    result = tasks_mod.extract_task("p-1", b"raw content", "text")

    assert result == {"pipeline_id": "p-1", "content_type": "text", "__traceparent": None}
    assert status.calls == [("p-1", "extracting")]
    assert errors.calls == []
    assert redis.data["pipeline:p-1:text"] == "extracted"


def test_chunk_task_executes_full_helper(monkeypatch):
    """chunk_task runs _run_chunk without passing the task as self."""
    import types

    from emerald.pipeline import tasks as tasks_mod
    from emerald.pipeline.chunking.base import Chunk

    status = _CallRecorder()
    errors = _CallRecorder()
    monkeypatch.setattr(tasks_mod, "_update_status", status)
    monkeypatch.setattr(tasks_mod, "_update_error", errors)
    monkeypatch.setattr(tasks_mod, "get_traceparent", lambda: None)

    class _Chunker:
        async def chunk(self, text):
            assert text == "extracted"
            return [Chunk(text="chunk-a", index=0), Chunk(text="chunk-b", index=1)]

    registry = types.SimpleNamespace(get=lambda t: _Chunker())
    monkeypatch.setattr("emerald.pipeline.chunking.get_default_registry", lambda: registry)

    redis = _RecorderRedis()
    redis.data["pipeline:p-1:text"] = "extracted"
    async def _ensure_redis():
        return redis

    monkeypatch.setattr("emerald.db.redis.ensure_redis_for_loop", _ensure_redis)

    result = tasks_mod.chunk_task({"pipeline_id": "p-1", "content_type": "text"})

    assert result["chunk_count"] == 2
    assert status.calls == [("p-1", "chunking")]
    assert errors.calls == []
    chunks = json.loads(redis.data["pipeline:p-1:chunks"])
    assert [c["text"] for c in chunks] == ["chunk-a", "chunk-b"]


def test_embed_task_executes_full_helper(monkeypatch):
    """embed_task runs _run_embed without passing the task as self."""
    import types

    from emerald.pipeline import tasks as tasks_mod

    status = _CallRecorder()
    errors = _CallRecorder()
    monkeypatch.setattr(tasks_mod, "_update_status", status)
    monkeypatch.setattr(tasks_mod, "_update_error", errors)
    monkeypatch.setattr(tasks_mod, "get_traceparent", lambda: None)

    class _Provider:
        async def embed(self, texts):
            assert texts == ["chunk-a", "chunk-b"]
            return [[0.1, 0.2], [0.3, 0.4]]

    monkeypatch.setattr("emerald.core.embedder.get_embedding_provider", lambda: _Provider())

    redis = _RecorderRedis()
    redis.data["pipeline:p-1:chunks"] = json.dumps(
        [
            {"text": "chunk-a", "index": 0, "token_count": 1, "memory_type": "fact",
             "internal_type": None, "confidence": 0.8, "summary": "", "valid_until": None},
            {"text": "chunk-b", "index": 1, "token_count": 1, "memory_type": "fact",
             "internal_type": None, "confidence": 0.8, "summary": "", "valid_until": None},
        ]
    )
    async def _ensure_redis():
        return redis

    monkeypatch.setattr("emerald.db.redis.ensure_redis_for_loop", _ensure_redis)

    result = tasks_mod.embed_task({"pipeline_id": "p-1", "content_type": "text"})

    assert result["pipeline_id"] == "p-1"
    assert status.calls == [("p-1", "embedding")]
    assert errors.calls == []
    embeddings = json.loads(redis.data["pipeline:p-1:embeddings"])
    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
