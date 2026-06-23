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
    monkeypatch.setattr("emerald.db.redis.get_redis_client", lambda: redis_client)
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
    monkeypatch.setattr("emerald.db.redis.get_redis_client", lambda: redis_client)
    monkeypatch.setattr("emerald.pipeline.tasks._update_status", _async_noop)
    monkeypatch.setattr("emerald.db.neo4j.init_neo4j", _async_noop)
    monkeypatch.setattr("emerald.db.neo4j.close_neo4j", _async_noop)

    await _run_index(None, {"pipeline_id": "p-456"}, "entity-1")

    assert fake_graph.calls[0]["valid_until"] is None
