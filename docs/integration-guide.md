# Emerald 集成指南

## 概述

Emerald 是面向 AI Agent 的记忆与上下文基础设施。外部项目通过两种方式接入：

| 方式 | 适用场景 | SDK |
|---|---|---|
| **SDK 直连** | Python 项目 | `EmeraldClient` |
| **REST API** | 任何语言 | HTTP + JSON |

---

## 1. 启动 Emerald 服务

```bash
# Docker Compose（开发环境）
docker compose up -d

# 或直接运行（需要 PostgreSQL + Neo4j + Redis + MinIO）
uvicorn emerald.api.app:app --host 0.0.0.0 --port 8000
```

服务启动后验证：

```bash
curl http://localhost:8000/v1/health
# {"status":"ok","version":"0.3.0","checks":{...}}
```

---

## 2. 创建 API Key

API Key 格式：`em_` + 32 字符随机字符串。服务端仅存储 SHA-256 哈希。

```python
# 通过 SDK 创建（需要 admin 权限）
# TODO: POST /v1/admin/api-keys
```

开发阶段可使用任意 `em_` 前缀的字符串。

---

## 3. Python SDK 集成

### 3.1 初始化

```python
from emerald.sdk import EmeraldClient

client = EmeraldClient(
    api_key="em_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    base_url="http://localhost:8000",   # 默认值，可省略
)
```

也可以通过环境变量：

```bash
export EMERALD_API_KEY="em_xxx"
export EMERALD_BASE_URL="http://localhost:8000"
```

```python
client = EmeraldClient()  # 从环境变量读取
```

### 3.2 四个核心方法

#### add() — 保存内容

```python
result = await client.add(
    "用户在 Stripe 工作，偏好 TypeScript 和函数式编程",
    entity_id="user_123",
    content_type="text",        # 可选，自动检测
    title="编程偏好",            # 可选
    metadata={"source": "chat"} # 可选
)

print(result.memory_ids)        # ["mem_abc123", ...]
print(result.pipeline_status)   # "done" 或 "queued"（异步文件）
```

#### search() — 搜索记忆

```python
results = await client.search(
    "TypeScript",
    entity_id="user_123",
    search_mode="hybrid",   # hybrid | memory | rag
    top_k=10,               # 返回条数
    rerank=False,           # 交叉编码器重排序
)

for r in results.results:
    print(f"[{r.source}] score={r.score:.2f}  {r.content}")
```

#### profile() — 获取用户画像

```python
profile = await client.profile("user_123")

# 静态事实（始终相关）
for fact in profile.static:
    print(f"[静态] {fact.content}  importance={fact.importance}")

# 动态事实（近期上下文）
for fact in profile.dynamic:
    print(f"[动态] {fact.content}  relevance={fact.relevance}")

print(f"总记忆数: {profile.memory_count}")
```

#### upload() — 上传文件

```python
# 文件路径
result = await client.upload("report.pdf", entity_id="user_123")

# 文件内容
with open("report.pdf", "rb") as f:
    result = await client.upload(f, entity_id="user_123")

print(result.pipeline_id)  # 异步处理，用此 ID 查询状态
```

### 3.3 辅助方法

```python
# 健康检查
health = await client.health()

# 管线状态查询（异步上传后使用）
status = await client.pipeline_status(result.pipeline_id)

# 获取单条记忆详情
memory = await client.get_memory("mem_abc123")
```

### 3.4 上下文管理器

```python
async with EmeraldClient(api_key="em_xxx") as client:
    await client.add("...", entity_id="user_123")
    # 自动 close()
```

或手动管理：

```python
client = EmeraldClient(api_key="em_xxx")
try:
    await client.add("...", entity_id="user_123")
finally:
    await client.close()
```

---

## 4. REST API 集成

### 4.1 认证

所有请求携带 `Authorization` 头：

```
Authorization: Bearer em_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 4.2 保存记忆

```bash
curl -X POST http://localhost:8000/v1/memories \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "用户在 Stripe 工作",
    "entity_id": "user_123",
    "content_type": "text",
    "title": "工作岗位",
    "metadata": {"source": "chat"}
  }'
```

响应：

```json
{
  "data": {
    "memory_ids": ["mem_abc123"],
    "pipeline_status": "done",
    "extracted_count": 1
  },
  "meta": {
    "request_id": "a1b2c3d4"
  }
}
```

### 4.3 搜索

```bash
curl -X POST http://localhost:8000/v1/search \
  -H "Authorization: Bearer em_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "q": "TypeScript",
    "entity_id": "user_123",
    "search_mode": "hybrid",
    "top_k": 10
  }'
