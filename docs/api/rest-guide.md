# REST API 指南

Emerald REST API 基于 FastAPI 构建，遵循极简接口原则。所有端点统一返回 `{"data": ..., "meta": {"request_id": "...", "took_ms": N}}` 格式。

本文以 [`openapi.yaml`](./openapi.yaml) 为权威契约：参数表、请求/响应 schema 与其保持一致，如有出入以 OpenAPI 为准。

## 文档分层

Emerald 文档按三层组织，按需取用：

| 层级 | 文档 | 内容 |
|---|---|---|
| L1 快速入门 | [`docs/quickstart.md`](../quickstart.md) | 5 分钟跑通「安装 → 添加 → 搜索 → 画像」最小闭环 |
| L2 核心四 | 本文「第一部分」 | `add` / `search` / `profile` / `upload` 四个核心方法，cURL + Python SDK + TypeScript SDK 三段示例 |
| L3 进阶 / 管理 | 本文「第二部分」「第三部分」 | 多跳检索、提及、Spaces、记忆管理、画像配置、API Key、会话、矛盾解析、数据源绑定、系统端点 |

相关文档：Python SDK 详解见 [`sdk-guide.md`](./sdk-guide.md)；错误码完整目录见 [`error-codes.md`](./error-codes.md)；机器可读契约见 [`openapi.yaml`](./openapi.yaml)。

---

## 基础信息

| 项 | 值 |
|---|---|
| 基础 URL | `http://localhost:8000/v1`（开发）/ `https://api.emerald.ai/v1`（生产） |
| 协议 | HTTPS（生产）/ HTTP（开发） |
| 数据格式 | JSON（除文件上传外） |
| 认证方式 | Bearer Token |

---

## 认证

所有端点（除 `/health` 与 `/sources/webhook` 外）需要在请求头中携带 API Key：

```http
Authorization: Bearer em_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

API Key 以 `em_` 开头，后跟 32 位随机字符。Key 的权限（`read` / `write` / `admin`）在创建时分配，且作用域限定在单个实体内（服务端只存 SHA-256 哈希）。Key 的创建与吊销见「第三部分 · API Key 管理」。

---

## 统一响应格式

### 成功响应

```json
{
  "data": { ... },
  "meta": {
    "request_id": "abc123",
    "took_ms": 45
  }
}
```

### 错误响应

```json
{
  "error": {
    "code": "INVALID_CONTENT_TYPE",
    "message": "Unsupported content type: application/octet-stream",
    "details": {}
  },
  "meta": {
    "request_id": "abc123",
    "took_ms": 12
  }
}
```

**错误码列表：**

| 错误码 | HTTP 状态 | 含义 |
|---|---|---|
| `INVALID_REQUEST` | 400 | 请求参数错误 |
| `INVALID_CONTENT_TYPE` | 400 | 不支持的内容类型 |
| `CONTENT_TOO_LARGE` | 413 | 内容过大 |
| `INVALID_ENTITY_ID` | 400 | 无效的实体 ID |
| `EMPTY_CONTENT` | 400 | 内容为空 |
| `UNAUTHORIZED` | 401 | 未认证 |
| `API_KEY_EXPIRED` | 401 | API Key 已过期 |
| `FORBIDDEN` | 403 | 权限不足 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `ALREADY_EXISTS` | 409 | 资源已存在 |
| `PAYLOAD_TOO_LARGE` | 413 | 请求体过大 |
| `RATE_LIMITED` | 429 | 请求过于频繁 |
| `INTERNAL_ERROR` | 500 | 内部错误 |
| `PIPELINE_UNAVAILABLE` | 503 | 管线服务不可用 |

错误处理细节与重试建议见 [`error-codes.md`](./error-codes.md)。

---

## 速率限制

基于 Redis 滑动窗口实现。超出限制时返回 `429 Too Many Requests`，响应头包含 `Retry-After`。

| 端点 | 限制 |
|---|---|
| `POST /memories` | 60 / 分钟 |
| `POST/GET /search` | 120 / 分钟 |
| `GET /profiles/{id}` | 300 / 分钟 |
| `POST /upload` | 10 / 分钟 |
| 默认 | 60 / 分钟 |

---

# 第一部分：核心四

AGENTS.md 原则：核心公共 API 只有 `add`、`search`、`profile`、`upload` 四个方法。本节每个端点给出 cURL + Python SDK + TypeScript SDK 三段示例。

## 1. 添加记忆 — `POST /v1/memories`

将内容摄入记忆图谱。文本内容同步处理；文件/批量内容异步处理。

**参数说明**（`AddMemoryRequest`）：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `content` | `string` | ✅ | — | 文本内容或 base64 编码的文件 |
| `entity_id` | `string` | ✅ | — | 实体标识 |
| `content_type` | `string \| null` | — | `text` | 内容类型：`text`、`conversation`、`url`、`pdf`、`image`、`audio`、`video`、`code`、`markdown`。缺省自动检测 |
| `title` | `string \| null` | — | `null` | 可选标题 |
| `metadata` | `object \| null` | — | `null` | 自定义键值元数据 |
| `async_mode` | `boolean` | — | `false` | 强制异步处理。默认根据内容类型自动判断 |
| `idempotency_key` | `string \| null` | — | `null` | 客户端幂等键。同键 + 同实体 1 小时内返回相同结果 |
| `require_confirmation_for_high_impact` | `boolean` | — | `false` | 为 `true` 时，高影响矛盾挂起待确认（见「矛盾解析」），而非自动解决 |
| `memory_type` | `string \| null` | — | `null` | 覆盖 LLM 提取的记忆类型：`fact` / `preference` / `episodic` |
| `confidence` | `number \| null` | — | `null` | 覆盖 LLM 置信度（0.0–1.0），适用于人工核验过的条目 |
| `container_tag` | `string \| null` | — | `null` | 关联到某个 Space（见「Spaces」）。`null` 表示不属于任何空间 |
| `valid_until` | `date-time \| null` | — | `null` | 记忆过期时间（如「我明天有考试」），过期后 ForgetEngine 将其标记为非最新 |

**cURL：**

```bash
curl -X POST http://localhost:8000/v1/memories \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "用户偏好 TypeScript 和函数式编程风格",
    "entity_id": "user_123",
    "content_type": "text",
    "metadata": {"source": "onboarding_chat", "session_id": "sess_456"}
  }'
