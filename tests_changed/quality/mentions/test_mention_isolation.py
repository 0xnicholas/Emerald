"""Quality suite section 4d — cross-entity isolation (ticket #25).

B3 T4 asserts, on the deterministic rule-only path:

- the same surface form mentioned in two entities yields two independent
  Mention nodes — the dedup key is entity-scoped (spec #21 user story 7)
- entity A's mentions are invisible from entity B's pool (graph direction)
- entity-scoped mention reads never return another entity's data (read
  direction): get_entity_mentions(a) contains only a's nodes, and a memory
  of b reads back only b's nodes — a full two-entity × two-mention matrix
  in both directions

The Neo4j Cypher branch of the same scenarios runs in
test_neo4j_mention_variants.py (skipped when no test backend is reachable).
"""

from __future__ import annotations

import pytest

from tests.quality.mentions.conftest import add_content
from tests.quality.mentions.corpus import HAPPY_PATH_CORPUS

pytestmark = [pytest.mark.quality]

# Two corpus entries mentioning different things ("Google" org, "Python" tech).
GOOGLE_ENTRY = HAPPY_PATH_CORPUS[1]
PYTHON_ENTRY = HAPPY_PATH_CORPUS[0]




async def test_same_surface_in_two_entities_yields_two_nodes(engine, entity_id):
    """Two entities mentioning "Google" get independent Mention nodes."""
    other = f"{entity_id}_other"
    mid_a = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    mid_b = await add_content(engine, other, GOOGLE_ENTRY[0])

    nodes_a = await engine.graph.get_entity_mentions(entity_id)
    nodes_b = await engine.graph.get_entity_mentions(other)
    assert len(nodes_a) == 1
    assert len(nodes_b) == 1
    assert nodes_a[0]["id"] != nodes_b[0]["id"]
    assert nodes_a[0]["canonical_form"] == nodes_b[0]["canonical_form"] == "Google"
    assert nodes_a[0]["entity_id"] == entity_id
    assert nodes_b[0]["entity_id"] == other

    # Each memory's read-back resolves to its own entity's node.
    mentions_a = await engine.graph.get_memory_mentions(mid_a)
    mentions_b = await engine.graph.get_memory_mentions(mid_b)
    assert mentions_a[0]["id"] == nodes_a[0]["id"]
    assert mentions_b[0]["id"] == nodes_b[0]["id"]


async def test_entity_a_mentions_invisible_in_entity_b_pool(engine, entity_id):
    """Entity B's pool contains none of entity A's mention nodes."""
    other = f"{entity_id}_other"
    await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    await add_content(engine, entity_id, PYTHON_ENTRY[0])
    await add_content(engine, other, GOOGLE_ENTRY[0])

    nodes_a = await engine.graph.get_entity_mentions(entity_id)
    nodes_b = await engine.graph.get_entity_mentions(other)
    ids_a = {n["id"] for n in nodes_a}
    ids_b = {n["id"] for n in nodes_b}
    # B sees exactly its own mention; no A node leaks into B's pool.
    assert len(ids_b) == 1
    assert ids_b.isdisjoint(ids_a)
    assert all(n["entity_id"] == other for n in nodes_b)


async def test_reads_are_entity_scoped_both_directions(engine, entity_id):
    """Full matrix: every entity-scoped read returns only its own nodes."""
    other = f"{entity_id}_other"
    for content, _ in (GOOGLE_ENTRY, PYTHON_ENTRY):
        await add_content(engine, entity_id, content)
        await add_content(engine, other, content)

    nodes_a = await engine.graph.get_entity_mentions(entity_id)
    nodes_b = await engine.graph.get_entity_mentions(other)
    assert len(nodes_a) == 2
    assert len(nodes_b) == 2
    assert all(n["entity_id"] == entity_id for n in nodes_a)
    assert all(n["entity_id"] == other for n in nodes_b)
    assert {n["id"] for n in nodes_a}.isdisjoint({n["id"] for n in nodes_b})


async def test_unknown_entity_mention_read_returns_empty(engine, entity_id):
    """Reading mentions for an unknown entity yields an empty list."""
    await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    assert await engine.graph.get_entity_mentions(f"{entity_id}_ghost") == []
