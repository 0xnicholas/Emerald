# Emerald vs Supermemory 深度对比

> **一句话总结：** Emerald 和 Supermemory 在核心概念、记忆本体论和 API 设计上高度同源——二者都基于「活的知识图谱」构建，区分记忆与 RAG，支持自动提取、时序追踪、矛盾解决和自动遗忘。差异主要体现在**商业模式**（开源自托管 vs SaaS）、**技术栈**（Python/Neo4j vs 闭源分布式后端）和**生态成熟度**（初版实现 vs 生产级服务）。

---

## 1. 产品定位与商业模式

| 维度 | Emerald | Supermemory |
|---|---|---|
| **定位** | 面向 AI Agent 的记忆与上下文基础设施 | State-of-the-art memory and context engine for AI |
| **开源策略** | **完全开源**（Python 后端 + SDK + MCP），可自托管 | **SaaS 优先**：后端闭源，客户端/SDK/插件开源 |
| **部署模式** | Docker Compose / K8s 私有化部署 | 托管云服务 `api.supermemory.ai`，也支持 self-hosted |
| **目标用户** | 需要数据主权、私有化部署的开发者/企业 | 追求快速集成、不愿运维基础设施的开发者 |
| **对标声明** | 明确对标 Supermemory，追求三项基准最优 | 本身就是标杆，LongMemEval/LoCoMo/ConvoMem 三项 #1 |
| **消费者产品** | 暂无 | 有 `app.supermemory.ai` 消费者应用 + 浏览器插件 |

**关键差异：**
- Emerald 是**基础设施层**的完整开源实现——你可以 fork、修改、部署在自己的数据中心。Supermemory 是**服务层**——你通过 API 调用，无法看到或修改后端实现。
- Supermemory 有完整的消费者产品线（App、浏览器插件、Nova Agent），Emerald 目前专注 B2B 开发者市场。

---

## 2. 架构设计对比

### 2.1 高层架构

两者在架构理念上几乎一致：

```
客户端 → API 网关 → 核心服务（记忆引擎/画像/搜索/连接器）
                              ↓
                    处理管线（提取→分块→嵌入→索引）
                              ↓
                    数据层（图谱 + 向量 + 文件存储 + 缓存）
```

### 2.2 技术栈细节

| 组件 | Emerald | Supermemory |
|---|---|---|
| **Web 框架** | FastAPI (Python) | 未公开（推测为 Node.js/TypeScript 或混合栈） |
| **图数据库** | **Neo4j**（图原生，Cypher 查询） | 未公开（内部图存储 + 向量索引 HNSW） |
| **向量存储** | **PostgreSQL + pgvector**（HNSW 索引） | 内部实现（HNSW，O(log n) 搜索） |
| **文件存储** | **MinIO**（S3 兼容，私有化） | 未公开（云对象存储） |
| **缓存/队列** | **Redis + Celery** | 未公开 |
| **任务队列** | Celery + Celery Beat（定时遗忘任务） | 未公开 |
| **嵌入模型** | 可插拔（默认 OpenAI，回退 MockEmbeddingProvider） | 未公开（state-of-the-art 嵌入模型） |
| **部署** | Docker Compose（开发）+ K8s（生产模板已就绪） | 完全托管，无需部署 |

### 2.3 部署复杂度

| 场景 | Emerald | Supermemory |
|---|---|---|
| 开发环境 | `docker compose up -d` + `alembic upgrade head` | `npm install supermemory` / `pip install supermemory` |
| 生产环境 | 需运维 Neo4j + PostgreSQL + Redis + MinIO + Emerald 服务 | 零运维，API Key 即用 |
| 数据主权 | ✅ 数据完全私有 | ⚠️ 数据在 Supermemory 云端（企业版可能有私有化选项） |
| 定制能力 | ✅ 可修改任何组件 | ❌ 仅能通过 SDK 配置参数 |

