# Emerald

**面向 AI Agent 的记忆与上下文基础设施。**

AI Agent 在每次对话之间会遗忘一切。Emerald 解决了这个问题。它自动从对话中学习、提取事实、构建用户画像、处理知识更新和矛盾、遗忘过期信息，并在恰当的时机传递正确的上下文——这一切通过一个简洁的 API 完成。

| | |
|---|---|
| **记忆引擎** | 从对话中提取事实。处理时序变化、矛盾解决和自动维护——6 种策略：时间过期、矛盾取代、噪音过滤、情节衰减、社区遗忘、重复整合。 |
| **用户画像** | 自动维护的用户上下文——稳定事实 + 近期动态。一次调用，~50ms。 |
| **混合搜索** | 单次查询同时返回 RAG 结果和记忆结果，知识库文档与个性化上下文合为一体。 |
| **图谱深度** | 提及节点（NER，ADR-0005）+ 实体中心检索（`about=`）+ 多跳图谱推理（`depth` ≤ 4，路径与跳数透明）。 |
| **连接器** | 接入连接中心 Totem（ADR-0004，内部自托管动作层）：OAuth/同步/执行外包，Emerald 维护数据源绑定；Pilot 验证通过（2026-08-10） |
| **多模态提取** | PDF、图片（OCR）、视频（转录）、代码（AST 感知分块）。上传即可用。 |
| **Web UI** | 内置 Web 控制台（ADR-0003，产品层）：摄入、三态搜索、画像、流式对话、图谱可视化。compose 起栈后浏览器即用。 |

所有这一切运行在同一个记忆图谱之上——记忆、画像和搜索共享同一个上下文池。

---

## 工作原理

```
你的应用 / AI Agent / 浏览器（Web UI）
      ↓
   Emerald
      │
      ├── 记忆引擎     提取事实、追踪更新、解决矛盾、自动遗忘过期信息
      ├── 用户画像     静态事实 + 动态上下文，始终最新
      ├── 混合搜索     RAG + 记忆，一次查询；提及桥 + 关系链多跳扩展
      ├── 数据源绑定  经连接中心接入外部数据源
      └── 文件处理     PDF、图片、视频、代码 → 可搜索的分块
```

1. 你将文本、文件、URL 和对话发送给 Emerald。
2. Emerald 智能地索引它们，并在每个实体（用户、项目、组织）之上构建语义理解图谱。
3. 查询时，Emerald 仅获取最相关的上下文传递给模型。

---

## 记忆 vs RAG —— 根本区别

这是最重要的概念。记忆不是 RAG。

**RAG** 回答：*「我知道什么？」*
**记忆** 回答：*「我记得你的什么？」*

| | RAG | 记忆 |
|---|---|---|
| **状态** | 无状态——所有人结果相同 | 有状态——每个用户/实体各不相同 |
| **时序** | 没有时间概念 | 追踪事实何时为真、何时过期 |
| **关系** | 无 | 事实建立在其他事实之上（更新、扩展、推导） |
| **遗忘** | 从不遗忘 | 自动过期临时事实、解决矛盾 |
| **适用场景** | 文档、知识库、通用问答 | 用户偏好、对话历史、个人事实 |

**示例：** 某用户第 1 天说喜欢 Adidas 运动鞋，第 30 天抱怨鞋子坏了、质量极差，第 31 天说改用 Puma。第 45 天被问「我该买什么运动鞋？」——RAG 返回「喜欢 Adidas」（语义相似度最高）。记忆返回「现在偏好 Puma」，因为它追踪了时序演进和矛盾。Emerald 默认同时运行两者。

---

## 图谱记忆

Emerald 构建一个活的知识图谱，记忆与记忆彼此连接。与传统实体-关系-实体的三元组图谱不同，Emerald 的图谱是**建立在其他事实之上的事实**。

### 三种关系类型

**更新 — 信息变化**

当新信息与已有知识矛盾时，Emerald 将旧事实标记为被取代，并用 `isLatest` 字段追踪最新版本。

```
「你在 Google 工作」 → 「你刚加入 Stripe」
                        记忆 2 更新 记忆 1
```

**扩展 — 信息丰富**

当新信息在不取代的情况下补充已有知识时，Emerald 将它们连接起来。两个事实都保持有效且可搜索。

