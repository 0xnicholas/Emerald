"""Unit tests for GraphStore (in-memory fallback mode)."""

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.graph import GraphStore


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.mark.asyncio
async def test_create_memory_returns_id(graph):
    mid = await graph.create_memory("test content", entity_id="e1")
    assert isinstance(mid, str) and len(mid) > 0


@pytest.mark.asyncio
async def test_create_memory_defaults(graph):
    mid = await graph.create_memory("test", entity_id="e1")
    m = await graph.get_memory(mid)
    assert m["is_latest"] is True
    assert m["memory_type"] == "fact"
    assert m["confidence"] == 0.8
    assert isinstance(m["valid_from"], datetime)


@pytest.mark.asyncio
async def test_get_memory_not_found(graph):
    assert await graph.get_memory("nonexistent") is None


@pytest.mark.asyncio
async def test_list_latest_excludes_expired(graph):
    mid = await graph.create_memory("expired", entity_id="e1")
    for m in graph._memories.get("e1", []):
        if m["id"] == mid:
            m["valid_until"] = datetime.now(UTC) - timedelta(days=1)
    latest = await graph.list_latest_memories("e1")
    assert not any(m["id"] == mid for m in latest)


@pytest.mark.asyncio
async def test_list_latest_respects_limit(graph):
    for i in range(10):
        await graph.create_memory(f"mem {i}", entity_id="e1")
    latest = await graph.list_latest_memories("e1", limit=3)
    assert len(latest) == 3


@pytest.mark.asyncio
async def test_update_is_latest_with_replaced_by(graph):
    mid = await graph.create_memory("old", entity_id="e1")
    await graph.update_is_latest(mid, False, replaced_by="new_id")
    m = await graph.get_memory(mid)
    assert m["is_latest"] is False
    assert m["replaced_by"] == "new_id"


@pytest.mark.asyncio
async def test_list_latest_keeps_valid_until_future(graph):
    """Memories with a future valid_until remain in latest list."""
    future = datetime.now(UTC) + timedelta(days=1)
    mid = await graph.create_memory("future", entity_id="e1", valid_until=future)
    latest = await graph.list_latest_memories("e1")
    assert any(m["id"] == mid for m in latest)


@pytest.mark.asyncio
async def test_list_latest_excludes_not_latest(graph):
    """Memories with is_latest=False are excluded from latest list."""
    mid = await graph.create_memory("superseded", entity_id="e1")
    await graph.update_is_latest(mid, is_latest=False)
    latest = await graph.list_latest_memories("e1")
    assert not any(m["id"] == mid for m in latest)


@pytest.mark.asyncio
async def test_list_latest_empty_entity(graph):
    """Querying a non-existent entity returns an empty list."""
    latest = await graph.list_latest_memories("nonexistent")
    assert latest == []


@pytest.mark.asyncio
async def test_list_latest_filter_by_memory_type(graph):
    """Filtering by memory_type returns only matching memories."""
    await graph.create_memory("fact 1", entity_id="e1", memory_type="fact")
    await graph.create_memory("pref 1", entity_id="e1", memory_type="preference")
    facts = await graph.list_latest_memories("e1", memory_type="fact")
    assert len(facts) == 1
    assert facts[0]["memory_type"] == "fact"


@pytest.mark.asyncio
async def test_entity_isolation(graph):
    await graph.create_memory("alice", entity_id="alice")
    await graph.create_memory("bob", entity_id="bob")
    alice_mems = await graph.list_latest_memories("alice")
    assert all("bob" not in m["content"] for m in alice_mems)


async def test_list_entity_ids_all_active(graph):
    """list_entity_ids returns all entities with latest memories."""
    await graph.create_memory("a", entity_id="e1")
    await graph.create_memory("b", entity_id="e1")
    await graph.create_memory("c", entity_id="e2")

    ids = await graph.list_entity_ids()
    assert set(ids) == {"e1", "e2"}


async def test_list_entity_ids_empty(graph):
    """Empty store returns empty list."""
    assert await graph.list_entity_ids() == []


async def test_list_entity_ids_excludes_not_latest(graph):
    """Entity with only not-latest memories is excluded."""
    mid = await graph.create_memory("stale", entity_id="ghost")
    await graph.update_is_latest(mid, False)

    ids = await graph.list_entity_ids()
    assert "ghost" not in ids


# ---------------------------------------------------------------------------
# Mention nodes (B3 NER, ticket #22) — in-memory fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_mentions_creates_typed_nodes_in_entity_pool(graph):
    """Each mention becomes a typed Mention node under the entity's pool."""
    from emerald.core.mentions import Mention

    mid = await graph.create_memory("用户用 Python 写代码", entity_id="e1")
    count = await graph.attach_mentions(
        mid, "e1",
        [Mention("Python", "Python", "technology", 0.9)],
    )
    assert count == 1

    pool = graph._mentions.get("e1", [])
    assert len(pool) == 1
    node = pool[0]
    assert node["canonical_form"] == "Python"
    assert node["type"] == "technology"
    assert node["entity_id"] == "e1"
    assert node["mention_count"] == 1
    assert node["aliases"] == ["Python"]
    assert node["created_at"] is not None
    assert node["last_seen_at"] is not None


