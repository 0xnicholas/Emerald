"""Quality suite section 3 — graph relationship precision (ADR-0001, ticket #11).

Scenarios (roadmap M2):
- type classification: UPDATES / EXTENDS / NONE judged correctly on a
  labelled corpus
- direction & semantics: UPDATES edges point new -> old, replaced_by is
  recorded, relation properties are correct
- atomicity: the UPDATES invariant (edge exists <=> target archived with
  replaced_by = source) holds under every mutation, with zero violations
- cross-entity isolation: no relationships or retrieval leakage across
  entities

Metrics and thresholds (all must pass for the suite to be green):
- type classification accuracy >= 95%
- direction correctness       >= 98%
- atomicity violation rate    =  0%
- cross-entity leakage rate   =  0%

Deterministic labelled corpus, rule-only path (use_llm=False).
"""

from __future__ import annotations

import pytest

from emerald.core.relationship import RelationshipEngine, RelationType

pytestmark = [pytest.mark.quality]

# ---------------------------------------------------------------------------
# Labelled corpus: (new, old, expected) — 61 deterministic examples.
# ---------------------------------------------------------------------------

CLASSIFICATION_CORPUS = [
    # UPDATES: structure / numeric / contradiction / temporal-completion.
    ("用户在 Google 工作", "用户在 Stripe 工作", RelationType.UPDATES),
    ("用户在上海工作", "用户在北京工作", RelationType.UPDATES),
    ("用户用 Rust 写代码", "用户用 Python 写代码", RelationType.UPDATES),
    ("用户体重 65kg", "用户体重 70kg", RelationType.UPDATES),
    ("用户存款 20万元", "用户存款 10万元", RelationType.UPDATES),
    ("用户今年 31岁", "用户今年 30岁", RelationType.UPDATES),
    ("产品涨价 8%", "产品涨价 5%", RelationType.UPDATES),
    ("用户搬到旧金山", "用户住在西雅图", RelationType.UPDATES),
    ("用户不再喝咖啡", "用户喜欢喝咖啡", RelationType.UPDATES),
    ("用户不喜欢吸烟", "用户喜欢吸烟", RelationType.UPDATES),
    ("明天的考试取消了", "明天有考试", RelationType.UPDATES),
    ("产品会议取消了", "下周开产品会议", RelationType.UPDATES),
    ("用户改用 Puma 运动鞋", "用户喜欢 Adidas 运动鞋", RelationType.UPDATES),
    ("用户年薪 50万", "用户年薪 30万", RelationType.UPDATES),
    ("产品定价 120元", "产品定价 100元", RelationType.UPDATES),
    ("用户每天跑 8km", "用户每天跑 5km", RelationType.UPDATES),
    ("用户离职了", "用户在 Google 工作", RelationType.UPDATES),
    ("用户现在有对象了", "用户是单身", RelationType.UPDATES),
    ("项目预算 150万元", "项目预算 100万元", RelationType.UPDATES),
    ("用户换了 Android 手机", "用户用 iPhone", RelationType.UPDATES),
    ("明天的出差取消了", "明天要出差", RelationType.UPDATES),
    ("公司搬到了杭州", "公司在深圳", RelationType.UPDATES),
    ("会议刚改到周三", "会议安排在周一", RelationType.UPDATES),
    ("用户现在 75kg", "用户体重 80kg", RelationType.UPDATES),
    ("产品的发布已完成", "下个月发布产品", RelationType.UPDATES),
    # EXTENDS: complementary detail on the same subject.
    ("用户用 Python 写数据管线", "用户喜欢 Python", RelationType.EXTENDS),
    ("用户住在北京朝阳区", "用户住在北京", RelationType.EXTENDS),
    ("用户在 Stripe 领导支付团队", "用户在 Stripe 工作", RelationType.EXTENDS),
    ("用户喜欢喝现磨的咖啡", "用户喜欢喝咖啡", RelationType.EXTENDS),
    ("用户每天早晨跑 5km", "用户每天跑步", RelationType.EXTENDS),
    ("用户用 MacBook 开发后端服务", "用户用 MacBook", RelationType.EXTENDS),
    ("用户用 TypeScript 写前端", "用户喜欢 TypeScript", RelationType.EXTENDS),
    ("用户在学日语准备 JLPT N2", "用户在学日语", RelationType.EXTENDS),
    ("用户的猫叫米粒", "用户养了一只猫", RelationType.EXTENDS),
    ("用户喜欢周末去爬香山", "用户喜欢爬山", RelationType.EXTENDS),
    ("用户在阿里做云计算业务", "用户在阿里工作", RelationType.EXTENDS),
    ("用户喜欢喝龙井茶", "用户喜欢喝茶", RelationType.EXTENDS),
    ("用户常在健身房练力量", "用户常去健身房", RelationType.EXTENDS),
    ("用户用 VS Code 写 Python", "用户用 VS Code", RelationType.EXTENDS),
    ("用户喜欢看科幻电影", "用户喜欢看电影", RelationType.EXTENDS),
    ("用户读的是计算机博士", "用户在读博士", RelationType.EXTENDS),
    ("用户喜欢做川菜", "用户喜欢做菜", RelationType.EXTENDS),
    ("用户用 Notion 管理项目", "用户用 Notion 记笔记", RelationType.EXTENDS),
    # NONE: unrelated facts.
    ("用户喜欢 Python", "明天北京天气晴", RelationType.NONE),
    ("用户住在北京", "公司发布了新产品", RelationType.NONE),
    ("用户每天跑步", "汇率今天又跌了", RelationType.NONE),
    ("用户用 MacBook", "邻居家新养了条狗", RelationType.NONE),
    ("用户在学日语", "iPhone 发布了新款", RelationType.NONE),
    ("用户养了一只猫", "会议改到了下午三点", RelationType.NONE),
    ("用户喜欢爬山", "油价上涨了 5%", RelationType.NONE),
    ("用户朋友在读书", "公司在阿里招人", RelationType.NONE),
    ("用户喜欢喝茶", "超市在搞促销活动", RelationType.NONE),
    ("用户常去健身房", "飞机晚点了两个小时", RelationType.NONE),
    ("用户用 VS Code", "今年冬天会很冷", RelationType.NONE),
    ("用户喜欢看电影", "股票账户又亏钱了", RelationType.NONE),
    ("用户在读博士", "小区门口在修路", RelationType.NONE),
    ("用户喜欢做菜", "快递明天才能送到", RelationType.NONE),
    ("用户用 Notion 记笔记", "世界杯马上就要开始了", RelationType.NONE),
    ("用户每天跑 5km", "晚饭吃了火锅", RelationType.NONE),
    ("用户在 Stripe 工作", "热水器坏了需要维修", RelationType.NONE),
    ("用户喜欢喝咖啡", "这个月电费账单出来了", RelationType.NONE),
]


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


