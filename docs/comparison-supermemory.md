# Emerald vs Supermemory 深度对比

> **更新日期：2026-06-09，基于 Emerald v0.3.0 与 Supermemory 公开文档/API**

---

## 总览：同源不同路，差距显著

Emerald 在**架构设计、概念模型和 API 命名上高度对标 Supermemory**，三者几乎完全一致的结构（知识图谱、三种关系类型、静态/动态画像、自动遗忘）。但在**实际实现深度**上存在巨大鸿沟——Supermemory 是生产级系统，Emerald 当前仍处于"架构完整但功能浅层"的原型阶段。

| 维度 | Emerald | Supermemory | Emerald 差距 |
|---|---|---|---|
| **版本** | v0.3.0 Beta | v4 生产级 | 距离 1.0 至少 2-3 个里程碑 |
| **事实提取** | 无——仅做内容类型转换（PDF→text，图片→OCR） | LLM 驱动的事实提取——从对话中提取多条结构化事实 | 🔴 **致命差距** |
| **关系推断** | 基于规则（关键词匹配 + bigram 重叠） | LLM 驱动语义理解 + 规则 | 🔴 质量差异极大 |
| **图谱搜索** | 无图谱遍历——仅过滤 is_latest + valid_until | Relationship Expansion——搜索结果沿关系链扩展 | 🔴 关键功能缺失 |
| **TypeScript SDK** | 无 | ✅ 完整 SDK | 🟡 限 Python |
| **框架集成** | Pandaria（Rust）仅一个 | LangChain / Mastra / OpenAI SDK / Vercel AI / Agno / CrewAI / n8n ... | 🔴 生态空白 |
| **消费者产品** | 无 | Web App / 浏览器插件 / Raycast 扩展 / Nova Agent | 🟢 定位不同（B2B vs B2C） |
| **API 成熟度** | v1 = 实际；v2 = v1 的别名（无差异） | v3→v4 持续演进，v4 有实质性改进 | 🔴 v2 是虚假版本号 |
| **内容管理** | 仅 `get_memory()` | documents.list / delete / get / update | 🟡 操作性不足 |
| **图谱可视化** | 无 | `POST /v3/graph/viewport` | 🟡 |
| **metadata 过滤** | 仅 `memory_type` + `min_confidence` | $and / $or / 数值比较 / 数组包含 / 字符串包含 | 🟡 |
| **提取引导** | 无 | `entityContext` 参数引导提取方向 | 🟡 |
| **基准成绩** | 无（仅有评估脚本框架） | LongMemEval #1 / LoCoMo #1 / ConvoMem #1 | 🔴 未验证 |
| **首选项强化** | 无 | 重复提及则加强权重 | 🟡 |
| **幂等写入** | Redis 缓存 idempotency_key（1h TTL） | `customId` 原生支持 | 🟡 |
| **Docker 生产镜像** | 从 development 复制 site-packages | 生产级构建 | 🟡 |
| **同步阻塞** | MinIO 同步调用阻塞 async 事件循环 | 异步全链路 | 🟡 |

---

## 1. 事实提取 —— Emerald 最核心的功能缺失

这是 Emerald 与 Supermemory 最大的差距。Supermemory 的核心价值是**自动从自然语言中提取结构化事实**，而非简单的文件格式转换。

### Supermemory 的能力

```
输入：刚和 Alex 打了个很棒的沟通电话。他挺喜欢 Stripe 的 PM 新角色，
      不过支付基础设施的工作强度很大。他为此搬去了西雅图，
      在 Capitol Hill 租了房子。还说下次我来这边要一起吃个饭。

输出（多条自动提取的记忆）：
├── Alex 在 Stripe 担任 PM              (fact, confidence: 0.9)
├── Alex 负责支付基础设施                (extends 上一记忆)
├── Alex 住在西雅图 Capitol Hill         (fact, confidence: 0.8)
└── Alex 想约一顿饭                     (episodic, confidence: 0.7)
```

### Emerald 的实际行为

```
输入：同上文本
输出：整段文本作为一个 chunk 存入 Neo4j，类型标记为 "fact"，content 为原文
      → 没有事实提取，没有多条记忆，没有记忆类型区分
```

**根因分析：**

Emerald 的提取层全部是内容类型转换器，**没有任何 LLM 调用**：

| Emerald 提取器 | 实际行为 |
|---|---|
| `TextExtractor` | `content.strip()` ——去除空白后原样返回 |
| `URLExtractor` | HTML → trafilatura 清洗 → 纯文本 |
| `PDFExtractor` | PyMuPDF → 纯文本 |
| `ImageExtractor` | Tesseract → OCR 文本 |
| `AudioExtractor` | FasterWhisper → 转录文本 |
| `VideoExtractor` | ffmpeg 抽取音频 → Whisper 转录 |
| `CodeExtractor` | tree-sitter 解析后原样返回 |

全部提取器都是："把 A 格式变成纯文本"，没有一个是"从文本中理解含义并提取事实"。`content_type` 参数（text/conversation/markdown）在提取阶段无实际差异——全部走 `TextExtractor` 的 `strip()`。