```
「你在 Stripe 工作」 → 「你领导一个 5 人的支付团队」
                        记忆 2 扩展 记忆 1
```

**推导 — 信息推理**

当 Emerald 从模式中检测并推理出你未明确陈述的新事实时。

```
「Dhravya 是创始人」 + 「Dhravya 每天都在讨论 AI」
                       → 「Emerald 很可能是一家 AI 公司」
```

### 提及节点

除了记忆之间的三种关系，Emerald 还把记忆中提到的命名事物解析为图节点（ADR-0005）：

```
「Alex 在 Stripe 工作」── MENTIONS ──> (Mention: Stripe，类型 = organization)
```

- **非事实引用类别**——提及不是第四种关系，是记忆 → 事物的引用
- **规范形式去重**——「谷歌」「Google」「GOOGLE」解析到同一节点，表层别名累积
- **封闭分类法**——person / organization / location / technology / concept 五类，域外回退 concept
- **规则提取**——确定性路径（无 LLM），低置信丢弃，创建/重复附加幂等

提及节点是图谱深度的物理基底：共享同一提及的记忆互为兄弟，多跳推理沿提及桥行走。

### 实体中心检索与多跳推理

搜索不只是向量相似度——图谱遍历是 `search` 的深度参数：

```python
# 实体中心检索：该实体上下文池内提及 Stripe 的全部最新记忆（跨所有表层形式）
results = client.search(
    q="", entity_id="user_123", search_mode="memory", about="Stripe"
)

# 多跳推理：沿共享提及桥 + UPDATES/EXTENDS/DERIVES_FROM 链式行走（depth 0-4）
results = client.search(q="支付基础设施", entity_id="user_123", depth=2)
for r in results.results:
    if r.depth > 0:
        print(r.depth, r.path)  # 每个多跳结果携带 path（途经节点与边）与 depth 溯源
```

- **共享主体串联**：提及同一事物的记忆一跳互达
- **关系链式**：`D2 ← D1 ← A`，查 A 时 D2 以 depth 2 浮现
- **路径透明**：结果携带 `path` 与 `depth`；排名按信任分 × 0.85^depth 折扣，同分种子在前
- **历史不穿越**：被取代的事实只在沿 UPDATES 被踩到时浮出，从不主动返回历史
- **默认关闭**：`depth=0` 行为与现状完全一致，显式 opt-in

### 自动记忆提取

从一段对话中，Emerald 提取出多个相互关联的事实：

> *「刚和 Alex 打了个很棒的沟通电话。他挺喜欢 Stripe 的 PM 新角色，不过支付基础设施的工作强度很大。他为此搬去了西雅图，在 Capitol Hill 租了房子。还说下次我来这边要一起吃个饭。」*

提取出的记忆：
- Alex 在 Stripe 担任 PM
- Alex 负责支付基础设施（*扩展角色记忆*）
- Alex 住在西雅图 Capitol Hill
- Alex 想约一顿饭（*情节记忆*）

每个事实自动连接到相关记忆。你无需手动定义关系、打标签、清理旧记忆或解决矛盾。只需添加内容，然后搜索。

### 自动遗忘

Emerald 知道什么时候记忆不再有意义——6 种自动维护策略，全部后台调度、零手动干预：
- **基于时间：**「我明天有考试」——考试日期过后自动遗忘
- **矛盾解决：**被更新取代的旧事实保留历史记录，但不在搜索中返回
- **噪音过滤：**随意的、无意义的内容不会成为永久记忆
- **情节衰减：**不重要的事件随时间推移失去相关性
- **社区遗忘：**标签传播划分记忆社区，活性评分（置信度/时近性/密度/画像引用）低的社区整体淘汰；桥接记忆与画像引用豁免
- **重复整合：**语义重复组收敛为单代表（确定性全序），护栏否决（画像保护/矛盾/UPDATES 边）绝不被绕过——误并率 = 0 硬门

### 记忆类型（自动检测）

| 类型 | 示例 | 行为 |
|---|---|---|
| **事实** | 「Alex 在 Stripe 担任 PM」 | 持续有效，直到被更新 |
| **偏好** | 「Alex 偏好上午开会」 | 随重复次数增强 |
| **情节** | 「周二和 Alex 喝了咖啡」 | 除非重要，否则衰减 |