# ---------------------------------------------------------------------------
# Scenario 1 — type classification on the labelled corpus
# ---------------------------------------------------------------------------


async def _run_classification_scenario(rel: RelationshipEngine) -> Metric:
    """61 labelled pairs must be classified exactly as labelled."""
    metric = Metric("type_classification_accuracy", 0.95)
    for idx, (new, old, expected) in enumerate(CLASSIFICATION_CORPUS):
        result = await rel.classify_relation(
            f"new_{idx}", f"old_{idx}", f"entity_{idx}", new, old,
        )
        ok = result == expected
        metric.record(ok)
        assert ok, (
            f"Classification mismatch: {old!r} -> {new!r} "
            f"expected={expected.value!r} got={result.value!r}"
        )
    return metric


# ---------------------------------------------------------------------------
# Scenario 2 — direction & semantics of created relationships
# ---------------------------------------------------------------------------


async def _run_direction_scenario(graph) -> Metric:
    """UPDATES points new -> old; replaced_by recorded; EXTENDS keeps both."""
    metric = Metric("direction_correctness", 0.98)
    entity = "user_quality_graph_direction"

    update_pairs = [
        ("用户在 Google 工作", "用户在 Stripe 工作"),
        ("用户不再喝咖啡", "用户喜欢喝咖啡"),
        ("用户体重 65kg", "用户体重 70kg"),
        ("用户搬到旧金山", "用户住在西雅图"),
        ("明天的考试取消了", "明天有考试"),
        ("用户改用 Puma 运动鞋", "用户喜欢 Adidas 运动鞋"),
        ("用户年薪 50万", "用户年薪 30万"),
        ("产品定价 120元", "产品定价 100元"),
        ("用户离职了", "用户在 Google 工作"),
        ("公司搬到了杭州", "公司在深圳"),
        ("用户换了 Android 手机", "用户用 iPhone"),
        ("产品会议取消了", "下周开产品会议"),
        ("会议刚改到周三", "会议安排在周一"),
        ("用户现在有对象了", "用户是单身"),
        ("用户现在 75kg", "用户体重 80kg"),
        ("产品的发布已完成", "下个月发布产品"),
        ("项目预算 150万元", "项目预算 100万元"),
        ("用户每天跑 8km", "用户每天跑 5km"),
        ("用户存款 20万元", "用户存款 10万元"),
        ("用户今年 31岁", "用户今年 30岁"),
    ]

    for _idx, (new_content, old_content) in enumerate(update_pairs):
        old_id = await graph.create_memory(
            old_content, entity_id=entity, confidence=0.8,
        )
        new_id = await graph.create_memory(
            new_content, entity_id=entity, confidence=0.8,
        )
        await graph.create_update_relation(
            new_id, old_id,
            properties={"reason": "contradiction", "confidence": 0.8},
        )

        old = await graph.get_memory(old_id)
        new = await graph.get_memory(new_id)
        ok = (
            old is not None and old["is_latest"] is False
            and old.get("replaced_by") == new_id
            and new is not None and new["is_latest"] is True
        )
        rels = (old or {}).get("relationships", [])
        ok = ok and any(
            r.get("type") == "UPDATES"
            and r.get("from_id") == new_id
            and r.get("reason") == "contradiction"
            for r in rels
        )
        metric.record(ok)
        assert ok, f"UPDATES direction wrong for {old_content!r} -> {new_content!r}"

    # EXTENDS: both stay latest, edge has aspect property.
    old_ext = await graph.create_memory("用户喜欢 Python", entity_id=entity)
    new_ext = await graph.create_memory(
        "用户用 Python 写数据管线", entity_id=entity,
    )
    await graph.create_relationship(
        new_ext, old_ext, "EXTENDS", properties={"aspect": "detail"},
    )
    old_ext_mem = await graph.get_memory(old_ext)
    assert old_ext_mem is not None and old_ext_mem["is_latest"] is True
    ext_rels = old_ext_mem.get("relationships", [])
    ok = any(
        r.get("type") == "EXTENDS"
        and r.get("from_id") == new_ext
        and r.get("aspect") == "detail"
        for r in ext_rels
    )
    metric.record(ok)
    assert ok, "EXTENDS relation missing or wrong direction"

    return metric


