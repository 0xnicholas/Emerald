# Emerald REST API 使用指南

Emerald REST API 基于 FastAPI 构建，遵循极简接口原则。所有端点统一返回 `{"data": ..., "meta": {"request_id": "...", "took_ms": N}}` 格式。

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

所有端点（除 `/health` 外）需要在请求头中携带 API Key：

```http
Authorization: Bearer em_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

API Key 以 `em_` 开头，后跟 32 位随机字符。Key 的权限（`read` / `write` / `admin`）在创建时分配。

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

## 核心端点

### 1. 添加记忆 — `POST /memories`

将内容摄入记忆图谱。文本内容同步处理；文件/批量内容异步处理。

**请求：**

```http
POST /v1/memories
Authorization: Bearer em_xxx
Content-Type: application/json

{
  "content": "用户偏好 TypeScript 和函数式编程风格",
  "entity_id": "user_123",
  "content_type": "text",
  "metadata": {
    "source": "onboarding_chat",
    "session_id": "sess_456"
  }
}
```

**响应（同步）：**

```json
{
  "data": {
    "memory_ids": ["mem_abc123", "mem_def456"],
    "pipeline_status": "done",
    "extracted_count": 2
  },
  "meta": {
    "request_id": "a1b2c3d4",
    "took_ms": 120
  }
}
```

**参数说明：**

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `content` | `string` | ✅ | 文本内容或 base64 编码的文件 |
| `entity_id` | `string` | ✅ | 实体标识 |
| `content_type` | `string` | — | 内容类型。支持：`text`、`conversation`、`url`、`pdf`、`image`、`audio`、`video`、`code`、`markdown`。默认 `text`，自动检测。 |
| `title` | `string` | — | 可选标题 |
| `metadata` | `object` | — | 自定义键值元数据 |
| `async_mode` | `boolean` | — | 强制异步处理。默认根据内容类型自动判断。 |

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

### 2. 获取记忆 — `GET /memories/{memory_id}`

获取单条记忆的完整信息，包括关系图谱。

**请求：**

```http
GET /v1/memories/mem_abc123
Authorization: Bearer em_xxx
```

**响应：**

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
      {
        "type": "extends",
        "target_id": "mem_old456",
        "target_summary": "用户是前端开发者"
      }
    ],
    "created_at": "2026-05-22T10:30:00Z",
    "updated_at": "2026-05-22T10:30:00Z"
  },
  "meta": {
    "request_id": "e5f6g7h8",
    "took_ms": 25
  }
}
```

---

### 3. 删除记忆 — `DELETE /memories/{memory_id}`

软删除——将记忆的 `is_latest` 标记为 `false`，而非物理删除。保留历史时序关系。

**请求：**

```http
DELETE /v1/memories/mem_abc123
Authorization: Bearer em_xxx
```

**响应：**

```json
{
  "data": {
    "deleted": true,
    "memory_id": "mem_abc123"
  },
  "meta": {
    "request_id": "i9j0k1l2",
    "took_ms": 30
  }
}
```

---

### 4. 搜索 — `POST /search`

混合搜索，单次查询同时检索个人记忆（知识图谱）和文档（向量 RAG）。

**请求：**

```http
POST /v1/search
Authorization: Bearer em_xxx
Content-Type: application/json

{
  "q": "用户偏好什么编程语言？",
  "entity_id": "user_123",
  "search_mode": "hybrid",
  "top_k": 10,
  "rerank": false,
  "rewrite_query": false,
  "filters": {
    "memory_type": "preference",
    "min_confidence": 0.5
  }
}
```

**响应：**

```json
{
  "data": {
    "results": [
      {
        "id": "mem_abc123",
        "content": "用户偏好 TypeScript 和函数式编程风格",
        "summary": "用户是 TypeScript 开发者，偏好函数式范式",
        "score": 0.92,
        "source": "memory",
        "memory_type": "preference",
        "is_latest": true,
        "document_id": null,
        "document_title": null,
        "created_at": "2026-05-22T10:30:00Z"
      },
      {
        "id": "chunk_xyz789",
        "content": "TypeScript 提供了强大的类型系统...",
        "summary": "",
        "score": 0.78,
        "source": "rag",
        "memory_type": "",
        "is_latest": true,
        "document_id": "doc_001",
        "document_title": "TypeScript 高级教程.pdf",
        "created_at": "2026-05-20T08:00:00Z"
      }
    ],
    "search_mode": "hybrid",
    "query_rewritten": null
  },
  "meta": {
    "request_id": "m3n4o5p6",
    "took_ms": 85
  }
}
```

