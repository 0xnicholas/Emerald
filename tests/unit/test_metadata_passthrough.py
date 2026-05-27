"""Tests verifying metadata passthrough on memory creation.

Per the plan: metadata was previously dropped in MemoryEngine._index() and not
accepted by GraphStore.create_memory(). The fix has been applied — these tests
verify metadata is stored without mangling and returned correctly.

Tests cover: GraphStore (direct), MemoryEngine (end-to-end), nested structures,
and all value types that a Pandaria adapter might send (session_id, model, etc.).
"""

import pytest

from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor


# ── GraphStore-level: metadata stored and retrieved verbatim ─────────────


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.mark.asyncio
async def test_metadata_stored_and_retrieved(graph):
    """Metadata dict is stored by GraphStore.create_memory() and returned by get_memory()."""
    meta = {"session_id": "sess-001", "model": "gpt-4", "source": "pandaria"}
    mid = await graph.create_memory("content", entity_id="e1", metadata=meta)

    memory = await graph.get_memory(mid)
    assert memory is not None
    assert memory["metadata"] == meta


@pytest.mark.asyncio
async def test_metadata_none_passthrough(graph):
    """metadata=None is stored as None (not converted to empty dict or string)."""
    mid = await graph.create_memory("content", entity_id="e1", metadata=None)

    memory = await graph.get_memory(mid)
    assert memory is not None
    assert memory["metadata"] is None


@pytest.mark.asyncio
async def test_metadata_empty_dict(graph):
    """Empty metadata dict is preserved as empty dict."""
    mid = await graph.create_memory("content", entity_id="e1", metadata={})

    memory = await graph.get_memory(mid)
    assert memory is not None
    assert memory["metadata"] == {}


@pytest.mark.asyncio
async def test_metadata_nested_dict(graph):
    """Nested dict metadata is preserved through round-trip."""
    meta = {
        "session": {"id": "abc", "turn": 5},
        "config": {"temperature": 0.7, "max_tokens": 4096},
    }
    mid = await graph.create_memory("content", entity_id="e1", metadata=meta)

    memory = await graph.get_memory(mid)
    assert memory["metadata"] == meta
    assert memory["metadata"]["session"]["id"] == "abc"
    assert memory["metadata"]["session"]["turn"] == 5


@pytest.mark.asyncio
async def test_metadata_with_list_values(graph):
    """Metadata containing list values is preserved."""
    meta = {
        "tags": ["important", "technical", "typescript"],
        "references": [101, 102, 103],
    }
    mid = await graph.create_memory("content", entity_id="e1", metadata=meta)

    memory = await graph.get_memory(mid)
    assert memory["metadata"] == meta
    assert len(memory["metadata"]["tags"]) == 3
    assert "typescript" in memory["metadata"]["tags"]


@pytest.mark.asyncio
async def test_metadata_all_scalar_types(graph):
    """Metadata with all JSON-compatible scalar types round-trips correctly."""
    meta = {
        "int_val": 42,
        "float_val": 3.14,
        "neg_float": -0.5,
        "bool_true": True,
        "bool_false": False,
        "str_val": "hello",
        "none_val": None,
        "zero": 0,
        "empty_str": "",
    }
    mid = await graph.create_memory("content", entity_id="e1", metadata=meta)

    memory = await graph.get_memory(mid)
    assert memory["metadata"] == meta
    # Verify specific types survived
    assert memory["metadata"]["int_val"] == 42
    assert isinstance(memory["metadata"]["int_val"], int)
    assert memory["metadata"]["float_val"] == 3.14
    assert memory["metadata"]["bool_true"] is True
    assert memory["metadata"]["none_val"] is None


@pytest.mark.asyncio
async def test_metadata_unicode_values(graph):
    """Metadata with Unicode values (Chinese, emoji) survives round-trip."""
    meta = {
        "用户名": "张三",
        "标签": "重要 🚀",
        "note": "ユーザーの設定",
    }
    mid = await graph.create_memory("content", entity_id="e1", metadata=meta)

    memory = await graph.get_memory(mid)
    assert memory["metadata"] == meta
    assert memory["metadata"]["用户名"] == "张三"
    assert "🚀" in memory["metadata"]["标签"]


