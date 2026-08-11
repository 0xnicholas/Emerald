# API 设计

Emerald API 遵循 RESTful 设计风格，以实体（Entity）为中心，提供最小的接口面。

---

## 1. 设计原则

| 原则 | 说明 |
|---|---|
| **最小接口面** | `add` / `search` / `profile` / `upload` 四个核心方法。其他为可选增强。 |
| **实体优先** | 每个操作限定在 `entity_id` 范围内。无全局匿名上下文池。 |
| **声明式** | 描述想要什么，而非如何实现。无需配置分块/嵌入/关系。 |
| **默认可用** | 混合搜索为默认模式。内容类型自动检测。智能默认值。 |
| **一致性** | 多语言 SDK 方法名、参数结构、返回类型一一对应。 |

---

## 2. 认证

### 2.1 API Key

所有 API 请求需要 API Key。格式：`em_` + 32 字符随机字符串。

```
Authorization: Bearer em_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

服务端仅存储 SHA-256 哈希，不存储明文 Key。

### 2.2 权限模型

```python
class Permission(str, Enum):
    READ = "read"        # 查询记忆、画像、搜索
    WRITE = "write"      # 添加记忆、上传文件
    ADMIN = "admin"      # 管理连接器、设置、API Key

# 每个 entity 可有多把 Key，各有权限范围
```

### 2.3 认证中间件

```python
async def api_key_auth(request: Request, db: AsyncSession):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer em_"):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")

    api_key = auth_header.removeprefix("Bearer ")
    key_hash = sha256(api_key.encode()).hexdigest()

    key_record = await db.scalar(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    if not key_record:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if key_record.expires_at and key_record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="API key expired")

    # 注入上下文
    request.state.entity_id = str(key_record.entity_id)
    request.state.permissions = key_record.permissions
    request.state.api_key_id = str(key_record.id)

    # 更新最后使用时间
    await db.execute(update(ApiKey).values(last_used_at=datetime.utcnow()))
```

---

## 3. 基础信息

| 属性 | 值 |
|---|---|
| Base URL | `https://api.emerald.ai/v1` (生产) 或 `http://localhost:8000/v1` (开发) |
| Content-Type | `application/json` |
| Accept | `application/json` |
| 字符编码 | UTF-8 |
| 日期格式 | ISO 8601 (`2026-05-22T10:30:00Z`) |

---

## 4. 统一响应格式

### 4.1 成功响应

```json
{
    "data": {
        // 端点特定的响应数据
    },
    "meta": {
        "request_id": "req_abc123",
        "took_ms": 45
    }
}
```

### 4.2 错误响应

```json
{
    "error": {
        "code": "INVALID_CONTENT_TYPE",
        "message": "不支持的内容类型：application/octet-stream",
        "details": {
            "supported_types": ["text", "url", "pdf", "image", "audio", "video", "code", "markdown", "json", "csv"]
        }
    },
    "meta": {
        "request_id": "req_abc123"
    }
}
```

### 4.3 错误码

| HTTP 状态码 | 错误码 | 说明 |
|---|---|---|
| 400 | `INVALID_REQUEST` | 请求格式错误 |
| 400 | `INVALID_CONTENT_TYPE` | 不支持的内容类型 |
| 400 | `CONTENT_TOO_LARGE` | 内容超过大小限制 |
| 400 | `INVALID_ENTITY_ID` | 实体 ID 格式无效 |
| 400 | `EMPTY_CONTENT` | 内容为空 |
| 401 | `UNAUTHORIZED` | 缺少或无效的 API Key |
| 401 | `API_KEY_EXPIRED` | API Key 已过期 |
| 403 | `FORBIDDEN` | 权限不足 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `ALREADY_EXISTS` | 资源重复 |
| 413 | `PAYLOAD_TOO_LARGE` | 请求体过大 |
| 429 | `RATE_LIMITED` | 速率限制 |
| 500 | `INTERNAL_ERROR` | 服务内部错误 |
| 503 | `PIPELINE_UNAVAILABLE` | 处理管线不可用 |

