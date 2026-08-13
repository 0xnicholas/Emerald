"""Mention scenarios on real storage (Neo4j) — ticket #25.

The in-memory mention suites (test_mention_precision.py /
test_mention_resolution.py / test_mention_taxonomy.py /
test_mention_isolation.py) run everywhere. This module re-runs the core
mention scenarios against a real Neo4j backend, covering the Cypher
branches of attach_mentions / get_entity_mentions / get_memory_mentions:

- cross-memory resolution + alias accumulation on the MERGE branch (#23)
- idempotent re-attach and confidence gating on the Cypher branch (#24)
- cross-entity isolation — graph direction (entity B has no path to
  entity A's Mention nodes) and read direction (#25)

Skipped when no test Neo4j is reachable; the CI `quality-temporal` job
runs it with the compose services up, so the aggregate gate covers both
backends.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.quality]


async def _clean_entity(driver, entity: str) -> None:
    """Remove an entity's memories, mentions and entity node (clean slate)."""
    async with driver.session() as session:
        await session.run(
            "MATCH (m:Memory) WHERE m.entity_id = $e DETACH DELETE m", e=entity,
        )
        await session.run(
            "MATCH (mn:Mention) WHERE mn.entity_id = $e DETACH DELETE mn", e=entity,
        )
        await session.run(
            "MATCH (e:Entity) WHERE e.id = $e DETACH DELETE e", e=entity,
        )


async def _run_resolution_and_gating_on_neo4j(driver) -> None:
    """Resolution, idempotency and gating hold on the Cypher branch."""
    from emerald.core.graph import GraphStore
    from emerald.core.mentions import Mention

    store = GraphStore(use_db=True)
    entity = "user_quality_neo4j_mention_res"
    await _clean_entity(driver, entity)

    mid_a = await store.create_memory("在 Google 工作", entity_id=entity)
    mid_b = await store.create_memory("在谷歌工作", entity_id=entity)
    assert (
        await store.attach_mentions(
            mid_a, entity, [Mention("Google", "Google", "organization", 0.9)],
        )
        == 1
    )
    assert (
        await store.attach_mentions(
            mid_b, entity, [Mention("谷歌", "Google", "organization", 0.9)],
        )
        == 1
    )

    # One resolved node, aliases accumulated, count = number of edges.
    nodes = await store.get_entity_mentions(entity)
    assert len(nodes) == 1
    node = nodes[0]
    assert node["canonical_form"] == "Google"
    assert sorted(node["aliases"]) == ["Google", "谷歌"]
    assert node["mention_count"] == 2

    # Re-attaching the same memory's mention is idempotent on Cypher.
    assert (
        await store.attach_mentions(
            mid_b, entity, [Mention("谷歌", "Google", "organization", 0.9)],
        )
        == 0
    )
    nodes = await store.get_entity_mentions(entity)
    assert len(nodes) == 1
    assert nodes[0]["mention_count"] == 2

    # Confidence gating drops below-threshold mentions on Cypher.
    mid_c = await store.create_memory("无关记忆", entity_id=entity)
    assert (
        await store.attach_mentions(
            mid_c, entity, [Mention("Google", "Google", "organization", 0.1)],
        )
        == 0
    )
    assert await store.get_memory_mentions(mid_c) == []


async def _run_isolation_on_neo4j(driver) -> None:
    """Cross-entity isolation holds on the Cypher branch, both directions."""
    from emerald.core.graph import GraphStore
    from emerald.core.mentions import Mention

    store = GraphStore(use_db=True)
    entity_a = "user_quality_neo4j_mention_iso_a"
    entity_b = "user_quality_neo4j_mention_iso_b"
    await _clean_entity(driver, entity_a)
    await _clean_entity(driver, entity_b)

    mentions = [
        Mention("Google", "Google", "organization", 0.9),
        Mention("Python", "Python", "technology", 0.9),
    ]
    mid_a = await store.create_memory("在 Google 用 Python", entity_id=entity_a)
    mid_b = await store.create_memory("在 Google 用 Python", entity_id=entity_b)
    await store.attach_mentions(mid_a, entity_a, mentions)
    await store.attach_mentions(mid_b, entity_b, mentions)

    nodes_a = await store.get_entity_mentions(entity_a)
    nodes_b = await store.get_entity_mentions(entity_b)
    assert len(nodes_a) == 2
    assert len(nodes_b) == 2
    # Same surface forms, independent nodes per entity.
    assert {n["id"] for n in nodes_a}.isdisjoint({n["id"] for n in nodes_b})
    assert all(n["entity_id"] == entity_a for n in nodes_a)
    assert all(n["entity_id"] == entity_b for n in nodes_b)

    # Read direction: entity B's memory reads back only B's nodes.
    mentions_b = await store.get_memory_mentions(mid_b)
    assert {m["id"] for m in mentions_b} == {n["id"] for n in nodes_b}
    assert all(m["entity_id"] == entity_b for m in mentions_b)

    # Graph direction: entity B has no path to any of A's Mention nodes.
    async with driver.session() as session:
        for node in nodes_a:
            result = await session.run(
                """
                MATCH p=(eB:Entity {id: $b})-[*1..4]->(mn:Mention {id: $nid})
                RETURN count(p) AS n
                """,
                b=entity_b,
                nid=node["id"],
            )
            record = await result.single()
            assert record is not None
            assert record["n"] == 0, (
                f"entity {entity_b} has a path to entity {entity_a}'s "
                f"mention {node['id']}"
            )


@pytest.mark.asyncio
async def test_mention_scenarios_on_neo4j(neo4j_driver):
    """Core mention scenarios hold on a real Neo4j backend."""
    await _run_resolution_and_gating_on_neo4j(neo4j_driver)
    await _run_isolation_on_neo4j(neo4j_driver)