@pytest.mark.asyncio
async def test_metadata_not_mangled_on_list_latest(graph):
    """Metadata is preserved when memories are listed via list_latest_memories()."""
    meta = {"key": "value", "number": 42}
    mid = await graph.create_memory("content", entity_id="e1", metadata=meta)

    latest = await graph.list_latest_memories("e1")
    found = [m for m in latest if m["id"] == mid]
    assert len(found) == 1
    assert found[0]["metadata"] == meta


# ── Engine-level: full pipeline metadata passthrough ─────────────────────


@pytest.fixture
def engine():
    """In-memory engine for metadata passthrough tests."""
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
async def test_engine_add_passes_metadata_to_graph(engine):
    """Engine.add() passes metadata through to GraphStore.create_memory()."""
    meta = {"session_id": "sess-pandaria-001", "model": "claude-3-opus"}
    result = await engine.add("test content", entity_id="e1", metadata=meta)

    assert len(result.memory_ids) > 0
    memory = await engine.graph.get_memory(result.memory_ids[0])
    assert memory is not None
    assert memory["metadata"] == meta


@pytest.mark.asyncio
async def test_engine_add_nested_metadata(engine):
    """Engine.add() preserves deeply nested metadata structures."""
    meta = {
        "context": {
            "session": {"id": "s1", "turn": 42},
            "agent": {"name": "pandaria", "version": "0.2.0"},
        },
        "flags": ["active", "pinned"],
    }
    result = await engine.add("test content", entity_id="e1", metadata=meta)

    memory = await engine.graph.get_memory(result.memory_ids[0])
    assert memory["metadata"] == meta
    assert memory["metadata"]["context"]["session"]["turn"] == 42


@pytest.mark.asyncio
async def test_engine_add_pandaria_style_metadata(engine):
    """Engine.add() preserves metadata in the format Pandaria's EmeraldMemoryStore sends."""
    # This emulates what the Rust adapter sends (see plan Phase 2, Task 2.1)
    meta = {
        "session_id": "550e8400-e29b-41d4-a716-446655440000",
        "model": "claude-sonnet-4-20250514",
        "tenant_id": "org_acme",
        "turn_index": 7,
        "content_type": "conversation",
    }
    result = await engine.add("User: hello", entity_id="org_acme", metadata=meta)

    memory = await engine.graph.get_memory(result.memory_ids[0])
    assert memory["metadata"] == meta
    assert memory["metadata"]["session_id"] == meta["session_id"]
    assert memory["metadata"]["tenant_id"] == "org_acme"


@pytest.mark.asyncio
async def test_engine_add_metadata_independent_across_memories(engine):
    """Metadata from one add() call does not leak into another's memories."""
    result1 = await engine.add("content a", entity_id="e1", metadata={"key": "a"})
    result2 = await engine.add("content b", entity_id="e1", metadata={"key": "b"})

    mem1 = await engine.graph.get_memory(result1.memory_ids[0])
    mem2 = await engine.graph.get_memory(result2.memory_ids[0])

    assert mem1["metadata"] == {"key": "a"}
    assert mem2["metadata"] == {"key": "b"}


@pytest.mark.asyncio
async def test_engine_add_metadata_mutation_isolation(engine):
    """Mutating the original metadata dict after add() does not affect stored data."""
    meta = {"session_id": "s1", "tags": ["a", "b"]}
    result = await engine.add("test", entity_id="e1", metadata=meta)

    # Mutate the original dict and list AFTER the add() call
    meta["session_id"] = "MODIFIED"
    meta["tags"].append("c")
    meta["new_key"] = "injected"

    memory = await engine.graph.get_memory(result.memory_ids[0])
    assert memory["metadata"]["session_id"] == "s1"
    assert memory["metadata"]["tags"] == ["a", "b"]
    assert "new_key" not in memory["metadata"]
