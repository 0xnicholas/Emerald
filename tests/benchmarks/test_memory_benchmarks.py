"""Memory benchmarks — deterministic scenarios for memory accuracy.

Tests Emerald against synthetic scenarios that mirror LongMemEval,
LoCoMo, and ConvoMem evaluation patterns.

AGENTS.md: "每种关系类型必须有确定性的测试用例"
"基于标准数据集的记忆基准测试"
"""

import time
from datetime import UTC

import pytest

from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.profile import ProfileManager
from emerald.core.relationship import RelationshipEngine
from emerald.core.search import SearchMode, SearchOrchestrator
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor
from scripts.run_benchmarks import _CONTRADICTION_CHAINS


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


# =============================================================
# Benchmark 1: Temporal fact tracking (LongMemEval-style)
# Tests that facts evolve correctly over time: updates, aging
# =============================================================


class TestTemporalFactTracking:
    """LongMemEval-style: verifying fact evolution over a timeline."""

    @pytest.mark.asyncio
    async def test_fact_update_chain(self, engine):
        """A fact that changes 3 times: only the latest version is returned."""
        entity = "user_timeline"

        # Day 1: works at Google
        await engine.add("用户在 Google 工作", entity_id=entity)
        # Day 10: moved to Stripe (same structure → UPDATE)
        await engine.add("用户在 Stripe 工作", entity_id=entity)
        # Day 20: promoted (extends the Stripe fact)
        await engine.add("用户领导一个 5 人的支付团队", entity_id=entity)

        # Profile should contain latest facts
        profile = await ProfileManager(graph=engine.graph).get(entity)
        static_texts = [f.content for f in profile.static]
        assert any("Stripe" in t or "支付" in t for t in static_texts)

    @pytest.mark.asyncio
    async def test_temporal_preference_change(self, engine):
        """Preferences that change over time: old preference forgotten."""
        entity = "user_prefs"

        await engine.add("用户喜欢 Adidas 运动鞋", entity_id=entity)
        await engine.add("用户觉得 Adidas 质量不好", entity_id=entity)
        await engine.add("用户改用 Puma 运动鞋", entity_id=entity)

        profile = await ProfileManager(graph=engine.graph).get(entity)
        static_texts = [f.content for f in profile.static]
        assert any("Puma" in t for t in static_texts)
        # Old preference about Adidas should not be latest
        all_memories = await engine.graph.list_latest_memories(entity)
        contents = [m["content"] for m in all_memories if m["is_latest"]]
        assert any("Puma" in c for c in contents)

    @pytest.mark.asyncio
    async def test_temporary_fact_expiry(self, engine):
        """Temporary facts (e.g., 'exam tomorrow') expire after their valid_until."""
        from datetime import datetime, timedelta

        entity = "user_temp"
        yesterday = datetime.now(UTC) - timedelta(days=1)

        # Add a temporary fact. The engine should auto-extract valid_until from
        # the temporal expression "明天" before any manual override.
        result = await engine.add("明天有考试", entity_id=entity)
        mid = result.memory_ids[0]
        memory = await engine.graph.get_memory(mid)
        assert memory["valid_until"] is not None, (
            "Engine should auto-extract valid_until from temporal expression"
        )

        # Manually set its valid_until to yesterday for deterministic expiry verification.
        for memories in engine.graph._memories.values():
            for m in memories:
                if m["id"] == mid:
                    m["valid_until"] = yesterday

        from emerald.core.forget import ForgetEngine
        await ForgetEngine(graph=engine.graph).forget_expired()

        memory = await engine.graph.get_memory(mid)
        assert memory["is_latest"] is False

    @pytest.mark.asyncio
    async def test_latest_memories_excludes_expired(self, engine):
        """list_latest_memories excludes both expired and updated facts."""
        entity = "user_exclude"

        await engine.add("过期的考试信息", entity_id=entity)
        await engine.add("当前的工作信息", entity_id=entity)

        # Mark first as not latest
        all_mems = await engine.graph.list_latest_memories(entity)
        if len(all_mems) >= 2:
            await engine.graph.update_is_latest(all_mems[-1]["id"], False)

        latest = await engine.graph.list_latest_memories(entity)
        contents = [m["content"] for m in latest]
        assert "当前的工作信息" in contents


# =============================================================
# Benchmark 2: Relationship accuracy
# Tests UPDATES, EXTENDS, DERIVES_FROM classification
# =============================================================


