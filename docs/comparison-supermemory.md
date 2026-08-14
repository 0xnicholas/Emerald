# Emerald vs Supermemory 深度对比

> **更新日期：2026-06-21（v2 重写），基于 Emerald 当前 HEAD（b301cfa）与 Supermemory 公开文档/API**
>
> **2026-08-14 增补（B3 NER + B4 多跳完成）**：§1.3 的 NER 差距已由 B3（issue #21–#28，提及节点 + ADR-0005）交付；§2 的深度=1 限制已由 B4（issue #29–#35，`search(..., about=, depth=)` 多跳推理）解除；§10 的 P2 NER / P3 多跳两项标记完成。差距矩阵与优先路径相应更新，其余章节保持 06-21 原状。
>
> **对比基线**：Supermemory 公开能力 + Emerald 源码。注：早期引用的 `reports/benchmark-20260615-*.json` 运行报告**从未纳入版本库**；2026-08-09 起按 ADR-0001，基准改为「合成对抗场景 + 真实嵌入绝对分」并承诺公开入库。
>
> **变更摘要**：相比 2026-06-09 的 v1 版本，Emerald 在 12 天内通过 33 个提交完成了**三项 P0 致命差距中两项的实质性修复**。本文档重写差距矩阵、优先路径与结论。

---

## 总览：从「架构正确但实现浅层」到「核心能力已对齐，仍缺生态与生产化打磨」

| 维度 | Emerald（v0.3.0+ 当前 HEAD） | Supermemory | 差距状态 |
|---|---|---|---|
| **版本** | v0.3.0（HEAD b301cfa，33 commits after 0.3.0 release） | v4 生产级 | 🟡 版本号差异缩小中 |
| **事实提取** | ✅ **已实现** DeepSeek V4-Flash LLM 驱动（多事实分解、类型分类、置信度评分、summary） | ✅ LLM 驱动 | 🟢 **已对齐** |
| **关系推断** | ✅ LLM-first + bigram 预滤 + 规则降级 | ✅ LLM 驱动语义理解 | ✅ 已对齐 |
| **NER 实体抽取层** | ✅ **已实现**（B3，issue #21–#28）：提及（Mention）节点，实体隔离，`(entity_id, 规范形式, 类型)` 去重，表层别名累积，质量套件 4a 节 | ✅ 实体理解 | 🟢 **已对齐** |
| **图谱搜索** | ✅ **已实现** 多跳图谱推理（B4，issue #29–#35）：`about=` 实体中心检索（跨表层形式）+ 共享主体 MENTIONS 桥 + UPDATES/EXTENDS/DERIVES_FROM 双向链式遍历（depth ≤ 4，默认 0）+ 路径/深度透明 + 历史节点标记 | ✅ Relationship Expansion | 🟢 **Emerald 深度优势** |
| **首选项强化** | ✅ **已实现** `_strengthen_preferences()`（重复偏好 +0.05 置信度，上限 0.95） | ✅ 重复提及增强 | 🟢 **已对齐** |
| **记忆类型自动检测** | ✅ **已实现** fact/preference/episodic 三类自动分类（LLM 提取阶段） | ✅ 类型检测 | 🟢 **已对齐** |
| **元数据过滤** | ✅ MongoDB 风格（`$and`/`$or`/`$gte`/`$lte`/`$eq`/`$ne`） | ✅ 复杂过滤 | 🟢 已对齐 |
| **批量写入** | ✅ `POST /v1/memories/batch`（最多 50 条） | ✅ | 🟢 已对齐 |
| **图谱可视化** | ✅ `GET /v1/memories/graph`（节点+边） | ✅ | 🟢 已对齐 |
| **基准测试** | ✅ 6 维度 / 1154 行 / JSON 报告；真实嵌入绝对分已发布（bge-m3，Aggregate 0.943，7/7 通过——第二模型对照待补） | ✅ LongMemEval/LoCoMo/ConvoMem 公开分数 | 🟡 跑分存在但需真实 LLM |
| **本地嵌入** | ✅ **新** fastembed（ONNX，无 PyTorch） | ❌ 仅云端 | 🟢 **Emerald 优势** |
| **双写一致性** | ✅ **新** ReconciliationEngine（后台修复孤立节点） | ✅ | 🟢 已对齐 |
| **生产级 Dockerfile** | ❌ 仍从 development 阶段拷贝 site-packages | ✅ 多阶段独立构建 | 🔴 仍存在 |
| **TypeScript SDK** | ❌ 仍仅 Python SDK | ✅ 完整 TS SDK | 🔴 仍存在 |
| **框架集成生态** | 🟡 仅 Pandaria（Rust） | ✅ LangChain/Mastra/OpenAI/Vercel AI/CrewAI/n8n… | 🔴 仍存在 |
| **消费者产品** | ❌ 无 | ✅ Web App/浏览器插件/Raycast/Nova Agent | 🟢 定位不同（B2B vs B2C） |
| **v2 API 实质改进** | ❌ 仍为 v1 别名（每文件一行 `from v1.xxx import router`） | ✅ v3→v4 持续演进 | 🔴 仍存在 |
| **SDK 幂等** | 🟡 Redis 缓存 idempotency_key（1h TTL） | ✅ `customId` 原生 | 🟡 |
| **CORS 生产加固** | ✅ 已实现（基于环境变量，区分 wildcard 与严格模式） | ✅ | 🟢 已对齐 |