```

### 4.4 获取画像

```bash
curl http://localhost:8000/v1/profiles/user_123 \
  -H "Authorization: Bearer em_xxx"
```

### 4.5 上传文件

```bash
curl -X POST http://localhost:8000/v1/upload \
  -H "Authorization: Bearer em_xxx" \
  -F "file=@report.pdf" \
  -F "entity_id=user_123" \
  -F "title=架构设计文档"
```

### 4.6 查询管线状态

```bash
curl http://localhost:8000/v1/pipelines/{pipeline_id} \
  -H "Authorization: Bearer em_xxx"
```

---

## 5. 典型集成模式

### 5.1 AI Agent 对话循环

```python
async def handle_message(user_id: str, message: str) -> str:
    client = EmeraldClient(api_key="em_xxx")

    # 1. 画出画像 — 注入 Agent 系统提示词
    profile = await client.profile(user_id)
    static_context = "\n".join(f"- {f.content}" for f in profile.static)
    dynamic_context = "\n".join(f"- {f.content}" for f in profile.dynamic)

    system_prompt = f"""你正在与用户对话。
已知信息：
{static_context}

最近上下文：
{dynamic_context}
"""

    # 2. 搜索相关记忆 — 回答问题时使用
    memories = await client.search(message, entity_id=user_id)
    memory_context = "\n".join(
        f"- {r.content}" for r in memories.results[:5]
    )

    # 3. 调用 LLM
    response = await llm.chat(
        system_prompt + f"\n相关记忆:\n{memory_context}",
        user_message=message,
    )

    # 4. 保存新知 — 对话结束后
    await client.add(
        f"用户说: {message}\n助手回复: {response}",
        entity_id=user_id,
        content_type="conversation",
    )

    await client.close()
    return response
```

### 5.2 知识库索引

```python
async def index_documents(user_id: str, files: list[str]):
    client = EmeraldClient(api_key="em_xxx")

    for path in files:
        result = await client.upload(path, entity_id=user_id)
        # 轮询直到处理完成
        while True:
            status = await client.pipeline_status(result.pipeline_id)
            if status.status in ("done", "failed"):
                break
            await asyncio.sleep(1)

    await client.close()
```

### 5.3 时序事实追踪

```python
# Day 1
await client.add("用户在 Google 工作", entity_id="user_123")

# Day 30 — 换工作
await client.add("用户在 Stripe 工作", entity_id="user_123")
# Emerald 自动检测到与旧事实矛盾 → 旧事实 is_latest=False

# Day 31 — 补充信息
await client.add("用户领导一个 5 人的支付团队", entity_id="user_123")
# Emerald 自动创建 EXTENDS 关系（两者都保持有效）

# 查询时只返回最新事实
profile = await client.profile("user_123")
# static: "用户在 Stripe 工作", "用户领导支付团队"
# 旧事实 "用户在 Google 工作" 已自动隐藏
```

---

## 6. 实体隔离

每个 `entity_id` 的记忆完全隔离：

```python
await client.add("Alice 的秘密", entity_id="alice")
await client.add("Bob 的公开信息", entity_id="bob")

# Alice 搜不到 Bob 的内容
results = await client.search("秘密", entity_id="alice")
# → Alice 的秘密

results = await client.search("秘密", entity_id="bob")
# → 空
```

`entity_id` 可以是用户 ID、项目 ID、组织 ID 或任意自定义标识。

---

## 7. 内容类型支持

| 类型 | content_type | 说明 |
|---|---|---|
| 文本 | `text` | 默认，自动检测 |
| 对话 | `conversation` | 多轮对话，保留说话人 |
| URL | `url` | 自动抓取并清洗正文 |
| PDF | `pdf` | 文本提取 + OCR（扫描件） |
| 图片 | `image` | OCR 文字识别 |
| 音频 | `audio` | 语音转文字（Faster-Whisper） |
| 视频 | `video` | 音轨转录 + 关键帧 OCR |
| 代码 | `code` | AST 感知分块（Python/TS/JS/Go/Rust） |
| Markdown | `markdown` | 标题层级分块 |

---

## 8. 速率限制

| 端点 | 限制 (次/分钟) |
|---|---|
| POST /v1/memories | 60 |
| POST /v1/search | 120 |
| GET /v1/profiles/{id} | 300 |
| POST /v1/upload | 10 |

超限返回 HTTP 429 + `Retry-After` 头。

---

## 9. 安全

- **API Key 格式**：`em_` + 32 字符，服务端仅存 SHA-256
- **文件隔离**：按 `entity_id` 路径前缀，MinIO bucket 级别隔离
- **OAuth 凭证**：AES-256-GCM 加密存储
- **传输**：生产环境使用 HTTPS（Nginx/K8s Ingress 配置 TLS）
- **文件大小**：文本 1MB，上传 50MB

---

## 10. Pandaria 集成

Pandaria（Rust Agent Runtime）通过 `EmeraldMemoryStore` HTTP 适配器与 Emerald 集成。

### 10.1 架构

```
Pandaria Agent Runtime
  │
  ├── MemoryStore trait
  │      └── EmeraldMemoryStore  (HTTP adapter)
  │            ├── remember() → POST /v1/memories
  │            └── recall()   → POST /v1/search
  │
  └── Emerald REST API
         ├── /v1/memories
         ├── /v1/search
         └── /v1/profiles/{id}
