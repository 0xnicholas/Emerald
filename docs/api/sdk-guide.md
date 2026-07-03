# Emerald Python SDK 指南

Emerald 提供官方 Python SDK，以最小化的接口封装 REST API。SDK 遵循 AGENTS.md 设计原则：**不暴露内部图谱操作**，公共方法仅限 `add`、`search`、`profile`、`upload` 四个核心方法。

> **需要 TypeScript / JavaScript？** 参见 [`sdk/typescript/README.md`](../../sdk/typescript/README.md)（`@emerald/sdk`，v0.5.0）。两个 SDK 在方法集、异常体系、错误码上保持一致。

---

## 安装

```bash
pip install emerald
```

或从源码安装：

```bash
git clone https://github.com/emerald-ai/emerald.git
cd emerald
pip install -e ".[dev]"
```

---

## 快速开始

```python
import asyncio
from emerald.sdk import EmeraldClient

async def main():
    client = EmeraldClient(
        api_key="em_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        base_url="http://localhost:8000",  # 生产环境使用 https://api.emerald.ai
    )

    # 1. 添加记忆
    result = await client.add(
        content="用户偏好 TypeScript 和函数式编程风格",
        entity_id="user_123",
        content_type="text",
        metadata={"source": "onboarding_chat"},
    )
    print(f"Created memories: {result.memory_ids}")

    # 2. 搜索
    results = await client.search(
        q="用户喜欢什么编程语言？",
        entity_id="user_123",
        search_mode="hybrid",
        top_k=5,
    )
    for r in results.results:
        print(f"[{r.source}] {r.content[:60]}... (score: {r.score:.3f})")

    # 3. 获取用户画像
    profile = await client.profile("user_123")
    print(f"Static facts: {[f.content for f in profile.static]}")
    print(f"Dynamic facts: {[f.content for f in profile.dynamic]}")

    await client.close()

asyncio.run(main())
```

---

## 认证

SDK 支持两种配置方式：

### 方式一：构造函数参数

```python
client = EmeraldClient(
    api_key="em_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    base_url="http://localhost:8000",
)
```

### 方式二：环境变量

```bash
export EMERALD_API_KEY="em_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export EMERALD_BASE_URL="http://localhost:8000"
```

```python
client = EmeraldClient()  # 自动从环境变量读取
```

---

## 核心方法

### `add(content, *, entity_id, content_type="text", title=None, metadata=None)`

将内容摄入记忆图谱。对于文本内容同步返回记忆 ID；对于文件内容，自动走异步管线。

**参数：**

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `content` | `str` | ✅ | 文本内容 |
| `entity_id` | `str` | ✅ | 实体标识 |
| `content_type` | `str` | — | 内容类型：`text`（默认）、`conversation`、`url`、`code`、`markdown` |
| `title` | `str` | — | 可选标题 |
| `metadata` | `dict` | — | 自定义元数据 |

**返回：** `AddResult`

| 字段 | 类型 | 说明 |
|---|---|---|
| `memory_ids` | `list[str]` | 创建的记忆 ID |
| `pipeline_status` | `str` | `done` 或 `queued` |
| `extracted_count` | `int` | 提取出的记忆数量 |
| `pipeline_id` | `str \| None` | 异步管线 ID（仅异步模式） |

**示例：**

```python
# 添加事实
result = await client.add(
    "用户是资深前端工程师，偏好 React 和 TypeScript",
    entity_id="user_123",
    metadata={"source": "linkedin_import"},
)

# 添加对话
result = await client.add(
    "Assistant: 你好！User: 你好，我想学习 Rust",
    entity_id="user_123",
    content_type="conversation",
)

# 添加 URL
result = await client.add(
    "https://example.com/blog/rust-tutorial",
    entity_id="user_123",
    content_type="url",
)
```

---

### `search(q, *, entity_id, search_mode="hybrid", top_k=10, rerank=False, rewrite_query=False, filters=None)`

混合搜索——单次查询同时返回记忆结果和 RAG 文档结果。

**参数：**

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `q` | `str` | ✅ | 搜索查询 |
| `entity_id` | `str` | ✅ | 实体范围 |
| `search_mode` | `str` | — | `hybrid`（默认）、`memory`、`rag` |
| `top_k` | `int` | — | 返回结果数（1-100，默认 10） |
| `rerank` | `bool` | — | 启用重排序 |
| `rewrite_query` | `bool` | — | 启用查询改写 |
| `filters` | `dict` | — | 元数据过滤 |