---

## 用户画像

传统记忆依赖搜索——你需要知道要问什么。Emerald 自动为每个实体维护一个丰富的画像。

```python
result = client.profile(entity_id="user_123")
print(result.profile.static)   # 静态事实
print(result.profile.dynamic)  # 动态上下文
```

| | 描述 | 示例 |
|---|---|---|
| **静态** | Agent 应始终知晓的稳定事实 | 「资深工程师」「偏好深色模式」「使用 Vim」 |
| **动态** | 情节性的、近期的上下文 | 「正在进行认证迁移」「正在调试限流问题」 |

一次调用。注入系统提示词，你的 Agent 瞬间就知道在和谁对话。开发者可根据使用场景配置哪些内容属于静态、哪些属于动态。

---

## 混合搜索

Emerald 将 RAG 和记忆统一为一次查询。同一个上下文池，按需混合使用。

```python
# 默认：混合模式 — RAG + 记忆一起返回
results = client.search(
    q="如何部署？",
    entity_id="user_123",
    search_mode="hybrid"
)
# 返回：部署文档（RAG）+ 用户的部署偏好（记忆）

# 仅记忆
results = client.search(q="用户偏好", search_mode="memory")

# 仅文档
results = client.search(q="API 参考", search_mode="rag")
```

优化能力：
- **重排序：** 使用交叉编码器对结果重新评分，复杂查询精度更高
- **查询改写：** 扩展短查询以获得更高召回率

---

## 支持的内容类型

所有内容经过同一管线：提取 → 分块 → 嵌入 → 关系构建。

| 类型 | 处理方式 |
|---|---|
| **文本** | 聊天消息、笔记、转录文本、原始字符串 |
| **对话** | 多轮对话，附带说话人标注 |
| **URL** | 抓取、清洗（去除导航和广告）、提取正文 |
| **PDF** | 文本 + 表格 + 标题，扫描件支持 OCR |
| **图片** | OCR 文字识别、视觉描述（PNG、JPG、WebP、GIF） |
| **音频** | 转录、说话人检测（MP3、WAV、M4A） |
| **视频** | 转录、主题分割（MP4、WebM） |
| **代码** | AST 感知分块——函数、类、逻辑块保持完整 |
| **Markdown** | 按标题层级分块，保留文档结构 |
| **结构化数据** | JSON、CSV，自动检测并索引 |

二进制文件使用 base64 编码。Emerald 自动检测内容类型——仅二进制上传时需要指定 `content_type`。

---

## 处理管线

| 阶段 | 发生什么 |
|---|---|
| **排队** | 内容等待处理 |
| **提取** | 按类型特定方式提取（OCR、转录、AST 解析） |
| **分块** | 按内容类型采用最优分块策略 |
| **嵌入** | 生成向量表示 |
| **索引** | 构建关系，连接到图谱 |
| **完成** | 完全可搜索，已融入记忆 |

---

## API 概览

```python
# 存储内容——文本、对话、URL、文件
client.add(content="用户喜欢 TypeScript", entity_id="user_123")

# 获取用户画像 + 搜索，一次调用
result = client.profile(
    entity_id="user_123",
    q="用户偏好什么编程风格？"
)

# 跨记忆和文档的混合搜索
results = client.search(
    q="部署最佳实践",
    entity_id="user_123",
    search_mode="hybrid"
)

# 上传并处理文件
client.upload(file=pdf_bytes, title="架构文档.pdf")
```

无需配置向量数据库。无需搭建嵌入管线。无需选择分块策略。只需添加内容和搜索。

---

## TypeScript SDK

Emerald 提供官方 TypeScript SDK（`@emerald/sdk`），与 Python SDK 方法集一一对应，支持浏览器、Node.js、Bun、Deno 等运行时。

```ts
import { EmeraldClient, EmeraldNotFoundError } from "@emerald/sdk";

const client = new EmeraldClient({ apiKey: "em_xxx" });

await client.add("用户偏好 TypeScript", "user_123");
const results = await client.search("TypeScript", "user_123");
const profile = await client.profile("user_123");
```

