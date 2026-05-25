"""Integration test: text end-to-end pipeline."""

import pytest

from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor


@pytest.fixture
def engine():
    """Create a MemoryEngine with in-memory stores (no DB required)."""
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
async def test_add_text_returns_memory_ids(engine):
    """Adding text returns memory IDs."""
    result = await engine.add(
        "用户喜欢 TypeScript 和函数式编程风格",
        entity_id="user_123",
    )
    assert len(result.memory_ids) > 0
    assert result.pipeline_status == "done"
    assert result.extracted_count > 0


@pytest.mark.asyncio
async def test_memory_stored_in_graph(engine):
    """Memories are stored in the graph store after add()."""
    content = "用户偏好上午开会"
    result = await engine.add(content, entity_id="user_123")
    memory_id = result.memory_ids[0]

    memory = await engine.graph.get_memory(memory_id)
    assert memory is not None
    assert memory["content"] == content
    assert memory["is_latest"] is True
    assert memory["memory_type"] == "fact"


@pytest.mark.asyncio
async def test_memory_searchable_in_vector_store(engine):
    """Memories are searchable via vector similarity after add()."""
    content = "TypeScript 是一种强类型编程语言"
    result = await engine.add(content, entity_id="user_123")

    # Get the embedding for the stored text and search for similar
    query_embedding = (await engine.embedder.embed([content]))[0]
    search_results = await engine.vector.search(
        query_embedding, entity_id="user_123", top_k=5
    )

    assert len(search_results) > 0
    # The first result should be our stored content (or very similar)
    chunk_id, text, score = search_results[0]
    assert score > 0.9  # Same text should have high similarity


@pytest.mark.asyncio
async def test_add_multiple_texts(engine):
    """Multiple calls to add() store independent memories."""
    texts = [
        "用户喜欢 TypeScript",
        "用户住在北京",
        "用户是一名资深前端工程师",
    ]

    all_ids = []
    for text in texts:
        result = await engine.add(text, entity_id="user_123")
        all_ids.extend(result.memory_ids)

    # All should be retrievable
    for memory_id in all_ids:
        memory = await engine.graph.get_memory(memory_id)
        assert memory is not None
        assert memory["is_latest"] is True


@pytest.mark.asyncio
async def test_different_entities_isolated(engine):
    """Memories from different entities do not mix."""
    await engine.add("Alice 的内容", entity_id="alice")
    await engine.add("Bob 的内容", entity_id="bob")

    alice_memories = await engine.graph.list_latest_memories("alice")
    bob_memories = await engine.graph.list_latest_memories("bob")

    alice_texts = [m["content"] for m in alice_memories]
    bob_texts = [m["content"] for m in bob_memories]

    assert "Alice 的内容" in alice_texts
    assert "Bob 的内容" not in alice_texts
    assert "Bob 的内容" in bob_texts


@pytest.mark.asyncio
async def test_vector_search_respects_entity_isolation(engine):
    """Vector search only returns results for the specified entity."""
    await engine.add("Alice loves Python", entity_id="alice")
    await engine.add("Bob loves Rust", entity_id="bob")

    query = (await engine.embedder.embed(["loves"]))[0]

    alice_results = await engine.vector.search(query, entity_id="alice", top_k=5)
    bob_results = await engine.vector.search(query, entity_id="bob", top_k=5)

    alice_texts = [text for _, text, _ in alice_results]
    bob_texts = [text for _, text, _ in bob_results]

    assert any("Alice" in t for t in alice_texts)
    assert not any("Bob" in t for t in alice_texts)
    assert any("Bob" in t for t in bob_texts)
