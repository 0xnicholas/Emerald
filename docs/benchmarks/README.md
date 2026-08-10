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
./scripts/run_real_benchmarks.sh
# 依次跑 text-embedding-3-small (1536 dim) 与 text-embedding-3-large (3072 dim)
# 两次结果合并为每维度两列对照的 Markdown 报告到 docs/benchmarks/
# 3-large 跑失败时自动回退单列报告，不会整体中断
```

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

- [Mock 嵌入基线](./mock-results.md)（CI 基线）
- [真实 LLM 嵌入跑分](./real-llm-results.md)（首次真实嵌入）
- [真实 LLM + DeepSeek 关系分类](./real-llm-deepseek-results.md)

## 已知局限

- Mock 嵌入无语义能力，Fact Recall / Distractor 维度得分偏低（~10-20%）
- 真实 LLM 跑分需要付费 API key
- 基准不覆盖：多模态摄入性能、跨语言能力、图谱规模 > 100k 节点
