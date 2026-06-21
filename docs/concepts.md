# Emerald 核心概念

> **目标读者：** 第一次接触 Emerald 的开发者、AI Agent 工程师、架构师。
>
> 阅读时间：~15 分钟。
>
> 阅读完本文，你将理解：什么是记忆（vs RAG）、三种记忆类型（fact/preference/episodic）的区别、三种关系（UPDATES/EXTENDS/DERIVES_FROM）的语义、何时该用 Emerald、何时不该用。

---

## 1. 记忆 ≠ RAG（最重要的概念）

这是理解 Emerald 之前必须内化的根本区别。

### 1.1 一句话区分

| 系统 | 它回答的问题 | 状态 |
|---|---|---|
| **RAG**（检索增强生成） | 「**我知道什么？**」 | **无状态**——所有人查询结果相同 |
| **记忆**（Emerald） | 「**我记得你的什么？**」 | **有状态**——不同用户/实体结果不同 |

### 1.2 详细对比

| 维度 | RAG | 记忆 |
|---|---|---|
| **状态** | 无状态 | 有状态（按 entity 区分） |
| **时序** | 无时间概念 | 追踪事实何时为真、何时过期 |
| **关系** | 无 | 事实建立在其他事实之上（更新、扩展、推导） |
| **遗忘** | 从不遗忘 | 自动过期临时事实、解决矛盾、衰减情节 |
| **典型场景** | 文档库、知识库、通用问答 | 用户偏好、对话历史、个人事实 |
| **检索方式** | 向量相似度 | 图谱遍历 + 时序过滤 + 向量相似度 |

### 1.3 经典反例（说明为什么要记忆而非 RAG）

```
用户第 1 天说：「我喜欢 Adidas 运动鞋」
用户第 30 天说：「Adidas 鞋子质量差，我换 Puma 了」
用户第 45 天问：「我该买什么运动鞋？」

❌ RAG 返回：「你喜欢 Adidas」（语义相似度最高的旧记忆）
✅ 记忆返回：「你偏好 Puma」（追踪了时序演进 + 矛盾解决）
```

Emerald **同时运行两者**——混合搜索 `search_mode="hybrid"` 默认组合 RAG 与记忆结果。但只有记忆能正确处理「用户在变化」这种场景。

---

## 2. 三种记忆类型（fact / preference / episodic）

Emerald 自动从文本中识别每条事实属于以下三种类型之一：

### 2.1 fact（事实）

**定义：** 实体属性、关系、状态——相对稳定的客观陈述。

**示例：**
- 「Alex 在 Stripe 担任 PM」
- 「Alex 住在西雅图 Capitol Hill」
- 「Alex 负责支付基础设施」

**行为：**
- 持续有效，**直到被 UPDATES 关系取代**
- `confidence` 由 LLM 评分（明确陈述 → 0.8-0.95；隐含可推断 → 0.5-0.7）
- 画像中作为**静态事实**长期保留

### 2.2 preference（偏好）

**定义：** 习惯、倾向、风格——用户的个人选择。

**示例：**
- 「Alex 偏好上午开会」
- 「Alex 喜欢深色模式」
- 「Alex 偏好 TypeScript」

**行为：**
- **重复提及则置信度强化**：`+0.05/repeat`，上限 0.95（`emerald/core/engine.py:_strengthen_preferences`）
- 高 bigram 重叠（≥0.3）的相似偏好会**合并**，不是创建新记忆
- 画像中作为**静态事实**长期保留（`type_weight=1.0`，最高优先级）

### 2.3 episodic（情节）

**定义：** 一次性事件、互动记录——临时性。

**示例：**
- 「周二和 Alex 喝了咖啡」
- 「Alex 下周三有考试」
- 「Alex 提到下周会搬去西雅图」

**行为：**
- **除非重要，否则随时间衰减**（指数衰减，half-life=30 天）
- 有 `valid_until` 字段（可设置时间过期）
- 超 N 天无 EXTENDS 关系 → 降低搜索权重 → 超 2N 天 → 归档
- 画像中作为**动态事实**短期保留

### 2.4 自动分类示例

输入对话：
> 「刚和 Alex 打了个很棒的沟通电话。他挺喜欢 Stripe 的 PM 新角色，不过支付基础设施的工作强度很大。他为此搬去了西雅图，在 Capitol Hill 租了房子。还说下次我来这边要一起吃个饭。」

提取结果：