---

## 1. 事实提取 —— 从「致命差距」到「已对齐」✅

这是 v0.3.0 之后**变化最大**的领域。原文档结论为「Emerald 仅做内容类型转换，无 LLM 事实提取」——**这一结论现已被彻底反转**。

### 1.1 现状（HEAD b301cfa）

`emerald/pipeline/chunking/fact_extractor.py`（222 行）实现了完整的 LLM 事实提取管道：

```python
class DeepSeekFactExtractor(FactExtractor):
    """Fact extraction via DeepSeek V4-Flash (OpenAI-compatible API)."""

    VALID_TYPES = frozenset({"fact", "preference", "episodic"})

    async def extract(self, text: str, *, entity_context: str | None = None):
        # system prompt guides LLM to:
        #   - Split text into 1-2 sentence atomic facts
        #   - Classify each: fact / preference / episodic
        #   - Score confidence (0.0-1.0)
        #   - Generate 1-sentence summary (search/profile display)
        #   - Return strict JSON: {"facts": [{text, type, confidence, summary}, ...]}
        # Graceful fallback: API fail / JSON parse fail / empty input → []
```

**关键设计决策**：
- **可选注入**：`get_fact_extractor()` 在无 API key 时返回 `None`，引擎走无提取降级路径——保持向后兼容
- **Entity context 支持**：`extract(text, entity_context="Alex 是 PM")` 可引导 LLM 关注特定实体
- **强类型校验**：`memory_type` 必须在 `{fact, preference, episodic}`，否则降级为 `fact`
- **去重**：`seen_texts` 集合基于 normalized text 去重
- **优雅降级链**：API 异常 → JSON 解析失败 → 剥离 markdown 代码围栏 → 重试 → 最终返回 `[]`

### 1.2 与 Supermemory 对齐点

| 能力 | Supermemory | Emerald |
|---|---|---|
| 多事实分解 | ✅ | ✅ |
| 类型自动分类 | ✅ | ✅ |
| 置信度评分 | ✅ | ✅ |
| Summary 生成 | ✅ | ✅ |
| Entity context 引导 | ✅ `entityContext` 参数 | ✅ `entity_context` 参数 |
| 优雅失败 | ✅ | ✅（返回空列表，引擎跳过 LLM 步骤） |

### 1.3 仍存在的次要差距

- ~~**未实现**：NER（命名实体识别）~~ ✅ **已交付**（2026-08，B3 issue #21–#28）：提取后解析提及（Mention）图节点（ADR-0005），`(entity_id, 规范形式, 类型)` 去重、表层别名累积、封闭类型分类法与置信度门槛，UPDATES 保留历史提及、遗忘剪除孤立节点；确定性质量套件 `tests/quality/mentions/` 回归保护。
- **未实现**：细粒度实体链接（entity linking）—— 提及节点是实体引用（谈论对象），但不与外部知识库 ID 对齐（如 Wikidata）。B3 定界：跨实体提及合并永久 out。
- **token 成本**：DeepSeek V4-Flash 成本低于 OpenAI，但仍是按调用计费

---

## 2. 搜索 —— 从「关键缺失」到「已对齐」到「图谱深度优势」✅

### 2.1 现状（2026-08-14 增补：B4 多跳图谱推理）