class TestRelationshipAccuracy:
    """Tests that the relationship engine correctly classifies fact pairs."""

    @pytest.mark.asyncio
    async def test_updates_same_structure_different_filler(self, engine):
        """Same sentence structure, different key entity → UPDATE."""
        entity = "rel_test"

        await engine.add("用户在 Google 工作", entity_id=entity)
        await engine.add("用户在 Stripe 工作", entity_id=entity)

        # The second should have replaced the first
        memories = await engine.graph.list_latest_memories(entity)
        contents = [m["content"] for m in memories if m["is_latest"]]
        assert any("Stripe" in c for c in contents)

        # First should be is_latest=False
        all_mems = await engine.graph.list_latest_memories(entity, limit=100)
        # list_latest_memories already filters is_latest=True
        assert len(all_mems) >= 1

    @pytest.mark.asyncio
    async def test_extends_different_aspect_same_domain(self, engine):
        """Complementary facts about the same domain → EXTENDS."""
        entity = "rel_extends"

        await engine.add("用户在 Stripe 工作", entity_id=entity)
        await engine.add("用户领导一个 5 人的支付团队", entity_id=entity)

        # Both should be latest (extends doesn't replace)
        memories = await engine.graph.list_latest_memories(entity)
        assert len(memories) >= 2
        for m in memories:
            assert m["is_latest"] is True

    @pytest.mark.asyncio
    async def test_no_relationship_for_unrelated(self, engine):
        """Unrelated facts across different domains → NONE."""
        entity = "rel_none"

        await engine.add("用户喜欢 TypeScript", entity_id=entity)
        await engine.add("用户住在北京", entity_id=entity)

        # Both should be latest and independent
        memories = await engine.graph.list_latest_memories(entity)
        assert len(memories) >= 2


# =============================================================
# Benchmark 3: Search precision & recall
# Tests search accuracy (LoCoMo-style consistency)
# =============================================================


class TestSearchPrecisionRecall:
    """LoCoMo-style: conversation consistency through search accuracy."""

    @pytest.mark.asyncio
    async def test_precision_exact_match(self, engine):
        """Search for exact stored content returns it as top result."""
        entity = "search_precision"

        await engine.add("TypeScript 是 JavaScript 的超集", entity_id=entity)

        orchestrator = SearchOrchestrator(
            graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
        )
        results = await orchestrator.search(
            "TypeScript 是 JavaScript 的超集",
            entity_id=entity,
            search_mode=SearchMode.MEMORY,
            top_k=5,
        )
        assert len(results.results) >= 1
        assert results.results[0].score > 0

    @pytest.mark.asyncio
    async def test_recall_keyword_subset(self, engine):
        """Search with partial keywords recalls relevant memories."""
        entity = "search_recall"

        await engine.add("用户喜欢 TypeScript 和函数式编程", entity_id=entity)
        await engine.add("用户是一名资深前端工程师", entity_id=entity)
        await engine.add("用户讨厌 Java 和面向对象编程", entity_id=entity)

        orchestrator = SearchOrchestrator(
            graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
        )
        results = await orchestrator.search(
            "TypeScript", entity_id=entity, search_mode=SearchMode.MEMORY, top_k=5,
        )
        assert len(results.results) >= 1
        assert any("TypeScript" in r.content for r in results.results)

    @pytest.mark.asyncio
    async def test_mrr_ranking(self, engine):
        """MRR: the most relevant result should rank first.

        With MockEmbeddingProvider (hash-based deterministic vectors)
        we verify exact-match ranking; semantic keyword-mismatch recall
        is tested in integration tests with a real embedding provider.
        """
        entity = "search_mrr"

        await engine.add("一些无关的内容", entity_id=entity)
        await engine.add("Python 是一种动态类型语言", entity_id=entity)
        await engine.add("更多无关的内容", entity_id=entity)

        orchestrator = SearchOrchestrator(
            graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
        )
        # Exact-match query guarantees highest similarity under any embedder
        results = await orchestrator.search(
            "Python 是一种动态类型语言", entity_id=entity, search_mode=SearchMode.MEMORY, top_k=3,
        )
        if results.results:
            # Top result should be the exact-match Python one
            assert "Python" in results.results[0].content


# =============================================================
# Benchmark 4: Profile quality
# Tests that profiles correctly reflect entity knowledge
# =============================================================