**搜索模式说明：**

| 模式 | 说明 |
|---|---|
| `hybrid`（默认） | 同时搜索记忆图谱和向量文档，合并、去重、排序 |
| `memory` | 仅搜索个人记忆（图谱） |
| `rag` | 仅搜索文档向量（RAG） |

**搜索算法流程（hybrid 模式）：**

1. 将查询文本嵌入为向量
2. **记忆搜索**：向量相似度搜索（取 `top_k × 5` 候选）→ 从图谱解析完整记忆 → 过滤 `is_latest=true` + 未过期 + 元数据过滤 → 分数 = 向量相似度 × 置信度
3. **RAG 搜索**：纯向量相似度搜索
4. **合并**：按归一化内容去重，按分数排序
5. **重排序**（可选）：关键词重叠度提升（最高 +15%）
6. **查询改写**（可选）：简单中文启发式扩展（如 "如何" → "方法 步骤"）

---

### 5. 快速搜索 — `GET /search`

简化版 GET 搜索，便于调试和浏览器直接访问。

```http
GET /v1/search?q=用户偏好&entity_id=user_123&search_mode=hybrid&top_k=5
Authorization: Bearer em_xxx
```

---

### 6. 获取画像 — `GET /profiles/{entity_id}`

获取实体的双层画像：静态事实 + 动态事实。

目标延迟：约 50ms（Redis 缓存）。

**请求：**

```http
GET /v1/profiles/user_123
Authorization: Bearer em_xxx
```

**响应：**

```json
{
  "data": {
    "entity_id": "user_123",
    "static": [
      {
        "content": "资深前端工程师",
        "importance": 0.95
      },
      {
        "content": "偏好 TypeScript 和 React",
        "importance": 0.88
      }
    ],
    "dynamic": [
      {
        "content": "正在学习 Rust",
        "relevance": 0.92,
        "source": "最近对话",
        "acquired_at": "2026-05-28T14:00:00Z"
      }
    ],
    "memory_count": 128,
    "computed_at": "2026-05-29T08:00:00Z",
    "version": 12
  },
  "meta": {
    "request_id": "q7r8s9t0",
    "took_ms": 48
  }
}
```

**画像计算规则：**

| 层级 | 条件 | 排序 | 上限 |
|---|---|---|---|
| **静态** | `memory_type` 为 `fact` 或 `preference`，`confidence ≥ 0.5` | 按 `importance` 降序 | 10 条 |
| **动态** | `memory_type` 为 `episodic`，`confidence ≥ 0.3`，近 7 天内 | 按 `relevance` 降序 | 5 条 |

---

### 7. 上传文件 — `POST /upload`

上传文件进行异步处理。返回 `202 Accepted` 和 `pipeline_id`。

**请求：**

```http
POST /v1/upload
Authorization: Bearer em_xxx
Content-Type: multipart/form-data

------Boundary
Content-Disposition: form-data; name="file"; filename="resume.pdf"
Content-Type: application/pdf

<binary data>
------Boundary
Content-Disposition: form-data; name="entity_id"

user_123
------Boundary
Content-Disposition: form-data; name="title"

用户简历
------Boundary--
```

**响应：**

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
  "meta": {
    "request_id": "u1v2w3x4",
    "took_ms": 60
  }
}
```

**限制：** 单个文件最大 50MB。

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

---

### 8. 管线状态 — `GET /pipelines/{pipeline_id}`

查询异步处理管线的状态。

```http
GET /v1/pipelines/pipe_abc123
Authorization: Bearer em_xxx
```

**响应：**

```json
{
  "data": {
    "pipeline_id": "pipe_abc123",
    "status": "embedding",
    "entity_id": "user_123",
    "document_id": "doc_xyz789",
    "content_type": "pdf",
    "chunk_count": 34,
    "error_message": null,
    "retry_count": 0,
    "created_at": "2026-05-29T08:00:00Z",
    "started_at": "2026-05-29T08:00:05Z",
    "completed_at": null
  },
  "meta": {
    "request_id": "y5z6a7b8",
    "took_ms": 15
  }
}
```

**状态流转：**

```
queued → extracting → chunking → embedding → indexing → done
                ↓
             failed