`emerald/core/search.py` 的 `search(..., about=, depth=)` 在原有深度=1 的 `_expand_relationships()`（EXTENDS/DERIVES_FROM 双向、0.85 折扣，保留为 depth=0 现状语义）之上，新增了多跳遍历引擎（`emerald/core/multihop.py`）：

- **实体中心检索**：`about=<规范形式或提及 id>` 返回实体上下文池内提及该事物的全部最新记忆，跨所有表层形式（「谷歌」「GOOGLE」→ Google 同一提及节点，B3 解析语义）；纯图谱操作，不经向量相似度。
- **共享主体串联**：`Memory-MENTIONS->Mention<-MENTIONS-Memory`——同一实体内提及同一事物的记忆互为兄弟节点。
- **关系链式**：沿 UPDATES/EXTENDS/DERIVES_FROM **双向**行走，depth ≥ 2 链式（D2 推导自 D1 推导自 A → 查 A 时 D2 以 depth 2 浮现）；每跳实体隔离。
- **历史节点**：is_latest=False 仅在沿 UPDATES 被踩到时浮出并标记，从不主动搜历史、从不穿越历史。
- **路径透明**：每个多跳结果携带 `path`（经过的节点/边）与 `depth`（跳数）——Agent 可解释「为什么返回这条」。
- **深度语义**：`depth` 默认 0（现状不变），显式 opt-in；上限 4（REST `le=4` + 引擎 clamp）。
- **环路安全**：visited 集合，浅层深度优先，不重复不死亡循环（质量套件 5e 节）。

配套 `GraphStore` 遍历接缝：`get_memories_mentioning` / `get_memory_mentions`（提及桥，实体作用域）与 `get_relationship_neighbors`（关系邻接双向读取，含边类型/方向/实体/历史状态），Cypher + 内存双实现；质量套件 `tests/quality/multihop/`（63 项含 Neo4j 变体）回归保护。

### 2.2 与 Supermemory 对齐点

| 能力 | Supermemory | Emerald |
|---|---|---|
| 向量搜索起点 | ✅ | ✅ |
| EXTENDS 扩展 | ✅ | ✅（深度 1 现状 + 多跳 depth ≤ 4） |
| DERIVES 扩展 | ✅ | ✅（深度 1 现状 + 链式 depth ≥ 2） |
| 分数折扣 | ✅ | ✅（`expansion_factor=0.85` + 多跳 0.85^depth） |
| 防结果膨胀 | ✅ | ✅（截断到 `top_k * 2` + top_k 合并） |
| 实体中心检索 | — | ✅ **Emerald 优势**（`about=`，跨表层形式） |
| 多跳路径解释 | — | ✅ **Emerald 优势**（每结果 path + depth） |

### 2.3 深度限制说明（已解除）

~~当前实现仅支持深度 = 1。~~ 2026-08 B4（issue #29–#35）交付后：深度是 `search(..., depth=N)` 的参数（0 默认 = 现状，上限 4），支持 UPDATES/EXTENDS/DERIVES_FROM 双向链式遍历与共享主体桥接；每一跳实体隔离，历史节点仅在 UPDATES 链上浮出。多跳结果的路径解释与跳数标注已进 REST/SDK（issue #33）。

---

## 3. 关系推断 —— 已对齐 ✅

### 3.1 现状

`emerald/core/relationship.py:109-160` 实现了两阶段分类：

```python
async def classify_relation(self, new_content: str, old_content: str):
    """Classify relationship between new and existing memory.

    Two-stage approach:
    1. Rule-based classification (structural templates, negation detection)
    2. LLM-based semantic classification (when rules are inconclusive)

    LLM_CONFIDENCE_THRESHOLD = 0.7
    """
    # Stage 1: rule classify
    rule_result = self._rule_classify(new_content, old_content)
    if rule_result != RelationType.NONE:
        return rule_result

    # Stage 2: LLM classify (DeepSeek preferred, OpenAI fallback)
    if settings.deepseek_api_key or settings.openai_api_key:
        return await self._llm_classify(new_content, old_content)

    return RelationType.NONE
```

### 3.2 基准分数（mock 嵌入，2026-06-15 运行；报告未入库，分数按 ADR-0001 将重跑并以真实嵌入公开）

`Relationship Classification` 维度（18 个关系对，规则路径，LLM 关闭）：