**Emerald 的架构优势：** 技术选型完全透明，Neo4j 的图查询能力在复杂关系遍历（多跳推理、时序链追踪）上非常强大。pgvector 与 PostgreSQL 统一运维，降低复杂度。

**Supermemory 的架构优势：** 无需关心基础设施，全球分布式部署，自动扩缩容，SLA 保障。

---

## 3. 数据模型与记忆本体论

这是两者最核心的相似点——它们在记忆哲学的定义上几乎完全一致。

### 3.1 核心概念对照表

| 概念 | Emerald 术语 | Supermemory 术语 | 说明 |
|---|---|---|---|
| 记忆归属单元 | **entity_id** | **containerTag** | 用户/项目/组织的隔离标识 |
| 静态事实 | static facts (`is_static` 隐含) | static memories (`isStatic: true`) | 永久属性：姓名、职业、偏好 |
| 动态事实 | dynamic facts | dynamic memories (`isStatic: false`) | 近期上下文、情节记忆 |
| 关系：时序更新 | **UPDATES** | **Updates** | 新事实取代旧事实 |
| 关系：上下文丰富 | **EXTENDS** | **Extends** | 补充信息，两者都有效 |
| 关系：模式推导 | **DERIVES_FROM** | **Derives** | 从模式中推理出新事实 |
| 版本追踪 | `is_latest` 标志位 | `isLatest` 标志位 | 查询时默认只返回最新版本 |
| 自动遗忘 | ✅ 时间过期 + 矛盾解决 + 噪音过滤 + 情节衰减 | ✅ 临时事实过期 + 矛盾自动解决 + 噪音过滤 | 完全一致的理念 |

### 3.2 记忆 ≠ RAG

两者都强调这一根本区分：

| | Emerald | Supermemory |
|---|---|---|
| **RAG 定义** | 无状态文档检索，所有人结果相同 | 无状态文档块检索，静态结果 |
| **记忆定义** | 有状态事实追踪，理解时序演进和矛盾 | 有状态事实追踪，自动处理更新和矛盾 |
| **典型示例** | Adidas→Puma 偏好转变 | React 17→React 18 版本更新 |
| **默认行为** | **混合搜索**（RAG + 记忆同时返回） | **混合搜索**（hybrid mode） |

### 3.3 知识图谱结构

两者都采用「**事实建立在其他事实之上**」的图谱模型，而非传统的实体-关系-实体三元组。

```
# Emerald
「用户在 Google 工作」 --UPDATES--> 「用户在 Stripe 工作」
「用户在 Stripe 工作」 --EXTENDS--> 「用户领导 5 人支付团队」

# Supermemory
「User prefers React 17」 --Updates--> 「User now uses React 18」
「User likes TypeScript」 --Extends--> 「User completed TS tutorial」
```

**细微差异：**
- Emerald 的关系命名使用全大写（`UPDATES`/`EXTENDS`/`DERIVES_FROM`），Supermemory 使用首字母大写（`Updates`/`Extends`/`Derives`）。
- Emerald 的推导关系命名为 `DERIVES_FROM`，Supermemory 为 `Derives`。

---

## 4. API 设计对比

### 4.1 核心方法对照

| 操作 | Emerald API | Supermemory API |
|---|---|---|
| 保存内容 | `client.add(content, entity_id=...)` | `client.add({ content, containerTag })` |
| 搜索 | `client.search(q, entity_id=..., search_mode=...)` | `client.search.memories({ q, containerTag, searchMode })` |
| 用户画像 | `client.profile(entity_id)` | `client.profile({ containerTag, q? })` |
| 上传文件 | `client.upload(file, entity_id=...)` | `client.documents.uploadFile({ file, containerTag })` |
| 列出文档 | — | `client.documents.list({ containerTag })` |
| 删除文档 | — | `client.documents.delete({ docId })` |
| 健康检查 | `client.health()` | — |
| 管线状态 | `client.pipeline_status(pipeline_id)` | 通过 `documents.list(status=...)` 间接查询 |

### 4.2 命名风格