@pytest.mark.asyncio
async def test_attach_mentions_memory_edges_point_memory_to_mention(graph):
    """MENTIONS edges live on the memory, pointing at the mention node."""
    from emerald.core.mentions import Mention

    mid = await graph.create_memory("用户在 Google 工作", entity_id="e1")
    await graph.attach_mentions(
        mid, "e1",
        [Mention("Google", "Google", "organization", 0.95)],
    )
    memory = await graph.get_memory(mid)
    edges = memory.get("mentions", [])
    assert len(edges) == 1
    edge = edges[0]
    assert edge["surface_form"] == "Google"
    assert edge["confidence"] == 0.95
    node_ids = {n["id"] for n in graph._mentions["e1"]}
    assert edge["mention_id"] in node_ids


@pytest.mark.asyncio
async def test_get_memory_mentions_reads_back_nodes_and_edges(graph):
    """The internal read-back method merges node fields with edge fields."""
    from emerald.core.mentions import Mention

    mid = await graph.create_memory("用户在 Google 用 Python", entity_id="e1")
    await graph.attach_mentions(
        mid, "e1",
        [
            Mention("Google", "Google", "organization", 0.9),
            Mention("Python", "Python", "technology", 0.8),
        ],
    )
    mentions = await graph.get_memory_mentions(mid)
    assert len(mentions) == 2
    by_canonical = {m["canonical_form"]: m for m in mentions}
    google = by_canonical["Google"]
    assert google["type"] == "organization"
    assert google["entity_id"] == "e1"
    assert google["surface_form"] == "Google"
    assert google["confidence"] == 0.9
    assert google["mention_count"] == 1
    assert google["aliases"] == ["Google"]
    python = by_canonical["Python"]
    assert python["type"] == "technology"
    assert python["confidence"] == 0.8


@pytest.mark.asyncio
async def test_get_memory_mentions_empty_for_memory_without_mentions(graph):
    """No mentions attached → empty list, not an error."""
    mid = await graph.create_memory("用户喜欢喝咖啡", entity_id="e1")
    assert await graph.get_memory_mentions(mid) == []


@pytest.mark.asyncio
async def test_get_memory_mentions_unknown_memory_returns_empty(graph):
    assert await graph.get_memory_mentions("nonexistent") == []


@pytest.mark.asyncio
async def test_attach_mentions_unknown_memory_is_noop(graph):
    """Attaching to a missing memory is a no-op (parity with Cypher MATCH)."""
    from emerald.core.mentions import Mention

    count = await graph.attach_mentions(
        "nonexistent", "e1", [Mention("Google", "Google", "organization", 0.9)],
    )
    assert count == 0
    assert "e1" not in graph._mentions


@pytest.mark.asyncio
async def test_attach_mentions_skips_invalid_mentions(graph):
    """Empty surface/canonical mentions are skipped without raising."""
    from emerald.core.mentions import Mention

    mid = await graph.create_memory("content", entity_id="e1")
    count = await graph.attach_mentions(
        mid, "e1",
        [
            Mention("", "", "organization", 0.9),
            Mention("Google", "Google", "organization", 0.9),
        ],
    )
    assert count == 1
    pool = graph._mentions.get("e1", [])
    assert len(pool) == 1
    assert pool[0]["canonical_form"] == "Google"


@pytest.mark.asyncio
async def test_attach_mentions_missing_type_defaults_to_concept(graph):
    """A mention without a declared type lands as concept (taxonomy default)."""
    from emerald.core.mentions import Mention

    mid = await graph.create_memory("content", entity_id="e1")
    await graph.attach_mentions(mid, "e1", [Mention("某物", "某物", "", 0.9)])
    pool = graph._mentions["e1"]
    assert pool[0]["type"] == "concept"


@pytest.mark.asyncio
async def test_attach_mentions_logs_count(graph):
    """Attaching mentions logs a graph.mentions.attached event."""
    import structlog

    from emerald.core.mentions import Mention

    mid = await graph.create_memory("content", entity_id="e1")
    with structlog.testing.capture_logs() as logs:
        await graph.attach_mentions(
            mid, "e1",
            [
                Mention("Google", "Google", "organization", 0.9),
                Mention("Python", "Python", "technology", 0.9),
            ],
        )
    attached = [e for e in logs if e.get("event") == "graph.mentions.attached"]
    assert attached and attached[-1]["count"] == 2
    assert attached[-1]["memory_id"] == mid
    assert attached[-1]["entity_id"] == "e1"
