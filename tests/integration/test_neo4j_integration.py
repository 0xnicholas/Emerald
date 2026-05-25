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

    # Cleanup: delete test data
    async with driver.session() as session:
        await session.run("MATCH (m:Memory) WHERE m.id STARTS WITH 'user_int_test' DETACH DELETE m")
        await session.run("MATCH (e:Entity) WHERE e.id STARTS WITH 'user_int_test' DELETE e")

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