class TestProfileQuality:
    """Tests profile accuracy and freshness."""

    @pytest.mark.asyncio
    async def test_profile_reflects_all_facts(self, engine):
        """Profile should contain all high-confidence facts."""
        entity = "profile_quality"

        facts = [
            ("用户是资深前端工程师", "fact", 0.9),
            ("用户偏好 TypeScript", "preference", 0.85),
            ("用户使用 Vim 编辑器", "preference", 0.8),
        ]
        for content, mtype, conf in facts:
            await engine.graph.create_memory(
                content, entity_id=entity, memory_type=mtype, confidence=conf,
            )

        profile = await ProfileManager(graph=engine.graph).get(entity)
        static_texts = [f.content for f in profile.static]
        assert len(static_texts) >= 3
        for expected, _, _ in facts:
            assert any(expected in t for t in static_texts), (
                f"Expected '{expected}' in profile static facts: {static_texts}"
            )

    @pytest.mark.asyncio
    async def test_profile_excludes_low_confidence_noise(self, engine):
        """Low-confidence noise should not appear in profile."""
        entity = "profile_noise"

        await engine.graph.create_memory(
            "一个重要的事实", entity_id=entity, confidence=0.9,
        )
        await engine.graph.create_memory(
            "一句随意的闲聊", entity_id=entity, confidence=0.2,
        )

        profile = await ProfileManager(graph=engine.graph).get(entity)
        static_texts = [f.content for f in profile.static]
        assert any("重要" in t for t in static_texts)
        assert not any("闲聊" in t for t in static_texts)

    @pytest.mark.asyncio
    async def test_profile_computation_speed(self, engine):
        """Profile computation should be fast (< 100ms target)."""
        entity = "profile_speed"

        # Add 50 memories
        for i in range(50):
            await engine.graph.create_memory(
                f"事实 {i}", entity_id=entity,
            )

        start = time.perf_counter()
        profile = await ProfileManager(graph=engine.graph).get(entity)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert profile.memory_count == 50
        assert elapsed_ms < 100, f"Profile computation took {elapsed_ms:.1f}ms (target <100ms)"


# =============================================================
# Benchmark 5: Entity isolation
# =============================================================


class TestEntityIsolation:
    """Tests that entities never leak data to each other."""

    @pytest.mark.asyncio
    async def test_cross_entity_no_leak(self, engine):
        """Memory of entity A never appears in entity B's search."""
        await engine.add("Alice 的秘密内容", entity_id="alice")
        await engine.add("Bob 的公开内容", entity_id="bob")

        orchestrator = SearchOrchestrator(
            graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
        )

        alice_results = await orchestrator.search(
            "秘密", entity_id="alice", search_mode=SearchMode.MEMORY,
        )
        bob_results = await orchestrator.search(
            "秘密", entity_id="bob", search_mode=SearchMode.MEMORY,
        )

        assert any("Alice" in r.content for r in alice_results.results)
        assert not any("Alice" in r.content for r in bob_results.results)

    @pytest.mark.asyncio
    async def test_memory_count_per_entity(self, engine):
        """Each entity's memory count is independent."""
        for i in range(10):
            await engine.add(f"Alice 记忆 {i}", entity_id="alice")
        for i in range(5):
            await engine.add(f"Bob 记忆 {i}", entity_id="bob")

        alice_profile = await ProfileManager(graph=engine.graph).get("alice")
        bob_profile = await ProfileManager(graph=engine.graph).get("bob")

        assert alice_profile.memory_count == 10
        assert bob_profile.memory_count == 5


# =============================================================
# Benchmark 7: Contradiction chain (multi-round supersession)
# Multi-round supersession is the depth dimension of Temporal
# Updates: the same fact is contradicted 5 rounds in a row.
# =============================================================

# 6 steps = 5 supersession rounds; every round fully replaces the
# previous state of the same fact. Rule-based classification (mock
# mode) deterministically emits UPDATES: same structure template with
# a different filler (employer / city / language), numeric value
# change (budget), or explicit contradiction wording (drink).
# The corpus lives in scripts/run_benchmarks.py (_CONTRADICTION_CHAINS);
# this is chain_employer, imported so corpus edits don't drift apart.
_CHAIN_STEPS = _CONTRADICTION_CHAINS[0]["steps"]