```

**Python SDK：**

```python
from emerald.sdk import EmeraldClient

client = EmeraldClient(api_key="em_xxx", base_url="http://localhost:8000")

result = await client.add(
    "用户偏好 TypeScript 和函数式编程风格",
    entity_id="user_123",
    content_type="text",
    metadata={"source": "onboarding_chat"},
)
print(result.memory_ids)  # ["mem_abc123", ...]
```

**TypeScript SDK：**

```ts
import { EmeraldClient } from "@emerald/sdk";

const client = new EmeraldClient({ apiKey: "em_xxx" });

const result = await client.add(
  "用户偏好 TypeScript 和函数式编程风格",
  "user_123",
  { metadata: { source: "onboarding_chat" } },
);
console.log(result.memory_ids); // ["mem_abc123", ...]
```

**响应（同步，`200`）：**

```json
{
  "data": {
    "memory_ids": ["mem_abc123", "mem_def456"],
    "pipeline_status": "done",
    "extracted_count": 2
  },
  "meta": { "request_id": "a1b2c3d4", "took_ms": 120 }
}
```

**内容类型自动检测规则：**

| 内容特征 | 检测类型 |
|---|---|
| 纯文本 | `text` |
| 包含 `User:` / `Assistant:` 轮次 | `conversation` |
| `http://` / `https://` 开头 | `url` |
| 文件扩展名 `.py` / `.js` / `.go` / `.rs` | `code` |
| 文件扩展名 `.md` / `.markdown` | `markdown` |
| MIME type `application/pdf` | `pdf` |
| MIME type `image/*` | `image` |
| MIME type `audio/*` | `audio` |
| MIME type `video/*` | `video` |

---

## 2. 搜索 — `POST /v1/search`

混合搜索，单次查询同时检索个人记忆（知识图谱）和文档（向量 RAG）。另有查询参数 `page_token` 用于游标分页。

**参数说明**（`SearchRequest`）：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `q` | `string` | — | `""` | 查询文本（`about` 实体中心检索时可为空） |
| `entity_id` | `string` | ✅ | — | 实体标识 |
| `search_mode` | `string` | — | `hybrid` | `hybrid` / `memory` / `rag`，见下表 |
| `top_k` | `int` | — | `30` | 返回条数，1–100 |
| `rerank` | `boolean` | — | `false` | 关键词重叠度重排序（最高 +15%） |
| `rewrite_query` | `boolean` | — | `false` | 查询改写（简单中文启发式扩展） |
| `filters` | `object \| null` | — | `null` | MongoDB 风格元数据过滤，见「进阶 · 元数据过滤」 |
| `min_confidence` | `number \| null` | — | `null` | 置信度下限（0.0–1.0） |
| `dynamic_truncation` | `boolean` | — | `true` | 动态截断 |
| `about` | `string \| null` | — | `null` | 实体中心检索：提及的规范形式或 Mention 节点 id。见「进阶 · 提及」 |
| `depth` | `int` | — | `0` | 图谱遍历跳数，0–4。`≥1` 显式开启多跳。见「进阶 · 多跳推理」 |

**搜索模式说明：**

| 模式 | 说明 |
|---|---|
| `hybrid`（默认） | 同时搜索记忆图谱和向量文档，合并、去重、排序 |
| `memory` | 仅搜索个人记忆（图谱） |
| `rag` | 仅搜索文档向量（RAG） |

**cURL：**

```bash
curl -X POST http://localhost:8000/v1/search \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "q": "用户偏好什么编程语言？",
    "entity_id": "user_123",
    "search_mode": "hybrid",
    "top_k": 10
  }'
```

**Python SDK：**

```python
results = await client.search(
    "用户偏好什么编程语言？",
    entity_id="user_123",
    search_mode="hybrid",
    top_k=10,
)
for r in results.results:
    print(f"[{r.source}] {r.content[:60]} (score: {r.score:.3f})")
```

**TypeScript SDK：**

```ts
const results = await client.search("用户偏好什么编程语言？", "user_123", {
  search_mode: "hybrid",
  top_k: 10,
});
console.log(results.results[0].content);
```

**响应（`200`，截关键字段）：**

```json
{
  "data": {
    "results": [
      {
        "id": "mem_abc123",
        "content": "用户偏好 TypeScript 和函数式编程风格",
        "summary": "用户是 TypeScript 开发者，偏好函数式范式",
        "score": 0.92,
        "source": "memory",           // memory | memory_expanded | rag
        "memory_type": "preference",
        "is_latest": true,
        "depth": 0,                   // 多跳结果跳数；种子为 0
        "path": []                    // 多跳路径；种子为空
      }
      // RAG 命中项形如 {"id": "chunk_...", "source": "rag", "document_id": "...", "document_title": "..."}
    ],
    "search_mode": "hybrid",
    "query_rewritten": null
  },
  "meta": { "request_id": "m3n4o5p6", "took_ms": 85 }
}
```