```

### 10.2 Entity 映射策略

| Pandaria 字段 | Emerald 字段 | 说明 |
|---|---|---|
| `tenant_id` | `entity_id` | 用户/租户级标识，跨 session 共享记忆 |
| `session_id` | `metadata.session_id` | Session 级追踪，不影响搜索范围 |
| `model` | `metadata.model` | 记录使用的 LLM 模型 |

**设计原则：** `tenant_id` 作为 `entity_id` 允许同一用户在不同 session 之间共享长期记忆。`session_id` 仅用于元数据追踪，不改变记忆归属。

### 10.3 配置示例

```rust
use pandaria::memory::EmeraldMemoryStore;

let memory = EmeraldMemoryStore::new(
    "http://localhost:8000",   // Emerald base URL
    "em_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",  // API Key
);

// 在 Agent 配置中注册
let agent = Agent::builder()
    .memory_store(memory)
    .build();
```

### 10.4 对话格式

Pandaria 输出的 Markdown 格式对话自动识别：

```markdown
**User**: 你好，我想了解 TypeScript 泛型
**Assistant**: TypeScript 泛型允许创建可复用的类型安全组件...
**User**: 和接口有什么区别？
```

Emerald 的 `ConversationChunker` 自动识别 `**User**:` / `**Assistant**:` 格式，将每轮对话分割为独立 chunk 并标注说话人。

### 10.5 超时和错误处理

| 操作 | 超时 | 错误处理 |
|---|---|---|
| `remember()` | 5s | `MemoryError::StoreError` |
| `recall()` | 3s | 返回空列表，不阻塞 Agent |
| `forget_session()` | — | v0.2.0 为 no-op（依赖 Emerald 自动遗忘） |

推荐：在 Pandaria 侧实现指数退避重试（max 3 次），Emerald 短暂不可用时 Agent 继续运行。

---

## 11. MCP Server

Emerald 提供 [MCP (Model Context Protocol)](https://modelcontextprotocol.io) 服务，任何 MCP 客户端可直接调用。

### 11.1 安装

```bash
pip install -e ".[mcp]"  # 安装 fastmcp>=3.0,<4.0
```

### 11.2 启动

```bash
# stdio 模式（Claude Desktop 推荐）
EMERALD_API_KEY=em_xxx python -m emerald.mcp.server --transport stdio

# SSE 模式（HTTP，远程访问）
EMERALD_API_KEY=em_xxx python -m emerald.mcp.server --transport sse --port 8001
```

### 11.3 暴露的工具

| 工具 | 功能 | 参数 |
|---|---|---|
| `emerald_add` | 保存记忆 | `content`, `entity_id`, `content_type`, `metadata` |
| `emerald_search` | 搜索记忆和文档 | `q`, `entity_id`, `search_mode`, `top_k` |
| `emerald_profile` | 获取用户画像 | `entity_id` |

### 11.4 Claude Desktop 配置

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）或相应平台配置：

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

重启 Claude Desktop 后，在对话中直接调用：

> "保存这条信息：用户偏好使用 TypeScript"
> "搜索用户关于部署的记忆"
> "获取用户画像"

### 11.5 Docker Compose

`docker-compose.yml` 已包含 `mcp` 服务：

```bash
docker compose up -d mcp
# SSE 端点：http://localhost:8001
```

### 11.6 环境变量

| 变量 | 必需 | 默认值 | 说明 |
|---|---|---|---|
| `EMERALD_API_KEY` | ✅ | — | Emerald API Key |
| `EMERALD_BASE_URL` | ❌ | `http://localhost:8000` | Emerald REST API 地址 |

---

## 12. 故障处理

| 场景 | 行为 |
|---|---|
| Emerald 不可用 | SDK 抛连接错误，调用方应重试 |
| 管线处理失败 | `pipeline_status` 返回 `failed` + `error_message` |
| 提取依赖缺失 | 抛 `ExtractionError`，不阻塞管线 |
| 速率限制 | HTTP 429，等待 `Retry-After` 后重试 |
| 文件损坏 | 单文件失败不阻塞其他文件同步 |
