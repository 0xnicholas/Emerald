"""Quality suite section 1 — temporal correctness (ADR-0001, ticket #9).

Scenarios (roadmap M2):
- update chains: a new fact replaces an old fact (UPDATES + is_latest=False)
- time expiry: valid_until-passed memories are suppressed from retrieval
- explicit conflict triage: high-impact contradictions go to PENDING_CONFLICT
  instead of silent auto-overwrite
- retention: unrelated/valid facts are preserved

Metrics and thresholds (all must pass for the suite to be green):
- replacement correctness  >= 99%
- expiry suppression       >= 99%
- retention correctness    >= 98%
- triage accuracy          >= 95%

Deterministic corpus, rule-only path (use_llm=False), mock embeddings.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.conflict import ConflictEngine, ResolutionAction
from emerald.core.forget import ForgetEngine
from emerald.core.search import SearchMode, SearchOrchestrator

pytestmark = [pytest.mark.quality]

# ---------------------------------------------------------------------------
# Deterministic corpus: (new, old) — new replaces old.
# ---------------------------------------------------------------------------

UPDATE_CORPUS = [
    ("用户在 Google 工作", "用户在 Stripe 工作"),
    ("用户在上海工作", "用户在北京工作"),
    ("用户用 Rust 写代码", "用户用 Python 写代码"),
    ("用户体重 65kg", "用户体重 70kg"),
    ("用户存款 20万元", "用户存款 10万元"),
    ("用户今年 31岁", "用户今年 30岁"),
    ("产品涨价 8%", "产品涨价 5%"),
    ("用户搬到旧金山", "用户住在西雅图"),
    ("用户不再喝咖啡", "用户喜欢喝咖啡"),
    ("用户不喜欢吸烟", "用户喜欢吸烟"),
    ("明天的考试取消了", "明天有考试"),
    ("产品会议取消了", "下周开产品会议"),
    ("用户改用 Puma 运动鞋", "用户喜欢 Adidas 运动鞋"),
    ("用户年薪 50万", "用户年薪 30万"),
    ("产品定价 120元", "产品定价 100元"),
    ("用户每天跑 8km", "用户每天跑 5km"),
    ("用户离职了", "用户在 Google 工作"),
    ("用户现在有对象了", "用户是单身"),
    ("项目预算 150万元", "项目预算 100万元"),
    ("用户换了 Android 手机", "用户用 iPhone"),
    ("明天的出差取消了", "明天要出差"),
    ("公司搬到了杭州", "公司在深圳"),
    ("会议刚改到周三", "会议安排在周一"),
    ("用户现在 75kg", "用户体重 80kg"),
    ("产品的发布已完成", "下个月发布产品"),
]

# (anchor, unrelated): the anchor must stay latest and relation-free.
RETENTION_CORPUS = [
    ("用户喜欢 Python", "明天北京天气晴"),
    ("用户住在北京", "公司发布了新产品"),
    ("用户养了一只猫", "会议改到了下午三点"),
    ("用户喜欢爬山", "油价上涨了 5%"),
    ("用户用 Notion 记笔记", "世界杯马上就要开始了"),
    ("用户每天跑 5km", "晚饭吃了火锅"),
    ("用户喜欢喝咖啡", "这个月电费账单出来了"),
    ("用户用 MacBook", "邻居家新养了条狗"),
    ("用户在学日语", "iPhone 发布了新款"),
    ("用户常去健身房", "飞机晚点了两个小时"),
]

# Temporal facts whose valid_until is auto-extracted, then forced into the past.
EXPIRY_CORPUS = [
    "明天有考试",
    "后天提交报告",
    "下周面试",
    "下个月搬家",
    "明天交房租",
    "大后天体检",
    "下周还书",
    "下个月续约",
    "明天取快递",
    "后天开会",
    "3天后交论文",
    "5天后出差",
    "下周去医院复查",
    "下个月办签证",
    "明天参加婚礼",
    "后天搬家",
    "下周缴水电费",
    "下个月考驾照",
    "明天做体检",
    "10天后交标书",
]


class Metric:
    """Count pass/fail outcomes; assert the aggregate threshold at the end."""

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


# ---------------------------------------------------------------------------
# Scenario A — update chains replace the old fact
# ---------------------------------------------------------------------------


async def _run_update_chain_case(engine, entity_id, new_content, old_content) -> bool:
    """add(old) then add(new); returns True when the replacement is correct."""
    old_result = await engine.add(old_content, entity_id=entity_id)
    new_result = await engine.add(new_content, entity_id=entity_id)
    if not old_result.memory_ids or not new_result.memory_ids:
        return False

    old_id = old_result.memory_ids[0]
    new_id = new_result.memory_ids[0]

    old = await engine.graph.get_memory(old_id)
    if old is None or old["is_latest"] is not False:
        return False
    if old.get("replaced_by") != new_id:
        return False

    rels = old.get("relationships", [])
    if not any(r.get("type") == "UPDATES" and r.get("from_id") == new_id for r in rels):
        return False

    # Retrieval: the replaced fact must not surface anymore.
    results = await _search(engine, old_content, entity_id)
    return not any(r.content.strip() == old_content.strip() for r in results)


async def _run_update_chain_scenario(engine) -> Metric:
    """25 update pairs: old fact must be archived and hidden from search."""
    metric = Metric("replacement_correctness", 0.99)
    for idx, (new_content, old_content) in enumerate(UPDATE_CORPUS):
        entity = f"user_quality_temporal_update_{idx}"
        ok = await _run_update_chain_case(engine, entity, new_content, old_content)
        metric.record(ok)
        assert ok, (
            f"Update chain failed for ({old_content!r} -> {new_content!r}): "
            "old fact not replaced or still retrievable"
        )
    return metric


# ---------------------------------------------------------------------------
# Scenario B — time expiry suppresses expired memories
# ---------------------------------------------------------------------------


async def _run_expiry_case(engine, entity_id, content) -> bool:
    """add() a temporal fact, backdate its valid_until, expect suppression."""
    result = await engine.add(content, entity_id=entity_id)
    if not result.memory_ids:
        return False
    mid = result.memory_ids[0]

    memory = await engine.graph.get_memory(mid)
    if memory is None or memory.get("valid_until") is None:
        return False  # temporal expression was not extracted

    # Deterministic expiry: force valid_until into the past.
    for m in engine.graph._memories.get(entity_id, []):
        if m["id"] == mid:
            m["valid_until"] = datetime.now(UTC) - timedelta(hours=1)
            break

    forgetter = ForgetEngine(graph=engine.graph)
    await forgetter.forget_expired(entity_id)

    memory = await engine.graph.get_memory(mid)
    if memory is None or memory["is_latest"] is not False:
        return False

    # Retrieval suppression.
    results = await _search(engine, content, entity_id)
    return not any(r.content.strip() == content.strip() for r in results)


async def _run_expiry_scenario(engine) -> Metric:
    """20 expired temporal facts: archived and absent from search results."""
    metric = Metric("expiry_suppression", 0.99)
    for idx, content in enumerate(EXPIRY_CORPUS):
        entity = f"user_quality_temporal_expiry_{idx}"
        ok = await _run_expiry_case(engine, entity, content)
        metric.record(ok)
        assert ok, f"Expiry suppression failed for {content!r}"
    return metric


# ---------------------------------------------------------------------------
# Scenario C — explicit conflict triage
# ---------------------------------------------------------------------------


async def _triage_high_impact(engine, entity_id, new_content, old_content) -> bool:
    """High-impact contradiction must create a PENDING_CONFLICT, not auto-replace."""
    old_id = await engine.graph.create_memory(
        old_content, entity_id=entity_id,
        memory_type="fact", internal_type="decision", confidence=0.95,
    )
    new_id = await engine.graph.create_memory(
        new_content, entity_id=entity_id,
        memory_type="fact", internal_type="decision", confidence=0.95,
    )
    result = await engine.relationships.infer_with_conflicts(
        [new_id], entity_id, require_confirmation_for_high_impact=True,
    )
    if len(result["pending_conflicts"]) != 1:
        return False

    conflict = result["pending_conflicts"][0]
    if conflict["new_memory_id"] != new_id or conflict["old_memory_id"] != old_id:
        return False

    old = await engine.graph.get_memory(old_id)
    if old is None or old["is_latest"] is not True:
        return False  # must NOT have been auto-archived
    rel = await engine.graph.get_relationship_by_property(
        rel_type="PENDING_CONFLICT", key="conflict_id", value=conflict["conflict_id"],
    )
    return rel is not None and rel.get("from_id") == new_id and rel.get("to_id") == old_id


async def _triage_low_impact(engine, entity_id, new_content, old_content) -> bool:
    """Low-impact contradiction must auto-resolve via UPDATES, no pending."""
    old_id = await engine.graph.create_memory(
        old_content, entity_id=entity_id,
        memory_type="fact", confidence=0.7,
    )
    new_id = await engine.graph.create_memory(
        new_content, entity_id=entity_id,
        memory_type="fact", confidence=0.7,
    )
    result = await engine.relationships.infer_with_conflicts(
        [new_id], entity_id, require_confirmation_for_high_impact=True,
    )
    if len(result["pending_conflicts"]) != 0:
        return False

    old = await engine.graph.get_memory(old_id)
    if old is None or old["is_latest"] is not False:
        return False
    return old.get("replaced_by") == new_id


async def _run_triage_scenario(engine) -> Metric:
    """12 contradictions: high-impact → pending, low-impact → auto-update."""
    metric = Metric("triage_accuracy", 0.95)
    for idx, (new_content, old_content) in enumerate(UPDATE_CORPUS[:6]):
        entity = f"user_quality_temporal_conflict_hi_{idx}"
        ok = await _triage_high_impact(engine, entity, new_content, old_content)
        metric.record(ok)
        assert ok, f"High-impact triage failed for ({old_content!r} -> {new_content!r})"

    for idx, (new_content, old_content) in enumerate(UPDATE_CORPUS[6:12]):
        entity = f"user_quality_temporal_conflict_lo_{idx}"
        ok = await _triage_low_impact(engine, entity, new_content, old_content)
        metric.record(ok)
        assert ok, f"Low-impact triage failed for ({old_content!r} -> {new_content!r})"
    return metric


async def _run_resolution_scenario(engine) -> None:
    """Resolution actions (keep_old / keep_new / keep_both / manual) behave."""
    conflict_engine = ConflictEngine(graph=engine.graph)

    entity = "user_quality_temporal_resolve"
    old_id = await engine.graph.create_memory(
        "用户喜欢喝咖啡", entity_id=entity,
        memory_type="fact", internal_type="decision", confidence=0.95,
    )
    new_id = await engine.graph.create_memory(
        "用户不再喝咖啡", entity_id=entity,
        memory_type="fact", internal_type="decision", confidence=0.95,
    )
    conflict_id = await conflict_engine.create_pending_conflict(
        new_id, old_id, impact_score=0.9,
    )
    result = await conflict_engine.resolve(conflict_id, ResolutionAction.KEEP_OLD)
    assert result["status"] == "resolved"
    old = await engine.graph.get_memory(old_id)
    new = await engine.graph.get_memory(new_id)
    assert old is not None and old["is_latest"] is True
    assert new is not None and new["is_latest"] is False
    assert new["replaced_by"] == old_id

    entity2 = "user_quality_temporal_resolve2"
    old2_id = await engine.graph.create_memory(
        "用户喜欢喝咖啡", entity_id=entity2,
        memory_type="fact", internal_type="decision", confidence=0.95,
    )
    new2_id = await engine.graph.create_memory(
        "用户不再喝咖啡", entity_id=entity2,
        memory_type="fact", internal_type="decision", confidence=0.95,
    )
    conflict2_id = await conflict_engine.create_pending_conflict(
        new2_id, old2_id, impact_score=0.9,
    )
    await conflict_engine.resolve(conflict2_id, ResolutionAction.KEEP_NEW)
    old2 = await engine.graph.get_memory(old2_id)
    assert old2 is not None and old2["is_latest"] is False
    assert old2["replaced_by"] == new2_id
    rels = old2.get("relationships", [])
    assert any(
        r.get("type") == "UPDATES" and r.get("from_id") == new2_id for r in rels
    )

    entity3 = "user_quality_temporal_resolve3"
    a_id = await engine.graph.create_memory("事实A", entity_id=entity3)
    b_id = await engine.graph.create_memory("事实B", entity_id=entity3)
    c3 = await conflict_engine.create_pending_conflict(a_id, b_id)
    await conflict_engine.resolve(c3, ResolutionAction.KEEP_BOTH)
    assert (await engine.graph.get_memory(a_id))["is_latest"] is True
    assert (await engine.graph.get_memory(b_id))["is_latest"] is True

    entity4 = "user_quality_temporal_resolve4"
    a4 = await engine.graph.create_memory("事实A4", entity_id=entity4)
    b4 = await engine.graph.create_memory("事实B4", entity_id=entity4)
    c4 = await conflict_engine.create_pending_conflict(a4, b4)
    result4 = await conflict_engine.resolve(c4, ResolutionAction.MANUAL)
    assert result4["status"] == "manual"
    assert (await engine.graph.get_memory(a4))["is_latest"] is True


# ---------------------------------------------------------------------------
# Scenario D — retention: unrelated and valid facts are preserved
# ---------------------------------------------------------------------------


async def _run_retention_case(engine, entity_id, unrelated, anchor) -> bool:
    """Adding an unrelated fact must not archive the anchor fact."""
    await engine.add(anchor, entity_id=entity_id)
    await engine.add(unrelated, entity_id=entity_id)
    anchor_id = None
    for m in engine.graph._memories.get(entity_id, []):
        if m["content"] == anchor:
            anchor_id = m["id"]
            break
    if anchor_id is None:
        return False
    anchor_mem = await engine.graph.get_memory(anchor_id)
    if anchor_mem is None or anchor_mem["is_latest"] is not True:
        return False
    return not anchor_mem.get("relationships")


async def _run_retention_scenario(engine) -> Metric:
    """10 unrelated pairs must be preserved (anchor stays latest, no relations)."""
    metric = Metric("retention_correctness", 0.98)
    for idx, (anchor, unrelated) in enumerate(RETENTION_CORPUS):
        entity = f"user_quality_temporal_retention_{idx}"
        ok = await _run_retention_case(engine, entity, unrelated, anchor)
        metric.record(ok)
        assert ok, f"Retention failed for anchor {anchor!r} vs unrelated {unrelated!r}"
    return metric


async def _run_future_expiry_case(engine) -> bool:
    """Facts with valid_until in the future must survive forget_expired."""
    entity = "user_quality_temporal_retention_future"
    future = datetime.now(UTC) + timedelta(days=30)
    result = await engine.add("下个月有马拉松比赛", entity_id=entity)
    if not result.memory_ids:
        return False
    mid = result.memory_ids[0]
    for m in engine.graph._memories.get(entity, []):
        if m["id"] == mid:
            m["valid_until"] = future
            break

    forgetter = ForgetEngine(graph=engine.graph)
    await forgetter.forget_expired(entity)
    memory = await engine.graph.get_memory(mid)
    return memory is not None and memory["is_latest"] is True


async def _run_retention_future_scenario(engine) -> Metric:
    metric = Metric("retention_correctness", 0.98)
    metric.record(await _run_future_expiry_case(engine))
    return metric


# ---------------------------------------------------------------------------
# Aggregate gate — the section is green only when every metric passes.
# ---------------------------------------------------------------------------


async def test_temporal_correctness_metrics(engine) -> None:
    """Aggregate gate: all four metrics must meet their thresholds."""
    replacement_metric = await _run_update_chain_scenario(engine)
    expiry_metric = await _run_expiry_scenario(engine)
    triage_metric = await _run_triage_scenario(engine)
    retention_metric = await _run_retention_scenario(engine)
    await _run_resolution_scenario(engine)
    future_metric = await _run_retention_future_scenario(engine)

    replacement_metric.assert_threshold()
    expiry_metric.assert_threshold()
    triage_metric.assert_threshold()
    retention_metric.assert_threshold()
    future_metric.assert_threshold()

    print(
        f"\n[temporal-correctness] replacement={replacement_metric.rate:.3f} "
        f"expiry={expiry_metric.rate:.3f} triage={triage_metric.rate:.3f} "
        f"retention={retention_metric.rate:.3f}"
    )
