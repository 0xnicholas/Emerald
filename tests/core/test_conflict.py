"""Tests for optional interactive conflict confirmation."""

import pytest

from emerald.core.conflict import ConflictEngine, ResolutionAction
from emerald.core.graph import GraphStore
from emerald.core.relationship import RelationshipEngine


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.fixture
def rel_engine(graph):
    return RelationshipEngine(graph=graph)


@pytest.fixture
def conflict_engine(graph):
    return ConflictEngine(graph=graph)


@pytest.mark.asyncio
async def test_high_impact_conflict_flagged_when_confirmation_enabled(graph, rel_engine):
    """A high-confidence contradiction on a decision is flagged, not auto-resolved."""
    old_id = await graph.create_memory(
        "我们决定使用 PostgreSQL",
        entity_id="user_123",
        memory_type="fact",
        internal_type="decision",
        confidence=0.9,
    )
    new_id = await graph.create_memory(
        "我们决定改用 MySQL",
        entity_id="user_123",
        memory_type="fact",
        internal_type="decision",
        confidence=0.95,
    )

    result = await rel_engine.infer_with_conflicts(
        [new_id],
        entity_id="user_123",
        require_confirmation_for_high_impact=True,
    )

    assert result["relationships_created"] == 0
    assert len(result["pending_conflicts"]) == 1
    assert result["pending_conflicts"][0]["old_memory_id"] == old_id

    old_memory = await graph.get_memory(old_id)
    assert old_memory["is_latest"] is True


@pytest.mark.asyncio
async def test_low_impact_conflict_auto_resolved(graph, rel_engine):
    """A generic fact contradiction is still auto-resolved."""
    old_id = await graph.create_memory(
        "用户住在北京",
        entity_id="user_123",
        memory_type="fact",
        confidence=0.9,
    )
    new_id = await graph.create_memory(
        "用户住在上海",
        entity_id="user_123",
        memory_type="fact",
        confidence=0.95,
    )

    result = await rel_engine.infer_with_conflicts(
        [new_id],
        entity_id="user_123",
        require_confirmation_for_high_impact=True,
    )

    assert len(result["pending_conflicts"]) == 0
    assert result["relationships_created"] == 1

    old_memory = await graph.get_memory(old_id)
    assert old_memory["is_latest"] is False


@pytest.mark.asyncio
async def test_conflict_resolution_keep_new(graph, rel_engine, conflict_engine):
    """Resolving a conflict with keep_new applies the update."""
    old_id = await graph.create_memory(
        "我们决定使用 PostgreSQL",
        entity_id="user_123",
        memory_type="fact",
        internal_type="decision",
        confidence=0.9,
    )
    new_id = await graph.create_memory(
        "我们决定改用 MySQL",
        entity_id="user_123",
        memory_type="fact",
        internal_type="decision",
        confidence=0.95,
    )

    result = await rel_engine.infer_with_conflicts(
        [new_id],
        entity_id="user_123",
        require_confirmation_for_high_impact=True,
    )
    conflict_id = result["pending_conflicts"][0]["conflict_id"]

    resolve_result = await conflict_engine.resolve(conflict_id, ResolutionAction.KEEP_NEW)
    assert resolve_result["status"] == "resolved"

    old_memory = await graph.get_memory(old_id)
    assert old_memory["is_latest"] is False
    new_memory = await graph.get_memory(new_id)
    assert new_memory["is_latest"] is True


@pytest.mark.asyncio
async def test_conflict_resolution_keep_old(graph, rel_engine, conflict_engine):
    """Resolving a conflict with keep_old archives the new memory."""
    old_id = await graph.create_memory(
        "我们决定使用 PostgreSQL",
        entity_id="user_123",
        memory_type="fact",
        internal_type="decision",
        confidence=0.9,
    )
    new_id = await graph.create_memory(
        "我们决定改用 MySQL",
        entity_id="user_123",
        memory_type="fact",
        internal_type="decision",
        confidence=0.95,
    )

    result = await rel_engine.infer_with_conflicts(
        [new_id],
        entity_id="user_123",
        require_confirmation_for_high_impact=True,
    )
    conflict_id = result["pending_conflicts"][0]["conflict_id"]

    resolve_result = await conflict_engine.resolve(conflict_id, ResolutionAction.KEEP_OLD)
    assert resolve_result["status"] == "resolved"

    old_memory = await graph.get_memory(old_id)
    assert old_memory["is_latest"] is True
    new_memory = await graph.get_memory(new_id)
    assert new_memory["is_latest"] is False


@pytest.mark.asyncio
async def test_conflict_impact_score_bounds():
    """Impact score is clamped to [0, 1]."""
    high = {"memory_type": "fact", "internal_type": "decision", "confidence": 0.95}
    old = {"memory_type": "fact", "internal_type": "decision", "confidence": 0.9}
    score = ConflictEngine.impact_score(high, old)
    assert 0.0 <= score <= 1.0
