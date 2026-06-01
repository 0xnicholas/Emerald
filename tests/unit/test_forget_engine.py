"""Tests for ForgetEngine.

Covers time-based expiry, noise filtering, and episodic decay strategies.
"""

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.forget import ForgetEngine
from emerald.core.graph import GraphStore


@pytest.fixture
def engine():
    graph = GraphStore(use_db=False)
    return ForgetEngine(graph=graph)


@pytest.fixture
def entity_id():
    return "user_forget_123"


async def _seed_memory(graph, entity_id, content, **kwargs):
    return await graph.create_memory(
        content=content,
        entity_id=entity_id,
        **kwargs,
    )


# ---- forget_expired ----

@pytest.mark.asyncio
async def test_forget_expired_past_valid_until(engine, entity_id):
    """Memories with valid_until in the past are archived."""
    past = datetime.now(UTC) - timedelta(days=1)
    mid = await _seed_memory(
        engine.graph, entity_id, "临时会议", valid_until=past
    )

    count = await engine.forget_expired(entity_id)
    assert count == 1

    mem = await engine.graph.get_memory(mid)
    assert mem["is_latest"] is False
    assert mem["expired_at"] is not None


@pytest.mark.asyncio
async def test_forget_expired_future_valid_until_stays(engine, entity_id):
    """Memories with valid_until in the future remain active."""
    future = datetime.now(UTC) + timedelta(days=1)
    mid = await _seed_memory(
        engine.graph, entity_id, "明天考试", valid_until=future
    )

    count = await engine.forget_expired(entity_id)
    assert count == 0

    mem = await engine.graph.get_memory(mid)
    assert mem["is_latest"] is True


@pytest.mark.asyncio
async def test_forget_expired_no_valid_until_stays(engine, entity_id):
    """Memories without valid_until are never expired by time."""
    mid = await _seed_memory(engine.graph, entity_id, "永久事实")

    count = await engine.forget_expired(entity_id)
    assert count == 0

    mem = await engine.graph.get_memory(mid)
    assert mem["is_latest"] is True


@pytest.mark.asyncio
async def test_forget_expired_all_entities_when_no_filter(engine, entity_id):
    """When no entity_id is passed, scans all entities."""
    past = datetime.now(UTC) - timedelta(days=1)
    await _seed_memory(engine.graph, entity_id, "过期1", valid_until=past)
    await _seed_memory(engine.graph, "other_user", "过期2", valid_until=past)

    count = await engine.forget_expired()
    assert count == 2


# ---- forget_noise ----

@pytest.mark.asyncio
async def test_forget_noise_low_confidence_old(engine, entity_id):
    """Low-confidence memories older than 7 days are archived."""
    old = datetime.now(UTC) - timedelta(days=10)
    mid = await _seed_memory(
        engine.graph, entity_id, "random thought", confidence=0.2,
    )
    # Override created_at manually
    mem = await engine.graph.get_memory(mid)
    mem["created_at"] = old

    count = await engine.forget_noise(entity_id)
    assert count == 1

    mem = await engine.graph.get_memory(mid)
    assert mem["is_latest"] is False


@pytest.mark.asyncio
async def test_forget_noise_recent_low_confidence_stays(engine, entity_id):
    """Recent low-confidence memories are kept."""
    mid = await _seed_memory(
        engine.graph, entity_id, "fresh thought", confidence=0.2,
    )

    count = await engine.forget_noise(entity_id)
    assert count == 0

    mem = await engine.graph.get_memory(mid)
    assert mem["is_latest"] is True


@pytest.mark.asyncio
async def test_forget_noise_high_confidence_stays(engine, entity_id):
    """High-confidence old memories are kept."""
    old = datetime.now(UTC) - timedelta(days=10)
    mid = await _seed_memory(
        engine.graph, entity_id, "important fact", confidence=0.9,
    )
    mem = await engine.graph.get_memory(mid)
    mem["created_at"] = old

    count = await engine.forget_noise(entity_id)
    assert count == 0


# ---- decay_episodic ----

@pytest.mark.asyncio
async def test_decay_episodic_old_memories_archived(engine, entity_id):
    """Episodic memories older than 90 days are archived."""
    old = datetime.now(UTC) - timedelta(days=100)
    mid = await _seed_memory(
        engine.graph, entity_id, "old conversation", memory_type="episodic",
    )
    mem = await engine.graph.get_memory(mid)
    mem["created_at"] = old

    count = await engine.decay_episodic()
    assert count == 1

    mem = await engine.graph.get_memory(mid)
    assert mem["is_latest"] is False


@pytest.mark.asyncio
async def test_decay_episodic_recent_stays(engine, entity_id):
    """Recent episodic memories are kept."""
    mid = await _seed_memory(
        engine.graph, entity_id, "yesterday chat", memory_type="episodic",
    )

    count = await engine.decay_episodic()
    assert count == 0

    mem = await engine.graph.get_memory(mid)
    assert mem["is_latest"] is True


@pytest.mark.asyncio
async def test_decay_episodic_facts_not_affected(engine, entity_id):
    """Non-episodic memories are never archived by episodic decay."""
    old = datetime.now(UTC) - timedelta(days=100)
    mid = await _seed_memory(
        engine.graph, entity_id, "old fact", memory_type="fact",
    )
    mem = await engine.graph.get_memory(mid)
    mem["created_at"] = old

    count = await engine.decay_episodic()
    assert count == 0

    mem = await engine.graph.get_memory(mid)
    assert mem["is_latest"] is True


# ---- Combined strategies ----

@pytest.mark.asyncio
async def test_strategies_do_not_conflict(engine, entity_id):
    """Multiple strategies can target the same memory but idempotent."""
    past = datetime.now(UTC) - timedelta(days=100)
    mid = await _seed_memory(
        engine.graph, entity_id, "old expired episodic",
        memory_type="episodic",
        valid_until=past,
        confidence=0.2,
    )
    mem = await engine.graph.get_memory(mid)
    mem["created_at"] = past

    # Time expiry runs first
    count1 = await engine.forget_expired(entity_id)
    assert count1 == 1

    # Noise filter: already archived, should not count
    count2 = await engine.forget_noise(entity_id)
    assert count2 == 0

    # Episodic decay: already archived, should not count
    count3 = await engine.decay_episodic()
    assert count3 == 0

    mem = await engine.graph.get_memory(mid)
    assert mem["is_latest"] is False