| 文本 | 类型 | confidence | 备注 |
|---|---|---|---|
| Alex 在 Stripe 担任 PM | fact | 0.9 | 明确陈述 |
| Alex 负责支付基础设施 | fact | 0.85 | 补充细节（EXTENDS 上一条） |
| Alex 住在西雅图 Capitol Hill | fact | 0.85 | 明确陈述 |
| Alex 想约一顿饭 | episodic | 0.7 | 临时互动 |

---

## 3. 三种关系类型（UPDATES / EXTENDS / DERIVES_FROM）

Emerald 的图谱是**建立在其他事实之上的事实**——记忆与记忆之间通过三种有向关系连接。

### 3.1 UPDATES（更新）— 信息变化

当新信息与已有知识**矛盾**时，Emerald 将旧事实标记为被取代。

```
「你在 Google 工作」 → 「你刚加入 Stripe」
                        记忆 2 UPDATES 记忆 1
```

**实现细节：**
- 旧记忆 `is_latest=False`
- 新记忆 `is_latest=True`
- 新记忆 `replaced_by=<new_id>`（旧指向新）
- 旧记忆保留以支持时序查询（"你之前在哪工作过？"）

### 3.2 EXTENDS（扩展）— 信息丰富

当新信息**补充**已有知识（不矛盾）时，两者**都保持有效**。

```
「你在 Stripe 工作」 → 「你领导一个 5 人的支付团队」
                        记忆 2 EXTENDS 记忆 1
```

**用途：** 搜索时自动扩展——命中「Stripe 工作」会同时召回「5 人支付团队」。

### 3.3 DERIVES_FROM（推导）— 信息推理

当 Emerald 从模式中**推理**出未明确陈述的新事实时。

```
「Dhravya 是创始人」 + 「Dhravya 每天都在讨论 AI」
                       → 「Emerald 很可能是一家 AI 公司」
                                    DERIVES_FROM 两条源记忆
```

**特点：** 推导出的记忆带有来源链，可追溯。**当前实现为启发式**（bigram 交叉覆盖），LLM-first 关系推断在 M2 (v0.5.0) 路线图。

### 3.4 关系选择决策树

```
新记忆 vs 已有记忆 ─┬─ 矛盾（讲同一件事但不同）
                   │    → UPDATES（旧标记为非最新）
                   │
                   ├─ 补充（讲同一件事但更详细）
                   │    → EXTENDS（两者都有效）
                   │
                   ├─ 推理（从多条已有事实推导）
                   │    → DERIVES_FROM（标注来源链）
                   │
                   └─ 无关
                       → 无关系，独立记忆
```

---

## 4. 用户画像（Profile）

### 4.1 双层结构

```
画像 = 静态事实（长期） + 动态事实（短期）

静态事实（始终注入 Agent 上下文）：
  - 用户类型（用户/项目/组织）
  - 长期偏好（语言/工具/风格）
  - 稳定属性（职位/地点/技能）

动态事实（最近、情节性）：
  - 最近 N 次对话摘要
  - 当前工作项目/上下文
  - 最近关注的话题
```

### 4.2 使用模式

```python
# 注入到 Agent 系统提示词
result = client.profile(entity_id="user_123")
print(result.profile.static)    # 长期事实
print(result.profile.dynamic)   # 近期上下文

# 在会话开始时调用
result = client.profile(
    entity_id="user_123",
    q="用户最近在关注什么？"  # 可选查询，会并入搜索结果
)
```

### 4.3 性能目标

- 缓存命中：< 50ms（Redis 直接返回）
- 缓存未命中：< 500ms（P50），< 100ms（P99）
- 缓存 TTL：24h，摄入新内容时主动失效

### 4.4 多因子评分

Post-v0.3.0 引入 `importance` 字段，多因子加权：

```
importance = 0.35 × confidence      # LLM 评分
          + 0.25 × recency           # 指数衰减, half_life=30天
          + 0.20 × type_weight       # preference(1.0) > fact(0.8) > episodic(0.5)
          + 0.20 × relationship_count # 关联记忆数
```

**与 confidence 的区别：** confidence 是来源可信度（LLM 评的）；importance 是当前相关度（结合时间+关系动态计算）。

---

## 5. 时序完整性

每个事实都有时序上下文。

### 5.1 时序字段

```python
class Memory:
    valid_from: DateTime      # 事实生效时间（默认 created_at）
    valid_until: DateTime     # 事实失效时间（可选，临时事实用）
    expired_at: DateTime      # 实际过期处理时间（由遗忘引擎设置）
    replaced_by: String       # 取代此记忆的最新记忆 ID（UPDATES 时设置）
```