| 类型 | 正确 | 总数 | 准确率 |
|---|---|---|---|
| UPDATES | 6 | 7 | 85.7% |
| EXTENDS | 6 | 6 | 100% |
| NONE | 5 | 5 | 100% |
| **总计** | **17** | **18** | **94.4%** |

错误案例：`"Dave 的项目预算是 50 万"` → `"Dave 的预算被砍到了 30 万"` 应为 UPDATES，被规则识别为 EXTENDS。

### 3.3 仍存在的差距

- 规则路径对**隐含矛盾**（无否定词、无结构模板）的检测能力弱
- LLM 路径**当前 CI 跑分中关闭**（无 API key），实际生产表现待验证
- DERIVES_FROM 启发式（bigram 交叉覆盖 ≥2 记忆）实际触发率低，对话场景下难以生成有效推导

---

## 4. 首选项强化 —— 已对齐 ✅

### 4.1 现状

`emerald/core/engine.py:353-419` 实现 `_strengthen_preferences()`：

```python
async def _strengthen_preferences(self, chunks, memory_ids, entity_id, metadata=None):
    """Strengthen existing preference confidence when similar preferences repeat.

    If a new preference has high text overlap with an existing preference,
    boost the existing one's confidence by 0.05 (capped at 0.95) instead of
    creating a duplicate.  Lower-overlap preferences are kept as separate
    memories (complements, not duplicates).

    Only applies to chunks with memory_type='preference'.
    """
    THRESHOLD = 0.3  # bigram overlap threshold for "same preference"
```

配套语义去重（`engine.py:437-475`）：`_check_duplicate()` 使用 bigram 快速过滤 + LLM 边界判定。

### 4.2 与 Supermemory 对齐点

| 能力 | Supermemory | Emerald |
|---|---|---|
| 重复偏好增强 | ✅ 权重随重复次数增加 | ✅ confidence +0.05/repeat, 上限 0.95 |
| 类型自动检测 | ✅ | ✅ fact/preference/episodic |
| 置信度来源 | ✅ 多信号 | ✅ LLM 评分 + 重复强化 |

---

## 5. API 成熟度 —— 部分修复（v2 仍未实质化）🟡

### 5.1 已实现的改进

| 端点 / 能力 | 状态 | 实现位置 |
|---|---|---|
| `POST /v1/memories/batch` | ✅ 新增（最多 50 条） | `api/routes/v1/memories.py:94` |
| `GET /v1/memories/graph` | ✅ 新增（节点+边，可视化用） | `api/routes/v1/system.py:77` |
| 元数据过滤 `$and`/`$or`/`$gte`/`$lte`/`$eq`/`$ne` | ✅ 新增 | `core/search.py:263-321` |
| Engine metadata override | ✅ `memory_type`/`confidence`/`valid_until` | `core/engine.py` |
| Query rewrite LLM 化 | ✅ DeepSeek → OpenAI 降级 | `core/search.py:584-605` |
| 画像多因子评分 | ✅ confidence 35% + recency 25% + type 20% + rels 20% | `core/profile.py:264-322` |

### 5.2 仍存在的差距（关键）

#### 5.2.1 v2 仍是虚假版本号（🔴）

```bash
$ cat emerald/api/routes/v2/memories.py
"""V2 re-export of V1 memories router.

When a breaking change is needed for this resource, replace this file
with a concrete V2 implementation instead of importing from V1.
"""

from emerald.api.routes.v1.memories import router

__all__ = ["router"]
```

每个 v2 路由文件均如此——纯一行 `from v1.xxx import router`。**v2 实质上不存在。**

#### 5.2.2 Dockerfile 未优化（🔴）

```dockerfile
# Dockerfile — production stage
COPY --from=development /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
```

production 阶段仍从 development 阶段拷贝整个 site-packages：
- 镜像体积膨胀（包含 dev dependencies）
- 无法独立控制生产依赖版本
- 违反 Docker 多阶段构建最佳实践

#### 5.2.3 TypeScript SDK 缺失（🔴）

`emerald/sdk/` 仍仅 Python（`client.py` + `models.py`）。Supermemory 拥有完整 TS SDK + Mastra 框架集成。

---

## 6. 基准测试 —— 基础设施就位，真实分数待发布（ADR-0001）

### 6.1 现状

