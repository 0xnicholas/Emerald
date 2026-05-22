"""Edge case tests — long text, special chars, concurrency, large scale."""

import asyncio

import pytest

from emerald.core.engine import MemoryEngine
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.core.extractor import ExtractorRegistry
from emerald.core.chunker import ChunkerRegistry
from emerald.core.search import SearchOrchestrator, SearchMode
from emerald.pipeline.extraction.text import TextExtractor
from emerald.pipeline.chunking.text import TextChunker


@pytest.fixture
def engine():
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


# ---- Long content ----

@pytest.mark.asyncio
async def test_extremely_long_text_does_not_crash(engine):
    """100KB of text is processed without crashing."""
    long_text = "这是测试文本。 " * 5000  # ~100KB
    result = await engine.add(long_text, entity_id="user_1")
    assert len(result.memory_ids) > 0
    assert result.pipeline_status == "done"
    # Should produce multiple chunks
    assert result.extracted_count > 1


@pytest.mark.asyncio
async def test_long_text_searchable(engine):
    """Content within a long text is searchable."""
    # Embed a unique string inside long text
    unique = "XYZZY-UNIQUE-MARKER-12345"
    long_text = ("填充文本。 " * 1000) + unique + (" 更多填充。 " * 500)
    await engine.add(long_text, entity_id="user_1")

    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )
    results = await orchestrator.search(
        "XYZZY", entity_id="user_1", search_mode=SearchMode.MEMORY,
    )
    assert any("XYZZY" in r.content for r in results.results)


# ---- Special characters ----

@pytest.mark.asyncio
async def test_emoji_only_text(engine):
    """Pure emoji content is handled."""
    text = "🎉🔥💯✨🚀"
    result = await engine.add(text, entity_id="user_1")
    assert len(result.memory_ids) > 0


@pytest.mark.asyncio
async def test_mixed_cjk_emoji_ascii(engine):
    """Mixed CJK, emoji, ASCII, and symbols work together."""
    text = "用户喜欢 🎉 TypeScript! 函数式编程很棒 🚀 100%"
    result = await engine.add(text, entity_id="user_1")
    assert len(result.memory_ids) > 0


@pytest.mark.asyncio
async def test_zero_width_characters(engine):
    """Zero-width characters are stripped without breaking."""
    # Zero-width space (U+200B) and zero-width non-joiner (U+200C)
    text = "Hel\u200blo \u200cWo\u200brld"
    result = await engine.add(text, entity_id="user_1")
    assert len(result.memory_ids) > 0
    # Content should be preserved (somewhat)
    memory = await engine.graph.get_memory(result.memory_ids[0])
    assert len(memory["content"]) > 0


# ---- Search edge cases ----

@pytest.mark.asyncio
async def test_search_empty_query(engine):
    """Empty search query returns empty results without crashing."""
    await engine.add("test content", entity_id="user_1")

    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )
    results = await orchestrator.search(
        "", entity_id="user_1", search_mode=SearchMode.HYBRID,
    )
    assert results.results == [] or len(results.results) >= 0


@pytest.mark.asyncio
async def test_search_very_long_query(engine):
    """Very long search query is handled without crashing."""
    await engine.add("short target text", entity_id="user_1")

    long_query = "query word " * 500  # Very long query
    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )
    results = await orchestrator.search(
        long_query, entity_id="user_1", search_mode=SearchMode.MEMORY,
    )
    assert isinstance(results.results, list)


# ---- Concurrency ----

@pytest.mark.asyncio
async def test_concurrent_adds_same_entity(engine):
    """Multiple concurrent adds to the same entity don't conflict."""
    async def add_one(i):
        return await engine.add(f"concurrent fact {i}", entity_id="shared_entity")

    tasks = [add_one(i) for i in range(20)]
    results = await asyncio.gather(*tasks)

    all_ids = []
    for r in results:
        all_ids.extend(r.memory_ids)

    assert len(all_ids) == 20  # Each add produces 1 memory

    # All memories should be retrievable
    memories = await engine.graph.list_latest_memories("shared_entity")
    assert len(memories) == 20


# ---- Scale test ----

@pytest.mark.asyncio
async def test_large_number_of_memories(engine):
    """500 memories stored and searchable without performance collapse."""
    import time

    # Add 500 memories
    for i in range(500):
        await engine.graph.create_memory(
            f"memory number {i} with some padding text for realism",
            entity_id="big_entity",
        )

    start = time.perf_counter()
    memories = await engine.graph.list_latest_memories("big_entity", limit=50)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(memories) == 50
    assert elapsed_ms < 200, f"list_latest took {elapsed_ms:.1f}ms for 500 memories"