**搜索算法流程（hybrid 模式）：**

1. 将查询文本嵌入为向量
2. **记忆搜索**：向量相似度搜索（取 `top_k × 5` 候选）→ 从图谱解析完整记忆 → 过滤 `is_latest=true` + 未过期 + 元数据过滤 → 分数 = 向量相似度 × 置信度
3. **RAG 搜索**：纯向量相似度搜索
4. **合并**：按归一化内容去重，按分数排序
5. **重排序**（可选）：`rerank=true`，关键词重叠度提升
6. **查询改写**（可选）：`rewrite_query=true`，如 "如何" → "方法 步骤"

**GET 变体** — `GET /v1/search`：同一搜索的 GET 版本，便于调试和浏览器直接访问。参数走 query string（`q`、`entity_id`（必填）、`search_mode`、`top_k`、`rewrite_query`、`min_confidence`、`dynamic_truncation`、`about`、`depth`）：

```bash
curl "http://localhost:8000/v1/search?q=用户偏好&entity_id=user_123&top_k=5" \
  -H "Authorization: Bearer em_xxx"
```

---

## 3. 获取画像 — `GET /v1/profiles/{entity_id}`

获取实体的双层画像：静态事实 + 动态事实。目标延迟约 50ms（Redis 缓存，摄入时重算）。

**cURL：**

```bash
curl http://localhost:8000/v1/profiles/user_123 \
  -H "Authorization: Bearer em_xxx"
```

**Python SDK：**

```python
profile = await client.profile("user_123")
print([f.content for f in profile.static])    # 长期事实
print([f.content for f in profile.dynamic])   # 近期情节
```

**TypeScript SDK：**

```ts
const profile = await client.profile("user_123");
console.log(profile.static);  // long-term facts
console.log(profile.dynamic); // recent episodic facts
```

**响应（`200`）：**

```json
{
  "data": {
    "entity_id": "user_123",
    "static": [
      { "content": "资深前端工程师", "importance": 0.95 },
      { "content": "偏好 TypeScript 和 React", "importance": 0.88 }
    ],
    "dynamic": [
      { "content": "正在学习 Rust", "relevance": 0.92, "source": "最近对话", "acquired_at": "2026-05-28T14:00:00Z" }
    ],
    "memory_count": 128,
    "computed_at": "2026-05-29T08:00:00Z",
    "version": 12
  },
  "meta": { "request_id": "q7r8s9t0", "took_ms": 48 }
}
```

**画像计算规则（默认值，可按实体覆盖，见「进阶 · 画像进阶」）：**

| 层级 | 条件 | 排序 | 上限 |
|---|---|---|---|
| **静态** | `memory_type` 为 `fact` 或 `preference`，`confidence ≥ 0.5` | 按 `importance` 降序 | 10 条 |
| **动态** | `memory_type` 为 `episodic`，`confidence ≥ 0.3`，近 7 天内 | 按 `relevance` 降序 | 5 条 |

---

## 4. 上传文件 — `POST /v1/upload`

上传文件进行异步处理。返回 `202 Accepted` 和 `pipeline_id`，用 `GET /v1/pipelines/{id}` 轮询进度。单个文件最大 50MB。

**参数说明**（multipart/form-data）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | `file` | ✅ | 文件二进制 |
| `entity_id` | `string` | ✅ | 实体标识 |
| `content_type` | `string \| null` | — | 内容类型，缺省自动检测 |
| `title` | `string \| null` | — | 可选标题 |

**cURL：**

```bash
curl -X POST http://localhost:8000/v1/upload \
  -H "Authorization: Bearer em_xxx" \
  -F "file=@/path/to/document.pdf" \
  -F "entity_id=user_123" \
  -F "title=用户简历"
```

**Python SDK：**

```python
result = await client.upload("/path/to/document.pdf", entity_id="user_123", title="用户简历")
print(result.pipeline_id)  # 用于轮询管线状态
```

**TypeScript SDK：**

```ts
const result = await client.upload(file, "user_123");
console.log(result.pipeline_id); // track async processing
```

**响应（`202`）：**

```json
{
  "data": {
    "document_id": "doc_xyz789",
    "pipeline_id": "pipe_abc123",
    "pipeline_status": "queued",
    "file_size_bytes": 204800,
    "content_type": "application/pdf",
    "title": "用户简历"
  },
  "meta": { "request_id": "u1v2w3x4", "took_ms": 60 }
}
```

**支持的文件类型：**

| 类型 | 扩展名 | 处理方式 |
|---|---|---|
| PDF | `.pdf` | PyMuPDF 提取 + OCR 回退 |
| 文本 | `.txt` | 直接读取 |
| Markdown | `.md` | 按标题层级分块 |
| 图片 | `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp` | Tesseract OCR |
| 音频 | `.mp3`, `.wav`, `.m4a` | Faster-Whisper 转录 |
| 视频 | `.mp4`, `.mov`, `.avi` | 提取音轨后转录 |
| 代码 | `.py`, `.js`, `.ts`, `.go`, `.rs` 等 | AST 感知提取和分块 |

### 管线状态 — `GET /v1/pipelines/{pipeline_id}`

查询异步处理管线的状态（文件上传、大文档提取、嵌入索引）。

```bash
curl http://localhost:8000/v1/pipelines/pipe_abc123 \
  -H "Authorization: Bearer em_xxx"
```