`scripts/run_benchmarks.py` 从 ~250 行扩到 **1154 行**，新增 6 维度评估：

| # | 维度 | 对齐基准 | 数据规模 |
|---|---|---|---|
| 1 | Fact Recall | LongMemEval Info Extraction | 100 facts → 30 queries |
| 2 | Temporal Updates | LongMemEval Knowledge Updates | 10 timelines × 5 steps |
| 3 | Relationship Class | 自定义 | 18 pairs |
| 4 | Profile Accuracy | LoCoMo persona | 20 facts |
| 5 | Distractor Resist | LoCoMo/ConvoMem | 5 targets + 50 distractors |
| 6 | Forgetting Correct | 自定义 | 10 mixed facts |

### 6.2 真实跑分（reports/benchmark-20260615-075836.json，mock 嵌入）

| 维度 | 分数 | 通过 | 关键指标 |
|---|---|---|---|
| Fact Recall | precision@1 = 0.133, recall@5 = 0.133 | ❌ | mock 嵌入语义能力极弱 |
| Temporal Updates | overall_accuracy = 1.0 | ✅ | UPDATES 链路完整 |
| Relationship Class | accuracy = 0.944 | ✅ | 规则路径表现良好 |
| Profile Accuracy | coverage = 0.75, has_both_layers = true | ✅ | 静态/动态分离正确 |
| Distractor Resist | recall@5 = 0.0 | ❌ | mock 嵌入无法抗干扰 |
| Forgetting Correct | keep_rate = 1.0, forget_rate = 1.0 | ✅ | 三种策略均正确触发 |
| **总分** | **4/6 通过 = 0.667** | 🟡 | 跑分系统本身**正常工作** |

### 6.3 关键观察

- ✅ **Temporal Updates 100%**：时序链路（UPDATES + is_latest）完全可用
- ✅ **Forgetting 100%**：三种遗忘策略（time/noise/episodic decay）正确触发
- ✅ **Relationship 94.4%**：规则路径在结构化场景下准确率高
- ❌ **Fact Recall 13.3%**：mock 嵌入无语义能力，需 `--real` 参数启用 OpenAI/DeepSeek 嵌入才能拿到真实分数
- ❌ **Distractor 0%**：同上

**结论**：跑分基础设施已经完整并可工作。**真实成绩取决于 LLM/嵌入服务的启用**——这是基准能力的「开关」而非「缺失」。

---

## 7. 代码质量 —— 多项修复（5 项中 3 项已对齐）

### 7.1 已修复

#### 7.1.1 异步阻塞（✅ 已修复）

```python
# emerald/api/routes/v1/upload.py:50
await asyncio.to_thread(  # ✅ 改用 asyncio.to_thread
    client.put_object, ...
)
```

#### 7.1.2 Neo4j 生产配置（✅ 已修复）

```python
# emerald/db/neo4j.py:17-23
_driver = AsyncGraphDatabase.driver(
    settings.neo4j_uri,
    auth=(settings.neo4j_user, settings.neo4j_password),
    max_connection_pool_size=50,           # ✅ 新增
    connection_acquisition_timeout=30,     # ✅ 新增
    connection_timeout=10,                 # ✅ 新增
    max_transaction_retry_time=30.0,       # ✅ 新增
)
```

#### 7.1.3 双写一致性（✅ 已修复）

新增 `emerald/core/reconciliation.py`（173 行）+ `GraphStore.list_entity_ids()`：

```python
class ReconciliationEngine:
    """Background reconciliation — repair orphaned graph nodes
    missing vector entries.

    Iterates recent graph nodes, checks for matching embeddings row,
    marks orphans with `is_latest=False` + `replaced_by="reconciliation_failed"`.
    Runs as Celery Beat scheduled task.
    """
```

#### 7.1.4 CORS 生产加固（✅ 已修复）

```python
# emerald/api/app.py:163-185
# Distinguishes wildcard mode (development) from restricted mode (production)
# Logs warning when wildcard is used in production
# Validates CORS_ALLOWED_ORIGINS env var
```

#### 7.1.5 Redis 分布式锁（✅ 新增，文档未提及）

新增 `emerald/core/lock.py`（191 行）—— 防止 Celery Beat 多实例并发执行：

```python
@beat_lock(ttl_seconds=600)
def my_scheduled_task():
    """Only one Beat instance processes this per 10 minutes."""
```

