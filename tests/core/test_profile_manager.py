"""Tests for ProfileManager.

AGENTS.md requirements:
- Profile = static facts + dynamic facts
- Static: always-relevant preferences, stable attributes
- Dynamic: recent episodic context
- Read target: ~50ms from Redis cache
- Computed on write (pipeline INDEXING stage), cached in Redis
"""


import pytest

from emerald.core.graph import GraphStore
from emerald.core.profile import ProfileManager


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.fixture
def manager(graph):
    return ProfileManager(graph=graph)


@pytest.mark.asyncio
async def test_empty_profile(manager):
    """Entity with no memories has an empty profile."""
    profile = await manager.get("user_123")
    assert profile.entity_id == "user_123"
    assert profile.static == []
    assert profile.dynamic == []
    assert profile.memory_count == 0


@pytest.mark.asyncio
async def test_profile_has_memory_count(manager, graph):
    """Profile tracks total memory count."""
    await graph.create_memory("事实 1", entity_id="user_123")
    await graph.create_memory("事实 2", entity_id="user_123")

    profile = await manager.get("user_123")
    assert profile.memory_count == 2


@pytest.mark.asyncio
async def test_static_facts_from_fact_type(manager, graph):
    """Memory_type='fact' or 'preference' with high confidence → static."""
    await graph.create_memory(
        "用户是资深前端工程师", entity_id="user_123",
        memory_type="fact", confidence=0.9,
    )
    await graph.create_memory(
        "用户偏好 TypeScript", entity_id="user_123",
        memory_type="preference", confidence=0.85,
    )

    profile = await manager.get("user_123")
    static_texts = [f.content for f in profile.static]
    assert any("资深前端工程师" in t for t in static_texts)
    assert any("TypeScript" in t for t in static_texts)


@pytest.mark.asyncio
async def test_dynamic_facts_from_recent_episodic(manager, graph):
    """Recent episodic memories → dynamic facts."""
    await graph.create_memory(
        "正在调试 Redis 限流问题", entity_id="user_123",
        memory_type="episodic", confidence=0.7,
    )

    profile = await manager.get("user_123")
    dynamic_texts = [f.content for f in profile.dynamic]
    assert any("Redis" in t for t in dynamic_texts)


@pytest.mark.asyncio
async def test_static_excludes_low_confidence(manager, graph):
    """Low confidence facts are excluded from static profile."""
    await graph.create_memory(
        "用户可能喜欢 Go", entity_id="user_123",
        memory_type="preference", confidence=0.3,
    )
    await graph.create_memory(
        "用户喜欢 Python", entity_id="user_123",
        memory_type="preference", confidence=0.9,
    )

    profile = await manager.get("user_123")
    static_texts = [f.content for f in profile.static]
    assert any("Python" in t for t in static_texts)
    assert not any("Go" in t for t in static_texts)


@pytest.mark.asyncio
async def test_profile_excludes_not_latest(manager, graph):
    """is_latest=False memories are excluded from profile."""
    old_id = await graph.create_memory(
        "用户在 Google 工作", entity_id="user_123",
    )
    # Mark as not latest (simulating an update)
    await graph.update_is_latest(old_id, False)

    profile = await manager.get("user_123")
    static_texts = [f.content for f in profile.static]
    assert not any("Google" in t for t in static_texts)


@pytest.mark.asyncio
async def test_cache_hit_avoids_recomputation(manager, graph):
    """Second profile read hits cache (no Neo4j query)."""
    await graph.create_memory("用户喜欢 Vim", entity_id="user_123")

    # First read: computes + caches
    profile1 = await manager.get("user_123")
    assert profile1.version == 1

    # Second read: cache hit
    profile2 = await manager.get("user_123")
    assert profile2.version == 1

    # Should be same object reference (cached)
    assert profile2.memory_count == profile1.memory_count


@pytest.mark.asyncio
async def test_invalidate_clears_cache(manager, graph):
    """Invalidate forces recomputation on next read."""
    await graph.create_memory("事实 A", entity_id="user_123")
    profile1 = await manager.get("user_123")

    # Invalidate cache
    await manager.invalidate("user_123")

    # Add new memory
    await graph.create_memory("事实 B", entity_id="user_123")

    # Next read should recompute
    profile2 = await manager.get("user_123")
    assert profile2.memory_count == 2
    assert profile2.version > profile1.version


@pytest.mark.asyncio
async def test_different_entities_have_separate_profiles(manager, graph):
    """Each entity has its own independent profile."""
    await graph.create_memory("Alice 的内容", entity_id="alice")
    await graph.create_memory("Bob 的内容", entity_id="bob")

    alice = await manager.get("alice")
    bob = await manager.get("bob")

    alice_texts = [f.content for f in alice.static]
    assert any("Alice" in t for t in alice_texts)
    assert not any("Bob" in t for t in alice_texts)