---

## 5. 端点

### 5.1 记忆

#### 添加记忆

```
POST /v1/memories
```

**请求体：**

```json
{
    "content": "用户偏好 TypeScript 和函数式编程风格",
    "entity_id": "user_123",
    "content_type": "text",
    "title": "编程偏好",
    "metadata": {
        "source": "chat",
        "session_id": "sess_456"
    }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `content` | string \| base64 | 是 | 文本内容或 base64 编码的文件 |
| `entity_id` | string | 是 | 实体 ID |
| `content_type` | string | 否 | 内容类型（自动检测时不填） |
| `title` | string | 否 | 内容标题 |
| `metadata` | object | 否 | 自定义元数据 |
| `async_mode` | boolean | 否 | 是否异步处理（默认文件类自动异步） |

**响应 (同步 - 文本内容)：**

```json
{
    "data": {
        "memory_ids": ["mem_abc123", "mem_def456"],
        "pipeline_status": "done",
        "extracted_count": 2
    },
    "meta": { "request_id": "req_abc123", "took_ms": 320 }
}
```

**响应 (异步 - 文件内容)：**

HTTP 202 Accepted

```json
{
    "data": {
        "pipeline_id": "pipe_xyz789",
        "pipeline_status": "queued",
        "estimated_duration_seconds": 45
    },
    "meta": { "request_id": "req_abc123" }
}
```

#### 获取记忆

```
GET /v1/memories/{memory_id}
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
                "target_id": "mem_xyz001",
                "target_summary": "用户是一名资深前端工程师"
            }
        ],
        "created_at": "2026-05-22T10:30:00Z",
        "updated_at": "2026-05-22T10:30:00Z"
    }
}
```

#### 删除记忆

```
DELETE /v1/memories/{memory_id}
```

返回 204 No Content。

---

### 5.2 搜索

#### 混合搜索

```
POST /v1/search
```

**请求体：**

```json
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

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `q` | string | 是 | — | 搜索查询 |
| `entity_id` | string | 是 | — | 实体 ID |
| `search_mode` | string | 否 | `hybrid` | `hybrid` / `memory` / `rag` |
| `top_k` | integer | 否 | 10 | 返回结果数 |
| `rerank` | boolean | 否 | false | 是否使用交叉编码器重排序 |
| `rewrite_query` | boolean | 否 | false | 是否使用 LLM 扩展查询 |
| `filters` | object | 否 | {} | 元数据筛选 |

**响应：**

```json
{
    "data": {
        "results": [
            {
                "id": "mem_abc123",
                "content": "用户偏好 TypeScript 和函数式编程风格",
                "summary": "用户是 TypeScript 开发者",
                "memory_type": "preference",
                "score": 0.92,
                "source": "memory",
                "is_latest": true,
                "created_at": "2026-05-20T14:00:00Z"
            },
            {
                "id": "doc_chunk_456",
                "content": "TypeScript 是一种强类型编程语言，由微软开发...",
                "score": 0.85,
                "source": "rag",
                "document_id": "doc_789",
                "document_title": "TypeScript 官方文档",
                "chunk_index": 4
            }
        ],
        "search_mode": "hybrid",
        "query_rewritten": null
    },
    "meta": { "request_id": "req_abc123", "took_ms": 120 }
}
```

#### GET 简化搜索

```
GET /v1/search?q=...&entity_id=...&search_mode=hybrid&top_k=10
```

功能与 POST 相同，适合快速调试。

---

### 5.3 用户画像

#### 获取画像