### 7.2 仍存在

- ❌ **Dockerfile 未优化**（见 5.2.2）
- ❌ **v2 是虚假版本号**（见 5.2.1）
- ❌ **TypeScript SDK 缺失**（见 5.2.3）

---

## 8. 新增能力 —— 原文档未提及的 8 项

`commit 0f29876` 一次性新增 8 项能力（除已在第 1-7 节覆盖的之外）：

| # | 能力 | 实现位置 |
|---|---|---|
| 1 | **语义去重** bigram 快速过滤 + LLM 边界判定 | `engine.py:_check_duplicate` |
| 2 | **多因子画像评分** 置信度 35% + 时近性 25% + 类型 20% + 关系 20% | `profile.py:_compute_importance` |
| 3 | **`update_memory_confidence()`** 原子置信度更新 | `graph.py` |
| 4 | **本地嵌入** fastembed (ONNX, 无 PyTorch) | `embedder.py:210-258` |
| 5 | **`engine.add()` metadata 覆盖** `memory_type`/`confidence`/`valid_until` | `engine.py` |
| 6 | **ForgetEngine 生产修复** `GraphStore.list_entity_ids()` | `graph.py:200` |
| 7 | **`/v1/memories/batch`** 批量 50 条 | `api/routes/v1/memories.py:94` |
| 8 | **`/v1/memories/graph`** 节点+边可视化 | `api/routes/v1/system.py:77` |

### 8.1 本地嵌入（Emerald 差异化优势）

`fastembed` 提供 ONNX 运行时嵌入，**无需 PyTorch**：

```python
class FastEmbedProvider(EmbeddingProvider):
    """Local embedding via fastembed (ONNX runtime, no PyTorch).

    Gracefully degrades if fastembed not installed.
    """
    async def embed(self, texts: list[str]) -> list[list[float]]:
        from fastembed import TextEmbedding
        # ... async wrapper around fastembed.embed() generator
```

**价值**：
- 完全离线运行 → 适合金融/医疗/政府等数据敏感场景
- 无 GPU 依赖 → 部署成本低
- 与 OpenAI/DeepSeek API 并存 → 可降级链完整

### 8.2 多因子画像评分

```python
# emerald/core/profile.py:265-267
WEIGHT_CONFIDENCE = 0.35      # LLM 评分
WEIGHT_RECENCY = 0.25          # 指数衰减，半衰期 30 天
WEIGHT_TYPE = 0.20             # preference(1.0) > fact(0.8) > episodic(0.5) > noise(0.2)
WEIGHT_RELATIONSHIPS = 0.20    # 关系数归一化到 [0,1]
```

这比原文档描述的「confidence 硬编码 0.8」复杂得多，也更接近 Supermemory 的多信号画像排序。

---

## 9. 当前真实差距矩阵（重新评估）

按**是否阻塞核心使用**重新分类：

| 类别 | 差距 | 阻塞？ | 工作量 |
|---|---|---|---|
| **功能性已对齐** | 事实提取、图谱搜索遍历、首选项强化、类型检测、元数据过滤、批量写入、图谱可视化、本地嵌入、Redis 锁、CORS 加固、Neo4j 配置、Reconciliation | 否 | — |
| **质量待验证** | 关系推断 LLM 路径质量、查询改写 LLM 质量、真实 LLM 嵌入下的基准分数 | 否（开关打开即可） | 启用 + 跑分 |
| **生态/集成缺失** | TypeScript SDK、LangChain/Mastra/OpenAI/Vercel AI 框架集成、消费者产品 | 是（限制采用） | 高（1-3 个月） |
| **生产化打磨** | Dockerfile 多阶段独立构建、v2 真实 API 演进、分页、限流、SDK 幂等 `customId` | 是（限制生产部署） | 中（1-2 周） |

---

## 10. 新的优先路径（取代原文档的 P0/P1/P2/P3）

