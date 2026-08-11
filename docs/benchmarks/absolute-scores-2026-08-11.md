# Emerald 绝对分报告

**日期:** 2026-08-11（主跑分时间戳）

**模型:** BAAI/bge-m3 (1024 dims)

**对比基线:** mock 嵌入（`docs/benchmarks/mock-baseline.json`，双门槛同源）

## Summary

| Model | Pass rate | Aggregate score |
|---|---|---|
| BAAI/bge-m3 | 7/7 = 100.0% | 0.943 |

## 每维度三列对比

| Dimension | BAAI/bge-m3 | — | Mock 基线 | Δ |
|---|---|---|---|---|
| Fact Recall | 0.933 | — | 0.167 | +0.766 |
| Temporal Updates | 1.000 | — | 1.000 | +0.000 |
| Relationship Classification | 1.000 | — | 1.000 | +0.000 |
| Profile Accuracy | 0.750 | — | 0.750 | +0.000 |
| Distractor Resistance | 0.600 | — | 0.200 | +0.400 |
| Forgetting Correctness | 1.000 | — | 1.000 | +0.000 |
| Contradiction Chain | 1.000 | — | 1.000 | +0.000 |

Δ = 模型分数 − mock 基线分数。

## 双门槛结论

| 模型 | 发布门槛（每维 ≥ mock 基线） | 通过门槛（矛盾链 ≥ 80% 且 7 维等权均分 ≥ 70%） |
|---|---|---|
| BAAI/bge-m3 | ✅ 通过 | ✅ 通过 |

> ⚠️ 第二模型（text-embedding-3-large 对照）跑分缺失，未评估其门槛。

发布门槛：全部维度 ≥ mock 基线。

通过门槛明细：

- BAAI/bge-m3: 矛盾链 1.000 / 0.800 · 等权均分 0.898 / 0.700

## 矛盾链维度说明

**Contradiction Chain**（第 7 维度，issue #17 T1）：多轮取代对抗场景，5 条链 × 5 轮连续取代，每轮对同一实体的事实写入完全矛盾的新事实（结构模板换填充 / 数值变更 / 矛盾措辞三类语料，规则分类器在 mock 下确定性输出 UPDATES）。每轮验证：旧事实 `is_latest` 翻转为 False 且 `replaced_by` 指向新事实、UPDATES 边由新指向旧、最新事实按精确文本查询命中 top-1、过期事实不再被召回。指标：`latest_recall@1` / `expired_exclusion_rate` / `is_latest_flip_rate` / `update_relation_rate` / `overall_accuracy`。

## 独立侧套件与依据

- **独立侧套件**（ADR-0001）：`tests/quality/temporal/`（`test_temporal_correctness.py` / `test_forgetting_effectiveness.py` / `test_graph_relationship_precision.py` / `test_neo4j_quality_variants.py`）——独立于本报告语料与指标，互不背书。

- **ADR-0001**（[度量体系：绝对分与独立侧套件](../adr/0001-metrics-absolute-scores-and-independent-suites.md)）：绝对分只对自己负责，Emerald 不背书参照系的基准声明。

