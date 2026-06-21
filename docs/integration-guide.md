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

---

## 13. Post-v0.3.0 集成增强（2026-06-02 之后）

> 本节记录 v0.3.0 之后 33 个 commit 中影响集成路径的重大变更。详见 [`docs/roadmap.md`](roadmap.md)。

### 13.1 LLM 事实提取集成（核心变更）

Post-v0.3.0 中，摄入到 Emerald 的内容不再原样存储，而是被 LLM 分解为多条结构化事实。

**对集成方的影响：**

| 之前 | 之后 |
|---|---|
| 发送 1 段对话 → 返回 1 个 memory_id | 发送 1 段对话 → 返回 N 个 memory_id（LLM 提取的多条事实） |
| 记忆的 content == 原始文本 | 记忆的 content == LLM 提取的 1-2 句原子事实 |
| 没有 memory_type / confidence | 每个记忆自动分类 (fact/preference/episodic) 并评分 (0-1) |

**集成代码适配示例：**

```python
# 之前
result = await client.add(content="...", entity_id="user_123")
# result.memory_ids == ["mem_xxx"]
# 单个记忆包含整段原始文本

# 之后
result = await client.add(content="...", entity_id="user_123")
# result.memory_ids 可能是 ["mem_001", "mem_002", "mem_003"]
# 每个记忆是 LLM 提取的原子事实
# 可以查看 result.facts_extracted 等元数据
```

**如果需要 LLM 不介入：** 在调用 `add()` 时显式指定 `memory_type` 和 `confidence`（SDK / REST 都支持），引擎会跳过 LLM 提取。

```python
result = await client.add(
    content="用户偏好 TypeScript",
    entity_id="user_123",
    memory_type="preference",
    confidence=0.95,
    # 跳过 LLM 提取，直接存入
)
```

**降级行为：** 无 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 时，引擎走降级路径——整段文本作为单个 chunk，memory_type 默认 `fact`。

### 13.2 批量添加集成

Post-v0.3.0 新增 `POST /v1/memories/batch` 端点，一次最多 50 条：

```python
# REST
async with httpx.AsyncClient(...) as h:
    resp = await h.post("/v1/memories/batch", json={
        "memories": [
            {"content": "...", "entity_id": "user_a"},
            {"content": "...", "entity_id": "user_a"},
            {"content": "...", "entity_id": "user_b", "memory_type": "preference"},
        ]
    })
```

**SDK 暂未暴露 batch 方法**——临时通过 httpx 调用。详见 [`docs/architecture/api-design.md`](architecture/api-design.md) §11.1。

**适用场景：**
- 预填充：从 CSV/数据库批量导入历史记录
- 多用户隔离：一次提交多个 entity 的内容
- 离线批处理：定期上传积累的内容

### 13.3 元数据过滤集成

Post-v0.3.0 搜索支持 MongoDB 风格 metadata 过滤：

```python
# 仅检索高置信度偏好
result = await client.search(
    q="用户偏好什么",
    entity_id="user_123",
    filters={
        "$and": [
            {"memory_type": "preference"},
            {"confidence": {"$gte": 0.7}},
        ]
    },
)

# 检索最近事实或情节
result = await client.search(
    q="用户最近在做什么",
    entity_id="user_123",
    filters={
        "$or": [
            {"memory_type": "fact"},
            {"memory_type": "episodic"},
        ]
    },
)
```

### 13.4 图谱可视化集成（前端场景）

Post-v0.3.0 新增 `GET /v1/memories/graph`，返回节点+边数据供 D3.js / vis-network 渲染：

```python
# 获取图谱可视化数据
async with httpx.AsyncClient(...) as h:
    resp = await h.get(
        "/v1/memories/graph",
        params={"entity_id": "user_123", "limit": 100},
    )
    graph_data = resp.json()["data"]
    # graph_data["nodes"]: [{"id": "mem_xxx", "label": "...", "memory_type": "fact"}, ...]
    # graph_data["edges"]: [{"source": "mem_yyy", "target": "mem_xxx", "type": "EXTENDS"}, ...]
```

**前端集成示例（D3.js）：**

```javascript
// 使用 d3-force + d3-drag 渲染
const graphData = await fetch(`/v1/memories/graph?entity_id=${userId}&limit=100`)
  .then(r => r.json()).then(d => d.data);

const simulation = d3.forceSimulation(graphData.nodes)
  .force("link", d3.forceLink(graphData.edges).id(d => d.id))
  .force("charge", d3.forceManyBody().strength(-200))
  .force("center", d3.forceCenter(width / 2, height / 2));
```

### 13.5 软删除集成

Post-v0.3.0 新增 `DELETE /v1/memories/{id}` 软删除：

```python
async with httpx.AsyncClient(...) as h:
    resp = await h.delete(f"/v1/memories/{memory_id}")
    # 返回 {"data": {"memory_id": "...", "deleted_at": "...", "is_latest": false}, ...}
```

**软删除语义：** 记忆 `is_latest=False`，不在默认搜索返回，但保留在数据库中可追溯。如需硬删除（GDPR 等），联系运维手动执行。

### 13.6 集成方需要关注的 Post-v0.3.0 兼容性

| 集成类型 | 是否需要调整 | 原因 |
|---|---|---|
| 简单添加+搜索 | ❌ 无需调整 | API 表面不变 |
| 精确记忆 ID 跟踪 | ✅ **需要适配** | 1 段输入可能产生 N 个记忆 |
| 自定义 content_type 处理 | ⚠️ 需验证 | LLM 提取后会忽略某些自定义字段 |
| 实时同步（每分钟级） | ⚠️ 需关注配额 | LLM 提取增加 token 消耗 |
| 预填充大量历史数据 | ✅ 用 batch 端点 | `/memories/batch` 性能更好 |

### 13.7 本地嵌入集成（数据敏感场景）

如果你的场景禁止外部 API 调用，Post-v0.3.0 支持 fastembed 本地嵌入：

```bash
# .env
EMBEDDING_PROVIDER=fastembed
FASTEMBED_MODEL=BAAI/bge-small-en-v1.5
pip install fastembed
```

**注意：** LLM 事实提取（DeepSeek/OpenAI）仍需要外部 API。仅嵌入可本地化。

**完全离线场景：** 暂不支持（事实提取是 Emerald 核心价值）。建议等待 M3+ 路线图中的小型 LLM 集成方案。

### 13.8 MCP 集成增强

Post-v0.3.0 中 MCP Server 保持稳定（3 个工具：`emerald_add`、`emerald_search`、`emerald_profile`）。但工具返回格式有变化：

```json
// emerald_search 工具返回
{
  "results": [
    {
      "id": "mem_xxx",
      "content": "用户在 Stripe 工作",
      "summary": "...",           // 【新增】LLM 生成的摘要
      "score": 0.92,
      "memory_type": "fact",      // 【新增】自动分类
      "source": "memory"          // 可能为 "memory" / "memory_expanded" / "rag"
    }
  ],
  "profile": {...}               // 可选，并行调用
}
```

Claude Desktop 集成无需变更；MCP 客户端会自动适配新字段。

### 13.9 路线图集成影响

| 里程碑 | 对集成方的影响 |
|---|---|
| M2 (v0.5.0) | TypeScript SDK v1 发布，TypeScript/JS 集成成为一等公民 |
| M3 (v0.6.0) | LangChain.js / Vercel AI SDK 集成，框架生态扩展 |
| M4 (v0.7.0) | 多跳推理，搜索结果可能包含 DERIVES_FROM 链 |
| M5 (v0.8.0) | Production-Ready Beta，SLA 文档发布，集成方需关注性能承诺 |