| 优先级 | 项目 | 理由 | 工作量 |
|---|---|---|---|
| **P0** | 优化 Dockerfile（production 独立 `pip install`） | 当前部署镜像 ~2GB 含 dev 依赖，生产环境启动慢、攻击面大 | 1-2 天 |
| **P0** | 在真实 LLM/嵌入配置下重跑基准测试，发布分数 | 当前所有「LLM 质量」差距均为推测性，无真实数据支撑 | ✅ 部分完成（08-11：bge-m3 绝对分报告已发布，7/7 通过；第二模型对照待补） |
| **P1** | TypeScript SDK v1（对齐 Python SDK 方法集） | 拓展开发者基础，TS 生态（LangChain.js、Vercel AI SDK、Mastra）是 AI 应用主流 | ✅ 已完成（M2，`sdk/typescript/`） |
| **P1** | 至少 2 个框架集成：LangChain.js + Vercel AI SDK | 进入主流 AI 开发生态是 Supermemory 拉开差距的主因 | 🟡 M3 精简为仅 LangChain.js（2026-08-13 决议），待启动 |
| **P1** | v2 API 真实改进（v2 是 v1 别名问题） | 至少实现分页、限流、`customId` 幂等 3 项实质差异 | ✅ 已完成（M2：分页/限流/错误码在 v1 落地，v2 别名下线） |
| **P2** | ~~关系推断规则路径重写为 LLM-first~~ ✅ 已完成（2026-06-22） | LLM-first + bigram 预滤 + 规则降级 | — |
| **P2** | ~~NER 实体抽取层（在 LLM 提取后补充结构化实体节点）~~ ✅ 已完成（2026-08，B3 issue #21–#28） | 提及（Mention）图节点 + 实体隔离 + 跨表层解析 + 质量套件 | — |
| **P3** | ~~真实时序扩展（depth=2+ 多跳推理）~~ ✅ 已完成（2026-08，B4 issue #29–#35） | `search(..., depth=)`：共享主体桥 + 关系链式 depth ≤ 4 + 路径透明 + 历史标记 | — |
| **P3** | 框架生态扩张（CrewAI/n8n/Mastra 等） | 长期生态建设 | 持续 |

---

## 11. 结论

### 11.1 与原文档结论的对比

| 维度 | 原文档 v1 结论（2026-06-09） | 当前结论（2026-06-21） |
|---|---|---|
| 核心实现深度 | 「架构正确但功能浅层」 | **核心能力已对齐 Supmemory 的 8 项主要功能** |
| 致命差距数量 | 3（事实提取、图谱遍历、语义关系） | **0**（已修复 2，1 转为「待 LLM 验证」） |
| 关键缺失数量 | 多项（API、SDK、集成、基准） | **核心引擎层面已对齐**；生态与生产化层面仍落后 |
| 系统本质 | 「带图谱元数据的向量数据库」 | **真正的记忆引擎**——事实提取、关系推断、图谱遍历、画像评分、本地嵌入、批量写入、可视化端点全部到位 |

### 11.2 当前定位

Emerald v0.3.0+ HEAD 已完成 **核心记忆引擎能力的实质性构建**。从「带图谱元数据的向量数据库」升级为「支持多模态摄入、LLM 事实提取、图谱遍历、本地嵌入的生产级记忆引擎」。

**剩余差距集中在三个层面**：
1. **生态与集成**（TypeScript SDK、框架集成）—— 限制采用规模
2. **生产化打磨**（Dockerfile、v2 API、SDK `customId`）—— 限制生产部署
3. **质量验证**（真实 LLM/嵌入跑分）—— 限制可信度宣称

这些差距**不影响核心引擎可用性**，但限制了 Emerald 在更广泛场景下的竞争力。建议下一阶段（P0/P1）聚焦生态与生产化打磨，再发起对外宣传。

### 11.3 何时发起对外对标宣传

✅ **现在可以宣称**：
- 支持 LLM 驱动的事实提取（DeepSeek/OpenAI）
- 支持图谱关系遍历的混合搜索
- 支持多模态摄入（PDF/图片/音频/视频/代码/对话）
- 支持本地嵌入（无需 API key，无需 GPU）
- 已有 6 维度基准测试套件（绝对分报告将按 ADR-0001 公开入库）

⚠️ **建议延后宣称**：
- 「达到 Supermemory 同等水平」—— 真实跑分未公开
- 「生产就绪」—— Dockerfile 未优化
- 「完整框架生态」—— TS SDK 缺失

---

*本对比基于对 Emerald 当前 HEAD（commit b301cfa, 2026-06-17）源码的完整审查、Supermemory 公开文档与 API 规范，以及一次 mock 嵌入下的本地基准运行（`reports/` 未入库，2026-08-09 按 ADR-0001 修正叙事）。*