| | Emerald | Supermemory |
|---|---|---|
| **参数风格** | Pythonic: `entity_id`, `content_type`, `search_mode` | TypeScript 风格: `containerTag`, `entityContext`, `searchMode` |
| **标识符** | `em_xxx` (API Key), `mem_xxx` (记忆 ID) | `sm_xxx` (API Key), `doc_xxx`/`mem_xxx` (文档/记忆 ID) |
| **搜索模式** | `hybrid` / `memory` / `rag` | `hybrid` / `semantic` / `memories` |

### 4.3 API 设计哲学

**共同点（极其一致）：**
- 都追求**最小接口面**：4 个核心方法覆盖 80% 用例
- 都使用**实体隔离**：每个操作限定在 `entity_id`/`containerTag` 范围内
- 都遵循**声明式**设计：开发者描述要什么，不配置怎么实现
- 都提供**开箱即用默认值**：自动内容类型检测、默认混合搜索

**差异点：**
- Supermemory 的 API 更丰富：`documents.list/delete`、`settings.update`，以及更复杂的 metadata filtering（支持 `$and`/`$or` 逻辑、数值比较 `$gte` 等）。
- Emerald 的 API 更精简：`add`/`search`/`profile`/`upload` + `health`/`pipeline_status`，符合 AGENTS.md 中「最小接口面」原则。
- Supermemory 支持 `customId` 幂等性写入，Emerald 目前未提及此功能。
- Supermemory 的 `profile()` 方法可以**同时返回画像和搜索结果**（如果传入 `q` 参数），Emerald 的 `profile()` 和 `search()` 是分开的两个调用。

### 4.4 REST API 端点

| 功能 | Emerald | Supermemory |
|---|---|---|
| 添加记忆 | `POST /v1/memories` | `POST /v3/documents` / `POST /v4/memories` |
| 搜索 | `POST /v1/search` | `POST /v4/search` |
| 获取画像 | `GET /v1/profiles/{id}` | `POST /v4/memories`（间接）+ `profile()` SDK 方法 |
| 上传文件 | `POST /v1/upload` | `POST /v3/documents`（内容可以是文件路径） |
| 管线状态 | `GET /v1/pipelines/{id}` | 通过文档列表查询 |
| 指标 | `GET /v1/metrics`（Prometheus） | 未公开 |

Supermemory 的 API 版本演进更成熟（v3→v4），Emerald 目前统一使用 v1。

---

## 5. 功能特性矩阵

### 5.1 核心功能

| 功能 | Emerald | Supermemory |
|---|---|---|
| **自动事实提取** | ✅ 从对话/文本中自动提取结构化事实 | ✅ 自动提取记忆，支持 `entityContext` 引导 |
| **时序追踪** | ✅ `created_at` + `is_latest` + Update 关系 | ✅ 完整版本历史，支持查看最新/全部/特定版本 |
| **矛盾解决** | ✅ 自动检测矛盾，旧事实标记 `is_latest=false` | ✅ 自动处理，旧记忆保留历史但搜索中隐藏 |
| **自动遗忘** | ✅ 时间过期 + 噪音过滤 + 情节衰减（Celery Beat） | ✅ 临时事实过期 + 矛盾解决 + 噪音过滤 |
| **用户画像** | ✅ 静态 + 动态双层，<50ms，Redis 缓存 | ✅ 静态 + 动态双层，~50ms，缓存 |
| **混合搜索** | ✅ `hybrid`/`memory`/`rag` 三种模式 | ✅ `hybrid`/`semantic` 模式，支持 metadata filtering |
| **重排序** | ✅ 交叉编码器 | 未明确提及 |
| **查询改写** | ✅ 短查询扩展 | 未明确提及 |
| **关系推断** | ✅ 自动分类 UPDATES/EXTENDS/DERIVES_FROM | ✅ 自动建立 Updates/Extends/Derives 关系 |

### 5.2 内容处理

