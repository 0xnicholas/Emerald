"""Tests for ProfileManager.

Covers cache hit/miss, compute, invalidate, and Redis integration.
"""

import pytest

from emerald.core.profile import ProfileManager, ProfileFact, EntityProfile
from emerald.core.graph import GraphStore


@pytest.fixture
def manager():
    graph = GraphStore(use_db=False)
    return ProfileManager(graph=graph)


@pytest.fixture
def entity_id():
    return "user_profile_123"


async def _seed_memory(graph, entity_id, content, memory_type="fact", confidence=0.8):
    return await graph.create_memory(
        content=content,
        entity_id=entity_id,
        memory_type=memory_type,
        confidence=confidence,
    )


# ---- compute ----

@pytest.mark.asyncio
async def test_compute_static_facts(manager, entity_id):
    """High-confidence fact/preference memories become static facts."""
    await _seed_memory(manager.graph, entity_id, "喜欢 TypeScript", "preference", 0.9)
    await _seed_memory(manager.graph, entity_id, "住在上海", "fact", 0.8)

    profile = await manager.compute(entity_id)

    assert len(profile.static) == 2
    assert any("TypeScript" in f.content for f in profile.static)
    assert any("上海" in f.content for f in profile.static)


@pytest.mark.asyncio
async def test_compute_static_respects_confidence_threshold(manager, entity_id):
    """Low-confidence facts are excluded from static profile."""
    await _seed_memory(manager.graph, entity_id, "maybe likes Go", "fact", 0.2)

    profile = await manager.compute(entity_id)
    assert len(profile.static) == 0


@pytest.mark.asyncio
async def test_compute_dynamic_facts(manager, entity_id):
    """Recent episodic memories become dynamic facts."""
    await _seed_memory(
        manager.graph, entity_id, "昨天讨论了 API 设计", "episodic", 0.7
    )

    profile = await manager.compute(entity_id)

    assert len(profile.dynamic) == 1
    assert "API" in profile.dynamic[0].content


@pytest.mark.asyncio
async def test_compute_limits_max_items(manager, entity_id):
    """Static trimmed to STATIC_MAX_ITEMS, dynamic to DYNAMIC_MAX_ITEMS."""
    for i in range(15):
        await _seed_memory(
            manager.graph, entity_id, f"fact {i}", "fact", 0.9 - i * 0.01
        )

    profile = await manager.compute(entity_id)
    assert len(profile.static) <= manager.STATIC_MAX_ITEMS


@pytest.mark.asyncio
async def test_compute_sorts_by_importance(manager, entity_id):
    """Static facts sorted by confidence (importance) descending."""
    await _seed_memory(manager.graph, entity_id, "low", "fact", 0.5)
    await _seed_memory(manager.graph, entity_id, "high", "fact", 0.95)

    profile = await manager.compute(entity_id)
    assert profile.static[0].importance > profile.static[1].importance


@pytest.mark.asyncio
async def test_compute_increments_version(manager, entity_id):
    """Each compute increments the profile version."""
    p1 = await manager.compute(entity_id)
    p2 = await manager.compute(entity_id)
    assert p2.version == p1.version + 1


# ---- get (with caching) ----

@pytest.mark.asyncio
async def test_get_cache_miss_computes(manager, entity_id):
    """First get() computes the profile."""
    await _seed_memory(manager.graph, entity_id, "test fact", "fact", 0.9)

    profile = await manager.get(entity_id)
    assert isinstance(profile, EntityProfile)
    assert profile.memory_count == 1


@pytest.mark.asyncio
async def test_get_cache_hit_returns_cached(manager, entity_id):
    """Second get() returns cached profile without recomputing."""
    await _seed_memory(manager.graph, entity_id, "test fact", "fact", 0.9)

    p1 = await manager.get(entity_id)
    p1_version = p1.version

    # Add another memory
    await _seed_memory(manager.graph, entity_id, "another fact", "fact", 0.9)

    # Should still return cached version
    p2 = await manager.get(entity_id)
    assert p2.version == p1_version


@pytest.mark.asyncio
async def test_get_returns_memory_cache_when_no_redis(manager, entity_id):
    """In-memory cache works as fallback when Redis is unavailable."""
    await _seed_memory(manager.graph, entity_id, "cached", "fact", 0.9)

    p1 = await manager.get(entity_id)
    # Direct memory cache hit
    p2 = manager._memory_cache[entity_id]
    assert p1.entity_id == p2.entity_id


# ---- invalidate ----

@pytest.mark.asyncio
async def test_invalidate_clears_memory_cache(manager, entity_id):
    """invalidate() removes profile from in-memory cache."""
    await _seed_memory(manager.graph, entity_id, "test", "fact", 0.9)
    await manager.get(entity_id)
    assert entity_id in manager._memory_cache

    await manager.invalidate(entity_id)
    assert entity_id not in manager._memory_cache


@pytest.mark.asyncio
async def test_invalidate_on_missing_entity_is_noop(manager, entity_id):
    """Invalidating a non-existent entity does not raise."""
    await manager.invalidate(entity_id)  # No error
