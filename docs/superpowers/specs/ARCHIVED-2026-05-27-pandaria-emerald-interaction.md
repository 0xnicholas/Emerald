# Pandaria ↔ Emerald 交互逻辑

> **文档目的：** 明确两个独立系统之间的运行时通信流程  
> **阅读对象：** Pandaria 和 Emerald 双方开发者  

---

## 架构关系

```
┌─────────────────────────────────────────────────────────────┐
│  Pandaria (Rust Agent Runtime)                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Agent Loop                                          │   │
│  │  ┌────────────┐    ┌──────────┐    ┌─────────────┐ │   │
│  │  │ on_turn_end│───▶│ remember │───▶│    HTTP     │ │   │
│  │  └────────────┘    └──────────┘    │    POST     │ │   │
│  │                                    │ /v1/memories│ │   │
│  │  ┌────────────┐    ┌──────────┐    └──────┬──────┘ │   │
│  │  │ on_context │◀───│  recall  │◀──────────┘        │   │
│  │  └────────────┘    └──────────┘                   │   │
│  │                                    (Rust, 本地进程)  │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                  │
│           EmeraldMemoryStore (HTTP adapter)                  │
│                           │                                  │
│              reqwest::Client ──HTTP──▶                       │
│                           │                                  │
└───────────────────────────┼─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Emerald (Python Memory Infrastructure)                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  FastAPI Router                                      │   │
│  │  ┌──────────────┐  ┌─────────────┐  ┌────────────┐ │   │
│  │  │ /v1/memories │  │ /v1/search  │  │/v1/profiles│ │   │
│  │  └──────┬───────┘  └──────┬──────┘  └─────┬──────┘ │   │
│  │         │                 │               │        │   │
│  │  ┌──────▼───────┐  ┌──────▼──────┐  ┌────▼─────┐  │   │
│  │  │ MemoryEngine │  │SearchOrchest│  │ProfileMan│  │   │
│  │  │   .add()     │  │   .search() │  │ .profile()│  │   │
│  │  └──────┬───────┘  └──────┬──────┘  └────┬─────┘  │   │
│  │         │                 │              │        │   │
│  │  extract→chunk→embed→index  vector+graph  cache   │   │
│  │         │                 │              │        │   │
│  │  ┌──────▼───────┐  ┌──────▼──────┐  ┌────▼─────┐  │   │
│  │  │  GraphStore  │  │ VectorStore │  │  Redis   │  │   │
│  │  │  (Neo4j)     │  │ (pgvector)  │  │  (cache) │  │   │
│  │  └──────────────┘  └─────────────┘  └──────────┘  │   │
│  │                                    (Python, 可远程)   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**关键：** 两个系统是完全独立的进程，通过 HTTP 通信。Pandaria 不依赖 Emerald 的 Python 代码，Emerald 不依赖 Pandaria 的 Rust 代码。

---

## 时序：一次完整的对话

### Turn 1 — 首轮对话（无历史记忆）

```
用户: 你好，我想了解 TypeScript 泛型
     │
     ▼
Pandaria Agent ──▶ LLM 调用（无记忆注入）
     │
     ▼
Assistant: TypeScript 泛型允许创建可复用的类型安全组件...
     │
     ▼
Pandaria on_turn_end ──▶ EmeraldMemoryStore::remember()
     │
     │  POST /v1/memories
     │  {
     │    "content": "**User**: 你好，我想了解 TypeScript 泛型\n**Assistant**: TypeScript 泛型允许...",
     │    "entity_id": "tenant_acme",          ← tenant_id
     │    "content_type": "conversation",
     │    "metadata": {
     │      "session_id": "sess_001",           ← session 审计
     │      "model": "claude-sonnet-4"          ← 模型记录
     │    }
     │  }
     │
     ▼
Emerald ──▶ 3 chunks 存入图谱 (User/Assistant/User)
```

### Turn 2 — 后续对话（有历史记忆）

```
用户: 和接口有什么区别？
     │
     ▼
