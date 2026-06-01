#!/usr/bin/env python3
"""Emerald memory benchmark runner.

Runs deterministic benchmark scenarios and reports quantitative metrics:
- Accuracy (temporal fact tracking, relationship classification)
- Recall (search keyword recall)
- MRR (Mean Reciprocal Rank)
- Profile computation latency (P50, P99)

Usage:
    python scripts/run_benchmarks.py
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add project root to path for direct script execution
sys.path.insert(0, str(Path(__file__).parent.parent))

from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.profile import ProfileManager
from emerald.core.search import SearchMode, SearchOrchestrator
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor


def _make_engine() -> MemoryEngine:
    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    extractors.register("conversation", TextExtractor())
    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    chunkers.register("conversation", TextChunker())
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
# Benchmark 1: Temporal Fact Tracking (LongMemEval-style)
# =============================================================


async def benchmark_temporal_accuracy(engine: MemoryEngine) -> dict:
    """Test fact evolution accuracy over a timeline."""
    entity = "bench_temporal"
    correct = 0
    total = 3

    # Fact 1: Initial preference
    await engine.add("用户喜欢 Adidas 运动鞋", entity_id=entity)
    # Fact 2: Update (contradiction)
    await engine.add("用户觉得 Adidas 质量不好", entity_id=entity)
    # Fact 3: Final state
    await engine.add("用户改用 Puma 运动鞋", entity_id=entity)

    # Check: latest memory should reflect final state
    memories = await engine.graph.list_latest_memories(entity)
    latest_contents = [m["content"] for m in memories if m["is_latest"]]
    if any("Puma" in c for c in latest_contents):
        correct += 1

    # Check: old preference is archived
    all_mems = [
        m for mems in engine.graph._memories.values() for m in mems
        if m.get("content", "").startswith("用户喜欢 Adidas")
    ]
    if all_mems and not all_mems[0]["is_latest"]:
        correct += 1

    # Check: profile reflects latest preference
    profile = await ProfileManager(graph=engine.graph).get(entity)
    static_texts = [f.content for f in profile.static]
    if any("Puma" in t for t in static_texts):
        correct += 1

    return {"correct": correct, "total": total, "accuracy": correct / total}


# =============================================================
# Benchmark 2: Relationship Classification Accuracy
# =============================================================


async def benchmark_relationship_accuracy(engine: MemoryEngine) -> dict:
    """Test UPDATES vs EXTENDS vs NONE classification."""
    correct = 0
    total = 3

    # Case 1: UPDATES (same structure, different filler)
    entity1 = "bench_rel_updates"
    await engine.add("用户在 Google 工作", entity_id=entity1)
    await engine.add("用户在 Stripe 工作", entity_id=entity1)
    mems1 = await engine.graph.list_latest_memories(entity1, limit=100)
    old_google = [m for m in mems1 if "Google" in m["content"]]
    if old_google and not old_google[0]["is_latest"]:
        correct += 1

    # Case 2: EXTENDS (complementary, both stay latest)
    entity2 = "bench_rel_extends"
    await engine.add("用户在 Stripe 工作", entity_id=entity2)
    await engine.add("用户领导一个 5 人的支付团队", entity_id=entity2)
    mems2 = await engine.graph.list_latest_memories(entity2)
    if len(mems2) >= 2 and all(m["is_latest"] for m in mems2):
        correct += 1

    # Case 3: NONE (unrelated, both stay latest)
    entity3 = "bench_rel_none"
    await engine.add("用户喜欢 TypeScript", entity_id=entity3)
    await engine.add("用户住在北京", entity_id=entity3)
    mems3 = await engine.graph.list_latest_memories(entity3)
    if len(mems3) >= 2 and all(m["is_latest"] for m in mems3):
        correct += 1

    return {"correct": correct, "total": total, "accuracy": correct / total}


# =============================================================
# Benchmark 3: Search Recall (LoCoMo-style)
# =============================================================


async def benchmark_search_recall(engine: MemoryEngine) -> dict:
    """Test search keyword recall."""
    entity = "bench_search"
    # Seed 5 memories, 3 relevant to "TypeScript"
    memories = [
        "用户喜欢 TypeScript 和函数式编程",
        "用户是一名资深前端工程师",
        "用户讨厌 Java 和面向对象编程",
        "TypeScript 提供了优秀的类型系统",
        "React 和 TypeScript 是最佳搭档",
    ]
    for m in memories:
        await engine.add(m, entity_id=entity)

    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )
    results = await orchestrator.search(
        "TypeScript", entity_id=entity, search_mode=SearchMode.MEMORY, top_k=5,
    )

    relevant_found = sum(1 for r in results.results if "TypeScript" in r.content)
    total_relevant = 3

    recall = relevant_found / total_relevant if total_relevant else 0.0
    return {
        "relevant_found": relevant_found,
        "total_relevant": total_relevant,
        "recall": recall,
    }


# =============================================================
# Benchmark 4: MRR (Mean Reciprocal Rank)
# =============================================================


async def benchmark_mrr(engine: MemoryEngine) -> dict:
    """Test that exact-match queries rank first."""
    entity = "bench_mrr"
    queries = [
        "Python 是一种动态类型语言",
        "Rust 内存安全且无垃圾回收",
        "Go 语言适合构建高并发服务",
    ]
    for q in queries:
        await engine.add(q, entity_id=entity)
        # Add distractors
        await engine.add("一些无关的内容 A", entity_id=entity)
        await engine.add("一些无关的内容 B", entity_id=entity)

    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )

    rr_scores = []
    for q in queries:
        results = await orchestrator.search(
            q, entity_id=entity, search_mode=SearchMode.MEMORY, top_k=5,
        )
        for i, r in enumerate(results.results, start=1):
            if r.content == q:
                rr_scores.append(1.0 / i)
                break
        else:
            rr_scores.append(0.0)

    mrr = statistics.mean(rr_scores) if rr_scores else 0.0
    return {"mrr": mrr, "reciprocal_ranks": rr_scores}


# =============================================================
# Benchmark 5: Profile Latency
# =============================================================


async def benchmark_profile_latency(engine: MemoryEngine) -> dict:
    """Profile computation latency (cold and warm)."""
    entity = "bench_latency"
    for i in range(50):
        await engine.graph.create_memory(
            f"事实 {i}", entity_id=entity, confidence=0.8,
        )

    mgr = ProfileManager(graph=engine.graph)

    # Cold start (compute)
    times = []
    for _ in range(10):
        start = time.perf_counter()
        await mgr.get(entity)
        times.append((time.perf_counter() - start) * 1000)

    # Warm (cache hit) — invalidate then get again to measure cache
    await mgr.invalidate(entity)
    warm_times = []
    for _ in range(10):
        start = time.perf_counter()
        await mgr.get(entity)
        warm_times.append((time.perf_counter() - start) * 1000)
        await mgr.invalidate(entity)

    return {
        "cold_ms": {"p50": statistics.median(times), "p99": sorted(times)[int(len(times) * 0.99)]},
        "warm_ms": {"p50": statistics.median(warm_times), "p99": sorted(warm_times)[int(len(warm_times) * 0.99)]},
    }


# =============================================================
# Benchmark 6: ConvoMem-style conversation recall
# =============================================================


async def benchmark_conversation_recall(engine: MemoryEngine) -> dict:
    """ConvoMem-style: multi-turn conversation recall accuracy."""
    entity = "bench_convo"
    conversation = [
        ("User", "我想学习 Rust 语言"),
        ("Assistant", "Rust 是一种系统编程语言，强调内存安全"),
        ("User", "它和 C++ 有什么区别"),
        ("Assistant", "Rust 通过所有权系统避免内存泄漏，不需要垃圾回收"),
        ("User", "好的，推荐一些学习资源"),
        ("Assistant", "官方文档 The Rust Book 和 Rust by Example 是最佳入门"),
    ]

    for speaker, text in conversation:
        await engine.add(f"{speaker}: {text}", entity_id=entity, content_type="conversation")

    # Use keyword-based orchestrator (no embedder) for conversation recall
    # because MockEmbeddingProvider doesn't capture semantic similarity.
    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=None,
    )

    queries = [
        ("Rust 内存安全", ["Rust", "内存安全", "所有权"]),
        ("学习资源", ["Book", "Example"]),
        ("和 C++ 区别", ["C++", "垃圾回收"]),
    ]

    correct = 0
    total = 0
    for q, expected_keywords in queries:
        results = await orchestrator.search(
            q, entity_id=entity, search_mode=SearchMode.MEMORY, top_k=3,
        )
        total += 1
        if results.results:
            top = results.results[0].content
            if any(kw in top for kw in expected_keywords):
                correct += 1

    return {"correct": correct, "total": total, "accuracy": correct / total}


# =============================================================
# Main runner
# =============================================================


async def main() -> None:
    print("=" * 60)
    print("Emerald Memory Benchmarks")
    print("=" * 60)

    engine = _make_engine()

    benchmarks = [
        ("Temporal Fact Tracking (LongMemEval-style)", benchmark_temporal_accuracy),
        ("Relationship Classification", benchmark_relationship_accuracy),
        ("Search Recall (LoCoMo-style)", benchmark_search_recall),
        ("MRR (Mean Reciprocal Rank)", benchmark_mrr),
        ("Profile Computation Latency", benchmark_profile_latency),
        ("Conversation Recall (ConvoMem-style)", benchmark_conversation_recall),
    ]

    all_results = {}
    for name, fn in benchmarks:
        print(f"\n{name}...")
        result = await fn(engine)
        all_results[name] = result
        for k, v in result.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.3f}")
            else:
                print(f"  {k}: {v}")

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    accuracy_scores = [
        all_results["Temporal Fact Tracking (LongMemEval-style)"]["accuracy"],
        all_results["Relationship Classification"]["accuracy"],
        all_results["Conversation Recall (ConvoMem-style)"]["accuracy"],
    ]
    avg_accuracy = statistics.mean(accuracy_scores)
    print(f"Average Accuracy: {avg_accuracy:.3f}")

    recall = all_results["Search Recall (LoCoMo-style)"]["recall"]
    print(f"Search Recall:    {recall:.3f}")

    mrr = all_results["MRR (Mean Reciprocal Rank)"]["mrr"]
    print(f"MRR:              {mrr:.3f}")

    cold_p50 = all_results["Profile Computation Latency"]["cold_ms"]["p50"]
    warm_p50 = all_results["Profile Computation Latency"]["warm_ms"]["p50"]
    print(f"Profile Cold P50: {cold_p50:.2f}ms")
    print(f"Profile Warm P50: {warm_p50:.2f}ms")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
