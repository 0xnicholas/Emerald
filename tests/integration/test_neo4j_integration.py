"""Neo4j integration tests — verify GraphStore with real Neo4j via testcontainers."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def docker_skipif():
    """Skip entire module if Docker is not available."""
    import shutil

    if shutil.which("docker") is None:
        pytest.skip("Docker not available", allow_module_level=True)


@pytest.fixture
async def neo4j_driver(docker_skipif):
    """Yield an initialized Neo4j driver backed by a testcontainers container."""
    from testcontainers.neo4j import Neo4jContainer

    from emerald.db.neo4j import close_neo4j, init_neo4j

    container = Neo4jContainer("neo4j:5-community")
    container.with_env("NEO4J_PLUGINS", '["apoc"]')

    with container:
        bolt_url = container.get_connection_url()
        # Monkeypatch get_settings to return test URL
        import emerald.config as config_mod

        original_get_settings = config_mod.get_settings
        test_settings = original_get_settings()
        test_settings.neo4j_uri = bolt_url
        test_settings.neo4j_user = "neo4j"
        test_settings.neo4j_password = container.password

        config_mod.get_settings = lambda: test_settings

        await init_neo4j()

        from emerald.db.neo4j import get_neo4j_driver

        driver = get_neo4j_driver()
        yield driver

        await close_neo4j()
        config_mod.get_settings = original_get_settings


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