SDK 均有封装：`client.pipeline_status(pipeline_id)`（Python）/ `client.pipelineStatus(pipelineId)`（TS）。

**响应（`200`，截关键字段）：**

```json
{
  "data": {
    "pipeline_id": "pipe_abc123",
    "status": "embedding",
    "stage": "embedding",
    "document_id": "doc_xyz789",
    "content_type": "pdf",
    "memory_count": 0,
    "fact_extraction_status": null,
    "error_message": null,
    "started_at": "2026-05-29T08:00:05Z",
    "completed_at": null
  },
  "meta": { "request_id": "y5z6a7b8", "took_ms": 15 }
}
```

**状态流转：**

```
queued → extracting → chunking → embedding → indexing → done
                ↓
             failed
```

### 文件列表 — `GET /v1/files`

列出实体上传的文件，游标分页。SDK 未覆盖，请直接使用 REST。

**查询参数：**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `entity_id` | `string` | ✅ | — | 实体 ID |
| `status_filter` | `string` | — | `done` | 按状态过滤（`queued` / `processing` / `done` / `failed`） |
| `page_token` | `string \| null` | — | `null` | 上一页响应中 `pagination.next_page_token` 给出的游标 |
| `page_size` | `int` | — | `20` | 每页数量，1–100 |

```bash
curl "http://localhost:8000/v1/files?entity_id=user_123&status_filter=done&page_size=20" \
  -H "Authorization: Bearer em_xxx"
```

**响应（`200`，截关键字段）：**

```json
{
  "data": {
    "items": [
      {
        "id": "doc_abc123",
        "title": "report.pdf",
        "content_type": "application/pdf",
        "status": "done",
        "file_size_bytes": 102400,
        "chunk_count": 12,
        "created_at": "2026-06-21T10:00:00Z"
      }
    ]
  },
  "meta": { "request_id": "req_xyz", "took_ms": 12 },
  "pagination": { "next_page_token": "cur_...", "has_more": true, "total_count": 42 }
}
```

**特殊行为：**
- 未知的 `entity_id` 返回空列表（不是 404）
- 默认只返回 `status=done` 的文档
- 按 `created_at` 降序排列

---

# 第二部分：进阶

## 5. 多跳推理与实体中心检索（`about` / `depth`）

概念详见 [`docs/concepts.md` §4 多跳图谱推理](../concepts.md)。一句话：检索不只靠向量相似度，还可以沿图谱边行走——共享提及桥（记忆→提及→记忆）与关系边（UPDATES / EXTENDS / DERIVES_FROM，双向链式）。

在 `POST /v1/search` 上通过两个参数开启：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `about` | `string \| null` | `null` | 实体中心检索：提及的规范形式或 Mention 节点 id。非空时跳过向量/RAG/fast-lane，返回该实体上下文池内提及该事物的全部最新记忆（跨所有表层形式——「谷歌」「GOOGLE」都解析到 Google） |
| `depth` | `int` | `0` | 图谱遍历跳数：`0` = 现状（不遍历）；`≥1` 显式 opt-in 多跳，上限 4。多跳结果携带 `depth` 与 `path` |

**实体中心检索示例：**

```bash
curl -X POST http://localhost:8000/v1/search \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "q": "",
    "entity_id": "user_123",
    "search_mode": "memory",
    "about": "Google",
    "depth": 1
  }'
```

按提及查「该实体关于 Google 说过的全部记忆」——「在 Google 工作」「在谷歌工作」「在 GOOGLE 工作」经提及解析（同一规范形式节点）全部命中；`depth=1` 顺带桥接提及同一事物的兄弟记忆。纯图谱操作：无向量、无 RAG、结果集恰为提及集。

**关键语义（详见 concepts.md §4.2）：**

- 一跳 = 一次提及桥（记忆→提及→记忆）或一条关系边（UPDATES/EXTENDS/DERIVES_FROM，双向）；推导事实作为来源参与下一跳，链式展开
- 每跳实体隔离；环路安全（每条记忆只出现在最浅深度一次）
- 历史节点（`is_latest=false`）仅在沿 UPDATES 被踩到时返回并标记，从不主动搜历史、从不穿越历史
- 每个多跳结果携带 `depth` 与 `path`（经过的节点/边）；种子 depth 0、空路径；排名按信任分 × 0.85^depth 折扣

SDK 支持：`client.search(..., about="Google", depth=1)`（Python，关键词参数）/ `client.search(q, entityId, { about, depth })`（TS）。

---

## 6. 提及（Mentions）

提及是图谱中的实体节点（人、公司、技术），而非标签——详见 ADR-0005（[`docs/adr/0005-mentions-are-graph-nodes-not-tags.md`](../adr/0005-mentions-are-graph-nodes-not-tags.md)）。

对 API 使用者而言，提及没有独立端点：它们在摄入时自动提取，入口就是搜索的 `about=` 参数（见上节）。提及解析把同一事物的不同表层形式（「谷歌」/「GOOGLE」/「Google」）归一到同一个规范节点，使实体中心检索跨表层形式命中。

---

## 7. Spaces（空间）

Spaces 是用户显式创建的记忆组织视图（产品层意图，AGENTS.md 原则 4 的例外条款）。语义以 ADR-0002 为准（[`docs/adr/0002-spaces-are-views-not-partitions.md`](../adr/0002-spaces-are-views-not-partitions.md)）：