| 内容类型 | Emerald | Supermemory |
|---|---|---|
| **纯文本** | ✅ 自动检测 | ✅ |
| **对话** | ✅ 多轮对话，说话人标注 | ✅ |
| **URL** | ✅ 抓取 + 清洗 | ✅ |
| **PDF** | ✅ 文本 + 表格 + OCR | ✅ |
| **图片** | ✅ OCR + 视觉描述 | ✅ OCR + 图像理解 |
| **音频** | ✅ Faster-Whisper 转录 | ✅ 语音转文字 |
| **视频** | ✅ 音轨转录 + 关键帧 OCR | ✅ 转录 + 场景检测 |
| **代码** | ✅ **AST 感知分块**（Python/TS/JS/Go/Rust） | ✅ 语义分块 |
| **Markdown** | ✅ 按标题层级分块 | ✅ 语义分块 |
| **结构化数据** | ✅ JSON、CSV 自动检测 | 未明确提及 |

**细微差异：**
- Emerald 对代码的分块策略更具体：AST 感知（函数、类保持完整）。Supermemory 文档中只提到「semantic chunking」，未细化到 AST 级别。
- Emerald 明确支持结构化数据（JSON/CSV），Supermemory 文档未重点提及。
- Supermemory 支持 `entityContext` 参数来引导提取（"这是关于前端框架偏好的对话"），Emerald 目前未提供类似功能。

### 5.3 连接器（外部数据源同步）

| 连接器 | Emerald | Supermemory |
|---|---|---|
| **GitHub** | ✅ OAuth + 增量同步 | ✅ |
| **Google Drive** | ✅ OAuth + Webhook | ✅ |
| **Gmail** | ✅ OAuth + 增量同步 | ✅ |
| **Notion** | ✅ OAuth + 增量同步 | ✅ |
| **OneDrive** | — | ✅ |
| **Web Crawler** | — | ✅ |

Supermemory 的连接器生态更丰富（多一个 OneDrive 和 Web Crawler）。

### 5.4 搜索与过滤

| 功能 | Emerald | Supermemory |
|---|---|---|
| **语义搜索** | ✅ 向量相似度 | ✅ HNSW，O(log n) |
| **混合搜索（RAG+记忆）** | ✅ 默认模式 | ✅ hybrid 模式 |
| **metadata 过滤** | 基础支持 | ✅ 高级：$and/$or、数值比较、数组包含、字符串包含 |
| **阈值调节** | `top_k` + `rerank` | `chunkThreshold` (0-1) + `threshold` |
| **关系扩展** | 搜索时沿关系图谱扩展 | ✅ Relationship Expansion（搜索结果沿关系链扩展） |
| **按文档搜索** | — | ✅ `docId` 限定搜索范围 |

Supermemory 在搜索过滤能力上明显更强，特别是 metadata filtering 的表达能力。

---

## 6. 生态与框架集成

### 6.1 SDK 与语言支持

| | Emerald | Supermemory |
|---|---|---|
| **Python SDK** | ✅ `emerald.sdk.EmeraldClient` | ✅ `supermemory` (PyPI) |
| **TypeScript SDK** | — | ✅ `supermemory` (npm) |
| **异步支持** | ✅ `async/await` | ✅ `AsyncSupermemory` |
| **同步支持** | — | ✅ 同步客户端 |

Supermemory 的 SDK 覆盖更广（TypeScript + Python），Emerald 目前只有 Python SDK。

### 6.2 框架集成

| 框架 | Emerald | Supermemory |
|---|---|---|
| **Vercel AI SDK** | — | ✅ `@supermemory/ai-sdk` + Infinite Chat Provider |
| **LangChain** | — | ✅ 官方集成 |
| **LangGraph** | — | ✅ 官方集成 |
| **OpenAI Agents SDK** | — | ✅ 官方集成 |
| **Mastra** | — | ✅ 官方集成 |
| **Agno** | — | ✅ 官方集成 |
| **n8n** | — | ✅ 官方集成 |
| **CrewAI** | — | ✅ 示例代码 |
| **Pandaria (Rust)** | ✅ `EmeraldMemoryStore` HTTP 适配器 | — |

