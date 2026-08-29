"""Tests for ForgetEngine.

AGENTS.md requirement:
- "没有遗忘，每句随意的话都会变成永久记忆"
- "系统必须能区分有意义的事实和短暂的闲聊"
"""

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.forget import ForgetEngine
from emerald.core.graph import GraphStore


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.fixture
def engine(graph):
    return ForgetEngine(graph=graph)


# ---- Time-based expiry ----


@pytest.mark.asyncio
async def test_time_expiry_marks_expired(engine, graph):
    """Memories past their valid_until are marked is_latest=False."""
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)

    # Create a memory that expires yesterday
    mid = await graph.create_memory(
        "明天有考试", entity_id="user_123",
    )
    # Manually set as expired (valid_until in the past)
    for memories in graph._memories.values():
        for m in memories:
            if m["id"] == mid:
                m["valid_until"] = yesterday

    # Run forget
    count = await engine.forget_expired()
    assert count >= 1

    memory = await graph.get_memory(mid)
    assert memory["is_latest"] is False
    assert memory.get("expired_at") is not None


@pytest.mark.asyncio
async def test_time_expiry_ignores_future(engine, graph):
    """Memories with valid_until in the future are untouched."""
    now = datetime.now(UTC)
    tomorrow = now + timedelta(days=1)

    mid = await graph.create_memory("明天有考试", entity_id="user_123")
    for memories in graph._memories.values():
        for m in memories:
            if m["id"] == mid:
                m["valid_until"] = tomorrow

    count = await engine.forget_expired()
    assert count == 0

    memory = await graph.get_memory(mid)
    assert memory["is_latest"] is True


@pytest.mark.asyncio
async def test_time_expiry_ignores_no_valid_until(engine, graph):
    """Memories without valid_until are never time-expired."""
    mid = await graph.create_memory("一个普通的事实", entity_id="user_123")
    count = await engine.forget_expired()
    assert count == 0
    memory = await graph.get_memory(mid)
    assert memory["is_latest"] is True


# ---- Noise filtering ----


@pytest.mark.asyncio
async def test_noise_filter_removes_low_confidence_old(engine, graph):
    """Low-confidence, old, unreferenced memories are archived."""
    now = datetime.now(UTC)
    eight_days_ago = now - timedelta(days=8)

    mid = await graph.create_memory(
        "随便说的一句闲聊", entity_id="user_123",
        confidence=0.2,
    )
    # Manually age the memory
    for memories in graph._memories.values():
        for m in memories:
            if m["id"] == mid:
                m["created_at"] = eight_days_ago

    count = await engine.forget_noise()
    assert count >= 1

    memory = await graph.get_memory(mid)
    assert memory["is_latest"] is False


@pytest.mark.asyncio
async def test_noise_filter_keeps_recent(engine, graph):
    """Low-confidence but recent memories are kept."""
    mid = await graph.create_memory(
        "最近的闲聊", entity_id="user_123",
        confidence=0.2,
    )
    count = await engine.forget_noise()
    assert count == 0
    memory = await graph.get_memory(mid)
    assert memory["is_latest"] is True


@pytest.mark.asyncio
async def test_noise_filter_keeps_high_confidence(engine, graph):
    """High-confidence old memories are kept."""
    now = datetime.now(UTC)
    eight_days_ago = now - timedelta(days=8)

    mid = await graph.create_memory(
        "一个重要的事实", entity_id="user_123",
        confidence=0.9,
    )
    for memories in graph._memories.values():
        for m in memories:
            if m["id"] == mid:
                m["created_at"] = eight_days_ago

    count = await engine.forget_noise()
    assert count == 0
    memory = await graph.get_memory(mid)
    assert memory["is_latest"] is True


# ---- Episodic decay ----


@pytest.mark.asyncio
async def test_episodic_decay_archives_old(engine, graph):
    """Episodic memories > 90 days are archived."""
    now = datetime.now(UTC)
    ninety_one_days_ago = now - timedelta(days=91)

    mid = await graph.create_memory(
        "和老朋友喝了一杯咖啡", entity_id="user_123",
        memory_type="episodic",
    )
    for memories in graph._memories.values():
        for m in memories:
            if m["id"] == mid:
                m["created_at"] = ninety_one_days_ago

    count = await engine.decay_episodic()
    assert count >= 1

    memory = await graph.get_memory(mid)
    assert memory["is_latest"] is False


@pytest.mark.asyncio
async def test_episodic_decay_keeps_recent(engine, graph):
    """Recent episodic memories (< 30 days) are kept."""
    mid = await graph.create_memory(
        "昨天和团队开了个会", entity_id="user_123",
        memory_type="episodic",
    )
    count = await engine.decay_episodic()
    assert count == 0
    memory = await graph.get_memory(mid)
    assert memory["is_latest"] is True


@pytest.mark.asyncio
async def test_episodic_decay_only_affects_episodic(engine, graph):
    """Non-episodic memories are never decayed."""
    now = datetime.now(UTC)
    ninety_one_days_ago = now - timedelta(days=91)

    mid = await graph.create_memory(
        "一个重要的事实", entity_id="user_123",
        memory_type="fact",
    )
    for memories in graph._memories.values():
        for m in memories:
            if m["id"] == mid:
                m["created_at"] = ninety_one_days_ago

    count = await engine.decay_episodic()
    assert count == 0
    memory = await graph.get_memory(mid)
    assert memory["is_latest"] is True