- **Space 是视图，不是分区**：不改变「同一个上下文池」边界
- **搜索默认全池**，空间仅为可选过滤；画像跨空间聚合
- `container_tag` 可空（`null` = 不属于任何空间）；系统不自动创建或推断空间
- 记忆在摄入时通过 `container_tag` 字段归属空间（见「添加记忆」参数表）

> SDK 未覆盖 Spaces 端点，请直接使用 REST（与 [`sdk-guide.md`](./sdk-guide.md) 的覆盖现状一致）。

### 创建空间 — `POST /v1/spaces`

**请求体**（`SpaceCreateRequest`）：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | `string` | ✅ | — | 显示名称，1–100 字符 |
| `entity_id` | `string` | ✅ | — | 实体标识 |
| `emoji` | `string` | — | `📁` | 图标，最长 10 字符 |

```bash
curl -X POST http://localhost:8000/v1/spaces \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{"name": "Work", "emoji": "💼", "entity_id": "user_123"}'
```

**响应（`201`）：**

```json
{
  "data": {
    "container_tag": "work",
    "name": "Work",
    "emoji": "💼",
    "entity_id": "user_123",
    "created_at": "2026-08-23T08:00:00Z"
  },
  "meta": { "request_id": "...", "took_ms": 20 }
}
```

### 列出空间 — `GET /v1/spaces`

```bash
curl "http://localhost:8000/v1/spaces?entity_id=user_123" \
  -H "Authorization: Bearer em_xxx"
```

**响应（`200`）：** `data` 为该实体的空间数组（每项含 `container_tag`、`name`、`emoji`、`created_at` 等）。

### 更新空间 — `PATCH /v1/spaces/{container_tag}`

更新名称和/或 emoji。`entity_id` 为必填查询参数；请求体 `SpaceUpdateRequest` 两个字段均可选。

```bash
curl -X PATCH "http://localhost:8000/v1/spaces/work?entity_id=user_123" \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{"name": "Work Projects", "emoji": "🚀"}'
```

### 删除空间 — `DELETE /v1/spaces/{container_tag}`

```bash
curl -X DELETE "http://localhost:8000/v1/spaces/work?entity_id=user_123&detach_memories=true" \
  -H "Authorization: Bearer em_xxx"
```

**查询参数：**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `entity_id` | `string` | ✅ | — | 实体标识 |
| `detach_memories` | `boolean` | — | `true` | 为 `true` 时空间内记忆的 `container_tag` 置空（记忆保留在全池中），而非一并删除 |

---

## 8. 记忆管理

### 获取记忆 — `GET /v1/memories/{memory_id}`

获取单条记忆的完整信息，包括关系图谱。

```bash
curl http://localhost:8000/v1/memories/mem_abc123 \
  -H "Authorization: Bearer em_xxx"
```

SDK 支持：`client.get_memory(memory_id)`（Python）/ `client.getMemory(memoryId)`（TS）。

**响应（`200`，截关键字段）：**

```json
{
  "data": {
    "id": "mem_abc123",
    "content": "用户偏好 TypeScript 和函数式编程风格",
    "summary": "用户是 TypeScript 开发者，偏好函数式范式",
    "memory_type": "preference",
    "is_latest": true,
    "confidence": 0.85,
    "valid_from": "2026-05-22T10:30:00Z",
    "valid_until": null,
    "entity_id": "user_123",
    "relationships": [
      { "type": "extends", "target_id": "mem_old456", "target_summary": "用户是前端开发者" }
    ],
    "created_at": "2026-05-22T10:30:00Z",
    "updated_at": "2026-05-22T10:30:00Z"
  },
  "meta": { "request_id": "e5f6g7h8", "took_ms": 25 }
}
```

### 更新记忆 — `PATCH /v1/memories/{memory_id}`

更新记忆的内容、摘要、类型和/或置信度。SDK 未覆盖，请直接使用 REST。

**请求体**（`UpdateMemoryRequest`，全部可选，至少给一个）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | `string \| null` | 新内容 |
| `summary` | `string \| null` | 新摘要 |
| `memory_type` | `string \| null` | 须匹配 `^(fact|preference|episodic)$` |
| `confidence` | `number \| null` | 0.0–1.0 |

```bash
curl -X PATCH http://localhost:8000/v1/memories/mem_abc123 \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{"summary": "用户是 TypeScript 开发者，偏好函数式范式（2026 复核）", "confidence": 0.95}'
```

### 删除记忆（软删除）— `DELETE /v1/memories/{memory_id}`

软删除：将记忆标记为 `is_latest=false`，不物理删除节点（保留时序历史，仍可沿 UPDATES 链被检索到）。SDK 未覆盖，请直接使用 REST。

```bash
curl -X DELETE http://localhost:8000/v1/memories/mem_abc123 \
  -H "Authorization: Bearer em_xxx"
```

**响应（`200`）：**

```json
{
  "data": {
    "memory_id": "mem_abc123",
    "deleted_at": "2026-06-21T10:30:00Z",
    "is_latest": false
  },
  "meta": { "request_id": "...", "took_ms": 12 }
}
```

**注意：** 如需硬删除，联系运维手动执行。

### 验证记忆 — `POST /v1/memories/{memory_id}/validate`

递增记忆的 `validation_count`（表达更高信任度的信号，供信任分排名使用）。SDK 未覆盖，请直接使用 REST。

```bash
curl -X POST http://localhost:8000/v1/memories/mem_abc123/validate \
  -H "Authorization: Bearer em_xxx"
```

**响应（`200`）：** `data` 含 `memory_id` 与更新后的 `validation_count`。

---

## 9. 批量写入 — `POST /v1/memories/batch`

