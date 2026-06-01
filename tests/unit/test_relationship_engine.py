"""Tests for RelationshipEngine.

Covers relationship classification, atomic UPDATES transactions,
and EXTENDS / DERIVES_FROM creation.
"""

import pytest

from emerald.core.relationship import RelationType, RelationshipEngine
from emerald.core.graph import GraphStore


@pytest.fixture
def engine():
    graph = GraphStore(use_db=False)
    return RelationshipEngine(graph=graph)


@pytest.fixture
def entity_id():
    return "user_test_123"


async def _seed_memory(graph, entity_id, content, memory_type="fact", confidence=0.8):
    """Helper to create a memory and return its ID."""
    return await graph.create_memory(
        content=content,
        entity_id=entity_id,
        memory_type=memory_type,
        confidence=confidence,
    )


# ---- classify_relation ----

@pytest.mark.asyncio
async def test_classify_identical_content_returns_none(engine):
    assert (
        await engine.classify_relation("a", "b", "e", "same text", "same text")
        == RelationType.NONE
    )


@pytest.mark.asyncio
async def test_classify_contradictory_returns_updates(engine):
    """Negation words trigger UPDATES."""
    result = await engine.classify_relation(
        "a", "b", "e", "用户不再喜欢 Python", "用户喜欢 Python"
    )
    assert result == RelationType.UPDATES


@pytest.mark.asyncio
async def test_classify_complementary_returns_extends(engine):
    """Shared context + new info → EXTENDS."""
    result = await engine.classify_relation(
        "a", "b", "e", "用户在 Stripe 负责支付团队", "用户在 Stripe 工作"
    )
    assert result == RelationType.EXTENDS


@pytest.mark.asyncio
async def test_classify_same_structure_different_fillers_updates(engine):
    """Same sentence pattern with different entity → UPDATES."""
    result = await engine.classify_relation(
        "a", "b", "e", "用户在 Google 工作", "用户在 Stripe 工作"
    )
    assert result == RelationType.UPDATES


@pytest.mark.asyncio
async def test_classify_unrelated_returns_none(engine):
    result = await engine.classify_relation(
        "a", "b", "e", "猫咪在睡觉", "用户喜欢 TypeScript"
    )
    assert result == RelationType.NONE


# ---- create_update_relation ----

@pytest.mark.asyncio
async def test_update_relation_sets_is_latest_false(engine, entity_id):
    """UPDATES relation atomically sets old memory is_latest=False."""
    old_id = await _seed_memory(engine.graph, entity_id, "old fact")
    new_id = await _seed_memory(engine.graph, entity_id, "new fact")

    await engine.create_update_relation(new_id, old_id)

    old = await engine.graph.get_memory(old_id)
    assert old["is_latest"] is False
    assert old["replaced_by"] == new_id


@pytest.mark.asyncio
async def test_update_relation_skips_already_archived(engine, entity_id):
    """If old memory is already not latest, do nothing."""
    old_id = await _seed_memory(engine.graph, entity_id, "old fact")
    # Manually archive
    await engine.graph.update_is_latest(old_id, False)

    new_id = await _seed_memory(engine.graph, entity_id, "new fact")
    await engine.create_update_relation(new_id, old_id)

    old = await engine.graph.get_memory(old_id)
    assert old["replaced_by"] is None  # Not updated because already archived


# ---- create_extends_relation ----

@pytest.mark.asyncio
async def test_extends_relation_creates_graph_link(engine, entity_id):
    """EXTENDS relation is written to the graph."""
    existing_id = await _seed_memory(engine.graph, entity_id, "existing")
    new_id = await _seed_memory(engine.graph, entity_id, "new detail")

    await engine.create_extends_relation(new_id, existing_id, aspect="team")

    existing = await engine.graph.get_memory(existing_id)
    rels = existing.get("relationships", [])
    assert any(r["type"] == "EXTENDS" and r["from_id"] == new_id for r in rels)


# ---- create_derives_relation ----

@pytest.mark.asyncio
async def test_derives_relation_creates_multiple_links(engine, entity_id):
    """DERIVES_FROM creates one relationship per source."""
    src1 = await _seed_memory(engine.graph, entity_id, "source one")
    src2 = await _seed_memory(engine.graph, entity_id, "source two")
    derived = await _seed_memory(engine.graph, entity_id, "derived fact")

    await engine.create_derives_relation(derived, [src1, src2])

    for src_id in [src1, src2]:
        src = await engine.graph.get_memory(src_id)
        rels = src.get("relationships", [])
        assert any(
            r["type"] == "DERIVES_FROM" and r["from_id"] == derived for r in rels
        )


# ---- infer (end-to-end) ----

@pytest.mark.asyncio
async def test_infer_creates_updates_relation(engine, entity_id):
    """infer() walks all new memories and creates relationships."""
    old_id = await _seed_memory(engine.graph, entity_id, "用户在 Google 工作")
    new_id = await _seed_memory(engine.graph, entity_id, "用户在 Stripe 工作")

    created = await engine.infer([new_id], entity_id)
    assert created >= 1

    old = await engine.graph.get_memory(old_id)
    assert old["is_latest"] is False


@pytest.mark.asyncio
async def test_infer_skips_self(engine, entity_id):
    """New memory is not compared against itself."""
    mid = await _seed_memory(engine.graph, entity_id, "unique fact")
    created = await engine.infer([mid], entity_id)
    assert created == 0


@pytest.mark.asyncio
async def test_infer_extends_for_complementary(engine, entity_id):
    """Complementary memories trigger EXTENDS."""
    existing = await _seed_memory(engine.graph, entity_id, "用户在 Stripe 工作")
    new_id = await _seed_memory(engine.graph, entity_id, "用户在 Stripe 负责支付团队")

    created = await engine.infer([new_id], entity_id)
    assert created >= 1

    existing_mem = await engine.graph.get_memory(existing)
    rels = existing_mem.get("relationships", [])
    assert any(r["type"] == "EXTENDS" for r in rels)


@pytest.mark.asyncio
async def test_infer_derives_from_multiple_sources(engine, entity_id):
    """New memory combining 2+ sources triggers DERIVES_FROM."""
    src1 = await _seed_memory(engine.graph, entity_id, "用户喜欢 Python 编程")
    src2 = await _seed_memory(engine.graph, entity_id, "用户在 Stripe 工作")
    # Derived shares bigrams with both but adds new info
    derived = await _seed_memory(
        engine.graph, entity_id, "用户在 Stripe 用 Python 编程"
    )

    created = await engine.infer([derived], entity_id)
    # Should create at least one relationship (DERIVES_FROM)
    assert created >= 1


# ---- _find_derives_sources ----

@pytest.mark.asyncio
async def test_find_derives_sources_needs_at_least_two(engine, entity_id):
    """DERIVES_FROM requires 2+ sources."""
    src1 = await _seed_memory(engine.graph, entity_id, "source one")
    existing = [{"id": src1, "content": "source one"}]

    new_mem = {"content": "combined fact"}
    sources = RelationshipEngine._find_derives_sources(new_mem, existing)
    assert sources == []


@pytest.mark.asyncio
async def test_find_derives_sources_caps_at_three(engine, entity_id):
    """At most 3 sources are returned."""
    ids = []
    for i in range(5):
        mid = await _seed_memory(engine.graph, entity_id, f"shared word {i}")
        ids.append(mid)

    existing = [{"id": mid, "content": "shared word"} for mid in ids]
    new_mem = {"content": "shared word extra"}
    sources = RelationshipEngine._find_derives_sources(new_mem, existing)
    assert len(sources) == 3
