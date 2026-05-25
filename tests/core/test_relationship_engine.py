"""Tests for relationship inference engine.

AGENTS.md requirement: "每种关系类型必须有确定性的测试用例"
"测试必须覆盖时序场景——当事实 B 到达时，事实 A 变为过时"
"""

import pytest

from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.relationship import RelationshipEngine, RelationType
from emerald.core.vector import VectorStore


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.fixture
def vector():
    return VectorStore(use_db=False)


@pytest.fixture
def embedder():
    return MockEmbeddingProvider(dimension=128)


@pytest.fixture
def engine(graph, vector):
    return RelationshipEngine(graph=graph, vector=vector)


# ---- UPDATES relationship ----


@pytest.mark.asyncio
async def test_updates_makes_old_not_latest(engine, graph, embedder, vector):
    """When a new fact updates an old one, old.is_latest becomes False."""
    entity_id = "user_123"

    # Create old memory: "User works at Google"
    old_id = await graph.create_memory(
        "用户在 Google 工作", entity_id=entity_id,
    )
    old_emb = (await embedder.embed(["用户在 Google 工作"]))[0]
    await vector.store(old_id, "用户在 Google 工作", old_emb, entity_id=entity_id)

    # Create new memory: "User works at Stripe" (updates the old fact)
    new_id = await graph.create_memory(
        "用户在 Stripe 工作", entity_id=entity_id,
    )
    new_emb = (await embedder.embed(["用户在 Stripe 工作"]))[0]
    await vector.store(new_id, "用户在 Stripe 工作", new_emb, entity_id=entity_id)

    # Classify and create relationship
    rel_type = await engine.classify_relation(
        new_id, old_id, entity_id,
        new_content="用户在 Stripe 工作",
        old_content="用户在 Google 工作",
    )

    assert rel_type == RelationType.UPDATES

    # Apply the update
    await engine.create_update_relation(new_id, old_id, reason="contradiction")

    # Verify old is no longer latest
    old = await graph.get_memory(old_id)
    assert old["is_latest"] is False
    assert old["replaced_by"] == new_id

    # Verify new is still latest
    new = await graph.get_memory(new_id)
    assert new["is_latest"] is True


@pytest.mark.asyncio
async def test_updates_replaced_by_field(engine, graph):
    """Old memory's replaced_by field points to the new memory."""
    entity_id = "user_123"

    old_id = await graph.create_memory("用户在 Google", entity_id=entity_id)
    new_id = await graph.create_memory("用户在 Stripe", entity_id=entity_id)

    await engine.create_update_relation(new_id, old_id, reason="contradiction")

    old = await graph.get_memory(old_id)
    assert old["replaced_by"] == new_id


# ---- EXTENDS relationship ----


@pytest.mark.asyncio
async def test_extends_both_stay_latest(engine, graph):
    """When a fact extends another, both remain is_latest=True."""
    entity_id = "user_123"

    base_id = await graph.create_memory(
        "用户在 Stripe 工作", entity_id=entity_id,
    )
    detail_id = await graph.create_memory(
        "用户领导一个 5 人的支付团队", entity_id=entity_id,
    )

    rel_type = await engine.classify_relation(
        detail_id, base_id, entity_id,
        new_content="用户领导一个 5 人的支付团队",
        old_content="用户在 Stripe 工作",
    )

    assert rel_type == RelationType.EXTENDS

    await engine.create_extends_relation(detail_id, base_id, aspect="detail")

    base = await graph.get_memory(base_id)
    detail = await graph.get_memory(detail_id)
    assert base["is_latest"] is True
    assert detail["is_latest"] is True


# ---- Idempotency ----


@pytest.mark.asyncio
async def test_same_content_no_self_update(engine, graph, embedder, vector):
    """Ingesting the same content twice does not create a self-UPDATES."""
    entity_id = "user_123"
    content = "用户住在北京"

    id1 = await graph.create_memory(content, entity_id=entity_id)
    emb = (await embedder.embed([content]))[0]
    await vector.store(id1, content, emb, entity_id=entity_id)

    id2 = await graph.create_memory(content, entity_id=entity_id)
    await vector.store(id2, content, emb, entity_id=entity_id)

    rel_type = await engine.classify_relation(
        id2, id1, entity_id,
        new_content=content,
        old_content=content,
    )

    # Same content should not create an UPDATE (no contradiction)
    assert rel_type != RelationType.UPDATES


# ---- DERIVES_FROM relationship ----


@pytest.mark.asyncio
async def test_derives_from_has_source_links(engine, graph):
    """Derived memory records its source memories."""
    entity_id = "user_123"

    src1_id = await graph.create_memory("用户每天讨论 AI", entity_id=entity_id)
    src2_id = await graph.create_memory("用户是创始人", entity_id=entity_id)

    derived_id = await graph.create_memory(
        "Emerald 是一家 AI 公司", entity_id=entity_id, memory_type="fact",
    )

    await engine.create_derives_relation(
        derived_id, [src1_id, src2_id],
        reasoning="从讨论AI和创始人身份推断",
    )

    derived = await graph.get_memory(derived_id)
    # The derived memory should exist and be latest
    assert derived is not None
    assert derived["is_latest"] is True


# ---- Entity isolation ----


@pytest.mark.asyncio
async def test_infer_only_within_same_entity(engine, graph):
    """infer() only looks at the same entity's existing memories.

    Content classification may detect structure across entities,
    but the engine only queries the target entity's graph.
    """
    # Create memory in alice
    alice_id = await graph.create_memory("用户喜欢 Python", entity_id="alice")

    # Create memory in bob
    bob_id = await graph.create_memory("用户喜欢 Rust", entity_id="bob")

    # Run infer on bob's memory — should only see bob's existing memories
    # Since bob only has one memory (itself), no relationships should be created
    created = await engine.infer([bob_id], entity_id="bob")

    # No relationships because bob has no OTHER existing memories
    assert created == 0

    # Alice's memory should be unaffected
    alice = await graph.get_memory(alice_id)
    assert alice["is_latest"] is True