**影响：**
- 没有多事实提取 → 图谱中只有原始语料块，没有细粒度的记忆节点
- 没有自动类型检测 → 所有记忆都是 "fact" 类型
- 没有 NER/实体识别 → 无法知晓"Alex" 是个人、"Stripe" 是公司
- 关系推断退化为文本相似度匹配 → 失去了图谱推理的全部优势

---

## 2. 搜索 —— 缺乏图谱遍历

Supermemory 的搜索流程包含关键步骤 **Relationship Expansion**：

```
用户查询 → 向量搜索找到命中记忆 → 沿 EXTENDS/DERIVES 关系扩展
         → 获取关联记忆 → 合并排序 → 返回丰富上下文
```

Emerald 的搜索流程：

```
用户查询 → 向量搜索找到候选 → 检查 is_latest=True → 检查 valid_until 未过期
         → 按置信度加权排序 → 返回结果
```

**Emerald 完全没有利用它自己建立的图谱关系。** 虽然 `MemoryEngine.add()` 在摄入时会调用 `RelationshipEngine.infer()` 创建 UPDATES/EXTENDS/DERIVES 关系，但这些关系仅用于：
1. 画像增量刷新（profile.py 驱逐被取代的事实）
2. 遗忘（被 UPDATES 指向的旧事实不返回）

而搜索时从不沿关系链扩展结果。关系引擎建立的所有图谱连接在搜索路径上完全浪费。

---

## 3. 关系推断 —— 退化为文本匹配

Emerald 的关系推断是**局部的、成对的文本相似度检查**，而非语义理解。

| 检查方式 | 实现 | 实际限制 |
|---|---|---|
| 结构模板匹配 | 将"Google"→"*"、"北京"→"*"，同一模板不同填充词 → UPDATES | 仅匹配预定义的公司名、城市名、编程语言列表 |
| 矛盾检测 | 搜索否定词列表 `{"不","没","别","换了","改用","搬到","跳槽","离职"}` | 仅中文否定词；无法检测英文矛盾或语义矛盾（如 "quit Stripe" 与 "works at Stripe"） |
| 互补检测 | bigram 字符重叠计算 | 在中文上 bigram 粒度太细（"住在西雅图" → "在西","在西","西雅","雅图"），英文上又太粗糙 |
| DERIVES_FROM | bigram 交叉覆盖：新记忆的 bigram 与 ≥2 条已有记忆重叠 | 几乎不会触发有意义的推导关系 |

**实际效果：** 在大多数真实场景中，关系推断会退化为 `RelationType.NONE`。LLM 路径（Phase 2）需要手动配置 OpenAI API key 才会生效，且仅用于 UPDATES/EXTENDS 二分类（不用于提取，不用于多事实分解）。

---

## 4. 首选项强化 —— 完全缺失

Supermemory 文档明确提到：

> 偏好（Preferences）："Alex prefers morning meetings" — **Strengthens with repetition**

Emerald 中，`preference` 类型虽在 profile.py 和 models 中定义，但：
- 摄入时无法真正区分 fact vs preference——全部标记为 "fact"
- 没有任何基于重复次数的置信度增强逻辑
- `confidence` 字段硬编码为 0.8（index 阶段写死）
- 在 profile 计算中与 fact 一视同仁

---

## 5. API 成熟度 —— v2 是虚假版本号

| 检查项 | Emerald 实际状态 |
|---|---|
| v2 路由 | `emerald/api/routes/v2/` 中每个文件仅一行 `from emerald.api.routes.v1.xxx import router as v2_router` |
| v1 和 v2 差异 | 无任何差异，完全相同的路由和逻辑 |
| 错误码标准化 | 无——401/403/404/429 之外无业务错误码体系 |
| 分页支持 | 无——search 只有 `top_k`，无法翻页 |
| 批量操作 | 无——`add()` 一次一条内容 |

这意味着 README 中 "V1 + V2 双版本" 是一个**虚设的版本号**，并非真实的 API 演进。

---

## 6. 测试基准 —— 完全未验证

README 列出"基准测试 ✅ 完整：LongMemEval / LoCoMo / ConvoMem 风格评估脚本"。实际情况：

```bash
$ ls tests/benchmarks/
test_memory_benchmarks.py
```

`test_memory_benchmarks.py` 是一个**空的评估框架**（定义了测试类骨架和 mock 数据生成器），没有对任何标准数据集运行的实际评测，没有任何分数报告，没有结果分析。它定义了一组测试函数但全部使用 mock 数据，且不计算基准分数。

对比 Supermemory：在标准数据集上运行并获得公开的定量分数（LongMemEval 85.2%/99%，LoCoMo #1，ConvoMem #1），结果是可复现、可验证的。

---

## 7. 代码质量问题

### 7.1 同步阻塞 async 事件循环

```python
# emerald/api/routes/v1/upload.py
client.put_object(...)  # 同步 MinIO SDK 调用，阻塞整个 async 事件循环
```