支持 typed 异常体系（`EmeraldAuthError` / `EmeraldNotFoundError` / `EmeraldValidationError` / `EmeraldRateLimitError` / `EmeraldServerError` / `EmeraldNetworkError`）和 `async with` 上下文管理器。详见 [`sdk/typescript/README.md`](sdk/typescript/README.md) 与 [`docs/api/sdk-guide.md`](docs/api/sdk-guide.md)。

---

## Web UI

Emerald 内置 Web 控制台（ADR-0003：web UI 是产品层，所有操作走同一套 REST API）。compose 起栈后浏览器直接可用：

```bash
docker compose up -d
# 打开 http://localhost（nginx :80 对外；其余服务仅绑 127.0.0.1）
# 以 API key + Entity ID 登录；前端开发模式用 docker-compose.dev.yml override
```

| 能力 | 说明 |
|---|---|
| **摄入** | 快速笔记 + 弹窗三 tab：Note 直存 / Link 元数据记忆 / File 上传（管线状态轮询，完成报告记忆数，失败显式报错） |
| **搜索** | memory / rag / hybrid 三态真实切换；Spaces 过滤（指定空间或默认全池） |
| **画像** | 静态事实 + 记忆统计，新摄入管线完成后即时反映 |
| **对话** | SSE 流式输出；检索记忆 + 画像注入 system prompt；无 LLM key 时显式降级为「记忆检索模式」；支持 OpenAI 兼容后端（`OPENAI_BASE_URL` / `OPENAI_MODELS`） |
| **图谱** | 记忆关系图可视化 |
| **整合** | 数据源绑定（连接中心 Totem）面板 |

Web 核心循环以 [`docs/web-core-loop-standard.md`](docs/web-core-loop-standard.md) 为发布门——摄入/搜索/画像/对话四环黑盒走查验收。

---

## Pandaria 集成