```

---

### 9. 文件列表 — `GET /files`

列出实体上传的文件。**注意：当前为 stub，始终返回空列表。**

```http
GET /v1/files?entity_id=user_123&status=done&page=1&page_size=20
Authorization: Bearer em_xxx
```

---

## 高级端点（Post-v0.3.0）

### 9a. 批量添加记忆 — `POST /memories/batch`

一次提交多条记忆（最多 50 条），适用于用户批量上传或预填充场景。

```http
POST /v1/memories/batch
Authorization: Bearer em_xxx
Content-Type: application/json

{
  "memories": [
    {
      "content": "Alex 在 Stripe 担任产品经理",
      "entity_id": "user_alex"
    },
    {
      "content": "Alex 偏好用 TypeScript 写后端",
      "entity_id": "user_alex",
      "memory_type": "preference"
    },
    {
      "content": "Alex 最近在评估 Kafka vs Pulsar",
      "entity_id": "user_alex",
      "valid_until": "2026-07-01T00:00:00Z"
    }
  ]
}
```

**响应：**

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
  "meta": {"request_id": "...", "took_ms": 42}
}
```

**错误响应（部分失败）：**

```json
{
  "data": {
    "results": [
      {"index": 0, "memory_ids": ["mem_abc"], "status": "completed"},
      {"index": 1, "status": "failed", "error": "memory_type must be one of: fact, preference, episodic"}
    ],
    "total": 2,
    "successful": 1,
    "failed": 1
  }
}
```

**限制：** 每次最多 50 条。超出返 422 错误。

### 9b. 获取图谱节点和边 — `GET /memories/graph`

返回实体图谱的节点+边数据，供 D3.js / vis-network 等可视化库使用。

```http
GET /v1/memories/graph?entity_id=user_alex&limit=100
Authorization: Bearer em_xxx
```

**响应：**

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
  "meta": {"request_id": "...", "took_ms": 35}
}
```

**用途：** 在调试 UI 中可视化实体的记忆网络。

### 9c. 删除记忆（软删除）— `DELETE /memories/{memory_id}`

软删除：将记忆标记为 `is_latest=False`，不真正删除节点（保留时序历史）。

```http
DELETE /v1/memories/mem_abc123
Authorization: Bearer em_xxx
```

**响应：**

```json
{
  "data": {
    "memory_id": "mem_abc123",
    "deleted_at": "2026-06-21T10:30:00Z",
    "is_latest": false
  },
  "meta": {"request_id": "...", "took_ms": 12}
}
```

**注意：** 是软删除，记忆仍可通过 `is_latest=false` 查询访问。如需硬删除，联系运维手动执行。

### 9d. 元数据过滤（搜索接口增强）

在 `POST /search` 请求体中添加 `filters` 参数，支持 MongoDB 风格查询：

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
| (无) | 精确匹配 | `{"memory_type": "fact"}` |
| `$eq` / `$ne` | 等于 / 不等于 | `{"memory_type": {"$eq": "fact"}}` |
| `$gt` / `$gte` | 大于 / 大于等于 | `{"confidence": {"$gte": 0.5}}` |
| `$lt` / `$lte` | 小于 / 小于等于 | `{"confidence": {"$lte": 0.9}}` |
| `$and` | 所有子条件满足 | `{"$and": [{...}, {...}]}` |
| `$or` | 任一子条件满足 | `{"$or": [{"memory_type": "fact"}, {"memory_type": "episodic"}]}` |

---

## 连接器端点

### 10. 发起 OAuth 连接 — `POST /connectors/{provider}/connect`

```http
POST /v1/connectors/google_drive/connect
Authorization: Bearer em_xxx
```

**响应：**

```json
{
  "data": {
    "provider": "google_drive",
    "auth_url": "https://accounts.google.com/o/oauth2/auth?...",
    "state_token": "abc123",
    "expires_in": 600
  },
  "meta": {
    "request_id": "c9d0e1f2",
    "took_ms": 20
  }
}
```

**支持的提供商：** `google_drive`、`gmail`、`notion`、`github`

---

### 11. OAuth 回调 — `GET /connectors/{provider}/callback`

OAuth 授权后的回调端点。由提供商重定向调用，**无需手动调用**。

```http
GET /v1/connectors/google_drive/callback?code=xxx&state=abc123
```

---

### 12. Webhook 接收 — `POST /connectors/{provider}/webhook`

接收外部提供商的变更通知。**由提供商调用，无需手动调用。**

```http
POST /v1/connectors/github/webhook
X-Hub-Signature-256: sha256=xxx

