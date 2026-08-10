"""Quality suites on real storage (Neo4j) — ADR-0001 core scenarios.

The in-memory suites (test_temporal_correctness.py / test_forgetting_effectiveness.py
/ test_graph_relationship_precision.py) run everywhere. This module re-runs the
core graph scenarios against a real Neo4j backend (docker-compose.test.yml),
covering the Cypher branches of the graph store — the same guarantees the
in-memory suites assert, plus the atomic UPDATES invariant on a real database.

Skipped when no test Neo4j is reachable; the CI `quality-temporal` job runs it
with the compose services up, so the aggregate gate covers both backends.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.quality]


async def _run_update_chain_on_neo4j(driver) -> None:
    """create_update_relation is atomic on the Cypher path."""

    from emerald.core.graph import GraphStore

    store = GraphStore(use_db=True)
    entity = "user_quality_neo4j_update"

    # Clean slate for this entity.
    async with driver.session() as session:
        await session.run(
            "MATCH (m:Memory) WHERE m.entity_id = $e DETACH DELETE m", e=entity,
        )
        await session.run("MATCH (e:Entity) WHERE e.id = $e DELETE e", e=entity)

    old_id = await store.create_memory("用户喜欢喝咖啡", entity_id=entity)
    new_id = await store.create_memory("用户不再喝咖啡", entity_id=entity)
    await store.create_update_relation(
        new_id, old_id, properties={"reason": "contradiction", "confidence": 0.8},
    )

    old = await store.get_memory(old_id)
    assert old is not None
    assert old["is_latest"] is False
    assert old["replaced_by"] == new_id

    # UPDATES edge exists and points new -> old (real graph structure).
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (new:Memory {id: $new_id})-[r:UPDATES]->(old:Memory {id: $old_id})
            RETURN r.reason AS reason, r.confidence AS confidence
            """,
            new_id=new_id, old_id=old_id,
        )
        record = await result.single()
    assert record is not None, "UPDATES edge missing on real Neo4j"
    assert record["reason"] == "contradiction"

    # Re-updating an archived target is a no-op: still exactly one edge.
    later_id = await store.create_memory("用户喜欢喝白水", entity_id=entity)
    await store.create_update_relation(later_id, old_id)
    async with driver.session() as session:
        result = await session.run(
            "MATCH ()-[r:UPDATES]->(old:Memory {id: $old_id}) RETURN count(r) AS n",
            old_id=old_id,
        )
        record = await result.single()
    assert record["n"] == 1, f"Archived target received {record['n']} UPDATES edges"


async def _run_expiry_on_neo4j(driver) -> None:
    """list_latest_memories excludes valid_until-expired on the Cypher path."""
    from datetime import UTC, datetime, timedelta

    from emerald.core.graph import GraphStore

    store = GraphStore(use_db=True)
    entity = "user_quality_neo4j_expiry"
    async with driver.session() as session:
        await session.run(
            "MATCH (m:Memory) WHERE m.entity_id = $e DETACH DELETE m", e=entity,
        )
        await session.run("MATCH (e:Entity) WHERE e.id = $e DELETE e", e=entity)

    keep_id = await store.create_memory("永久事实", entity_id=entity)
    expire_id = await store.create_memory(
        "临时安排", entity_id=entity,
        valid_until=datetime.now(UTC) - timedelta(hours=1),
    )

    latest = await store.list_latest_memories(entity, limit=10)
    ids = {m["id"] for m in latest}
    assert keep_id in ids
    assert expire_id not in ids


async def _run_entity_isolation_on_neo4j(driver) -> None:
    """Memories are scoped per entity on the Cypher path."""
    from emerald.core.graph import GraphStore

    store = GraphStore(use_db=True)
    entity_a = "user_quality_neo4j_iso_a"
    entity_b = "user_quality_neo4j_iso_b"
    async with driver.session() as session:
        for e in (entity_a, entity_b):
            await session.run(
                "MATCH (m:Memory) WHERE m.entity_id = $e DETACH DELETE m", e=e,
            )
            await session.run("MATCH (e:Entity) WHERE e.id = $e DELETE e", e=e)

    await store.create_memory("用户喜欢 Python", entity_id=entity_a)
    await store.create_memory("用户喜欢 Python", entity_id=entity_b)
    await store.update_is_latest(
        await store.create_memory("用户不再喜欢 Python", entity_id=entity_a),
        is_latest=False, replaced_by="x",  # archive an unrelated node
    )

    latest_b = await store.list_latest_memories(entity_b, limit=10)
    contents = {m["content"] for m in latest_b}
    assert contents == {"用户喜欢 Python"}, f"Entity A leaked into B: {contents}"


@pytest.mark.asyncio
async def test_quality_graph_on_neo4j(neo4j_driver):
    """Core graph-precision scenarios hold on a real Neo4j backend."""
    await _run_update_chain_on_neo4j(neo4j_driver)
    await _run_expiry_on_neo4j(neo4j_driver)
    await _run_entity_isolation_on_neo4j(neo4j_driver)
