"""Tests for semantic memory search."""

import pytest

from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.search import SearchMode, SearchOrchestrator
from emerald.core.vector import VectorStore


@pytest.fixture
def populated_search():
    """Search orchestrator with hiking memory stored in graph + vector."""
    graph = GraphStore(use_db=False)
    vector = VectorStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)

    # Seed hiking memory
    memory_id = "mem_hiking_001"
    from datetime import datetime, timezone

    graph._memories.setdefault("user_1", []).append(
        {
            "id": memory_id,
            "content": "我喜欢周末去山里 hiking",
            "summary": "周末 hiking 爱好",
            "memory_type": "fact",
            "confidence": 0.9,
            "is_latest": True,
            "valid_from": None,
            "valid_until": None,
            "created_at": datetime.now(timezone.utc),
        }
    )
    import asyncio

    vec = asyncio.run(embedder.embed(["我喜欢周末去山里 hiking"]))[0]
    asyncio.run(
        vector.store(
            memory_id, "我喜欢周末去山里 hiking", vec, entity_id="user_1"
        )
    )

    orchestrator = SearchOrchestrator(
        graph=graph, vector=vector, embedder=embedder
    )
    return orchestrator


@pytest.mark.asyncio
async def test_memory_search_uses_vector_path(populated_search):
    """_search_memory must use vector.search when embedder is available."""
    from unittest.mock import AsyncMock, patch

    with patch.object(
        populated_search.vector, "search", new_callable=AsyncMock
    ) as mock_vec_search:
        mock_vec_search.return_value = [
            ("mem_hiking_001", "我喜欢周末去山里 hiking", 0.95)
        ]
        with patch.object(
            populated_search.graph, "get_memory", new_callable=AsyncMock
        ) as mock_graph_get:
            mock_graph_get.return_value = {
                "id": "mem_hiking_001",
                "content": "我喜欢周末去山里 hiking",
                "confidence": 0.9,
                "is_latest": True,
                "memory_type": "fact",
            }
            result = await populated_search.search(
                "户外活动",
                entity_id="user_1",
                search_mode=SearchMode.MEMORY,
                top_k=5,
            )

    mock_vec_search.assert_called_once()
    mock_graph_get.assert_called_once_with("mem_hiking_001")
    assert len(result.results) >= 1
    assert any("hiking" in r.content for r in result.results)


@pytest.mark.asyncio
async def test_memory_search_filters_not_latest(populated_search):
    """Memories with is_latest=False are filtered out."""
    from unittest.mock import AsyncMock, patch

    with patch.object(
        populated_search.vector, "search", new_callable=AsyncMock
    ) as mock_vec_search:
        mock_vec_search.return_value = [
            ("mem_hiking_001", "我喜欢周末去山里 hiking", 0.95)
        ]
        with patch.object(
            populated_search.graph, "get_memory", new_callable=AsyncMock
        ) as mock_graph_get:
            mock_graph_get.return_value = {
                "id": "mem_hiking_001",
                "content": "我喜欢周末去山里 hiking",
                "confidence": 0.9,
                "is_latest": False,
                "memory_type": "fact",
            }
            result = await populated_search.search(
                "户外活动",
                entity_id="user_1",
                search_mode=SearchMode.MEMORY,
                top_k=5,
            )

    assert len(result.results) == 0