**返回：** `SearchResults`

| 字段 | 类型 | 说明 |
|---|---|---|
| `results` | `list[SearchResult]` | 搜索结果列表 |
| `search_mode` | `str` | 实际使用的搜索模式 |
| `query_rewritten` | `str \| None` | 改写后的查询（如启用） |

`SearchResult` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 结果 ID |
| `content` | `str` | 内容 |
| `summary` | `str` | 摘要 |
| `score` | `float` | 相关性分数 |
| `source` | `str` | `memory` 或 `rag` |
| `memory_type` | `str` | 记忆类型（仅 memory） |
| `is_latest` | `bool` | 是否为最新版本（仅 memory） |
| `document_id` | `str \| None` | 文档 ID（仅 rag） |
| `document_title` | `str \| None` | 文档标题（仅 rag） |

**示例：**

```python
# 基础搜索
results = await client.search("用户的编程偏好", entity_id="user_123")

# 仅搜索记忆
results = await client.search(
    "用户最近的项目",
    entity_id="user_123",
    search_mode="memory",
    top_k=5,
)

# 仅搜索文档（RAG）
results = await client.search(
    "Rust 内存安全",
    entity_id="user_123",
    search_mode="rag",
    top_k=10,
)

# 带过滤的搜索
results = await client.search(
    "用户偏好",
    entity_id="user_123",
    filters={"memory_type": "preference", "min_confidence": 0.8},
)
```

---

### `profile(entity_id)`

获取实体画像——静态事实 + 动态事实的双层摘要。

目标延迟：约 50ms（Redis 缓存）。画像在摄入时更新，而非读取时计算。

**参数：**

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `entity_id` | `str` | ✅ | 实体标识 |

**返回：** `Profile`

| 字段 | 类型 | 说明 |
|---|---|---|
| `entity_id` | `str` | 实体 ID |
| `static` | `list[ProfileFact]` | 静态事实（长期偏好、属性） |
| `dynamic` | `list[ProfileFact]` | 动态事实（近期事件、话题） |
| `memory_count` | `int` | 该实体总记忆数 |
| `computed_at` | `str` | 计算时间（ISO 格式） |
| `version` | `int` | 版本号 |

`ProfileFact` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | `str` | 事实内容 |
| `importance` | `float` | 静态事实重要性（0-1） |
| `relevance` | `float` | 动态事实相关性（0-1） |
| `source` | `str` | 来源 |
| `acquired_at` | `str` | 获取时间 |

**示例：**

```python
profile = await client.profile("user_123")

print("=== 静态画像 ===")
for fact in profile.static:
    print(f"  • {fact.content} (importance: {fact.importance:.2f})")

print("=== 动态画像 ===")
for fact in profile.dynamic:
    print(f"  • {fact.content} (relevance: {fact.relevance:.2f}, source: {fact.source})")
```

---

### `upload(file, *, entity_id, content_type=None, title=None)`

上传文件进行异步处理。支持 PDF、图片、音频、视频、代码文件等。文件大小上限 50MB。

**参数：**

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `file` | `BinaryIO \| bytes \| str` | ✅ | 文件对象、字节串或文件路径 |
| `entity_id` | `str` | ✅ | 实体标识 |
| `content_type` | `str` | — | MIME 类型（自动检测） |
| `title` | `str` | — | 文件标题 |

**返回：** `AddResult`（`pipeline_id` 用于追踪处理状态）

**示例：**

```python
from pathlib import Path

# 上传文件路径
result = await client.upload(
    "/path/to/resume.pdf",
    entity_id="user_123",
    title="用户简历",
)
print(f"Pipeline ID: {result.pipeline_id}")

# 上传文件对象
with open("/path/to/photo.jpg", "rb") as f:
    result = await client.upload(f, entity_id="user_123")

# 上传字节串
raw_bytes = Path("/path/to/audio.mp3").read_bytes()
result = await client.upload(raw_bytes, entity_id="user_123")
```

---

## 工具方法

### `health()`

检查 API 服务健康状态。

```python
status = await client.health()
print(f"Status: {status.status}")
print(f"Version: {status.version}")
for svc, state in status.checks.items():
    print(f"  {svc}: {state}")
```

### `pipeline_status(pipeline_id)`

查询异步管线处理状态。

```python
status = await client.pipeline_status("pipe_abc123")
print(f"Status: {status.status}")  # queued | extracting | chunking | embedding | indexing | done | failed
print(f"Stage: {status.stage}")
print(f"Chunks: {status.chunk_count}")
if status.error_message:
    print(f"Error: {status.error_message}")
```