一次提交多条记忆（最多 50 条），适用于批量上传或预填充场景。每条元素即一个 `AddMemoryRequest`（字段同「添加记忆」）。SDK 未覆盖，请直接使用 REST。

```bash
curl -X POST http://localhost:8000/v1/memories/batch \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "memories": [
      {"content": "Alex 在 Stripe 担任产品经理", "entity_id": "user_alex"},
      {"content": "Alex 偏好用 TypeScript 写后端", "entity_id": "user_alex", "memory_type": "preference"},
      {"content": "Alex 最近在评估 Kafka vs Pulsar", "entity_id": "user_alex", "valid_until": "2026-07-01T00:00:00Z"}
    ]
  }'
```

**响应（`200`，全部成功）：**

```json
{
  "data": {
    "results": [
      {"index": 0, "memory_ids": ["mem_abc"], "status": "completed"},
      {"index": 1, "memory_ids": ["mem_def"], "status": "completed"},
      {"index": 2, "memory_ids": ["mem_ghi"], "status": "completed"}
    ],
    "total": 3,
    "successful": 3,
    "failed": 0
  },
  "meta": { "request_id": "...", "took_ms": 42 }
}
```

**部分失败** 时 `results` 中对应项为 `{"index": N, "status": "failed", "error": "..."}`，`failed` 计数递增；整体仍返回 `200`。超出 50 条返回 `422`。

---

## 10. 图谱可视化 — `GET /v1/memories/graph`

返回实体图谱的节点+边数据，供 D3.js / vis-network 等可视化库做力导向图渲染。SDK 未覆盖，请直接使用 REST。

> 注：该端点在 OpenAPI 中的 tag 当前为 `System`（实现位于 `system.py`），但按路径语义属于记忆操作，故归入本进阶章节。

**查询参数：**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `entity_id` | `string` | ✅ | — | 实体标识 |
| `limit` | `int` | — | `100` | 节点数量上限 |

```bash
curl "http://localhost:8000/v1/memories/graph?entity_id=user_alex&limit=100" \
  -H "Authorization: Bearer em_xxx"
```

**响应（`200`）：**

```json
{
  "data": {
    "nodes": [
      {"id": "mem_abc", "label": "Alex 在 Stripe 担任产品经理", "memory_type": "fact", "is_latest": true},
      {"id": "mem_def", "label": "Alex 偏好 TypeScript", "memory_type": "preference", "is_latest": true}
    ],
    "edges": [
      {"source": "mem_def", "target": "mem_abc", "type": "EXTENDS"}
    ]
  },
  "meta": { "request_id": "...", "took_ms": 35 }
}
```

**用途：** 在调试 UI 中可视化实体的记忆网络。

---

## 11. 元数据过滤

在 `POST /v1/search` 请求体中添加 `filters` 参数，支持 MongoDB 风格查询：

```json
{
  "q": "用户偏好什么",
  "entity_id": "user_123",
  "search_mode": "memory",
  "filters": {
    "$and": [
      {"memory_type": "preference"},
      {"confidence": {"$gte": 0.7}}
    ]
  }
}
```

**支持的操作符：**

| 操作符 | 用途 | 示例 |
|---|---|---|
| （无） | 精确匹配 | `{"memory_type": "fact"}` |
| `$eq` / `$ne` | 等于 / 不等于 | `{"memory_type": {"$eq": "fact"}}` |
| `$gt` / `$gte` | 大于 / 大于等于 | `{"confidence": {"$gte": 0.5}}` |
| `$lt` / `$lte` | 小于 / 小于等于 | `{"confidence": {"$lte": 0.9}}` |
| `$and` | 所有子条件满足 | `{"$and": [{...}, {...}]}` |
| `$or` | 任一子条件满足 | `{"$or": [{"memory_type": "fact"}, {"memory_type": "episodic"}]}` |

SDK 支持：`client.search(..., filters={...})`（Python）/ `client.search(q, entityId, { filters })`（TS）。

---

## 12. 画像进阶

### 画像配置 — `GET / PUT / DELETE /v1/profiles/{entity_id}/config`

按实体覆盖画像计算参数（静态/动态条数上限、回看天数、置信度阈值）。覆盖存储在 Redis，在下一次画像计算时生效；缓存立即失效，下一次 `GET /profiles/{id}` 即用新配置计算。SDK 未覆盖，请直接使用 REST。

**配置字段**（`ProfileConfig`，PUT 请求体）：

| 字段 | 类型 | 范围 | 默认 | 说明 |
|---|---|---|---|---|
| `static_max_items` | `int` | 1–50 | `10` | 静态层条数上限 |
| `dynamic_max_items` | `int` | 1–20 | `5` | 动态层条数上限 |
| `dynamic_lookback_days` | `int` | 1–90 | `7` | 动态层回看天数 |
| `min_confidence_static` | `number` | 0.0–1.0 | `0.5` | 静态层置信度阈值 |
| `min_confidence_dynamic` | `number` | 0.0–1.0 | `0.3` | 动态层置信度阈值 |

```bash
# 读取当前配置
curl http://localhost:8000/v1/profiles/user_123/config \
  -H "Authorization: Bearer em_xxx"

# 设置覆盖
curl -X PUT http://localhost:8000/v1/profiles/user_123/config \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{"static_max_items": 20, "dynamic_lookback_days": 30}'

# 重置为默认
curl -X DELETE http://localhost:8000/v1/profiles/user_123/config \
  -H "Authorization: Bearer em_xxx"
```

### MEMORY.md 导出 — `GET /v1/profiles/{entity_id}/memory.md`

