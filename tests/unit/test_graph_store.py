"""Unit tests for GraphStore (in-memory fallback mode)."""

import pytest
from datetime import datetime, timezone, timedelta

from emerald.core.graph import GraphStore


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.mark.asyncio
async def test_create_memory_returns_id(graph):
    mid = await graph.create_memory("test content", entity_id="e1")
    assert isinstance(mid, str) and len(mid) > 0


@pytest.mark.asyncio
async def test_create_memory_defaults(graph):
    mid = await graph.create_memory("test", entity_id="e1")
    m = await graph.get_memory(mid)
    assert m["is_latest"] is True
    assert m["memory_type"] == "fact"
    assert m["confidence"] == 0.8
    assert isinstance(m["valid_from"], datetime)


@pytest.mark.asyncio
async def test_get_memory_not_found(graph):
    assert await graph.get_memory("nonexistent") is None


@pytest.mark.asyncio
async def test_list_latest_excludes_expired(graph):
    mid = await graph.create_memory("expired", entity_id="e1")
    for m in graph._memories.get("e1", []):
        if m["id"] == mid:
            m["valid_until"] = datetime.now(timezone.utc) - timedelta(days=1)
    latest = await graph.list_latest_memories("e1")
    assert not any(m["id"] == mid for m in latest)


@pytest.mark.asyncio
async def test_list_latest_respects_limit(graph):
    for i in range(10):
        await graph.create_memory(f"mem {i}", entity_id="e1")
    latest = await graph.list_latest_memories("e1", limit=3)
    assert len(latest) == 3


@pytest.mark.asyncio
async def test_update_is_latest_with_replaced_by(graph):
    mid = await graph.create_memory("old", entity_id="e1")
    await graph.update_is_latest(mid, False, replaced_by="new_id")
    m = await graph.get_memory(mid)
    assert m["is_latest"] is False
    assert m["replaced_by"] == "new_id"


@pytest.mark.asyncio
async def test_entity_isolation(graph):
    await graph.create_memory("alice", entity_id="alice")
    await graph.create_memory("bob", entity_id="bob")
    alice_mems = await graph.list_latest_memories("alice")
    assert all("bob" not in m["content"] for m in alice_mems)