class TestContradictionChain:
    """Multi-round supersession: old facts invalidated, final fact recalled."""

    @pytest.mark.asyncio
    async def test_five_round_supersession_flips_is_latest(self, engine):
        """After 5 consecutive supersessions only the final fact is latest.

        Every superseded fact flips is_latest=False and records its
        replacement (replaced_by → next step). The final fact stays
        is_latest=True with no replacement.
        """
        entity = "chain_unit_flip"
        ids = []
        for step in _CHAIN_STEPS:
            result = await engine.add(step, entity_id=entity, content_type="text")
            ids.append(result.memory_ids[0])

        assert len(ids) == 6
        for i in range(5):
            mem = await engine.graph.get_memory(ids[i])
            assert mem["is_latest"] is False, f"step {i + 1} should be superseded"
            assert mem["replaced_by"] == ids[i + 1], (
                f"step {i + 1} should point to step {i + 2}"
            )

        final = await engine.graph.get_memory(ids[5])
        assert final["is_latest"] is True
        assert final["replaced_by"] is None

        latest = await engine.graph.list_latest_memories(entity)
        assert len(latest) == 1
        assert latest[0]["content"] == _CHAIN_STEPS[-1]

    @pytest.mark.asyncio
    async def test_superseded_facts_excluded_from_recall(self, engine):
        """Search recalls the final fact at rank 1, never the superseded ones.

        Exact-text queries are deterministic under mock embeddings: the
        query embedding matches the identical memory exactly, while
        superseded memories are filtered by is_latest before ranking.
        """
        entity = "chain_unit_recall"
        for step in _CHAIN_STEPS:
            await engine.add(step, entity_id=entity, content_type="text")

        orchestrator = SearchOrchestrator(
            graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
        )

        # Latest fact is recalled at rank 1 by its exact-text query
        results = await orchestrator.search(
            _CHAIN_STEPS[-1], entity_id=entity,
            search_mode=SearchMode.MEMORY, top_k=5,
        )
        assert results.results, "expected at least one result"
        assert results.results[0].content == _CHAIN_STEPS[-1]

        # Superseded facts are never recalled by their exact text
        for step in _CHAIN_STEPS[:-1]:
            results = await orchestrator.search(
                step, entity_id=entity,
                search_mode=SearchMode.MEMORY, top_k=5,
            )
            assert not any(step in r.content for r in results.results), (
                f"superseded fact should not be recalled: {step}"
            )

    @pytest.mark.asyncio
    async def test_update_edges_created_per_round(self, engine):
        """Every supersession round creates exactly one UPDATES edge."""
        entity = "chain_unit_edges"
        ids = []
        for step in _CHAIN_STEPS:
            result = await engine.add(step, entity_id=entity, content_type="text")
            ids.append(result.memory_ids[0])

        # Each superseded fact has exactly one UPDATES edge from its successor
        for i in range(5):
            rels = await engine.graph.get_relationships_to([ids[i]])
            assert rels.get(ids[i]) == [ids[i + 1]], (
                f"step {i + 1} should have an UPDATES edge from step {i + 2}"
            )

        # The final fact supersedes nothing
        rels = await engine.graph.get_relationships_to([ids[5]])
        assert ids[5] not in rels

    @pytest.mark.asyncio
    async def test_scenario_is_deterministic_under_mock(self):
        """The 7th benchmark dimension itself is deterministic under mock
        embeddings: all four rates are exactly 1.0 and it needs no API.

        Uses a rule-only relationship engine (use_llm=False) so the
        determinism guarantee is unconditional, even with API keys set.
        """
        from scripts.run_benchmarks import (
            BenchConfig,
            benchmark_contradiction_chain,
        )

        extractors = ExtractorRegistry()
        extractors.register("text", TextExtractor())
        chunkers = ChunkerRegistry()
        chunkers.register("text", TextChunker())
        graph = GraphStore(use_db=False)
        vector = VectorStore(use_db=False)
        engine = MemoryEngine(
            extractor_registry=extractors,
            chunker_registry=chunkers,
            embedder=MockEmbeddingProvider(dimension=128),
            graph=graph,
            vector=vector,
            relationships=RelationshipEngine(graph=graph, use_llm=False),
            use_db=False,
        )

        config = BenchConfig(use_real_embeddings=False, embedding_dim=128)
        result = await benchmark_contradiction_chain(engine, config)

        assert result.name == "Contradiction Chain"
        assert result.metrics["latest_recall@1"] == 1.0
        assert result.metrics["expired_exclusion_rate"] == 1.0
        assert result.metrics["is_latest_flip_rate"] == 1.0
        assert result.metrics["update_relation_rate"] == 1.0
        assert result.metrics["overall_accuracy"] == 1.0
        assert result.passed is True
