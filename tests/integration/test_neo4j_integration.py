"""Neo4j integration tests — verify GraphStore with a real Neo4j instance.

Uses a local Neo4j (localhost:7687, neo4j/emerald_dev) instead of
testcontainers when Docker is unavailable.

Start a local Neo4j manually before running these tests:
    cd /tmp/neo4j-community-5.26.0
    bin/neo4j start
    bin/neo4j-admin dbms set-initial-password emerald_dev

Or set EMERALD_TEST_NEO4J_URI / EMERALD_TEST_NEO4J_PASSWORD to point elsewhere.
"""

from __future__ import annotations

import os

import pytest

NEO4J_URI = os.environ.get("EMERALD_TEST_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("EMERALD_TEST_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("EMERALD_TEST_NEO4J_PASSWORD", "emerald_dev")


@pytest.fixture(scope="module")
def neo4j_available():
    """Skip module if local Neo4j is not reachable."""
    import asyncio

    from neo4j import AsyncGraphDatabase

    async def _check():
        try:
            driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            await driver.verify_connectivity()
            await driver.close()
            return True
        except Exception:
            return False

    if not asyncio.run(_check()):
        pytest.skip("Local Neo4j not reachable at " + NEO4J_URI, allow_module_level=True)


@pytest.fixture
async def neo4j_driver(neo4j_available):
    """Yield an initialized Neo4j driver connected to the local instance."""
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    await driver.verify_connectivity()

    # Patch get_neo4j_driver to return this driver
    import emerald.db.neo4j as neo4j_mod

    original = neo4j_mod.get_neo4j_driver

    def _patched():
        return driver

    neo4j_mod.get_neo4j_driver = _patched
    neo4j_mod._driver = driver

    yield driver

    # Cleanup: delete test data. Memory ids are random hex (not prefixed),
    # so memories are matched through their entity; Mention nodes through
    # their entity_id property (they carry no id prefix either).
    async with driver.session() as session:
        await session.run(
            "MATCH (mn:Mention) WHERE mn.entity_id STARTS WITH 'user_int_test' DETACH DELETE mn"
        )
        await session.run(
            "MATCH (e:Entity)-[:HAS_MEMORY]->(m:Memory) "
            "WHERE e.id STARTS WITH 'user_int_test' DETACH DELETE m"
        )
        await session.run(
            "MATCH (e:Entity) WHERE e.id STARTS WITH 'user_int_test' DETACH DELETE e"
        )

    await driver.close()
    neo4j_mod.get_neo4j_driver = original
    neo4j_mod._driver = None


@pytest.mark.asyncio
async def test_graph_store_create_memory(neo4j_driver):
    """GraphStore with use_db=True creates a memory node in Neo4j."""
    from emerald.core.graph import GraphStore

    store = GraphStore(use_db=True)
    memory_id = await store.create_memory(
        "用户喜欢 TypeScript",
        entity_id="user_int_test_1",
        memory_type="preference",
        confidence=0.95,
    )
    assert memory_id

    # Verify retrieval
    memory = await store.get_memory(memory_id)
    assert memory is not None
    assert "用户喜欢 TypeScript" in memory["content"]


@pytest.mark.asyncio
async def test_graph_store_list_latest_excludes_expired(neo4j_driver):
    """list_latest_memories excludes entries whose valid_until has passed."""
    from datetime import UTC, datetime, timedelta

    from emerald.core.graph import GraphStore

    store = GraphStore(use_db=True)
    entity_id = "user_int_test_2"

    # Create a normal memory
    mid1 = await store.create_memory(
        "正常工作",
        entity_id=entity_id,
    )

    # Create an already-expired memory
    past = datetime.now(UTC) - timedelta(hours=1)
    mid2 = await store.create_memory(
        "已过期",
        entity_id=entity_id,
        valid_until=past,
    )

    latest = await store.list_latest_memories(entity_id, limit=10)
    ids = {m["id"] for m in latest}
    assert mid1 in ids
    assert mid2 not in ids


@pytest.mark.asyncio
async def test_graph_store_update_is_latest(neo4j_driver):
    """update_is_latest sets is_latest=False and records replaced_by."""
    from emerald.core.graph import GraphStore

    store = GraphStore(use_db=True)
    entity_id = "user_int_test_3"

    old_id = await store.create_memory("旧事实", entity_id=entity_id)
    new_id = await store.create_memory("新事实", entity_id=entity_id)

    await store.update_is_latest(old_id, is_latest=False, replaced_by=new_id)

    old = await store.get_memory(old_id)
    assert old["is_latest"] is False
    assert old["replaced_by"] == new_id


# ---------------------------------------------------------------------------
# B6 T2 (#43): mark_consolidated on the Neo4j backend — the single-statement
# disposal + rewiring must match the in-memory behavior (dual-backend
# consistency, ticket criterion 2). The Cypher branch cannot be exercised
# by the in-memory unit suite, so the key invariants are asserted here:
# disposal fields + metadata reason, MENTIONS rewire/dedup with
# mention_count, EXTENDS/DERIVES_FROM rewiring exactly once (no row
# multiplication), UPDATES edges untouched, no self-loops, no
# representative→merged UPDATES edge, and the cross-entity no-op guard.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_consolidated_disposal_and_rewiring(neo4j_driver):
    """End-to-end consolidation on Neo4j: disposal, metadata, mention
    rewiring with dedup, EXTENDS/DERIVES_FROM rewiring, no UPDATES edge."""
    import json

    from emerald.core.graph import GraphStore
    from emerald.core.mentions import Mention

    store = GraphStore(use_db=True)
    entity_id = "user_int_test_consolidation"

    rep = await store.create_memory("用户住在北京", entity_id=entity_id)
    merged = await store.create_memory(
        "用户住在北京", entity_id=entity_id, metadata={"src": "conv"}
    )
    other = await store.create_memory("北京有地铁", entity_id=entity_id)
    await store.attach_mentions(rep, entity_id, [Mention("北京", "北京", "concept", 0.9)])
    await store.attach_mentions(merged, entity_id, [Mention("北京", "北京", "concept", 0.9)])
    await store.attach_mentions(merged, entity_id, [Mention("地铁", "地铁", "concept", 0.9)])
    await store.attach_mentions(other, entity_id, [Mention("北京", "北京", "concept", 0.9)])
    await store.create_relationship(merged, other, "EXTENDS", {"aspect": "detail"})
    await store.create_relationship(other, merged, "DERIVES_FROM", {"reasoning": "combined"})
    await store.create_relationship(rep, merged, "EXTENDS")  # self-loop guard case

    await store.mark_consolidated(merged, rep)

    # Disposal + metadata (Neo4j stores metadata as a JSON string).
    memory = await store.get_memory(merged)
    assert memory["is_latest"] is False
    assert memory["replaced_by"] == rep
    assert memory["expired_at"] is not None
    meta = json.loads(memory["metadata"])
    assert meta["reason"] == "consolidated"
    assert meta["src"] == "conv"

    # Representative untouched; no rep→merged UPDATES edge. (Neo4j
    # nodes omit null-valued properties, so unset keys read as absent.)
    rep_memory = await store.get_memory(rep)
    assert rep_memory["is_latest"] is True
    assert rep_memory.get("replaced_by") is None
    assert rep_memory.get("expired_at") is None
    updates = await store.get_relationship_neighbors([rep, merged], ["UPDATES"])
    assert updates == {}

    # MENTIONS: dedup 北京 into rep's existing edge (count 3→2), move 地铁.
    rep_mentions = await store.get_memory_mentions(rep)
    by_form = {m["surface_form"]: m for m in rep_mentions}
    assert set(by_form) == {"北京", "地铁"}
    assert by_form["北京"]["mention_count"] == 2  # rep + other
    assert by_form["地铁"]["mention_count"] == 1
    assert await store.get_memory_mentions(merged) == []
    referencing = await store.get_memories_mentioning(entity_id, "北京")
    assert sorted(m["id"] for m in referencing) == sorted([rep, other])

    # EXTENDS/DERIVES_FROM rewired exactly once (multi-mention input must
    # not multiply rows), self-loop case stays as rep→merged.
    out = await store.get_relationship_neighbors([rep, merged], ["EXTENDS", "DERIVES_FROM"])
    extends = [e for e in out.get(rep, []) if e["rel_type"] == "EXTENDS"]
    assert {e["id"] for e in extends} == {merged, other}  # rep→merged kept, rep→other exactly once
    derives = [e for e in out.get(rep, []) if e["rel_type"] == "DERIVES_FROM"]
    assert [e["id"] for e in derives] == [other]
    # merged's only remaining edge is the self-loop-guard rep→merged one.
    merged_edges = out.get(merged, [])
    assert [e["id"] for e in merged_edges] == [rep]

    # Rewired edge properties survive.
    rel = await store.get_relationship_by_property("EXTENDS", "aspect", "detail")
    assert rel is not None and rel["from_id"] == rep and rel["to_id"] == other


@pytest.mark.asyncio
async def test_mark_consolidated_cross_entity_noop(neo4j_driver):
    """A representative in another entity is a silent no-op on Neo4j too
    (dual-backend parity for the entity-isolation guard)."""
    from emerald.core.graph import GraphStore

    store = GraphStore(use_db=True)
    rep = await store.create_memory("用户住在北京", entity_id="user_int_test_consolidation_a")
    merged = await store.create_memory(
        "用户住在北京", entity_id="user_int_test_consolidation_b"
    )

    await store.mark_consolidated(merged, rep)

    memory = await store.get_memory(merged)
    assert memory["is_latest"] is True
    assert memory.get("replaced_by") is None


@pytest.mark.asyncio
async def test_mark_consolidated_already_historical_noop(neo4j_driver):
    """Re-consolidating an already-historical memory changes nothing."""
    from emerald.core.graph import GraphStore

    store = GraphStore(use_db=True)
    entity_id = "user_int_test_consolidation"
    rep = await store.create_memory("用户住在北京", entity_id=entity_id)
    merged = await store.create_memory("用户住在北京", entity_id=entity_id)

    await store.mark_consolidated(merged, rep)
    replaced_by = (await store.get_memory(merged))["replaced_by"]
    await store.mark_consolidated(merged, rep)

    memory = await store.get_memory(merged)
    assert memory["replaced_by"] == replaced_by == rep