Supermemory 的框架集成生态全面领先，几乎覆盖所有主流 AI 框架。Emerald 目前仅有 Pandaria（Rust Agent Runtime）的官方适配器。

### 6.3 MCP (Model Context Protocol)

| | Emerald | Supermemory |
|---|---|---|
| **MCP Server** | ✅ 内置 `emerald.mcp.server`（stdio + SSE） | ✅ `https://mcp.supermemory.ai/mcp` |
| **暴露工具** | `emerald_add`, `emerald_search`, `emerald_profile` | `memory`, `recall`, `context` |
| **安装方式** | `python -m emerald.mcp.server` | `npx install-mcp` |
| **OAuth 支持** | — | ✅ 一键 OAuth 安装 |
| **支持客户端** | Claude Desktop, Cursor 等 | Claude Desktop, Cursor, Windsurf, VS Code, Claude Code, OpenCode, OpenClaw, Hermes |

Supermemory 的 MCP 集成更成熟，支持 OAuth 一键安装和更多客户端。Emerald 的 MCP Server 是自托管的，需要手动配置环境变量。

### 6.4 消费者产品

| | Emerald | Supermemory |
|---|---|---|
| **Web App** | — | ✅ `app.supermemory.ai` |
| **浏览器插件** | — | ✅ 保存网页到记忆 |
| **桌面端** | — | — |
| **移动端** | — | — |
| **内嵌 Agent** | — | ✅ Nova Agent |
| **编辑器插件** | — | ✅ Raycast 扩展 |

Supermemory 有完整的消费者产品矩阵，Emerald 目前纯面向开发者。

---

## 7. 性能与基准

### 7.1 延迟指标

| 指标 | Emerald | Supermemory |
|---|---|---|
| **用户画像获取** | < 50ms（冷启动），Redis 缓存 | ~50ms |
| **搜索延迟** | 未公开基准 | < 50ms (p95) |
| **文档处理** | 未公开 | 文本 10s / URL 30s / PDF 1-2min / 视频 5-10min |
| **处理吞吐量** | 未公开 | 10,000 文档/小时 |

### 7.2 基准测试成绩

| 基准 | Emerald | Supermemory |
|---|---|---|
| **LongMemEval** | 未测试（有评估脚本） | **81.6% — #1** |
| **LoCoMo** | 未测试（有评估脚本） | **#1** |
| **ConvoMem** | 未测试（有评估脚本） | **#1** |

Supermemory 是三项主要记忆基准的绝对领先者。Emerald 目前处于 v0.3.0，已有基准评估脚本但尚未公布测试成绩。

### 7.3 可观测性

| | Emerald | Supermemory |
|---|---|---|
| **日志** | ✅ 结构化 JSON 日志，每个管线阶段记录 entity_id/内容类型/耗时/分块数/关系数/错误状态 | 未公开 |
| **指标** | ✅ Prometheus (`/v1/metrics`)：摄入吞吐量、提取延迟、画像延迟、搜索延迟、关系密度 | 未公开 |
| **APM** | — | `status.supermemory.ai` |

Emerald 在可观测性设计上非常完善（符合 AGENTS.md 要求），Supermemory 作为 SaaS 内部指标未对外公开。

---

## 8. 成熟度与可用性

| 维度 | Emerald | Supermemory |
|---|---|---|
| **版本** | v0.3.0 | 生产级（未公开版本号） |
| **测试覆盖** | 484 tests passing | 未公开 |
| **API 版本** | v1（单一版本） | v3→v4（持续演进） |
| **文档完整度** | ✅ README + AGENTS.md + 架构文档 + 集成指南 | ✅ 完整文档站 + API 参考 + SDK 指南 + 用例 |
| **社区** | 早期开源项目 | Discord + Twitter + 活跃社区 |
| **SLA** | 自托管，无 SLA | SaaS，有服务保障 |
| **安全认证** | API Key SHA-256 存储，AES-256-GCM OAuth 加密 | SOC 2, GDPR, AES-256 at rest, TLS 1.3 |

