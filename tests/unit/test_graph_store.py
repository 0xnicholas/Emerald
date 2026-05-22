"""Unit tests for GraphStore (in-memory mode)."""

from datetime import datetime, timedelta, timezone

import pytest

from emerald.core.graph import GraphStore


@pytest.fixture
def store():
    return GraphStore(use_db=False)


@pytest.mark.asyncio
async def test_create_memory_returns_string_id(store):
    mid = await store.create_memory("test", entity_id="user_1")
    assert isinstance(mid, str)
    assert len(mid) == 32  # UUID hex


@pytest.mark.asyncio
async def test_create_memory_sets_defaults(store):
    mid = await store.create_memory("hello world", entity_id="user_1")
    m = await store.get_memory(mid)
    assert m is not None
    assert m["is_latest"] is True
    assert m["confidence"] == 0.8
    assert m["memory_type"] == "fact"
    assert m["valid_from"] is not None
    assert m["valid_until"] is None
    assert m["expired_at"] is None
    assert m["replaced_by"] is None


@pytest.mark.asyncio
async def test_get_memory_found(store):
    mid = await store.create_memory("find me", entity_id="user_1")
    m = await store.get_memory(mid)
    assert m["content"] == "find me"


@pytest.mark.asyncio
async def test_get_memory_not_found(store):
    m = await store.get_memory("nonexistent_id")
    assert m is None


@pytest.mark.asyncio
async def test_list_latest_memories(store):
    await store.create_memory("m1", entity_id="user_1")
    await store.create_memory("m2", entity_id="user_1")
    await store.create_memory("m3", entity_id="user_1")

    memories = await store.list_latest_memories("user_1")
    assert len(memories) == 3
    # Most recent first
    assert memories[0]["content"] == "m3"


@pytest.mark.asyncio
async def test_list_latest_respects_limit(store):
    for i in range(10):
        await store.create_memory(f"m{i}", entity_id="user_1")

    memories = await store.list_latest_memories("user_1", limit=3)
    assert len(memories) == 3


@pytest.mark.asyncio
async def test_list_latest_excludes_not_latest(store):
    mid = await store.create_memory("expired", entity_id="user_1")
    await store.update_is_latest(mid, False)

    memories = await store.list_latest_memories("user_1")
    assert len(memories) == 0


@pytest.mark.asyncio
async def test_list_latest_excludes_expired_valid_until(store):
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    mid = await store.create_memory("expired soon", entity_id="user_1")
    # Manually set valid_until in the past
    for memories in store._memories.values():
        for m in memories:
            if m["id"] == mid:
                m["valid_until"] = yesterday

    memories = await store.list_latest_memories("user_1")
    assert len(memories) == 0


@pytest.mark.asyncio
async def test_list_latest_keeps_valid_until_future(store):
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(days=1)

    mid = await store.create_memory("valid future", entity_id="user_1")
    for memories in store._memories.values():
        for m in memories:
            if m["id"] == mid:
                m["valid_until"] = tomorrow

    memories = await store.list_latest_memories("user_1")
    assert len(memories) == 1


@pytest.mark.asyncio
async def test_update_is_latest_with_replaced_by(store):
    mid = await store.create_memory("old version", entity_id="user_1")
    await store.update_is_latest(mid, False, replaced_by="new_id_123")

    m = await store.get_memory(mid)
    assert m["is_latest"] is False
    assert m["replaced_by"] == "new_id_123"


@pytest.mark.asyncio
async def test_memory_entity_isolation(store):
    await store.create_memory("alice's", entity_id="alice")
    await store.create_memory("bob's", entity_id="bob")

    alice = await store.list_latest_memories("alice")
    bob = await store.list_latest_memories("bob")

    alice_texts = [m["content"] for m in alice]
    bob_texts = [m["content"] for m in bob]
    assert "alice's" in alice_texts
    assert "bob's" not in alice_texts
    assert "bob's" in bob_texts


@pytest.mark.asyncio
async def test_list_latest_empty_entity(store):
    memories = await store.list_latest_memories("nonexistent")
    assert memories == []


@pytest.mark.asyncio
async def test_list_latest_filter_by_memory_type(store):
    await store.create_memory("fact 1", entity_id="user_1", memory_type="fact")
    await store.create_memory("pref 1", entity_id="user_1", memory_type="preference")

    facts = await store.list_latest_memories("user_1", memory_type="fact")
    assert len(facts) == 1
    assert facts[0]["memory_type"] == "fact"