### 5.2 遗忘策略

| 策略 | 触发 | 行为 |
|---|---|---|
| **时间过期** | `valid_until` 已过 | `is_latest=False`，`expired_at=now` |
| **矛盾淘汰** | 已被 UPDATES 取代 | 保留历史，但不在默认搜索中返回 |
| **噪音过滤** | `confidence < threshold` + 无关系引用 | 移入 `archived` 状态 |
| **情节衰减** | `memory_type=episodic` + 创建超 N 天 + 无 EXTENDS | 降低搜索权重 → 超 2N 天归档 |

### 5.3 自动示例

```
第 1 天：「我明天有考试」
第 2 天：考试已过 → 遗忘引擎标记 `is_latest=False`，不再搜索返回
第 30 天：清理任务将该记忆归档到 cold storage
```

---

## 6. 何时用 Emerald、何时不用

### 6.1 ✅ 适合 Emerald 的场景

| 场景 | 原因 |
|---|---|
| **个性化 AI 助理** | 需要跨会话记住用户偏好、习惯、历史 |
| **客服/支持机器人** | 需要记住客户过往互动、问题历史 |
| **研究助理** | 需要跨文档追踪同一实体的演化（如某研究者多年来的研究方向变化） |
| **企业内部知识管理** | 需要追踪员工角色变化、项目演进 |
| **对话式应用** | 长对话中需要上下文一致性 |

### 6.2 ❌ 不适合 Emerald 的场景

| 场景 | 原因 | 推荐替代 |
|---|---|---|
| **通用问答** | 无状态，不需要记忆 | 纯向量数据库（如 Qdrant 直接用） |
| **一次性文档检索** | 不需要追踪变化 | RAG 框架（LangChain、LlamaIndex） |
| **超大规模（百万级）文档** | 图遍历性能瓶颈未充分验证 | 专用搜索引擎（Elasticsearch） |
| **毫秒级强延迟要求** | 图谱遍历 + LLM 调用链路较长 | 内存数据库 + 简单查询 |
| **数据主权敏感 + 无 LLM 访问** | Emerald 的核心价值依赖 LLM 提取 | 自建轻量方案 |

### 6.3 决策流程

```
问自己：
  Q1: 是否需要按用户/实体区分状态？
      ├─ 否 → 用 RAG 即可
      └─ 是 ↓
  
  Q2: 是否需要追踪事实随时间变化？
      ├─ 否 → 用 RAG + metadata
      └─ 是 ↓
  
  Q3: 事实之间是否有关系链（"X 工作于 Y，Y 在 Z 城市"）？
      ├─ 否 → 用纯向量数据库
      └─ 是 ↓
  
  Q4: 是否有 ≥ 1000 个用户/实体需要记忆？
      ├─ 否 → 用 SQLite + LLM summarization 即可
      └─ 是 → ✅ Emerald 适合
```

---

## 7. 关键设计原则（不可妥协）

来自 [`AGENTS.md`](../AGENTS.md)：

1. **记忆 ≠ RAG**——不为对齐其他系统而牺牲图谱独立性
2. **图谱优先**——多跳推理、实体关系优先于纯向量优化
3. **全自动**——用户/开发者无需手动定义关系、打标签、清理过期
4. **同一个上下文池**——记忆、画像、RAG 文档共享 entity_id
5. **时序完整性**——任何检索路径都不能破坏时序语义
6. **按类型分块**——代码用 AST、Markdown 用标题、PDF 用章节、对话用轮次
7. **提取，而非存储**——每段内容经过提取→分块→嵌入→关系构建

---

## 8. 相关文档

| 想了解 | 阅读 |
|---|---|
| 系统架构全景 | [`architecture/overview.md`](architecture/overview.md) |
| 数据模型细节 | [`architecture/data-model.md`](architecture/data-model.md) |
| 处理管线 | [`architecture/pipeline.md`](architecture/pipeline.md) |
| 5 分钟跑通 | [`quickstart.md`](quickstart.md) |
| REST API 完整参考 | [`api/rest-guide.md`](api/rest-guide.md) |
| Python SDK | [`api/sdk-guide.md`](api/sdk-guide.md) |
| 与 Supermemory 对比 | [`comparison-supermemory.md`](comparison-supermemory.md) |
| 路线图 | [`roadmap.md`](roadmap.md) |
