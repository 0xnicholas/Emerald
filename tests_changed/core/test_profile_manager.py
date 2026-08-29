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
def manager(graph, monkeypatch):
    m = ProfileManager(graph=graph)
    # Isolate from a live local Redis: without this, the first test that
    # computes a profile for an entity caches it (profile:{entity_id}) and
    # every later test for the same entity reads the stale cached profile
    # (observed 2026-08-11: test_empty_profile poisoned user_123 for the
    # whole suite, and the same failures showed up in CI unit-test step).
    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _fake_loop_redis():
        return fake_redis

    monkeypatch.setattr(m, "_get_loop_redis", _fake_loop_redis)
    return m


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


# ---- Profile config CRUD ----


@pytest.mark.asyncio
async def test_get_config_returns_defaults_when_none_set(manager):
    """With no per-entity config, get_config returns class defaults."""
    config = await manager.get_config("user_new")
    assert config.static_max_items == 10
    assert config.dynamic_max_items == 5
    assert config.dynamic_lookback_days == 7
    assert config.min_confidence_static == 0.5
    assert config.min_confidence_dynamic == 0.3


@pytest.mark.asyncio
async def test_set_config_and_read_back(manager):
    """set_config stores per-entity overrides retrievable via get_config."""
    from emerald.core.profile import ProfileConfig

    cfg = ProfileConfig(
        static_max_items=3,
        dynamic_max_items=2,
        dynamic_lookback_days=14,
        min_confidence_static=0.7,
        min_confidence_dynamic=0.4,
    )
    await manager.set_config("user_456", cfg)

    config = await manager.get_config("user_456")
    assert config.static_max_items == 3
    assert config.dynamic_max_items == 2
    assert config.dynamic_lookback_days == 14
    assert config.min_confidence_static == 0.7
    assert config.min_confidence_dynamic == 0.4


@pytest.mark.asyncio
async def test_delete_config_returns_to_defaults(manager):
    """After delete_config, get_config returns class defaults."""
    from emerald.core.profile import ProfileConfig

    cfg = ProfileConfig(static_max_items=3)
    await manager.set_config("user_789", cfg)

    deleted = await manager.delete_config("user_789")
    assert deleted is True

    config = await manager.get_config("user_789")
    assert config.static_max_items == 10  # Back to default


@pytest.mark.asyncio
async def test_delete_config_nonexistent_returns_false(manager):
    """Deleting config for entity with no override returns False."""
    deleted = await manager.delete_config("no_such_entity")
    assert deleted is False


@pytest.mark.asyncio
async def test_entity_config_isolation(manager):
    """Config overrides for one entity don't affect another."""
    from emerald.core.profile import ProfileConfig

    await manager.set_config("alice", ProfileConfig(static_max_items=3))
    await manager.set_config("bob", ProfileConfig(static_max_items=20))

    alice_cfg = await manager.get_config("alice")
    bob_cfg = await manager.get_config("bob")

    assert alice_cfg.static_max_items == 3
    assert bob_cfg.static_max_items == 20


@pytest.mark.asyncio
async def test_config_affects_profile_static_limit(manager, graph):
    """static_max_items config overrides the number of static facts returned."""
    from emerald.core.profile import ProfileConfig

    # Create 5 facts for this entity
    for i in range(5):
        await graph.create_memory(
            f"事实内容 {i}", entity_id="user_cfg",
            memory_type="fact", confidence=0.9,
        )

    # Default: up to 10 static items → all 5 should appear
    profile = await manager.get("user_cfg")
    assert len(profile.static) == 5

    # Set config: only 2 static items max
    await manager.set_config("user_cfg", ProfileConfig(static_max_items=2))

    # Invalidate so next get() recomputes with new config
    await manager.invalidate("user_cfg")

    profile = await manager.get("user_cfg")
    assert len(profile.static) == 2


@pytest.mark.asyncio
async def test_config_affects_profile_dynamic_limit(manager, graph):
    """dynamic_max_items config overrides the number of dynamic facts returned."""
    from emerald.core.profile import ProfileConfig

    # Create 4 episodic memories
    for i in range(4):
        await graph.create_memory(
            f"最近对话 {i}", entity_id="user_dyn",
            memory_type="episodic", confidence=0.7,
        )

    # Default: up to 5 dynamic items → all 4 should appear
    profile = await manager.get("user_dyn")
    assert len(profile.dynamic) == 4

    # Set config: only 1 dynamic item max
    await manager.set_config("user_dyn", ProfileConfig(dynamic_max_items=1))
    await manager.invalidate("user_dyn")

    profile = await manager.get("user_dyn")
    assert len(profile.dynamic) == 1


@pytest.mark.asyncio
async def test_set_config_invalidates_profile_cache(manager, graph):
    """Setting config invalidates profile cache so next get() recomputes."""
    from emerald.core.profile import ProfileConfig

    await graph.create_memory("事实", entity_id="user_inv", memory_type="fact", confidence=0.9)

    # First get: caches profile
    profile1 = await manager.get("user_inv")
    v1 = profile1.version

    # Set config: should invalidate cache
    await manager.set_config("user_inv", ProfileConfig(static_max_items=1))

    # Second get: should recompute (new version)
    profile2 = await manager.get("user_inv")
    assert profile2.version > v1