将实体记忆导出为 MEMORY.md 风格的 Markdown 文档（`text/plain`），适合注入 Agent 上下文或归档。SDK 未覆盖，请直接使用 REST。

```bash
curl http://localhost:8000/v1/profiles/user_123/memory.md \
  -H "Authorization: Bearer em_xxx"
```

**响应（`200`，`text/plain`）：** Markdown 文本，按静态事实 / 动态事实组织。

---

# 第三部分：管理与运维

本部分均为 **REST-only 管理扩展端点**：依据 AGENTS.md 原则 7（禁止 API 泄漏），SDK 不暴露这些操作，全部需直接调用 REST，且受 API Key 权限与实体作用域保护。

## 13. API Key 管理

Key 管理是实体作用域的：admin key 只能管理本实体的 key。SDK 未覆盖，请直接使用 REST。

### 创建 Key — `POST /v1/keys`

**请求体**（`CreateKeyRequest`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `entity_id` | `string` | ✅ | Key 归属的外部实体 ID，必须与调用方自身实体一致 |
| `permissions` | `string[]` | ✅ | 权限级别：`read` / `write` / `admin` |
| `expires_at` | `date-time \| null` | — | 可选过期时间，过期后请求返回 401 |

```bash
curl -X POST http://localhost:8000/v1/keys \
  -H "Authorization: Bearer em_xxx_admin_key" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "user_123", "permissions": ["read", "write"]}'
```

**响应（`201`）：**

```json
{
  "data": {
    "key": "em_a1b2c3d4e5f6...",   // 明文 key 仅此一次返回，服务端只存 SHA-256 哈希
    "key_id": "key_xyz789",
    "key_prefix": "em_a1b2",
    "permissions": ["read", "write"],
    "expires_at": null,
    "entity_id": "user_123"
  },
  "meta": { "request_id": "...", "took_ms": 30 }
}
```

### 列出 Key — `GET /v1/keys`

列出本实体的 key 元数据（不含哈希与明文），游标分页。

```bash
curl "http://localhost:8000/v1/keys?page_size=20" \
  -H "Authorization: Bearer em_xxx_admin_key"
```

**查询参数：** `page_token`（游标）、`page_size`（1–100，默认 20）。

**响应（`200`）：** `data.items` 为 `KeyMetadata` 数组（`key_id`、`key_prefix`、`permissions`、`expires_at`、`last_used_at`、`is_active`、`created_at`），并附 `pagination` 游标元数据。

### 吊销 Key — `DELETE /v1/keys/{key_id}`

软吊销：认证查询过滤 `is_active=True`，吊销后该 key 立即以 401 被拒绝。

```bash
curl -X DELETE http://localhost:8000/v1/keys/key_xyz789 \
  -H "Authorization: Bearer em_xxx_admin_key"
```

**响应（`204`）：** 无响应体。

---

## 14. 会话令牌

面向前端/终端用户场景的短期 JWT 会话令牌，作用域限定到实体（可选项目）。REST-only 管理扩展，SDK 不暴露。

### 创建会话 — `POST /v1/sessions`

参数全部走 query string：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `entity_id` | `string` | ✅ | — | 会话归属实体 |
| `project_id` | `string \| null` | — | `null` | 可选项目作用域 |
| `session_id` | `string \| null` | — | `null` | 客户端指定的会话 ID |
| `ttl_hours` | `number` | — | `24` | 令牌有效期（小时） |

```bash
curl -X POST "http://localhost:8000/v1/sessions?entity_id=user_123&ttl_hours=2" \
  -H "Authorization: Bearer em_xxx"
```

**响应（`200`）：** `data` 含 `session_token`（JWT）与过期时间等声明。

### 校验会话 — `GET /v1/sessions/verify`

校验会话令牌并返回其声明。令牌通过请求头 `X-Session-Token` 传递。

```bash
curl http://localhost:8000/v1/sessions/verify \
  -H "Authorization: Bearer em_xxx" \
  -H "X-Session-Token: eyJhbGciOi..."
```

---

## 15. 矛盾解析 — `POST /v1/conflicts/{conflict_id}/resolve`

解决一个待处理的高影响矛盾（当 `add` 携带 `require_confirmation_for_high_impact=true` 时，冲突不会自动解决，而是挂起等待人工裁决）。REST-only 管理扩展，SDK 不暴露。

**请求体**（`ResolveConflictRequest`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `action` | `string` | ✅ | 枚举：`keep_old`（保留旧事实）/ `keep_new`（采用新事实）/ `keep_both`（两者并存）/ `manual`（人工处理） |

```bash
curl -X POST http://localhost:8000/v1/conflicts/conf_abc123/resolve \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{"action": "keep_new"}'
```

---

## 16. URL 提取 — `POST /v1/extract-url`

从 URL 提取标题、描述、favicon。该端点会发起出站 HTTP 请求，因此要求认证并限流（未认证即构成 SSRF/资源滥用面，2026-08-10 审计修复）。REST-only，SDK 不暴露。

**请求体**（`ExtractUrlRequest`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `url` | `string` | ✅ | 待提取的 URL |

```bash
curl -X POST http://localhost:8000/v1/extract-url \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article"}'
```

**响应（`200`）：** `data` 含 `title`、`description`、`favicon` 等字段。

---

## 17. 数据源绑定

> ADR-0004（连接中心，当前实现 Totem）：凭证/OAuth/同步执行外包给连接中心，Emerald 只维护「数据源绑定」（授权关系 + 数据源身份）。REST-only 集成端点，SDK 不暴露。