```
GET /v1/profiles/{entity_id}
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
                "content": "偏好 TypeScript 和函数式编程",
                "importance": 0.88
            },
            {
                "content": "使用 Vim 编辑器",
                "importance": 0.80
            }
        ],
        "dynamic": [
            {
                "content": "正在进行认证模块迁移",
                "relevance": 0.90,
                "source": "最近对话",
                "acquired_at": "2026-05-21T15:00:00Z"
            },
            {
                "content": "调试 Redis 限流问题",
                "relevance": 0.85,
                "source": "最近对话",
                "acquired_at": "2026-05-22T09:00:00Z"
            }
        ],
        "memory_count": 128,
        "computed_at": "2026-05-22T10:30:00Z",
        "version": 12
    }
}
```

#### 更新画像配置

> ⚠️ **状态：计划中**。此端点尚未实现。代码中不存在 `PUT /v1/profiles/{entity_id}/config` 路由。计划在 [M2 (v0.5.0)](../roadmap.md) 实现。
>
> 下面是设计草案（供参考）：

```
PUT /v1/profiles/{entity_id}/config   [Planned for v0.5.0]
```

```json
{
    "static_max_items": 10,
    "dynamic_max_items": 5,
    "dynamic_lookback_days": 7,
    "min_confidence_static": 0.5,
    "min_confidence_dynamic": 0.3
}
```

**临时配置方式：** 当前画像参数（`min_confidence_static`、`dynamic_max_items` 等）在 `emerald/core/profile.py` 中硬编码默认值。如需调整，需直接修改代码并重启服务。

---

### 5.4 文件上传

#### 上传文件

