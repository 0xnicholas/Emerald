"""Tests for keyword search fallback and full-text index integration."""

from __future__ import annotations

import pytest

from emerald.core.graph import GraphStore
from emerald.core.search import SearchMode, SearchOrchestrator
from emerald.core.vector import VectorStore


class TestSearchKeyword:
    """Verify keyword search behaviour in embedder-fallback and DB modes."""

    @pytest.fixture
    def graph(self):
        return GraphStore(use_db=False)

    @pytest.fixture
    def vector(self):
        return VectorStore(use_db=False)

    @pytest.fixture
    def orchestrator(self, graph, vector):
        return SearchOrchestrator(graph=graph, vector=vector, embedder=None)

    @pytest.fixture
    def entity_id(self):
        return "user_keyword"

    async def test_fallback_keyword_search_without_embedder(self, orchestrator, graph, entity_id):
        await graph.create_memory("如何使用 Python 进行数据分析", entity_id=entity_id)
        await graph.create_memory("Python 入门教程", entity_id=entity_id)
        await graph.create_memory("JavaScript 异步编程", entity_id=entity_id)

        response = await orchestrator.search(
            "Python 数据分析", entity_id=entity_id, search_mode=SearchMode.MEMORY, top_k=5
        )
        contents = [r.content for r in response.results]
        assert "如何使用 Python 进行数据分析" in contents
        assert "Python 入门教程" in contents
        assert "JavaScript 异步编程" not in contents

    async def test_fallback_empty_query(self, orchestrator, graph, entity_id):
        await graph.create_memory("Some content", entity_id=entity_id)
        response = await orchestrator.search(
            "", entity_id=entity_id, search_mode=SearchMode.MEMORY, top_k=5
        )
        assert response.results == []

    async def test_fallback_cjk_characters(self, orchestrator, graph, entity_id):
        await graph.create_memory("北京今天天气很好", entity_id=entity_id)
        await graph.create_memory("上海下雨了", entity_id=entity_id)

        response = await orchestrator.search(
            "北京天气", entity_id=entity_id, search_mode=SearchMode.MEMORY, top_k=5
        )
        contents = [r.content for r in response.results]
        assert "北京今天天气很好" in contents
        assert "上海下雨了" not in contents

    async def test_vector_store_memory_keyword_search(self, vector):
        """VectorStore in-memory keyword search fallback."""
        vector._memory_texts["c1"] = "machine learning basics"
        vector._memory_entities["c1"] = "user_1"
        vector._memory_texts["c2"] = "deep learning advanced"
        vector._memory_entities["c2"] = "user_1"
        vector._memory_texts["c3"] = "cooking recipes"
        vector._memory_entities["c3"] = "user_1"

        results = await vector.keyword_search("machine learning", entity_id="user_1", top_k=5)
        texts = [r[1] for r in results]
        assert "machine learning basics" in texts
        assert "deep learning advanced" in texts
        assert "cooking recipes" not in texts

    async def test_vector_store_keyword_search_respects_entity(self, vector):
        vector._memory_texts["c1"] = "shared content"
        vector._memory_entities["c1"] = "user_a"
        vector._memory_texts["c2"] = "shared content"
        vector._memory_entities["c2"] = "user_b"

        results = await vector.keyword_search("shared", entity_id="user_a", top_k=5)
        assert len(results) == 1
        assert results[0][0] == "c1"

    async def test_graph_keyword_search_memories_fallback(self, graph, entity_id):
        await graph.create_memory("PostgreSQL indexing strategies", entity_id=entity_id)
        await graph.create_memory("Redis caching patterns", entity_id=entity_id)

        results = await graph.keyword_search_memories(
            entity_id, "PostgreSQL index", top_k=5
        )
        texts = [r[1] for r in results]
        assert "PostgreSQL indexing strategies" in texts
        assert "Redis caching patterns" not in texts