### 发起授权流 — `POST /v1/sources/connect`

```bash
curl -X POST http://localhost:8000/v1/sources/connect \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "user_123", "provider": "feishu"}'
```

**请求体**（`ConnectRequest`）：`entity_id`（必填，绑定归属实体）、`provider`（必填，连接中心上的 provider key，当前支持 `feishu`）。

**响应（`200`）：**

```json
{
  "data": {
    "auth_link_url": "https://totem.internal/oauth/start?tenant=...",
    "session_id": "...",
    "provider": "feishu"
  }
}
```

用户被送往 `auth_link_url`，在连接中心完成授权；返回后调用 `POST /v1/sources/refresh` 完成绑定。

### 列出现有绑定 — `GET /v1/sources`

```bash
curl "http://localhost:8000/v1/sources?entity_id=user_123" \
  -H "Authorization: Bearer em_xxx"
```

**响应（`200`）：**

```json
{
  "data": [
    {
      "id": "9c2e...",
      "provider": "feishu",
      "hub_account_id": "conn_abc123",
      "sync_status": "active",
      "last_synced_at": "2026-08-10T06:00:00Z",
      "error_message": null
    }
  ]
}
```

### 刷新绑定（授权后回调用）— `POST /v1/sources/refresh`

与连接中心对账，将新授权的账户 upsert 为绑定（v1 中这是主要绑定路径——Totem 不推送 `account.connected` 事件）。

```bash
curl -X POST "http://localhost:8000/v1/sources/refresh?entity_id=user_123" \
  -H "Authorization: Bearer em_xxx"
```

**响应（`200`）：**

```json
{
  "data": { "accounts": 1, "bindings": ["9c2e..."] }
}
```

### 删除绑定 — `DELETE /v1/sources/{binding_id}`

```bash
curl -X DELETE "http://localhost:8000/v1/sources/9c2e...?entity_id=user_123" \
  -H "Authorization: Bearer em_xxx"
```

数据保留在图谱中，停止后续同步。

**响应（`200`）：**

```json
{
  "data": { "deleted": true, "binding_id": "9c2e..." }
}
```

### Webhook（上游订阅「铃铛」）— `POST /v1/sources/webhook`

接收连接中心/上游的事件投递，验签（HMAC-SHA256，`x-totem-signature` 请求头，常量时间比较）后归一化入队。**由连接中心调用，无需手动调用**；无 API Key——签名本身即凭证。

```http
POST /v1/sources/webhook
X-Totem-Signature: base64url(...)
```

---

## 18. 系统

### 健康检查 — `GET /v1/health`

无需认证。探测所有依赖服务（Postgres、Neo4j、Redis、MinIO）并返回结构化健康报告。

```bash
curl http://localhost:8000/v1/health
```

SDK 支持：`client.health()`（Python 与 TS 均有）。

**响应（`200`）：**

```json
{
  "status": "ok",
  "version": "0.3.0",
  "checks": {
    "database": "ok",
    "neo4j": "ok",
    "redis": "ok",
    "minio": "ok"
  },
  "meta": { "took_ms": 25 }
}
```

### 指标 — `GET /v1/metrics`

Prometheus 格式的运行时指标。**注：** 该端点被有意排除在 OpenAPI schema 之外（`include_in_schema=False`），不在 [`openapi.yaml`](./openapi.yaml) 中出现，但仍可正常调用。

```bash
curl http://localhost:8000/v1/metrics
```

**关键指标：**

| 指标名 | 类型 | 说明 |
|---|---|---|
| `http_requests_total` | Counter | 按 method、endpoint、status 统计 |
| `http_request_duration_seconds` | Histogram | 请求处理延迟 |
| `pipeline_jobs_total` | Counter | 按 status 统计 |
| `profile_cache_hit_ratio` | Gauge | 画像缓存命中率 |

---

# 附录

## cURL 完整工作流示例

```bash
# 1. 健康检查
curl http://localhost:8000/v1/health

# 2. 添加记忆
curl -X POST http://localhost:8000/v1/memories \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "用户是 Google 的资深前端工程师，偏好 TypeScript",
    "entity_id": "user_123",
    "metadata": {"source": "resume"}
  }'

# 3. 搜索
curl -X POST http://localhost:8000/v1/search \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "q": "用户在哪里工作？",
    "entity_id": "user_123",
    "search_mode": "hybrid",
    "top_k": 5
  }'

# 4. 获取画像
curl http://localhost:8000/v1/profiles/user_123 \
  -H "Authorization: Bearer em_xxx"

# 5. 上传文件
curl -X POST http://localhost:8000/v1/upload \
  -H "Authorization: Bearer em_xxx" \
  -F "file=@/path/to/document.pdf" \
  -F "entity_id=user_123" \
  -F "title=技术文档"

# 6. 查询管线状态
curl http://localhost:8000/v1/pipelines/pipe_abc123 \
  -H "Authorization: Bearer em_xxx"
```

---

## 设计原则

Emerald API 遵循以下设计原则：

1. **最小接口面** — 核心只有 `add`、`search`、`profile`、`upload` 四个方法；管理扩展端点仅经 REST 提供，不进 SDK
2. **实体优先** — 每个操作都限定在 `entity_id` 范围内，无全局匿名池
3. **声明式** — 开发者描述想要什么，不配置分块参数、嵌入模型或关系
4. **开箱即用默认值** — 默认混合搜索，自动检测内容类型
5. **统一响应格式** — 所有端点返回 `{"data": ..., "meta": {...}}`