```
POST /v1/upload
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 文件二进制 |
| `entity_id` | string | 是 | 实体 ID |
| `content_type` | string | 否 | 文件类型（自动检测时不填） |
| `title` | string | 否 | 文件标题 |
| `metadata` | string (JSON) | 否 | 自定义元数据 |

**响应 (202 Accepted)：**

```json
{
    "data": {
        "document_id": "doc_xyz789",
        "pipeline_id": "pipe_abc123",
        "pipeline_status": "queued",
        "file_size_bytes": 204800,
        "content_type": "pdf",
        "title": "架构设计文档.pdf"
    }
}
```

#### 查询管线状态

```
GET /v1/pipelines/{pipeline_id}
```

**响应：**

```json
{
    "data": {
        "pipeline_id": "pipe_abc123",
        "status": "embedding",
        "stage": "embedding",
        "document_id": "doc_xyz789",
        "content_type": "pdf",
        "chunk_count": 34,
        "error_message": null
    }
}
```

#### 列出文件

```
GET /v1/files?entity_id=user_123&status=done&page=1&page_size=20
```

**响应：**

```json
{
    "data": {
        "items": [
            {
                "id": "doc_xyz789",
                "title": "架构设计文档.pdf",
                "content_type": "pdf",
                "file_size_bytes": 204800,
                "page_count": 12,
                "chunk_count": 34,
                "status": "done",
                "created_at": "2026-05-20T10:00:00Z"
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20
    }
}
```

---

### 5.5 数据源绑定（连接中心）

> ADR-0004：凭证/同步/执行外包给连接中心（当前实现 Totem，`../totem`）。Emerald 只维护
> 「数据源绑定」（授权关系 + 数据源身份）。详见[连接中心架构](connectors.md)。

#### 发起授权流

```
POST /v1/sources/connect
```

请求体：`{ "entity_id": "...", "provider": "feishu" }`（provider 当前仅支持 `feishu`）

**响应：**

```json
{
    "data": {
        "auth_link_url": "https://totem.internal/oauth/start?...",
        "session_id": "...",
        "provider": "feishu"
    }
}
```

用户被送往 `auth_link_url` 在连接中心完成授权；返回后调用 refresh 完成绑定。

#### 列出现有绑定

```
GET /v1/sources?entity_id=...
```

#### 刷新绑定（授权后回调用）

```
POST /v1/sources/refresh?entity_id=...
```

与连接中心对账，将新授权的账户 upsert 为绑定。

#### 删除绑定

```
DELETE /v1/sources/{binding_id}?entity_id=...
```

数据保留在图谱中，停止后续同步。

#### Webhook（上游订阅「铃铛」）

```
POST /v1/sources/webhook
```

连接中心/上游事件投递端点，验签后归一化入队（Totem v1 无投递面，见 ADR-0011；
标准契约见 Totem consumption standard §8）。

---

### 5.6 系统

#### 健康检查

```
GET /v1/health
```

```json
{
    "status": "ok",
    "version": "0.3.0",
    "checks": {
        "database": "ok",
        "neo4j": "ok",
        "redis": "ok",
        "minio": "ok",
        "celery": "ok"
    }
}
```

#### 指标

```
GET /v1/metrics
```

返回 Prometheus 格式的指标数据。

---

## 6. 分页规范

```json
{
    "data": {
        "items": [...],
        "total": 150,
        "page": 1,
        "page_size": 20,
        "next_cursor": null
    }
}
```

游标分页（推荐用于大数据集）：

```
GET /v1/memories?entity_id=user_123&cursor=mem_abc123&limit=20
```

---

## 7. 速率限制

| 端点 | 限制 | 窗口 |
|---|---|---|
| `POST /v1/memories` | 60 次 | 每分钟，每 API Key |
| `POST /v1/search` | 120 次 | 每分钟，每 API Key |
| `GET /v1/profiles/{id}` | 300 次 | 每分钟，每 API Key |
| `POST /v1/upload` | 10 次 | 每分钟，每 API Key |
| 其他端点 | 60 次 | 每分钟，每 API Key |

超限响应：

```
HTTP 429 Too Many Requests
Retry-After: 45

{
    "error": {
        "code": "RATE_LIMITED",
        "message": "已达速率限制，请在 45 秒后重试"
    }
}
```

---

## 8. 内容大小限制

| 类型 | 最大大小 |
|---|---|
| 文本（JSON body） | 1 MB |
| 文件上传 | 50 MB |
| URL 抓取 | 10 MB（抓取后） |
| 单次请求总大小 | 50 MB |

---

## 9. OpenAPI 规范

所有端点通过 FastAPI 自动生成 OpenAPI 文档：

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

---

## 10. SDK 对应关系

Python SDK 与 REST API 的映射关系必须一致：

| SDK 方法 | HTTP 端点 | 说明 |
|---|---|---|
| `client.add(...)` | `POST /v1/memories` | 添加内容 |
| `client.search(...)` | `POST /v1/search` | 混合搜索 |
| `client.profile(entity_id)` | `GET /v1/profiles/{id}` | 获取画像 |
| `client.upload(file, ...)` | `POST /v1/upload` | 上传文件 |
| `client.get_memory(id)` | `GET /v1/memories/{id}` | 获取记忆 |
| `client.list_files(...)` | `GET /v1/files` | 列出文件 |
| `client.pipeline_status(id)` | `GET /v1/pipelines/{id}` | 管线状态 |

---

## 11. Post-v0.3.0 API 增强（2026-06-02 之后）

> 本节记录 v0.3.0 之后 33 个 commit 中影响 API 设计的重大变更。详见 [`docs/roadmap.md`](../roadmap.md)。

### 11.1 新增端点

| 端点 | 用途 | SDK 覆盖 |
|---|---|---|
| `POST /v1/memories/batch` | 批量写入（最多 50 条） | ❌ 未暴露（可通过底层 httpx 手动调用） |
| `GET /v1/memories/graph` | 图谱可视化（节点+边） | ❌ 未暴露 |
| `DELETE /v1/memories/{id}` | 软删除 | ❌ 未暴露（见 11.3 SDK 现状） |

详见 [`docs/api/rest-guide.md`](../api/rest-guide.md) 中「高级端点」一节。

### 11.2 元数据过滤（MongoDB 风格）

`POST /v1/search` 请求体新增 `filters` 参数：

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

**支持的 6 个操作符：**

| 操作符 | 含义 | 示例 |
|---|---|---|
| (隐含) | 精确匹配 | `{"memory_type": "fact"}` |
| `$eq` / `$ne` | 等于 / 不等于 | `{"memory_type": {"$eq": "fact"}}` |
| `$gt` / `$gte` | 大于 / 大于等于 | `{"confidence": {"$gte": 0.5}}` |
| `$lt` / `$lte` | 小于 / 小于等于 | `{"confidence": {"$lte": 0.9}}` |
| `$and` | 所有子条件满足 | `{"$and": [{...}, {...}]}` |
| `$or` | 任一子条件满足 | `{"$or": [{...}, {...}]}` |

**Python SDK 用法：**

```python
result = await client.search(
    q="用户偏好什么",
    entity_id="user_123",
    search_mode="memory",
    filters={
        "$and": [
            {"memory_type": "preference"},
            {"confidence": {"$gte": 0.7}},
        ]
    },
)
```

### 11.3 SDK 暴露现状

Post-v0.3.0 新增的 3 个端点**目前未在 Python SDK 中暴露方法**。临时方案：

| 端点 | 临时用法 |
|---|---|
| `POST /v1/memories/batch` | 使用 `httpx.AsyncClient` 直接调用 |
| `GET /v1/memories/graph` | 使用 `httpx.AsyncClient` 直接调用 |
| `DELETE /v1/memories/{id}` | 使用 `httpx.AsyncClient` 直接调用 |

**路线图：** M3 (v0.6.0) 将补齐 SDK 方法。详见 [`docs/roadmap.md`](../roadmap.md)。

### 11.4 请求/响应模型扩展

**添加记忆请求体新增可选字段：**

```json
{
  "content": "...",
  "entity_id": "user_123",
  "content_type": "text",
  "memory_type": "fact",                  // 【Post-v0.3.0】覆盖 LLM 提取结果
  "confidence": 0.95,                     // 【Post-v0.3.0】覆盖 LLM 评分
  "valid_until": "2026-12-31T23:59:59Z",  // 【Post-v0.3.0】临时事实过期时间
  "metadata": {                            // 【Post-v0.3.0】MongoDB 过滤的目标
    "source": "manual_entry",
    "tags": ["important", "verified"]
  }
}
```

**记忆响应扩展：**

```json
{
  "memory_ids": ["mem_abc"],
  "pipeline_status": "completed",
  "memory_count": 1,
  "facts_extracted": 3,           // 【Post-v0.3.0】LLM 提取的事实数
  "extraction_skipped": false     // 【Post-v0.3.0】是否跳过（无 LLM key）
}
```

### 11.5 错误码扩展

Post-v0.3.0 新增 4 个业务错误码（与原有错误码体系一致）：

| HTTP | 错误码 | 场景 |
|---|---|---|
| 422 | `BATCH_SIZE_EXCEEDED` | `/memories/batch` 超过 50 条限制 |
| 422 | `INVALID_MEMORY_TYPE` | memory_type 不在 {fact, preference, episodic} |
| 422 | `INVALID_VALID_UNTIL` | valid_until 不是合法 ISO 8601 时间 |
| 404 | `MEMORY_NOT_FOUND` | `DELETE /memories/{id}` 找不到记忆 |

### 11.6 API 版本演进策略

| 版本 | 状态 | 兼容性 |
|---|---|---|
| v1 | 当前 | API 可能变更；不保证向后兼容 |
| **v0.8 (Production-Ready Beta)** | 路线图 | API 趋于稳定；仍可能变更 |
| **v1.0 (GA)** | 路线图 | 承诺 12 个月向后兼容 |

v1.0 不会因功能完成自动触发。详见 [`docs/roadmap.md` 第 10.2 节](../roadmap.md) 中的 7 个硬性条件。