# ---------------------------------------------------------------------------
# Scenario 3 — atomicity: the UPDATES invariant holds with zero violations
# ---------------------------------------------------------------------------


async def _scan_update_invariant(graph, entity_ids: list[str]) -> int:
    """Count UPDATES edges whose target is not archived-and-linked (violations).

    Invariant: every UPDATES edge (from -> to) must have
    to.is_latest == False and to.replaced_by == from.
    """
    violations = 0
    for entity in entity_ids:
        for m in graph._memories.get(entity, []):
            for rel in m.get("relationships", []):
                if rel.get("type") != "UPDATES":
                    continue
                from_id = rel.get("from_id")
                target = await graph.get_memory(m["id"])
                if target is None:
                    violations += 1
                    continue
                if target["is_latest"] is True or target.get("replaced_by") != from_id:
                    violations += 1
    return violations


async def _run_atomicity_scenario(graph) -> Metric:
    """Edge cases must never break the UPDATES invariant (violations = 0)."""
    metric = Metric("atomicity_violation_rate", 1.0)  # 100% clean required
    entity = "user_quality_graph_atomic"

    # Normal update.
    a1 = await graph.create_memory("用户喜欢喝茶", entity_id=entity)
    b1 = await graph.create_memory("用户不再喝茶", entity_id=entity)
    await graph.create_update_relation(b1, a1)

    # Update on an already-archived target: must be a no-op (no new edge).
    b2 = await graph.create_memory("用户喜欢喝白水", entity_id=entity)
    await graph.create_update_relation(b2, a1)
    a1_mem = await graph.get_memory(a1)
    updates_to_a1 = [
        r for r in a1_mem.get("relationships", [])
        if r.get("type") == "UPDATES"
    ]
    assert len(updates_to_a1) == 1, (
        f"Archived target received a second UPDATES edge: {updates_to_a1}"
    )

    # Update with a missing target: no-op, nothing raised.
    await graph.create_update_relation(b2, "nonexistent_id")

    # Update with a missing source: target untouched.
    a3 = await graph.create_memory("用户住在北京", entity_id=entity)
    await graph.create_update_relation("nonexistent_source", a3)
    a3_mem = await graph.get_memory(a3)
    assert a3_mem["is_latest"] is True

    # Multi-step chain A -> B -> C: each step archives exactly its target.
    chain_a = await graph.create_memory("用户体重 80kg", entity_id=entity)
    chain_b = await graph.create_memory("用户体重 75kg", entity_id=entity)
    chain_c = await graph.create_memory("用户体重 70kg", entity_id=entity)
    await graph.create_update_relation(chain_b, chain_a)
    await graph.create_update_relation(chain_c, chain_b)
    chain_a_mem = await graph.get_memory(chain_a)
    chain_b_mem = await graph.get_memory(chain_b)
    assert chain_a_mem["replaced_by"] == chain_b
    assert chain_b_mem["replaced_by"] == chain_c
    a_rels = [r for r in chain_a_mem.get("relationships", []) if r.get("type") == "UPDATES"]
    b_rels = [r for r in chain_b_mem.get("relationships", []) if r.get("type") == "UPDATES"]
    assert len(a_rels) == 1 and a_rels[0]["from_id"] == chain_b
    assert len(b_rels) == 1 and b_rels[0]["from_id"] == chain_c

    violations = await _scan_update_invariant(graph, [entity])
    metric.record(violations == 0)
    assert violations == 0, f"UPDATES invariant violated {violations} times"

    return metric


