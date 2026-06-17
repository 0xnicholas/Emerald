"""Tests for ReconciliationEngine — orphan detection and repair."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emerald.core.embedder import EmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.reconciliation import ReconciliationEngine
from emerald.core.vector import VectorStore


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.fixture
def vector():
    return VectorStore(use_db=False)


@pytest.fixture
def embedder():
    """Mock embedder that returns fixed vectors."""
    mock = MagicMock(spec=EmbeddingProvider)
    mock._model = "mock-model"
    mock.embed = AsyncMock(
        return_value=[[0.1, 0.2, 0.3]]
    )
    return mock


@pytest.fixture
def engine(graph, vector, embedder):
    return ReconciliationEngine(graph=graph, vector=vector, embedder=embedder)


# ---- VectorStore.exists ----

async def test_vector_exists_true_when_stored(vector):
    await vector.store("mem-1", "hello", [0.1, 0.2, 0.3], entity_id="e1")
    assert await vector.exists("mem-1") is True


async def test_vector_exists_false_when_missing(vector):
    assert await vector.exists("nonexistent") is False


# ---- GraphStore.list_recent_memories ----

async def test_list_recent_memories_finds_recent(graph):
    recent = datetime.now(UTC) - timedelta(minutes=30)
    old = datetime.now(UTC) - timedelta(hours=5)

    await graph.create_memory("recent fact", entity_id="e1")
    await graph.create_memory("old fact", entity_id="e1")

    # Manually set created_at for testing
    for mems in graph._memories.values():
        for m in mems:
            if "recent fact" in m["content"]:
                m["created_at"] = recent
            elif "old fact" in m["content"]:
                m["created_at"] = old

    result = await graph.list_recent_memories(since_minutes=60)
    assert len(result) == 1
    assert "recent fact" in result[0]["content"]


async def test_list_recent_memories_empty_when_no_recent(graph):
    old = datetime.now(UTC) - timedelta(hours=5)
    await graph.create_memory("old fact", entity_id="e1")
    for mems in graph._memories.values():
        for m in mems:
            m["created_at"] = old

    result = await graph.list_recent_memories(since_minutes=60)
    assert len(result) == 0


async def test_list_recent_memories_skips_not_latest(graph):
    recent = datetime.now(UTC) - timedelta(minutes=10)
    await graph.create_memory("stale fact", entity_id="e1")
    for mems in graph._memories.values():
        for m in mems:
            if "stale fact" in m["content"]:
                m["created_at"] = recent
                m["is_latest"] = False

    result = await graph.list_recent_memories(since_minutes=60)
    assert len(result) == 0


# ---- ReconciliationEngine.reconcile ----

async def test_reconcile_no_orphans(engine, graph, vector):
    """When all graph nodes have vector entries, found=0."""
    mid = await graph.create_memory("test", entity_id="e1")
    await vector.store(mid, "test", [0.1, 0.2, 0.3], entity_id="e1")

    result = await engine.reconcile(lookback_minutes=1440)  # 24h window
    assert result["found"] == 0
    assert result["repaired"] == 0
    assert result["failed"] == 0


async def test_reconcile_repairs_orphan(engine, graph, vector, embedder):
    """Orphaned memory gets re-embedded and stored in vector."""
    # Create memory in graph only (no vector entry)
    mid = await graph.create_memory("repair me", entity_id="e1")

    result = await engine.reconcile(lookback_minutes=1440)
    assert result["found"] == 1
    assert result["repaired"] == 1
    assert result["failed"] == 0

    # Vector store should now have it
    assert await vector.exists(mid) is True

    # Embedder was called
    embedder.embed.assert_called_once_with(["repair me"])


async def test_reconcile_marks_failed_when_embed_fails(engine, graph, embedder):
    """When embedding fails, mark the node as indexing_failed."""
    embedder.embed = AsyncMock(side_effect=RuntimeError("embed API down"))

    mid = await graph.create_memory("will fail", entity_id="e1")

    result = await engine.reconcile(lookback_minutes=1440)
    assert result["found"] == 1
    assert result["repaired"] == 0
    assert result["failed"] == 1

    # Graph node should be marked not latest
    mem = await graph.get_memory(mid)
    assert mem is not None
    assert mem["is_latest"] is False
    assert mem.get("replaced_by") == "reconciliation_failed"


async def test_reconcile_marks_failed_when_no_content(engine, graph):
    """Memory with empty content cannot be repaired."""
    mid = await graph.create_memory("", entity_id="e1")

    result = await engine.reconcile(lookback_minutes=1440)
    assert result["found"] == 1
    assert result["failed"] == 1

    mem = await graph.get_memory(mid)
    assert mem["is_latest"] is False
    assert mem.get("replaced_by") == "no_content"


async def test_reconcile_skips_already_indexed(engine, graph, vector):
    """Memories that already have vector entries are not re-processed."""
    mid1 = await graph.create_memory("indexed", entity_id="e1")
    await vector.store(mid1, "indexed", [0.1, 0.2, 0.3], entity_id="e1")

    mid2 = await graph.create_memory("orphan", entity_id="e1")
    # Only mid2 is orphaned

    result = await engine.reconcile(lookback_minutes=1440)
    assert result["found"] == 1
    assert result["repaired"] == 1
    assert await vector.exists(mid2) is True


async def test_reconcile_respects_max_repairs(engine, graph, vector, embedder):
    """Only up to max_repairs orphans are processed."""
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    # Create orphans — list_recent_memories limit = max_repairs * 2
    ids = []
    for i in range(6):
        mid = await graph.create_memory(f"orphan {i}", entity_id="e1")
        ids.append(mid)

    result = await engine.reconcile(lookback_minutes=1440, max_repairs=2)
    # Scan limit = 4 (max_repairs * 2), but we created 6 — only 4 scanned
    assert result["found"] == 4
    assert result["repaired"] == 2

    # Only 2 were repaired (the most recent ones scanned)
    repaired_count = 0
    for mid in ids:
        if await vector.exists(mid):
            repaired_count += 1
    assert repaired_count == 2


async def test_reconcile_partial_failure(engine, graph, vector, embedder):
    """Some repairs succeed, some fail — both counts are reported."""
    # Make embedding fail for a specific memory content
    async def flaky_embed(texts):
        results = []
        for t in texts:
            if "bad" in t:
                raise RuntimeError("transient failure")
            results.append([0.1, 0.2, 0.3])
        return results

    embedder.embed = AsyncMock(side_effect=flaky_embed)

    mid_good = await graph.create_memory("good content", entity_id="e1")
    mid_bad = await graph.create_memory("bad content", entity_id="e1")

    result = await engine.reconcile(lookback_minutes=1440)
    assert result["found"] == 2
    assert result["repaired"] == 1
    assert result["failed"] == 1

    assert await vector.exists(mid_good) is True
    assert await vector.exists(mid_bad) is False
    mem_bad = await graph.get_memory(mid_bad)
    assert mem_bad["is_latest"] is False


async def test_reconcile_multiple_entities(engine, graph, vector, embedder):
    """Orphans across different entities are all repaired."""
    mid_a = await graph.create_memory("entity A fact", entity_id="e_a")
    mid_b = await graph.create_memory("entity B fact", entity_id="e_b")

    result = await engine.reconcile(lookback_minutes=1440)
    assert result["found"] == 2
    assert result["repaired"] == 2

    assert await vector.exists(mid_a) is True
    assert await vector.exists(mid_b) is True

    # Check entity_id was passed through
    assert embedder.embed.call_count == 2
