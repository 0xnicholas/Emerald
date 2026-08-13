"""Quality suite section 4 — mention precision: happy path (ticket #22).

B3 T1 asserts, on the deterministic rule-only path:

- a memory whose facts mention named entities produces typed Mention nodes
  in that entity's context pool (spec #21 user stories 1, 6, 7)
- the memory links to each Mention via a MENTIONS edge, Memory → Mention
  (user story 9; the edge is a reference category, not a fact relation)
- each Mention belongs to exactly one Entity (HAS_MENTION) and is isolated
  by entity — a full cross-entity leakage matrix lands in #25
- mentions are readable back through the internal graph method (no public
  API in B3)
- the rule/mock extraction path is deterministic (no LLM) — the exact
  (canonical_form, type) expectations below only hold under determinism
- memories without named entities ingest with zero mentions (user story 11)
- ingestion logs the mention count (user story 17)

Later B3 tickets extend this section: canonical resolution / alias
accumulation (#23), closed-taxonomy validation + confidence gating (#24),
cross-entity isolation + Neo4j variants (#25), UPDATES integration (#26),
forgetting integration (#27).

Deterministic labelled corpus + mock embeddings + rule-only path.
"""

from __future__ import annotations

import pytest

from tests.quality.mentions.corpus import HAPPY_PATH_CORPUS

pytestmark = [pytest.mark.quality]


async def _expected_mentions(graph, memory_id: str) -> list[dict]:
    """Read back a memory's mentions through the internal graph method."""
    return await graph.get_memory_mentions(memory_id)


async def test_mention_nodes_created_with_type_in_entity_pool(engine, entity_id):
    """Mentions become typed Mention nodes inside the entity's pool."""
    content, expected = HAPPY_PATH_CORPUS[4]
    result = await engine.add(content, entity_id=entity_id)
    assert len(result.memory_ids) == 1
    memory_id = result.memory_ids[0]

    mentions = await _expected_mentions(engine.graph, memory_id)
    assert len(mentions) == len(expected)
    for mention, (canonical, mention_type) in zip(mentions, expected, strict=True):
        assert mention["canonical_form"] == canonical
        assert mention["type"] == mention_type
        assert mention["entity_id"] == entity_id
        assert mention["mention_count"] == 1
        assert 0.0 <= mention["confidence"] <= 1.0

    # The nodes live in the entity's mention pool (HAS_MENTION ownership).
    pool = engine.graph._mentions.get(entity_id, [])
    assert {m["id"] for m in mentions} == {n["id"] for n in pool}


async def test_mentions_edge_direction_memory_to_mention(engine, entity_id):
    """Each memory carries MENTIONS edges pointing at its mention nodes."""
    content, expected = HAPPY_PATH_CORPUS[1]  # "用户在 Google 工作"
    result = await engine.add(content, entity_id=entity_id)
    memory_id = result.memory_ids[0]

    memory = await engine.graph.get_memory(memory_id)
    edges = memory.get("mentions", [])
    assert len(edges) == len(expected)
    edge = edges[0]
    assert edge["surface_form"] == "Google"
    assert 0.0 <= edge["confidence"] <= 1.0

    # Every edge resolves to a Mention node in the entity's pool — the edge
    # direction is Memory → Mention (nodes never point back at memories).
    pool_by_id = {n["id"]: n for n in engine.graph._mentions[entity_id]}
    assert edge["mention_id"] in pool_by_id
    assert pool_by_id[edge["mention_id"]]["type"] == "organization"


async def test_mention_belongs_to_exactly_one_entity(engine, entity_id):
    """Mention nodes are scoped to exactly one entity's context pool."""
    content, _ = HAPPY_PATH_CORPUS[0]
    result = await engine.add(content, entity_id=entity_id)
    mentions = await _expected_mentions(engine.graph, result.memory_ids[0])

    assert len(mentions) == 1
    node = engine.graph._mentions[entity_id][0]
    assert node["entity_id"] == entity_id
    assert node["id"] == mentions[0]["id"]
    # No other pool contains this mention node.
    for other_entity, pool in engine.graph._mentions.items():
        if other_entity != entity_id:
            assert node["id"] not in {n["id"] for n in pool}


async def test_rule_path_is_deterministic(engine, entity_id):
    """The rule path yields identical mentions for identical content.

    Two entity pools ingesting the same content produce structurally
    identical mention sets (each scoped to its own pool).
    """
    content, expected = HAPPY_PATH_CORPUS[4]
    result_a = await engine.add(content, entity_id=entity_id)
    other_entity = f"{entity_id}_b"
    result_b = await engine.add(content, entity_id=other_entity)

    mentions_a = await _expected_mentions(engine.graph, result_a.memory_ids[0])
    mentions_b = await _expected_mentions(engine.graph, result_b.memory_ids[0])

    def shape(ms):
        return [(m["canonical_form"], m["type"], m["surface_form"]) for m in ms]

    # Identical structure across pools, and exactly the labelled mentions.
    assert shape(mentions_a) == shape(mentions_b)
    assert [(m["canonical_form"], m["type"]) for m in mentions_a] == expected


async def test_memory_without_mentions_ingests_with_zero_mentions(engine, entity_id):
    """No named entities → zero mentions, the memory still ingests."""
    content, expected = HAPPY_PATH_CORPUS[6]
    assert expected == []
    result = await engine.add(content, entity_id=entity_id)
    assert len(result.memory_ids) == 1
    assert await _expected_mentions(engine.graph, result.memory_ids[0]) == []
    memory = await engine.graph.get_memory(result.memory_ids[0])
    assert memory["is_latest"] is True


async def test_ingestion_logs_mention_count(engine, entity_id):
    """The ingestion completion log records the extracted mention count."""
    import structlog

    with structlog.testing.capture_logs() as logs:
        await engine.add(HAPPY_PATH_CORPUS[4][0], entity_id=entity_id)

    complete = [e for e in logs if e.get("event") == "memory.add.complete"]
    assert complete, "memory.add.complete log missing"
    assert complete[-1]["mention_count"] == 2


# ---------------------------------------------------------------------------
# Aggregate gate — every corpus entry must yield exactly its labelled
# mentions; precision is 100% on the deterministic rule path.
# ---------------------------------------------------------------------------


async def test_mention_precision_metrics(engine, entity_id) -> None:
    """Aggregate gate: mention extraction precision on the labelled corpus."""
    total = 0
    correct = 0
    for content, expected in HAPPY_PATH_CORPUS:
        result = await engine.add(content, entity_id=entity_id)
        assert len(result.memory_ids) == 1, f"expected one memory for {content!r}"
        mentions = await _expected_mentions(engine.graph, result.memory_ids[0])
        got = [(m["canonical_form"], m["type"]) for m in mentions]
        total += len(expected)
        correct += sum(1 for e in expected if e in got)
        assert got == expected, (
            f"mention mismatch for {content!r}: got={got} expected={expected}"
        )

    precision = correct / total if total else 1.0
    print(
        f"\n[mention-precision] extraction precision={precision:.3f} "
        f"({correct}/{total})"
    )
    assert precision >= 0.95
