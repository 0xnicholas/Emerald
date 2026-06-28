"""Tests for internal memory type tags (Phase 4)."""

import pytest

from emerald.core.engine import MemoryEngine
from emerald.core.fast_lane import FastLaneStore
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.base import Chunk
from emerald.pipeline.chunking.text import SemanticTextChunker


@pytest.fixture
def engine():
    return MemoryEngine(
        embedder=None,
        graph=GraphStore(use_db=False),
        vector=VectorStore(use_db=False),
        fast_lane_store=FastLaneStore(use_db=False),
        use_db=False,
    )


@pytest.mark.asyncio
async def test_graph_create_memory_stores_internal_type():
    graph = GraphStore(use_db=False)
    mid = await graph.create_memory(
        "决定使用 GraphQL",
        entity_id="user_123",
        memory_type="fact",
        internal_type="decision",
    )
    memory = await graph.get_memory(mid)
    assert memory["internal_type"] == "decision"


@pytest.mark.asyncio
async def test_chunk_internal_type_passed_to_graph(engine):
    """A chunk with internal_type propagates to the graph memory node."""
    chunk = Chunk(
        text="目标：三个月内上线新功能",
        index=0,
        memory_type="fact",
        internal_type="goal",
        confidence=0.85,
    )
    embeddings = [[0.1] * 128]

    memory_ids = await engine._index([chunk], embeddings, "user_123", "text", None)
    assert len(memory_ids) == 1

    memory = await engine.graph.get_memory(memory_ids[0])
    assert memory["memory_type"] == "fact"
    assert memory["internal_type"] == "goal"


@pytest.mark.asyncio
async def test_semantic_chunker_preserves_internal_type():
    """SemanticTextChunker copies internal_type from extracted facts to chunks."""
    from emerald.pipeline.chunking.fact_extractor import Fact

    class _StubExtractor:
        async def extract(self, text, *, entity_context=None):
            return [
                Fact(
                    text="承诺周五前交付 API 文档",
                    memory_type="fact",
                    internal_type="commitment",
                    confidence=0.9,
                    summary="API doc commitment",
                )
            ]

    chunker = SemanticTextChunker(fact_extractor=_StubExtractor())
    chunks = await chunker.chunk("承诺周五前交付 API 文档")
    assert len(chunks) == 1
    assert chunks[0].memory_type == "fact"
    assert chunks[0].internal_type == "commitment"