---

## 9. 差异化总结与场景建议

### 9.1 核心差异速览

| 差异点 | Emerald | Supermemory |
|---|---|---|
| **数据控制权** | ✅ 完全私有 | ⚠️ 云端托管 |
| **定制能力** | ✅ 可修改任何代码 | ❌ 仅 API 参数 |
| **基础设施成本** | 需自运维 | 按量付费 |
| **框架集成广度** | 初阶（Python + Pandaria） | 全面（所有主流框架） |
| **消费者产品** | ❌ | ✅ 完整矩阵 |
| **基准成绩** | 待验证 | ✅ 三项 #1 |
| **metadata 过滤** | 基础 | ✅ 高级表达式 |
| **API 成熟度** | v1，4 个核心方法 | v4，更丰富的方法集 |

### 9.2 选择建议

**选择 Emerald，如果你：**
- 🔒 **数据隐私是硬要求**——金融、医疗、政府等敏感行业，数据不能出内网
- 🔧 **需要深度定制**——需要修改提取逻辑、分块策略、关系推断算法，或集成内部系统
- 💰 **长期基础设施成本敏感**——自有硬件上运行，避免 SaaS 按量付费的累积成本
- 🐍 **Python 技术栈**——团队主要使用 Python，希望深度理解和调试记忆管线
- 🧪 **在研究/实验阶段**——希望 fork 代码、修改图谱结构、探索新的记忆算法

**选择 Supermemory，如果你：**
- 🚀 **追求最快上线速度**——`npm install supermemory`，5 分钟集成，零运维
- 🌐 **需要全球低延迟**——Supermemory 的分布式部署提供 <50ms p95 搜索延迟
- 🔗 **使用多种 AI 框架**——LangChain、Mastra、Vercel AI SDK 等，需要官方 drop-in 集成
- 👥 **有消费者用户**——需要浏览器插件、App 等消费级产品
- 📊 **需要经过验证的基准性能**——三项记忆基准 #1，性能已验证
- 🛠️ **不想维护基础设施**——无 Neo4j、PostgreSQL、Redis 运维经验或人力

### 9.3 战略关系

Emerald 和 Supermemory 不是零和竞争关系，而是**同源不同路**：

- **Supermemory 是「标杆 SaaS」**——定义了记忆系统的最佳实践和行业标准，用托管服务降低使用门槛。
- **Emerald 是「开源基础设施」**——为需要数据主权和深度定制的企业提供 Supermemory 理念的开源实现。

二者共享同一套记忆本体论（记忆≠RAG、三种关系类型、静态/动态画像、自动遗忘），开发者从 Supermemory 入门理解概念，在需要私有化时迁移到 Emerald——这是理想的路径。

---

## 附录：API 代码对照

### 添加记忆

```python
# Emerald
from emerald.sdk import EmeraldClient
client = EmeraldClient()
await client.add(
    "用户喜欢 TypeScript",
    entity_id="user_123",
    content_type="text"
)

# Supermemory
from supermemory import Supermemory
client = Supermemory()
client.add(
    content="用户喜欢 TypeScript",
    container_tag="user_123"
)
```

### 搜索

```python
# Emerald
results = await client.search(
    "TypeScript",
    entity_id="user_123",
    search_mode="hybrid",
    top_k=10
)

# Supermemory
results = client.search.memories(
    q="TypeScript",
    container_tag="user_123",
    search_mode="hybrid",
    limit=10
)
```

### 获取画像

```python
# Emerald
profile = await client.profile("user_123")
print(profile.static)   # 静态事实列表
print(profile.dynamic)  # 动态事实列表

# Supermemory
result = client.profile(container_tag="user_123")
print(result["profile"]["static"])   # 静态记忆列表
print(result["profile"]["dynamic"])  # 动态记忆列表
```

---

*文档生成时间：2026-06-01*
*基于 Emerald v0.3.0 与 Supermemory 公开文档对比*
