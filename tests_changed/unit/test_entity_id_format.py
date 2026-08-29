"""Tests verifying entity_id accepts arbitrary string formats.

Per AGENTS.md Principle 1 (entity-first design), every operation is scoped to an entity ID.
The ID itself MUST be an opaque string — no format validation, no character restrictions.
"""

import pytest
from pydantic import ValidationError

from emerald.api.schemas.memories import AddMemoryRequest
from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor


# ── Pydantic schema-level tests ──────────────────────────────────────────

_ID_FORMAT_CASES = [
    # Case,        entity_id string
    ("simple",      "user_123"),
    ("colon_sep",   "t1:s1"),
    ("multi_colon", "org:project:thread:abc"),
    ("uuid",        "550e8400-e29b-41d4-a716-446655440000"),
    ("email_like",  "user@example.com"),
    ("url_like",    "https://example.com/users/42"),
    ("path_like",   "a/b/c/d"),
    ("numeric",     "12345"),
    ("empty",       ""),
    ("whitespace",  "  "),
]


@pytest.mark.parametrize("case_name,entity_id", _ID_FORMAT_CASES)
def test_add_memory_request_accepts_arbitrary_entity_id(case_name, entity_id):
    """AddMemoryRequest Pydantic schema accepts any string as entity_id."""
    req = AddMemoryRequest(content="test content", entity_id=entity_id)
    assert req.entity_id == entity_id


_UNICODE_ID_CASES = [
    ("chinese",     "用户_张三"),
    ("japanese",    "ユーザー_太郎"),
    ("korean",      "사용자_홍길동"),
    ("emoji",       "user🚀_✨"),
    ("arabic",      "مستخدم_١٢٣"),
    ("hebrew",      "משתמש_אבג"),
    ("mixed",       "user_αβγ_你好"),
]


@pytest.mark.parametrize("case_name,entity_id", _UNICODE_ID_CASES)
def test_add_memory_request_accepts_unicode_entity_id(case_name, entity_id):
    """AddMemoryRequest Pydantic schema accepts arbitrary Unicode entity_id."""
    req = AddMemoryRequest(content="test content", entity_id=entity_id)
    assert req.entity_id == entity_id


def test_add_memory_request_rejects_none_entity_id():
    """entity_id=None should be rejected (it's required)."""
    with pytest.raises(ValidationError):
        AddMemoryRequest(content="test", entity_id=None)


# ── Engine-level tests (in-memory, no DB) ────────────────────────────────


@pytest.fixture
def engine():
    """In-memory engine for entity_id format tests."""
    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    embedder = MockEmbeddingProvider(dimension=128)
    graph = GraphStore(use_db=False)
    vector = VectorStore(use_db=False)

    return MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=embedder,
        graph=graph,
        vector=vector,
        use_db=False,
    )


@pytest.mark.asyncio
async def test_engine_add_with_colon_separated_entity_id(engine):
    """Engine.add() works with colon-separated entity_id like Pandaria's t1:s1."""
    result = await engine.add("hello world", entity_id="t1:s1")
    assert len(result.memory_ids) > 0
    assert result.pipeline_status == "done"

    # Verify the memory is stored under the correct entity
    memory = await engine.graph.get_memory(result.memory_ids[0])
    assert memory is not None
    # The entity_id field should match what was passed in
    # (GraphStore in-memory stores entity_id in the bucket key,
    #  but we also want to verify retrieval by entity works)
    latest = await engine.graph.list_latest_memories("t1:s1")
    assert any(m["id"] == result.memory_ids[0] for m in latest)


@pytest.mark.asyncio
async def test_engine_add_with_multi_colon_entity_id(engine):
    """Engine.add() works with arbitrarily nested colon-separated entity_id."""
    result = await engine.add("test content", entity_id="org:project:thread:abc-def")
    assert len(result.memory_ids) > 0


@pytest.mark.asyncio
async def test_engine_add_with_unicode_entity_id(engine):
    """Engine.add() works with Unicode entity_id."""
    result = await engine.add("test", entity_id="用户_张三")
    assert len(result.memory_ids) > 0


@pytest.mark.asyncio
async def test_engine_add_with_special_chars_entity_id(engine):
    """Engine.add() works with entity_id containing special characters."""
    special_ids = [
        "user@domain",
        "a/b/c",
        "key=value",
        "has spaces",
        "dot.separated.name",
        "hyphen-separated-name",
    ]
    for eid in special_ids:
        result = await engine.add("test", entity_id=eid)
        assert len(result.memory_ids) > 0, f"Failed for entity_id={eid!r}"


# ── GraphStore-level tests ───────────────────────────────────────────────


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.mark.asyncio
async def test_graph_create_memory_with_colon_entity_id(graph):
    """GraphStore.create_memory() works with colon-separated entity_id."""
    mid = await graph.create_memory("content", entity_id="a:b:c")
    memory = await graph.get_memory(mid)
    assert memory is not None

    # Memory should be listed under this entity_id
    latest = await graph.list_latest_memories("a:b:c")
    assert any(m["id"] == mid for m in latest)


@pytest.mark.asyncio
async def test_graph_entity_isolation_with_special_ids(graph):
    """Entities with different IDs (including special chars) are isolated."""
    await graph.create_memory("alice data", entity_id="user:alice:1")
    await graph.create_memory("bob data", entity_id="user:bob:1")

    alice_mems = await graph.list_latest_memories("user:alice:1")
    bob_mems = await graph.list_latest_memories("user:bob:1")

    # Each entity sees only its own memories
    alice_contents = [m["content"] for m in alice_mems]
    bob_contents = [m["content"] for m in bob_mems]
    assert "alice data" in alice_contents
    assert "bob data" in bob_contents
    assert "bob data" not in alice_contents
    assert "alice data" not in bob_contents


@pytest.mark.asyncio
async def test_graph_unicode_entity_ids_do_not_collide(graph):
    """Unicode entity_ids that differ should not collide."""
    await graph.create_memory("data1", entity_id="用户_张三")
    await graph.create_memory("data2", entity_id="用户_李四")

    mems_zhang = await graph.list_latest_memories("用户_张三")
    mems_li = await graph.list_latest_memories("用户_李四")

    assert len(mems_zhang) == 1
    assert len(mems_li) == 1
    assert mems_zhang[0]["content"] == "data1"
    assert mems_li[0]["content"] == "data2"


@pytest.mark.asyncio
async def test_graph_empty_entity_id(graph):
    """GraphStore handles empty string entity_id without crashing."""
    mid = await graph.create_memory("content", entity_id="")
    memory = await graph.get_memory(mid)
    assert memory is not None

    latest = await graph.list_latest_memories("")
    assert any(m["id"] == mid for m in latest)
