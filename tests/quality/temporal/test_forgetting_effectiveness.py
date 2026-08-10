"""Quality suite section 2 — forgetting effectiveness (ADR-0001, ticket #10).

Scenarios (roadmap M2):
- noise filtering: low-confidence + old memories are archived (forget_noise)
- episodic decay: episodic memories older than 90 days are archived
- noise-injection adversarial corpus at two noise ratios (50% and 80%)
- signal retention: high-confidence memories survive cleanup, retrieval
  quality is preserved

Metrics and thresholds (all must pass for the suite to be green):
- noise removal rate       >= 95%   (noise archived / all noise)
- signal survival rate     >= 98%   (signal kept / all signal; loss <= 2%)
- retrieval retention rate >= 95%   (signals still searchable after cleanup)
- graph slimming rate in [50%, 90%] (decayed memories / total memories)

Deterministic corpus, rule-only path (use_llm=False), mock embeddings.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.forget import ForgetEngine
from emerald.core.search import SearchMode, SearchOrchestrator

pytestmark = [pytest.mark.quality]


class Metric:
    """Count pass/fail outcomes; assert the pass-rate threshold at the end."""

    def __init__(self, name: str, threshold: float):
        self.name = name
        self.threshold = threshold
        self.numerator = 0
        self.denominator = 0

    def record(self, ok: bool) -> None:
        self.denominator += 1
        if ok:
            self.numerator += 1

    @property
    def rate(self) -> float:
        if self.denominator == 0:
            return 1.0
        return self.numerator / self.denominator

    def assert_threshold(self) -> None:
        assert self.rate >= self.threshold, (
            f"{self.name}: {self.rate:.4f} < {self.threshold} "
            f"({self.numerator}/{self.denominator})"
        )


async def _search(engine, q: str, entity_id: str):
    orchestrator = SearchOrchestrator(
        graph=engine.graph,
        vector=engine.vector,
        embedder=engine.embedder,
    )
    response = await orchestrator.search(
        q, entity_id=entity_id, search_mode=SearchMode.MEMORY, top_k=10,
    )
    return response.results


def _rewind(graph, entity_id: str, memory_id: str, days: int) -> None:
    """Rewind created_at so the memory is older than the strategy threshold."""
    for m in graph._memories.get(entity_id, []):
        if m["id"] == memory_id:
            m["created_at"] = datetime.now(UTC) - timedelta(days=days)
            return


# ---------------------------------------------------------------------------
# Scenario 1 — noise filtering
# ---------------------------------------------------------------------------


async def _run_noise_filter_scenario(graph, entity_id) -> Metric:
    """25 old noise memories archived; 5 recent low-confidence kept."""
    metric = Metric("noise_removal_rate", 0.95)

    noise_ids = []
    for i in range(25):
        mid = await graph.create_memory(
            f"随手记录的想法 {i}", entity_id=entity_id,
            memory_type="fact", confidence=0.10 + (i % 3) * 0.05,  # 0.10-0.20
        )
        _rewind(graph, entity_id, mid, days=10 + (i % 20))
        noise_ids.append(mid)

    recent_ids = []
    for i in range(5):
        mid = await graph.create_memory(
            f"刚发生的小事 {i}", entity_id=entity_id, confidence=0.15,
        )
        recent_ids.append(mid)

    engine = ForgetEngine(graph=graph)
    await engine.forget_noise(entity_id)

    for mid in noise_ids:
        memory = await graph.get_memory(mid)
        ok = memory is not None and memory["is_latest"] is False
        metric.record(ok)
        assert ok, f"Noise memory {mid} not archived"

    for mid in recent_ids:
        memory = await graph.get_memory(mid)
        ok = memory is not None and memory["is_latest"] is True
        metric.record(ok)
        assert ok, f"Recent low-confidence memory {mid} wrongly archived"

    return metric


# ---------------------------------------------------------------------------
# Scenario 2 — episodic decay + graph slimming
# ---------------------------------------------------------------------------


async def _run_episodic_decay_scenario(graph, entity_id) -> tuple[Metric, float]:
    """Old episodic memories archived; recent episodes and facts kept.

    Returns (archival_metric, slimming_rate) where slimming_rate is the
    fraction of total memories decayed by the strategy.
    """
    metric = Metric("episodic_archival_rate", 0.95)

    old_episodic = []
    for i in range(20):
        mid = await graph.create_memory(
            f"很久以前的对话片段 {i}", entity_id=entity_id,
            memory_type="episodic", confidence=0.7,
        )
        _rewind(graph, entity_id, mid, days=100 + i)
        old_episodic.append(mid)

    recent_episodic = []
    for i in range(10):
        mid = await graph.create_memory(
            f"最近的一次闲聊 {i}", entity_id=entity_id,
            memory_type="episodic", confidence=0.7,
        )
        recent_episodic.append(mid)

    old_facts = []
    for i in range(10):
        mid = await graph.create_memory(
            f"重要的长期事实 {i}", entity_id=entity_id,
            memory_type="fact", confidence=0.9,
        )
        _rewind(graph, entity_id, mid, days=100 + i)
        old_facts.append(mid)

    engine = ForgetEngine(graph=graph)
    await engine.decay_episodic()

    for mid in old_episodic:
        memory = await graph.get_memory(mid)
        ok = memory is not None and memory["is_latest"] is False
        metric.record(ok)
        assert ok, f"Old episodic memory {mid} not decayed"

    for mid in recent_episodic + old_facts:
        memory = await graph.get_memory(mid)
        ok = memory is not None and memory["is_latest"] is True
        metric.record(ok)
        assert ok, f"Valid memory {mid} wrongly decayed"

    total = len(old_episodic) + len(recent_episodic) + len(old_facts)
    return metric, len(old_episodic) / total


# ---------------------------------------------------------------------------
# Scenario 3 — noise injection adversarial corpus (50% and 80%)
# ---------------------------------------------------------------------------


SIGNAL_CONTENTS = [
    "用户在 Google 工作",
    "用户喜欢 Python",
    "用户住在北京",
    "用户养了一只猫",
    "用户喜欢爬山",
    "用户在学日语",
    "用户用 MacBook",
    "用户常去健身房",
    "用户喜欢看电影",
    "用户在读博士",
    "用户喜欢做菜",
    "用户用 Notion 记笔记",
]


async def _seed_mixed_corpus(
    graph, entity_id, *, noise_ratio: float,
) -> tuple[list[str], list[str]]:
    """Seed signal + noise memories; returns (signal_ids, noise_ids)."""
    total = 60
    noise_count = int(total * noise_ratio)
    signal_count = total - noise_count

    signal_ids = []
    for i in range(signal_count):
        content = SIGNAL_CONTENTS[i % len(SIGNAL_CONTENTS)] + f" 第{i}条"
        mid = await graph.create_memory(
            content, entity_id=entity_id,
            memory_type="fact" if i % 2 else "episodic",
            confidence=0.6 + 0.05 * (i % 7),  # 0.60-0.90
        )
        signal_ids.append(mid)

    noise_ids = []
    for i in range(noise_count):
        mid = await graph.create_memory(
            f"无意义的碎碎念 {i}", entity_id=entity_id,
            memory_type="fact", confidence=0.1 + 0.02 * (i % 10),
        )
        _rewind(graph, entity_id, mid, days=8 + (i % 25))
        noise_ids.append(mid)

    return signal_ids, noise_ids


async def _run_adversarial_corpus(
    graph, entity_id, *, noise_ratio: float,
) -> tuple[Metric, Metric]:
    """Run forget_noise against a mixed corpus; measure removal vs survival."""
    removal = Metric("noise_removal_rate", 0.95)
    survival = Metric("signal_survival_rate", 0.98)

    signal_ids, noise_ids = await _seed_mixed_corpus(graph, entity_id, noise_ratio=noise_ratio)
    engine = ForgetEngine(graph=graph)
    await engine.forget_noise(entity_id)

    for mid in noise_ids:
        memory = await graph.get_memory(mid)
        removal.record(memory is None or memory["is_latest"] is False)

    for mid in signal_ids:
        memory = await graph.get_memory(mid)
        survival.record(memory is not None and memory["is_latest"] is True)

    return removal, survival


# ---------------------------------------------------------------------------
# Scenario 4 — signal retention and retrieval quality
# ---------------------------------------------------------------------------


async def _run_signal_retention_scenario(engine, entity_id) -> tuple[Metric, Metric]:
    """High-confidence signals survive cleanup; search still finds them."""
    survival = Metric("signal_survival_rate", 0.98)
    retrieval = Metric("retrieval_retention_rate", 0.95)

    # Seed signals through the full engine pipeline (vector store included).
    for content in SIGNAL_CONTENTS[:12]:
        await engine.add(content, entity_id=entity_id)

    # Baseline: every signal must be searchable before cleanup.
    for content in SIGNAL_CONTENTS[:12]:
        results = await _search(engine, content, entity_id)
        assert any(r.content.strip() == content.strip() for r in results), (
            f"Baseline retrieval failed for {content!r}"
        )

    # Cleanup must not touch recent, high-confidence signals.
    engine.forget_engine = ForgetEngine(graph=engine.graph)
    await engine.forget_engine.forget_noise(entity_id)
    await engine.forget_engine.decay_episodic()

    for content in SIGNAL_CONTENTS[:12]:
        mid = None
        for m in engine.graph._memories.get(entity_id, []):
            if m["content"] == content:
                mid = m["id"]
                break
        memory = await engine.graph.get_memory(mid) if mid else None
        survival.record(memory is not None and memory["is_latest"] is True)

        results = await _search(engine, content, entity_id)
        retrieval.record(any(r.content.strip() == content.strip() for r in results))

    return survival, retrieval


# ---------------------------------------------------------------------------
# Aggregate gate
# ---------------------------------------------------------------------------


async def test_forgetting_effectiveness_metrics(engine, graph) -> None:
    """Aggregate gate: all metrics across all scenarios must pass."""
    noise_metric = await _run_noise_filter_scenario(graph, "user_quality_forget_noise")
    noise_metric.assert_threshold()

    decay_metric, slimming = await _run_episodic_decay_scenario(
        graph, "user_quality_forget_decay",
    )
    decay_metric.assert_threshold()
    assert 0.50 <= slimming <= 0.90, f"graph slimming {slimming:.3f} out of [0.5, 0.9]"

    removal50, survival50 = await _run_adversarial_corpus(
        graph, "user_quality_forget_adv50", noise_ratio=0.5,
    )
    removal50.assert_threshold()
    survival50.assert_threshold()

    removal80, survival80 = await _run_adversarial_corpus(
        graph, "user_quality_forget_adv80", noise_ratio=0.8,
    )
    removal80.assert_threshold()
    survival80.assert_threshold()

    survival, retrieval = await _run_signal_retention_scenario(
        engine, "user_quality_forget_signal",
    )
    survival.assert_threshold()
    retrieval.assert_threshold()

    print(
        f"\n[forgetting-effectiveness] noise_removal={removal50.rate:.3f}/{removal80.rate:.3f} "
        f"signal_survival={survival50.rate:.3f}/{survival80.rate:.3f}/{survival.rate:.3f} "
        f"retrieval={retrieval.rate:.3f} slimming={slimming:.3f}"
    )
