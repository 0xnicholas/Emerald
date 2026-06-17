"""Unit tests for GraphStore (in-memory fallback mode)."""

from datetime import UTC, datetime, timedelta

import pytest

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
            m["valid_until"] = datetime.now(UTC) - timedelta(days=1)
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
async def test_list_latest_keeps_valid_until_future(graph):
    """Memories with a future valid_until remain in latest list."""
    future = datetime.now(UTC) + timedelta(days=1)
    mid = await graph.create_memory("future", entity_id="e1", valid_until=future)
    latest = await graph.list_latest_memories("e1")
    assert any(m["id"] == mid for m in latest)


@pytest.mark.asyncio
async def test_list_latest_excludes_not_latest(graph):
    """Memories with is_latest=False are excluded from latest list."""
    mid = await graph.create_memory("superseded", entity_id="e1")
    await graph.update_is_latest(mid, is_latest=False)
    latest = await graph.list_latest_memories("e1")
    assert not any(m["id"] == mid for m in latest)


@pytest.mark.asyncio
async def test_list_latest_empty_entity(graph):
    """Querying a non-existent entity returns an empty list."""
    latest = await graph.list_latest_memories("nonexistent")
    assert latest == []


@pytest.mark.asyncio
async def test_list_latest_filter_by_memory_type(graph):
    """Filtering by memory_type returns only matching memories."""
    await graph.create_memory("fact 1", entity_id="e1", memory_type="fact")
    await graph.create_memory("pref 1", entity_id="e1", memory_type="preference")
    facts = await graph.list_latest_memories("e1", memory_type="fact")
    assert len(facts) == 1
    assert facts[0]["memory_type"] == "fact"


@pytest.mark.asyncio
async def test_entity_isolation(graph):
    await graph.create_memory("alice", entity_id="alice")
    await graph.create_memory("bob", entity_id="bob")
    alice_mems = await graph.list_latest_memories("alice")
    assert all("bob" not in m["content"] for m in alice_mems)


async def test_list_entity_ids_all_active(graph):
    """list_entity_ids returns all entities with latest memories."""
    await graph.create_memory("a", entity_id="e1")
    await graph.create_memory("b", entity_id="e1")
    await graph.create_memory("c", entity_id="e2")

    ids = await graph.list_entity_ids()
    assert set(ids) == {"e1", "e2"}


async def test_list_entity_ids_empty(graph):
    """Empty store returns empty list."""
    assert await graph.list_entity_ids() == []


async def test_list_entity_ids_excludes_not_latest(graph):
    """Entity with only not-latest memories is excluded."""
    mid = await graph.create_memory("stale", entity_id="ghost")
    await graph.update_is_latest(mid, False)

    ids = await graph.list_entity_ids()
    assert "ghost" not in ids
