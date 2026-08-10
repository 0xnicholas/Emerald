"""Tests for the FastLane store and engine integration."""

import json

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
async def test_store_binds_embedding_as_json(embedder):
    """DB path: embedding must be bound as a JSON string, not a raw list.

    Regression for P0-2: ``fast_lane_chunks.embedding`` is jsonb; binding a
    Python list through raw SQL raises asyncpg DataError, so fast-lane
    chunks were never persisted.
    """
    class _FakeSession:
        def __init__(self):
            self.params = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def execute(self, stmt, params=None):
            self.params = params or {}

        async def commit(self):
            pass

    class _FakeFactory:
        def __init__(self):
            self.session_ = _FakeSession()

        def session(self):
            return self.session_

    embedding = (await embedder.embed(["text"]))[0]
    factory = _FakeFactory()
    store = FastLaneStore(use_db=True)
    store._session_factory = factory

    await store.store("content", embedding, entity_id="user_123")

    bound = factory.session_.params["embedding"]
    assert isinstance(bound, str), "embedding must be JSON-serialized before binding"
    assert json.loads(bound) == embedding


@pytest.mark.asyncio
async def test_search_accepts_string_jsonb_embeddings(embedder):
    """Read path: jsonb columns may come back as str on some drivers."""
    import datetime

    class _Row:
        id = "fl-1"
        entity_id = "user_123"
        text = "content"
        created_at = datetime.datetime.now(datetime.UTC)
        embedding = None

    class _Result:
        def __init__(self, row):
            self.row = row

        def fetchall(self):
            return [self.row]

    class _FakeSession:
        def __init__(self, row):
            self.row = row

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def execute(self, stmt, params=None):
            return _Result(self.row)

        async def commit(self):
            pass

    class _FakeFactory:
        def __init__(self, row):
            self.session_ = _FakeSession(row)

        def session(self):
            return self.session_

    embedding = (await embedder.embed(["query"]))[0]
    row = _Row()
    row.embedding = json.dumps(embedding)  # driver returned the jsonb as str

    store = FastLaneStore(use_db=True)
    store._session_factory = _FakeFactory(row)

    hits = await store.search(embedding, entity_id="user_123", top_k=5)

    assert len(hits) == 1
    assert hits[0].text == "content"


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