### `get_memory(memory_id)`

获取单条记忆的完整信息。

```python
memory = await client.get_memory("mem_abc123")
print(memory["content"])
print(memory["relationships"])
```

---

## 高级用法

### 异步上下文管理器

```python
async with EmeraldClient() as client:
    result = await client.add("...", entity_id="user_123")
    # 离开上下文时自动关闭连接
```

### 批量添加记忆

```python
contents = [
    ("用户喜欢猫", {"source": "chat"}),
    ("用户在 Google 工作", {"source": "resume"}),
    ("用户明天有面试", {"source": "calendar"}),
]

for content, meta in contents:
    await client.add(content, entity_id="user_123", metadata=meta)
```

### 轮询管线状态

```python
import asyncio

async def wait_for_pipeline(client, pipeline_id, timeout=300):
    for _ in range(timeout):
        status = await client.pipeline_status(pipeline_id)
        if status.status == "done":
            return status
        if status.status == "failed":
            raise RuntimeError(f"Pipeline failed: {status.error_message}")
        await asyncio.sleep(1)
    raise TimeoutError("Pipeline did not complete in time")
```

---

## 错误处理

SDK 使用 `httpx.HTTPStatusError` 抛出 HTTP 错误。建议按状态码处理：

```python
import httpx

try:
    result = await client.add("...", entity_id="user_123")
except httpx.HTTPStatusError as e:
    if e.response.status_code == 401:
        print("API key 无效或已过期")
    elif e.response.status_code == 429:
        print("请求过于频繁，请稍后重试")
    elif e.response.status_code == 413:
        print("内容过大")
    else:
        print(f"请求失败: {e.response.text}")
```

---

## 数据模型参考

```python
from emerald.sdk.models import (
    AddResult,
    SearchResult,
    SearchResults,
    ProfileFact,
    Profile,
    HealthStatus,
    PipelineStatus,
)
```

---

## 与 MCP 集成

Emerald 同时提供 MCP（Model Context Protocol）服务器，供 Claude Desktop、Cursor 等客户端直接使用：

```bash
# 配置 claude_desktop_config.json
{
  "mcpServers": {
    "emerald": {
      "command": "python",
      "args": ["-m", "emerald.mcp.server"],
      "env": {
        "EMERALD_API_KEY": "em_xxx",
        "EMERALD_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

暴露的 MCP 工具：`emerald_add`、`emerald_search`、`emerald_profile`。

---

## Post-v0.3.0 SDK 增强（2026-06-02 之后）

> 本节记录 v0.3.0 之后影响 Python SDK 的重大变更（M1 + M2 全部完成，待 v0.4.0 发布）。详见 [`docs/roadmap.md`](../roadmap.md) 与 [`CHANGELOG.md`](../../CHANGELOG.md) Unreleased 段。

### SDK 方法覆盖现状

Python SDK (`emerald/sdk/client.py`) 当前公开 8 个方法，与 REST API 对应关系：

| SDK 方法 | HTTP 端点 | v0.3.0 覆盖 | Post-v0.3.0 增强 |
|---|---|---|---|
| `add(content, ...)` | `POST /v1/memories` | ✅ | + `metadata` 参数、`memory_type`/`confidence`/`valid_until` 覆盖 |
| `search(q, ...)` | `POST /v1/search` | ✅ | + `filters` 参数（MongoDB 风格） |
| `profile(entity_id)` | `GET /v1/profiles/{id}` | ✅ | + 多因子 `importance` 评分 |
| `upload(file, ...)` | `POST /v1/upload` | ✅ | + 异步执行（不阻塞） |
| `health()` | `GET /v1/health` | ✅ | — |
| `pipeline_status(id)` | `GET /v1/pipelines/{id}` | ✅ | + `fact_extraction_status` 字段 |
| `get_memory(id)` | `GET /v1/memories/{id}` | ✅ | — |
| `close()` | — | ✅ | — |

**SDK 未覆盖的 Post-v0.3.0 新端点**（临时通过 httpx 调用）：

```python
# POST /v1/memories/batch
import httpx
async with httpx.AsyncClient(base_url=client.base_url, headers=client._headers) as h:
    resp = await h.post("/v1/memories/batch", json={"memories": [...]})

# GET /v1/memories/graph
resp = await h.get("/v1/memories/graph", params={"entity_id": "...", "limit": 100})