Pandaria on_context ──▶ EmeraldMemoryStore::recall("和接口有什么区别？")
     │
     │  POST /v1/search
     │  {
     │    "q": "和接口有什么区别？",
     │    "entity_id": "tenant_acme",          ← 同一 tenant
     │    "search_mode": "hybrid",
     │    "top_k": 5
     │  }
     │
     ▼
Emerald ──▶ 返回相关记忆
     │  ["User: 你好，我想了解 TypeScript 泛型",
     │   "Assistant: TypeScript 泛型允许创建可复用的类型安全组件"]
     │
     ▼
Pandaria 将记忆注入 LLM 系统提示词
     │
     ▼
LLM 调用（带记忆上下文）──▶ Assistant: 主要区别在于泛型是参数化类型...
     │
     ▼
Pandaria on_turn_end ──▶ remember() 保存 Turn 2
```

### Session 2 — 跨 session 记忆召回

```
新 Session: sess_002
     │
     ▼
用户: 上次说的 TypeScript 泛型，能再详细点吗？
     │
     ▼
Pandaria on_context ──▶ recall("TypeScript 泛型")
     │
     │  POST /v1/search
     │  {
     │    "q": "TypeScript 泛型",
     │    "entity_id": "tenant_acme",          ← 同一 tenant_id！
     │    ...
     │  }
     │
     ▼
Emerald ──▶ 返回 Session 1 的记忆
     │  ["User: 你好，我想了解 TypeScript 泛型",
     │   "Assistant: TypeScript 泛型允许创建可复用的类型安全组件",
     │   "User: 和接口有什么区别？",
     │   "Assistant: 主要区别在于泛型是参数化类型..."]
     │
     ▼
LLM 看到完整历史 ──▶ 更连贯的回复
```

**关键点：** `entity_id = tenant_id`（不含 session），所以跨 session 自动共享。

---

## 三个 Hook 点详解

| Hook 点 | 触发时机 | Emerald 调用 | 超时 | 失败行为 |
|---|---|---|---|---|
| `on_turn_end` | 每轮对话结束时 | `remember(content, metadata)` | 5s | 静默丢弃，不阻塞 |
| `on_context` | 构建 LLM 上下文前 | `recall(query)` | 3s | 返回空，不注入记忆 |
| `on_compact_end` | 对话压缩(summary)后 | `remember(summary, metadata)` | 5s | 静默丢弃 |

### on_turn_end 的 content 格式

Pandaria 发送的 `content` 是 Markdown 格式 transcript：

```markdown
**User**: 你好，我想了解 TypeScript 泛型
**Assistant**: TypeScript 泛型允许创建可复用的类型安全组件
**User**: 和接口有什么区别？
**Assistant**: 主要区别在于泛型是参数化类型，而接口是结构契约
```

Emerald 的 `ConversationChunker` 自动识别 `**User**:` / `**Assistant**:`，分割为 4 个独立 chunk，每个 chunk 标注 speaker。

### on_context 的 query 构造

默认使用**用户当前消息**作为 query：

```rust
// Pandaria 侧
let query = &turn.user_message;  // "和接口有什么区别？"
let memories = store.recall(ctx, query).await?;
```

可选增强：使用最近 3 轮对话拼接作为 query，提高召回率。

### on_compact_end 的用途

当对话过长需要压缩时，Pandaria 生成 summary，然后调用 `remember()` 保存：

```markdown
**System**: [Compressed Context] 用户询问了 TypeScript 泛型的概念、
与接口的区别，以及实际使用场景。用户对类型系统有基础了解。
```

这样即使原始对话被压缩丢弃，核心信息仍保留在 Emerald 中。

---

## 数据流图

### remember() 数据流

```
Pandaria
  │
  │  content: Markdown transcript
  │  entity_id: tenant_id
  │  metadata: {session_id, model, ...}
  ▼
Emerald REST API
  │
  ▼