必须在生产修复：使用 `asyncio.to_thread()` 包裹或 MinIO 的 async API。

### 7.2 Docker 生产镜像未优化

```dockerfile
# Dockerfile — production stage
COPY --from=development /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=development /usr/local/bin /usr/local/bin
```

生产镜像从 development 阶段拷贝整个 site-packages，而非在 production stage 独立执行 `pip install --no-cache-dir`，导致：
- 镜像体积膨胀（包含 dev dependencies）
- 无法控制生产依赖版本
- 违反 Docker 最佳实践

### 7.3 Neo4j 驱动无生产配置

```python
# emerald/db/neo4j.py
_driver = AsyncGraphDatabase.driver(uri, auth=auth)  # 无连接池、超时、重试配置
```

生产环境缺少 `max_connection_pool_size`、`connection_acquisition_timeout`、`max_transaction_retry_time`。

### 7.4 双写一致性问题

`MemoryEngine._index()` 先写 Neo4j 再写 pgvector。后者失败时用补偿逻辑标记 `is_latest=False`，但如果补偿也失败（Neo4j 连接断开），图谱中有孤立节点。

---

## 8. Emerald 的真实优势

上述差距并不意味着 Emerald 毫无价值。在以下方面 Emerald 有其独特优势：

| 优势 | 说明 |
|---|---|
| **架构完整性** | 四层架构（客户端/网关/核心/数据）设计合理，管道编排（提取→分块→嵌入→索引→关系→画像）逻辑清晰，新增提取器/分块器只需注册 |
| **图片/视频/音频支持** | 支持 9 种内容类型，均通过独立提取器处理（FasterWhisper、PyMuPDF、tree-sitter、Tesseract），代码结构清晰 |
| **可观测性** | structlog 结构化日志 + Prometheus 指标 + OpenTelemetry 追踪 + 请求级 trace ID，比 99% 的早期项目更完善 |
| **K8s 模板** | Deployment / HPA / Ingress / CronJob 备份 / Secret / ConfigMap / Namespace —— 生产部署模板完整 |
| **连接器** | GitHub / Google Drive / Gmail / Notion 四个连接器，OAuth + Webhook + 增量同步实现完整 |
| **MCP Server** | stdio + SSE 双模式，3 个工具暴露完整 |
| **数据主权** | 完全自托管——金融、医疗等数据敏感行业可以私有化部署 |
| **嵌入缓存** | SHA256 哈希缓存 + Redis 7 天 TTL，显著降低 API 调用成本 |

---

## 9. 填补差距的优先级路径

按影响力排序，建议以下路线图：

| 优先级 | 差距 | 工作量 | 影响 |
|---|---|---|---|
| **P0** | LLM 驱动的事实提取 | 高（2-3 周） | 这是记忆系统与文档存储的本质区别。不做这点，Emerald 只是一个带图谱的向量数据库 |
| **P0** | 图谱搜索的关系扩展 | 中（1 周） | 让已建立的关系在搜索中产生价值，直接提升搜索结果质量 |
| **P1** | 关系推断升级为语义理解 | 高（2 周） | 当前规则匹配的准确率不足以支撑可信的自动关系建立 |
| **P1** | 首选项强化 + 记忆类型自动检测 | 中（1 周） | 让 fact/preference/episodic 分类真正发挥作用 |
| **P1** | 修复 Docker 生产镜像 + async 阻塞 | 低（1-2 天） | 生产部署的基础要求 |
| **P2** | API v2 真实改进（分页、批量、metadata 过滤增强） | 中（1 周） | 提升 API 成熟度 |
| **P2** | 在标准数据集的基准测试 | 中（1 周） | 验证系统在实际基准上的性能 |
| **P3** | TypeScript SDK | 中（1-2 周） | 拓宽开发者基础 |
| **P3** | 框架集成（LangChain、Mastra 等） | 中（2-3 周） | 进入主流 AI 开发生态 |

---

## 10. 结论

**Emerald 的架构设计是正确的**——四层分离、管道编排、图谱优先、画像双层、三种关系类型、四种遗忘策略。这些都是对的。

**但 Emerald 的核心实现是浅层的。** 它在三个最关键的能力上存在差距：

1. **不提取事实** — 它存储原始文本块，而非从文本中理解含义并分解为多条结构化事实
2. **不遍历图谱** — 它建立关系但不利用关系进行搜索扩展
3. **不语义理解** — 关系推断是字符级匹配而非含义级推理

这三个能力正是 Supermemory 成为标杆的核心原因。没有它们，Emerald 的"记忆引擎"本质上是一个**带知识图谱元数据的向量数据库**——它存储、分块、嵌入、检索，但不理解。

填补这些差距不涉及架构重构——现有的管道模式、引擎注入、提取器/分块器注册机制已经为 LLM 驱动的事实提取准备好了接口。需要的是在现有架构的**提取阶段**和**搜索阶段**加入真正的语义理解能力。

---
*本对比基于对 Emerald v0.3.0 源码的完整审查、Supermemory 的公开文档和 API 规范。*