# DELETE /v1/memories/{id}
resp = await h.delete(f"/v1/memories/{memory_id}")
```

**路线图：** M3 (v0.6.0) 将补齐这些方法为 SDK 一等公民。详见 [`docs/roadmap.md`](../roadmap.md)。

### 新增 `filters` 参数（搜索）

```python
# 查找高置信度的偏好记忆
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

# 查找最近 30 天的 fact 或 episodic
import datetime
from datetime import timezone
thirty_days_ago = (datetime.now(timezone.utc) - datetime.timedelta(days=30)).isoformat()

result = await client.search(
    q="用户最近在做什么",
    entity_id="user_123",
    filters={
        "$or": [
            {"memory_type": "fact"},
            {"memory_type": "episodic"},
        ],
        "created_at": {"$gte": thirty_days_ago},  # 注：created_at 过滤需要服务端支持
    },
)
```

**支持的操作符：** `$eq`、`$ne`、`$gt`、`$gte`、`$lt`、`$lte`、`$and`、`$or`。详见 [`docs/architecture/api-design.md`](../architecture/api-design.md) §11.2。

### `add()` 新增 metadata override

```python
# 覆盖 LLM 提取结果（高级用户场景）
result = await client.add(
    content="用户偏好 TypeScript",  # LLM 通常会归类为 preference
    entity_id="user_123",
    memory_type="preference",        # 显式指定
    confidence=0.95,                  # 跳过 LLM 评分
    valid_until=None,                 # 永不过期（默认）
    metadata={
        "source": "manual_entry",
        "tags": ["important", "verified"],
        "captured_by": "operator_jane",
    },
)
```

**注意：** 设置 `memory_type`/`confidence` 后，引擎跳过 LLM 提取阶段（节省 token 成本）。但你仍需保证内容确实属于该类型。

### `pipeline_status()` 返回 `fact_extraction_status`

```python
status = await client.pipeline_status(pipeline_id)
print(f"事实提取: {status.fact_extraction_status}")  # "success" | "failed" | "skipped"
print(f"提取事实数: {status.memory_count}")           # 可能 > 1（LLM 提取后多事实）
```

### 错误处理增强

Post-v0.3.0 SDK 抛出更具体的异常类型（基于 HTTP 错误码）：

| HTTP | SDK 异常 | 场景 |
|---|---|---|
| 401 | `EmeraldAuthError` | API Key 无效或过期 |
| 404 | `EmeraldNotFoundError` | 记忆/画像/管线不存在 |
| 422 | `EmeraldValidationError` | 请求体验证失败（包含字段级错误） |
| 429 | `EmeraldRateLimitError` | 速率限制（带 `Retry-After` header） |
| 5xx | `EmeraldServerError` | 服务端错误（自动重试 3 次） |
| 网络错误 | `EmeraldNetworkError` | 连接超时、DNS 失败等 |

```python
from emerald.sdk.exceptions import (
    EmeraldAuthError, EmeraldValidationError, EmeraldRateLimitError
)

try:
    result = await client.add(content=..., entity_id=...)
except EmeraldValidationError as e:
    print(f"字段错误: {e.field_errors}")  # {"memory_type": "must be one of fact, preference, episodic"}
except EmeraldRateLimitError as e:
    await asyncio.sleep(e.retry_after)  # 自动从 Retry-After header 读取
    # 重试...
```

### SDK 安装方式变化

Post-v0.3.0 推荐使用 `uv` 而非 `pip`：

```bash
# 推荐（10× 更快）
uv add emerald-sdk

# 兼容
pip install emerald-sdk
```

**源码安装（开发场景）：**

```bash
git clone https://github.com/your-org/Emerald.git
cd Emerald
uv pip install -e emerald/sdk
```

### 异步上下文管理器（增强）

```python
# 之前
client = EmeraldClient()
result = await client.add(...)
await client.close()

# 之后（推荐）
async with EmeraldClient() as client:
    result = await client.add(...)
    # 退出 with 块时自动 close()
```

### 调试技巧

```python
# 启用详细日志（默认 WARNING）
import logging
logging.basicConfig(level=logging.DEBUG)

# 查看原始 HTTP 请求/响应
client = EmeraldClient()
client._client = httpx.AsyncClient(
    base_url=client.base_url,
    headers=client._headers,
    timeout=30.0,
    event_hooks={
        "request": [lambda r: print(f">>> {r.method} {r.url}")],
        "response": [lambda r: print(f"<<< {r.status_code} {r.url}")],
    },
)
```