# ---------------------------------------------------------------------------
# Scenario 4 — cross-entity isolation
# ---------------------------------------------------------------------------


async def _run_isolation_scenario(engine) -> Metric:
    """Identical content in two entities never leaks across the boundary."""
    metric = Metric("cross_entity_leakage_rate", 1.0)  # 0% leakage required
    entity_a = "user_quality_graph_iso_a"
    entity_b = "user_quality_graph_iso_b"

    await engine.add("用户喜欢 Python", entity_id=entity_a)
    await engine.add("用户喜欢 Python", entity_id=entity_b)
    await engine.add("用户不再喜欢 Python", entity_id=entity_a)

    # A's own update chain archives A's copy — that is legitimate.
    a_mems = engine.graph._memories.get(entity_a, [])
    a_latest = [m for m in a_mems if m["is_latest"]]
    assert len(a_latest) == 1 and a_latest[0]["content"] == "用户不再喜欢 Python"

    # B's copy must be untouched: still latest, no relationships at all.
    b_mems = engine.graph._memories.get(entity_b, [])
    b_latest = [m for m in b_mems if m["is_latest"]]
    ok = (
        len(b_mems) == 1
        and len(b_latest) == 1
        and b_latest[0]["content"] == "用户喜欢 Python"
        and not b_latest[0].get("relationships")
    )
    metric.record(ok)
    assert ok, "Entity B memory was touched by Entity A's update"

    # Retrieval isolation: searching A must never return B's memory.
    from emerald.core.search import SearchMode, SearchOrchestrator

    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )
    results_a = await orchestrator.search(
        "用户喜欢 Python", entity_id=entity_a,
        search_mode=SearchMode.MEMORY, top_k=10,
    )
    b_id = b_latest[0]["id"]
    ok = ok and all(r.id != b_id for r in results_a.results)
    metric.record(ok)
    assert ok, "Entity B memory leaked into Entity A's search results"

    return metric


# ---------------------------------------------------------------------------
# Aggregate gate
# ---------------------------------------------------------------------------


async def test_graph_relationship_precision_metrics(engine, graph) -> None:
    """Aggregate gate: all four metrics must meet their thresholds."""
    rel = RelationshipEngine(graph=graph, vector=engine.vector, use_llm=False)

    classification = await _run_classification_scenario(rel)
    classification.assert_threshold()

    direction = await _run_direction_scenario(graph)
    direction.assert_threshold()

    atomicity = await _run_atomicity_scenario(graph)
    atomicity.assert_threshold()

    isolation = await _run_isolation_scenario(engine)
    isolation.assert_threshold()

    print(
        f"\n[graph-relationship-precision] classification={classification.rate:.3f} "
        f"direction={direction.rate:.3f} atomicity={atomicity.rate:.3f} "
        f"isolation={isolation.rate:.3f}"
    )
