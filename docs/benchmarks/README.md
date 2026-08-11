# Emerald Memory Benchmarks

## 概览

Emerald 基准测试套件评估记忆系统的 7 个核心维度，对齐 LongMemEval、LoCoMo、ConvoMem 三大公开基准。

## 运行方式

### Mock 嵌入（CI / 快速验证）
```bash
python scripts/run_benchmarks.py
# 7 维度全部跑完，~2 分钟
# 输出 JSON 到 reports/benchmark-*.json
```

### 真实嵌入（需要 API key）
```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.siliconflow.cn/v1"  # 可选：网关（OpenAI 不可达时）
./scripts/run_real_benchmarks.sh
# 依次跑 text-embedding-3-small (1536 dim) 与 text-embedding-3-large (3072 dim)
# 生成 docs/benchmarks/absolute-scores-<date>.md（每维度三列对比 + 双门槛结论）
# 3-large 跑失败时自动回退单列，不会整体中断；
# 中间产物（双列对照、DeepSeek 报告）输出到 gitignored 的 reports/
```

> **2026-08-11 模型口径变更**：发布环境无法直连 api.openai.com，
> 首个绝对分报告改用 **SiliconFlow 网关的 BAAI/bge-m3**（1024 维，中文强）
> 作为真实嵌入模型（`OPENAI_BASE_URL` + `--embedding-model BAAI/bge-m3`）。
> OpenAI 官方 3-small/3-large 双列仍是首选口径，网络可达时按原流程跑。

### 指定嵌入模型
```bash
export OPENAI_API_KEY="sk-..."
python scripts/run_benchmarks.py --real --embedding-model text-embedding-3-large
# 未指定时默认 text-embedding-3-small，行为与现状一致
# 维度自动映射：3-small → 1536，3-large → 3072（写入报告 config）
```

### 真实 LLM 关系分类
```bash
export DEEPSEEK_API_KEY="sk-..."
python scripts/run_benchmarks.py --real --llm
```

## 7 个维度

| 维度 | 对齐基准 | 数据规模 |
|---|---|---|
| Fact Recall | LongMemEval Info Extraction | 100 facts → 30 queries |
| Temporal Updates | LongMemEval Knowledge Updates | 10 timelines × 5 steps |
| Relationship Class | 自定义 | 18 pairs |
| Profile Accuracy | LoCoMo persona | 20 facts |
| Distractor Resist | LoCoMo/ConvoMem | 5 targets + 50 noise |
| Forgetting Correct | 自定义 | 10 mixed facts |
| Contradiction Chain | 自定义（Temporal Updates 深度） | 5 chains × 5 supersession rounds |

## 已发布的报告

- [Mock 嵌入基线](./mock-baseline.json) — 已入库对比基线，双门槛评估（发布门槛 / 通过门槛）同源；由维护者按需更新（`python scripts/run_benchmarks.py --mock` 后 `cp reports/benchmark-<ts>.json docs/benchmarks/mock-baseline.json`）
- [绝对分报告 2026-08-11](./absolute-scores-2026-08-11.md) — BAAI/bge-m3（SiliconFlow 网关）真实嵌入，7/7 维度通过，Aggregate 0.943，双门槛均通过；附 2026-08-11 基准与关系推断缺陷修复记录

绝对分报告按日期命名入库（`absolute-scores-<YYYY-MM-DD>.md`，可多期共存、可回溯），由维护者手动跑真实嵌入后提交：

1. `export OPENAI_API_KEY="sk-..."`（可选 `DEEPSEEK_API_KEY="sk-..."`）
2. `./scripts/run_real_benchmarks.sh` — 生成 `docs/benchmarks/absolute-scores-<date>.md`（每维度 3-small / 3-large / mock 基线三列 + 双门槛结论）
3. 审阅报告与门槛结论，`git add` 提交，并把链接加进本节

> 历史死链已移除（issue #20）：`mock-results.md` / `real-llm-results.md` / `real-llm-deepseek-results.md` 三个文件从未入库（CI 每轮 mock 跑分都会重新生成 `mock-results.md`，但从不提交），其链接已删除；中间产物统一由 CI 与脚本输出到 gitignored 的 `reports/`，`docs/benchmarks/` 只保留可回溯的入库基线与日期命名报告。

## 已知局限

- Mock 嵌入无语义能力，Fact Recall / Distractor 维度得分偏低（~10-20%）
- 真实 LLM 跑分需要付费 API key
- 基准不覆盖：多模态摄入性能、跨语言能力、图谱规模 > 100k 节点