MemoryEngine.add()
  │
  ├── Extract ──▶ 纯文本（conversation 类型直接透传）
  │
  ├── Chunk ──▶ ConversationChunker
  │   │  "**User**: hello" → Chunk {text: "User: hello", speaker: "User"}
  │   │  "**Assistant**: hi" → Chunk {text: "Assistant: hi", speaker: "Assistant"}
  │
  ├── Embed ──▶ MockEmbeddingProvider / OpenAI
  │   │  128-dim 向量（测试）或 1536-dim（生产）
  │
  ├── Index ──▶ GraphStore + VectorStore
  │   │  Graph: Memory node (content, metadata, is_latest=true)
  │   │  Vector: embedding row (same id as graph node)
  │
  └── Profile ──▶ invalidate cache
```

### recall() 数据流

```
Pandaria
  │
  │  query: "TypeScript 泛型"
  │  entity_id: tenant_id
  ▼
Emerald REST API
  │
  ▼
SearchOrchestrator.search()
  │
  ├── Vector Search ──▶ pgvector 相似度匹配
  │   │  SELECT * FROM embeddings WHERE entity_id = 'tenant_acme'
  │   │  ORDER BY cosine_similarity(embedding, query_embedding) DESC
  │   │  LIMIT 5
  │
  ├── Graph Lookup ──▶ Neo4j 获取节点详情
  │   │  MATCH (m:Memory) WHERE m.id IN [...]
  │   │  RETURN m.content, m.metadata, m.is_latest
  │
  ├── Filter ──▶ is_latest=true, not expired
  │
  └── Deduplicate + Rank ──▶ 按 score 排序
       │
       ▼
Pandaria
  │  ["User: 你好，我想了解 TypeScript 泛型",
  │   "Assistant: TypeScript 泛型允许..."]
  ▼
LLM Context Window
```

---

## 错误处理边界

```
┌─────────────────────────────────────────────────────────────┐
│                    Pandaria Agent Runtime                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ remember()  │  │   recall()  │  │    forget_session() │ │
│  │   fails     │  │    fails    │  │       (no-op)       │ │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                     │            │
│         ▼                ▼                     ▼            │
│    丢失一轮记忆      不注入上下文           无影响          │
│    Agent 继续运行    Agent 继续运行        Agent 继续运行   │
│    (可接受)          (可接受)              (可接受)         │
└─────────────────────────────────────────────────────────────┘
```

**核心原则：** 记忆系统是辅助设施，任何故障都不应阻塞 Agent 主流程。

---

## 配置对照

### Pandaria 侧 (`config.toml`)

```toml
[memory]
store = "emerald"  # 或 "in_memory" / "redis"

[memory.emerald]
base_url = "http://localhost:9999"  # 内存模式测试
# base_url = "http://localhost:8000"  # Docker Compose 完整模式
api_key = "em_test"

# 可选：超时配置（默认已足够）
remember_timeout_ms = 5000
recall_timeout_ms = 3000
```

### Emerald 侧 (`.env`)

```bash
# 内存模式不需要配置（test_server.py 内置）
# Docker Compose 模式需要：
EMERALD_API_KEY=em_test
EMERALD_BASE_URL=http://localhost:8000
```

---

## 本地联调步骤

```bash
# Terminal 1: 启动 Emerald（内存模式，30 秒）
cd /Users/nicholasl/Documents/build-whatever/Emerald
python3 scripts/test_server.py

# Terminal 2: 运行 Pandaria E2E 测试
cd /Users/nicholasl/Documents/build-whatever/pandaria
cargo test --package agent-core emerald_memory_store -- --nocapture

# Terminal 3: 手动验证（curl）
curl -s http://localhost:9999/v1/health
curl -s -X POST http://localhost:9999/v1/memories \
  -H "Authorization: Bearer em_test" \
  -H "Content-Type: application/json" \
  -d '{"content":"**User**: hello","entity_id":"test_tenant","content_type":"conversation"}'
curl -s -X POST http://localhost:9999/v1/search \
  -H "Authorization: Bearer em_test" \
  -H "Content-Type: application/json" \
  -d '{"q":"hello","entity_id":"test_tenant","search_mode":"hybrid"}'
```

---

**End of Document**
