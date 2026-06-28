"""Tests for the FastLane store and engine integration."""

import pytest

from emerald.core.constants import MemoryStage
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.fast_lane import FastLaneStore
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore


@pytest.fixture
def store():
    return FastLaneStore(use_db=False)


@pytest.fixture
def embedder():
    return MockEmbeddingProvider(dimension=128)


# ---- FastLaneStore ----

@pytest.mark.asyncio
async def test_store_and_search(store, embedder):
    """Stored fast-lane chunks are returned by similarity search."""
    text = "用户喜欢使用 Neovim 进行开发"
    embedding = (await embedder.embed([text]))[0]

    fl_id = await store.store(text, embedding, entity_id="user_123")
    assert fl_id

    hits = await store.search(embedding, entity_id="user_123", top_k=5)
    assert len(hits) == 1
    assert hits[0].fast_lane_id == fl_id
    assert hits[0].text == text


@pytest.mark.asyncio
async def test_search_filters_other_entities(store, embedder):
    """Fast-lane search respects entity boundaries."""
    emb = (await embedder.embed(["test"]))[0]
    await store.store("Alice 的内容", emb, entity_id="alice")
    await store.store("Bob 的内容", emb, entity_id="bob")

    hits = await store.search(emb, entity_id="alice", top_k=5)
    assert len(hits) == 1
    assert hits[0].entity_id == "alice"


@pytest.mark.asyncio
async def test_archive_removes_from_search(store, embedder):
    """Archived fast-lane chunks are no longer returned."""
    text = "临时 fast lane 内容"
    embedding = (await embedder.embed([text]))[0]
    fl_id = await store.store(text, embedding, entity_id="user_123")

    assert await store.archive(fl_id) is True

    hits = await store.search(embedding, entity_id="user_123", top_k=5)
    assert len(hits) == 0

    # Archiving an already-archived chunk is a no-op
    assert await store.archive(fl_id) is False


@pytest.mark.asyncio
async def test_cleanup_archives_old_chunks(store, embedder):
    """cleanup() archives chunks older than the configured age."""
    from datetime import UTC, datetime, timedelta

    text = "旧 fast lane 内容"
    embedding = (await embedder.embed([text]))[0]
    fl_id = await store.store(text, embedding, entity_id="user_123")

    # Manually age the chunk
    store._memory_store[fl_id]["created_at"] = datetime.now(UTC) - timedelta(hours=25)

    archived = await store.cleanup(max_age_hours=24)
    assert archived == 1

    hits = await store.search(embedding, entity_id="user_123", top_k=5)
    assert len(hits) == 0


# ---- Engine integration ----

@pytest.fixture
def engine(embedder):
    return MemoryEngine(
        embedder=embedder,
        graph=GraphStore(use_db=False),
        vector=VectorStore(use_db=False),
        fast_lane_store=FastLaneStore(use_db=False),
        use_db=False,
    )


@pytest.mark.asyncio
async def test_add_creates_and_archives_fast_lane(engine, embedder):
    """Sync add() indexes fast lane before pipeline and archives it after."""
    result = await engine.add(
        "用户喜欢 TypeScript 编程", entity_id="user_123", content_type="text"
    )
    assert len(result.memory_ids) > 0

    # After synchronous add, fast-lane chunks should be archived
    active = [
        m for m in engine.fast_lane_store._memory_store.values()
        if m.get("stage") == MemoryStage.FAST_LANE.value
    ]
    assert len(active) == 0


@pytest.mark.asyncio
async def test_fast_lane_search_in_orchestrator(engine, embedder):
    """Search can surface fast-lane chunks directly via FastLaneStore."""
    from emerald.core.search import SearchMode, SearchOrchestrator

    text = "Fast lane 测试内容"
    emb = (await embedder.embed([text]))[0]
    fl_id = await engine.fast_lane_store.store(text, emb, entity_id="user_123")

    orchestrator = SearchOrchestrator(
        graph=engine.graph,
        vector=engine.vector,
        fast_lane_store=engine.fast_lane_store,
        embedder=embedder,
    )
    results = await orchestrator.search(
        "Fast lane", entity_id="user_123", search_mode=SearchMode.MEMORY
    )

    fast_lane_hits = [r for r in results.results if r.source == "fast_lane"]
    assert len(fast_lane_hits) >= 1
    assert any(fl_id == r.id for r in fast_lane_hits)