[Pandaria](https://github.com/earendil-works/pandaria)（Rust Agent Runtime）通过 HTTP 适配器 `EmeraldMemoryStore` 与 Emerald 集成。Agent 的每一轮对话自动保存到 Emerald，后续对话自动召回相关记忆。

```rust
use pandaria::memory::EmeraldMemoryStore;

let memory = EmeraldMemoryStore::new(
    "http://localhost:8000",
    "em_xxx",
);

// 自动调用：remember() → POST /v1/memories
// 自动调用：recall()  → POST /v1/search
```

- `tenant_id` → `entity_id`（跨 session 用户级记忆）
- `session_id` → `metadata.session_id`（session 级追踪）
- `content_type="conversation"`（自动识别 **User**:/**Assistant**: 格式）

详见 [`docs/integration-guide.md`](docs/integration-guide.md)。

---

## MCP Server

Emerald 提供 [MCP (Model Context Protocol)](https://modelcontextprotocol.io) 服务，任何 MCP 客户端（Claude Desktop、Cursor 等）可直接调用记忆操作。

```bash
# stdio 模式（Claude Desktop 推荐）
EMERALD_API_KEY=em_xxx python -m emerald.mcp.server --transport stdio

# SSE 模式（远程访问）
EMERALD_API_KEY=em_xxx python -m emerald.mcp.server --transport sse --port 8001
```

暴露 3 个工具：
- `emerald_add` — 保存记忆
- `emerald_search` — 搜索记忆和文档
- `emerald_profile` — 获取用户画像

Claude Desktop 配置 (`claude_desktop_config.json`)：

```json
{
  "mcpServers": {
    "emerald": {
      "command": "python",
      "args": ["-m", "emerald.mcp.server", "--transport", "stdio"],
      "env": {
        "EMERALD_API_KEY": "em_xxx",
        "EMERALD_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

Docker Compose 已包含 `mcp` 服务：

```bash
docker compose up -d mcp
# SSE 端点：http://localhost:8001
```

---

## 项目状态

**当前版本：v0.7.0**（2026-08-29）。v0.5.0 完成 M2（测试卫生 / 独立侧质量套件 / 真实嵌入绝对分报告 / 安全审计，按 ADR-0001 重裁剪）；v0.6.0 按 ADR-0004 退役自研连接器；**v0.7.0 完成 M3「图谱深化与文档」**——B3 提及层 / B4 多跳推理 / B5 社区遗忘 / B6 重复整合 / A5 文档 overhaul / web 核心循环补全，发布门 #52 黑盒走查 19/19 过。详细变更见 [`CHANGELOG.md`](CHANGELOG.md)；生产就绪度见 [`docs/production-readiness-assessment.md`](docs/production-readiness-assessment.md)；长期路线图见 [`docs/roadmap.md`](docs/roadmap.md)。

**测试规模**：1207 个测试（含独立侧质量套件七节——时序 / 遗忘 / 图谱精度 / 提及 / 多跳 / 社区遗忘 / 整合 + 安全回归 + 基准链路）。

### v0.3.0 核心模块（已发布）

| 模块 | 状态 | 说明 |
|---|---|---|
| 文本管线 | ✅ 完整 | 提取→分块→嵌入→索引，端到端可工作 |
| 全内容类型 | ✅ 完整 | 10 种 extractor + 7 种 chunker（含 JSON/CSV 结构化分块与 text/markdown 别名），含优雅降级 |
| 关系推断引擎 | ✅ 完整 | UPDATES / EXTENDS / DERIVES_FROM 自动分类并写入图谱 |
| 用户画像 | ✅ 完整 | 静态+动态事实，Redis 缓存，< 50ms 冷启动 |
| 混合搜索 | ✅ 完整 | Memory + RAG 合并，支持重排序和查询改写 |
| 遗忘引擎 | ✅ 完整 | 时间过期、噪音过滤、情节衰减（Celery Beat） |
| REST API | ✅ 完整 | 12 组 v1 路由（memories/search/profiles/upload/pipelines/conflicts/extract/sessions/sources/spaces/system/keys） |
| Python SDK | ✅ 完整 | add / search / profile / upload / health / pipeline_status，typed 异常 + async context manager |
| 连接器 | ✅ 已退役 | 自研连接器已删除（issue #7，ADR-0004）；统一接入连接中心 Totem（内部自托管：OAuth/执行/审计外包，Emerald 维护数据源绑定，见 [验证记录](docs/verification/totem-pilot-verification.md)） |
| MCP Server | ✅ 完整 | stdio + SSE 双模式，3 个工具（add / search / profile） |
| 基准测试 | ✅ 公开报告 | 7 维度合成对抗场景（含矛盾链）+ 独立侧质量套件三节；真实嵌入绝对分报告已公开（Aggregate 0.943，ADR-0001，见 [`docs/benchmarks/`](docs/benchmarks/)） |
| 可观测性 | ✅ 完整 | Prometheus 指标 (`/v1/metrics`) + 结构化 JSON 日志 + OpenTelemetry 手动 span 集成 |
| Docker E2E | ✅ 完整 | `docker-compose.test.yml` + `.env.test`，全栈集成测试通过 |

### v0.4.0 增量（v0.3.0 → v0.4.0）

**M1 — 部署与可观测性加固**
- ✅ Dockerfile production stage 独立 `pip install`，镜像 < 1.2GB
- ✅ K8s manifest + 灾备演练脚本（`scripts/disaster_recovery_drill.sh`）
- ✅ OpenTelemetry 自动 instrumentation（FastAPI / SQLAlchemy / httpx / Redis）
- ✅ Locust 负载测试基础设施（`tests/load/`）
- ✅ CI 自动化（`scripts/generate_openapi.py --check` + drift 测试）

**M2 — API / SDK / 安全加固**
- ✅ **TypeScript SDK v1**（`sdk/typescript/`，对齐 Python SDK 方法集，typed 异常，async 支持）
- ✅ 错误码体系（[`docs/api/error-codes.md`](docs/api/error-codes.md)）+ OpenAPI 自动生成（`scripts/generate_openapi.py`）
- ✅ API 分页（memories 列表）+ 限流响应头（`X-RateLimit-Remaining` / `Retry-After`）
- ✅ P0：跨实体上传授权（`authorize_entity()` 集中到 `emerald/api/dependencies.py`）
- ✅ OAuth state 存 Redis（`OAuthStateStore`，TTL 10 分钟，多 worker 安全）
- ✅ CORS 生产加固（wildcard 在 production 启动时拒绝）
- ✅ SDK typed 异常（`EmeraldAuthError` / `EmeraldValidationError` / `EmeraldRateLimitError` 等）

**M3 增量能力**
- ✅ LLM 事实提取（DeepSeek V4-Flash，多事实分解、类型分类、置信度评分）
- ✅ 图谱搜索遍历（`_expand_relationships()` 沿 EXTENDS / DERIVES_FROM 双向）
- ✅ 首选项强化（重复偏好 +0.05 置信度）
- ✅ 本地嵌入（[fastembed](https://github.com/qdrant/fastembed)，ONNX 无 PyTorch）
- ✅ 批量写入（`POST /v1/memories/batch`，最多 50 条）
- ✅ 图谱可视化（`GET /v1/memories/graph`）
- ✅ MongoDB 风格元数据过滤（`$and` / `$or` / `$gte` / `$lte` / `$eq` / `$ne`）
- ✅ 双写一致性（`ReconciliationEngine` 后台修复孤立节点）
- ✅ Redis 分布式锁（防止 Celery Beat 多实例并发）
- ✅ Neo4j 生产配置（连接池、超时、重试）
- ✅ 多因子画像评分（置信度 35% + 时近性 25% + 类型 20% + 关系 20%）

### v0.5.0 增量（v0.4.0 → v0.5.0）— M2 质量与稳定

按 ADR-0001 重裁剪 M2 范围为「测试卫生 → 独立侧质量套件 → 绝对分报告 → 安全审计」：
- ✅ 独立侧质量套件三节（`tests/quality/temporal/`：时序正确性 65 例 / 遗忘有效性 / 图谱关系精度 61 例）+ CI 聚合门（`quality-temporal`）
- ✅ 修复规则矛盾检测误伤（含「不」即判取代曾致 19 条无关事实被标记过期；Fact Recall 0.133 → 0.933）
- ✅ 首个真实嵌入绝对分报告公开（BAAI/bge-m3，7/7 维度通过，Aggregate 0.943）
- ✅ 安全审计 0 P0/P1（pip-audit 硬门禁、Gitleaks 全历史、`/v1/extract-url` SSRF 修复）
- ✅ API Key 管理端点（`POST/GET/DELETE /v1/keys`）、`text/markdown` MIME 摄入修复、JSON/CSV 结构化分块

### v0.6.0 增量（v0.5.0 → v0.6.0）— 连接器退役维护版本

按 ADR-0004 契约阶段退役自研连接器（破坏性变更，故 minor 而非 patch）：
- ✅ 删除 `emerald/connectors/`（2,194 行：OAuth / 凭证加密 / webhook / Celery 同步）及路由 `/v1/connectors/*`、`Connector` 模型、`cryptography` 依赖
- ✅ 迁移 `009_drop_connectors`；连接能力外包给连接中心 Totem（Emerald 保留 `ConnectionHub` 抽象 + `/v1/sources/*` 绑定路由）
- ✅ 里程碑顺延：M3 → v0.7.0、M4 → v0.8.0、M5 生产就绪 Beta → v0.9.0

### v0.7.0 增量（v0.6.0 → v0.7.0，M3「图谱深化与文档」）

- ✅ **B3 NER 提及层**（ADR-0005）：`(:Memory)-[:MENTIONS]->(:Mention)` 规则提取、封闭五类分类法、规范形式去重（表层别名累积）、实体隔离、遗忘/更新时序集成（历史节点保留 MENTIONS 边）
- ✅ **B4 多跳图谱推理**：`search(about=...)` 实体中心检索 + `depth`（≤ 4）共享提及桥/关系链遍历、路径透明（`path`/`depth`）、信任分 × 0.85^depth 折扣排名、历史不穿越、默认关闭
- ✅ **B5 社区遗忘**：标签传播社区检测（确定性契约）+ 活性评分决策矩阵 + `forget_communities` 策略（桥接/画像引用豁免；Celery Beat 日级）
- ✅ **B6 重复整合**（ADR-0006）：向量候选 + 规则护栏（误并率 = 0 硬门）+ `consolidate_duplicates` 策略（日级；代表保留，被并者 `replaced_by` 可审计）
- ✅ **A5 API 文档 overhaul**：`docs/api/rest-guide.md` 重构为三层结构（快速入门 → 核心四 → 进阶/管理），34/34 端点入文，三处文档偏差修正，OpenAPI tags drift 修复
- ✅ **Web 核心循环补全**（issue #53，ADR-0003）：摄入三 tab 真实落库（含管线轮询）、三态搜索 + Spaces 过滤、画像注入对话 system prompt、SSE 流式 + 无 key 显式降级、chat OpenAI 兼容后端
- ✅ 框架集成取消（LangChain.js 等，2026-08-23 决议）：生态投资无真实用户信号不投入；R6 缓解改由 web 核心循环与 A5 文档承担

### 规划中（详见 [roadmap](docs/roadmap.md)）

- **M4 (v0.8.0)**：高级遗忘、负载测试验证、Staging 压测（解决性能 SLA P0）
- **M5 (v0.9.0)**：Production-Ready Beta（**不是** v1.0 GA——v1.0 需要真实生产使用后单独评估）
- 框架集成（LangChain.js / Vercel AI / Mastra）：仅以真实采用信号重启

## OpenAI API Key

Set your OpenAI API key for real semantic embeddings:

```bash
export OPENAI_API_KEY="sk-..."
```

Or place it in `.env.local` (see Development Setup below). It will override `.env` and is never committed to git.

If not set, the system falls back to `MockEmbeddingProvider` (deterministic but not semantic).

## Development Setup

```bash
# 1. Copy local secrets template and fill in real keys (never commit .env.local)
cp .env.local.example .env.local
# Edit .env.local with your OPENAI_API_KEY, DEEPSEEK_API_KEY, OAuth credentials, etc.

# 2. Start infrastructure（api / worker / beat / postgres / redis / minio / mcp / frontend / nginx）
docker compose up -d
# Web UI: http://localhost（API key + Entity ID 登录）

# 3. Run migrations
alembic upgrade head

# 4. Seed dev API key
python scripts/seed_dev_api_key.py

# 5. Run tests
pytest tests/unit/ -x

# 6. (可选) 启动测试基础设施，运行集成测试
docker compose -f docker-compose.test.yml up -d
cp .env.test .env.test.local  # 按需修改
set -a && source .env.test && set +a
alembic upgrade head
pytest  # 1207 个测试（集成/质量套件依赖测试基础设施）
```

> **Note:** `.env` provides default development values. `.env.local` overrides it for your machine and is ignored by git. Keep real API keys in `.env.local` only.

---

## 文档导航

| 我想知道 | 看这个 |
|---|---|
| 5 分钟跑通 Emerald | [docs/quickstart.md](docs/quickstart.md) |
| 记忆 vs RAG、三种记忆类型、三种关系 | [docs/concepts.md](docs/concepts.md) |
| 系统架构全景 | [docs/architecture/overview.md](docs/architecture/overview.md) |
| 数据模型设计 | [docs/architecture/data-model.md](docs/architecture/data-model.md) |
| 处理管线 | [docs/architecture/pipeline.md](docs/architecture/pipeline.md) |
| REST API（核心四 → 进阶 → 管理三层结构） | [docs/api/rest-guide.md](docs/api/rest-guide.md) |
| Python ↔ TypeScript SDK 对照 | [docs/api/sdk-guide.md](docs/api/sdk-guide.md) · [sdk/typescript/README.md](sdk/typescript/README.md) |
| 错误码 / OpenAPI spec | [docs/api/error-codes.md](docs/api/error-codes.md) · [docs/api/openapi.yaml](docs/api/openapi.yaml) |
| K8s 灾备 / 可观测性 | [docs/deployment/k8s-runbook.md](docs/deployment/k8s-runbook.md) · [docs/deployment/observability.md](docs/deployment/observability.md) |
| 生产就绪度评估 | [docs/production-readiness-assessment.md](docs/production-readiness-assessment.md) |
| Web UI 核心循环标尺 | [docs/web-core-loop-standard.md](docs/web-core-loop-standard.md) |
| 架构决策记录（ADR） | [docs/adr/](docs/adr/) |
| 与 Supermemory 能力对比 | [docs/comparison-supermemory.md](docs/comparison-supermemory.md) |
| 项目路线图 | [docs/roadmap.md](docs/roadmap.md) |
| Pandaria (Rust) 集成 | [docs/integration-guide.md](docs/integration-guide.md) |

---

**给你的 AI 一段记忆。**