{ "repository": { "owner": { "login": "user_123" } }, ... }
```

---

### 13. 获取连接状态 — `GET /connectors/{provider}`

```http
GET /v1/connectors/google_drive
Authorization: Bearer em_xxx
```

**响应（已连接）：**

```json
{
  "data": {
    "provider": "google_drive",
    "sync_status": "active",
    "last_synced_at": "2026-05-29T06:00:00Z",
    "error_message": null,
    "connected_at": "2026-05-20T10:00:00Z"
  },
  "meta": {
    "request_id": "g3h4i5j6",
    "took_ms": 18
  }
}
```

**响应（未连接）：**

```json
{
  "data": {
    "provider": "google_drive",
    "sync_status": "inactive",
    "last_synced_at": null,
    "error_message": null,
    "connected_at": null
  }
}
```

---

### 14. 撤销连接 — `DELETE /connectors/{provider}`

```http
DELETE /v1/connectors/google_drive
Authorization: Bearer em_xxx
```

**响应：** `204 No Content`

---

## 系统端点

### 15. 健康检查 — `GET /health`

无需认证。探测所有依赖服务状态。

```http
GET /v1/health
```

**响应：**

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
  "meta": {
    "took_ms": 25
  }
}
```

---

### 16. 指标 — `GET /metrics`

Prometheus 格式的运行时指标。

```http
GET /v1/metrics
```

**关键指标：**

| 指标名 | 类型 | 说明 |
|---|---|---|
| `http_requests_total` | Counter | 按 method、endpoint、status 统计 |
| `http_request_duration_seconds` | Histogram | 请求处理延迟 |
| `pipeline_jobs_total` | Counter | 按 status 统计 |
| `profile_cache_hit_ratio` | Gauge | 画像缓存命中率 |

---

## cURL 完整示例

### 完整工作流示例

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

## Python 请求示例

```python
import requests

API_KEY = "em_xxx"
BASE_URL = "http://localhost:8000/v1"
headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# 添加记忆
r = requests.post(f"{BASE_URL}/memories", headers=headers, json={
    "content": "用户明天下午 3 点有面试",
    "entity_id": "user_123",
    "content_type": "text",
})
print(r.json())

# 搜索
r = requests.post(f"{BASE_URL}/search", headers=headers, json={
    "q": "用户最近的安排",
    "entity_id": "user_123",
    "search_mode": "memory",
})
print(r.json())

# 上传文件
with open("document.pdf", "rb") as f:
    r = requests.post(
        f"{BASE_URL}/upload",
        headers={"Authorization": f"Bearer {API_KEY}"},
        files={"file": f},
        data={"entity_id": "user_123", "title": "技术文档"},
    )
print(r.json())
```

---

## 设计原则

Emerald API 遵循以下设计原则：

1. **最小接口面** — 核心只有 `add`、`search`、`profile`、`upload` 四个方法
2. **实体优先** — 每个操作都限定在 `entity_id` 范围内，无全局匿名池
3. **声明式** — 开发者描述想要什么，不配置分块参数、嵌入模型或关系
4. **开箱即用默认值** — 默认混合搜索，自动检测内容类型
5. **统一响应格式** — 所有端点返回 `{"data": ..., "meta": {...}}`
