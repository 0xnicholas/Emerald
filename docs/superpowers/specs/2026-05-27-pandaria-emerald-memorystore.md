# Pandaria → Emerald HTTP Adapter Spec

> **Version:** 1.0  
> **Date:** 2026-05-27  
> **Status:** Ready for implementation  
> **Emerald interface version:** v0.2.0 (frozen)  
> **Target Pandaria branch:** `feat/v0.2.0-pandaria-integration`

---

## 1. 目标

为 Pandaria 的 `agent-core` crate 实现一个 `MemoryStore` trait 的 HTTP adapter —— `EmeraldMemoryStore`。它将 Pandaria 的 turn 级记忆操作（remember/recall/forget_session）映射到 Emerald REST API 的对应端点。

**设计约束（不可违反）：**
- Emerald 侧不硬编码任何 Pandaria 特定逻辑。所有集成在 Pandaria 侧完成。
- `entity_id` 是任意字符串，Emerald 不做格式校验。
- `metadata` 完整透传，Emerald 不解析其内容。

---

## 2. Emerald 接口冻结状态（v0.2.0）

以下接口已在 Emerald 侧实现并验证，对 Pandaria 稳定可用。

### 2.1 `POST /v1/memories` — 保存记忆

```json
{
  "content": "string (required)",
  "entity_id": "string (required, 任意格式)",
  "content_type": "string (optional, default: text)",
  "title": "string (optional)",
  "metadata": "object (optional, 任意 JSON)"
}
```

**Pandaria 使用方式：**
- `content`：Markdown 格式对话 transcript（见 §4.1）
- `entity_id`：`ctx.tenant_id`（见 §3 Entity 映射）
- `content_type`：`"conversation"`
- `metadata`：合并后的 dict，包含 `session_id`、`model`、`turn_index` 等

**响应：**
```json
{
  "data": {
    "memory_ids": ["hex_id_1", "hex_id_2"],
    "pipeline_status": "done",
    "extracted_count": 2
  },
  "meta": { "request_id": "...", "took_ms": 42 }
}
```

### 2.2 `POST /v1/search` — 搜索记忆

```json
{
  "q": "string (required)",
  "entity_id": "string (required)",
  "search_mode": "string (optional, default: hybrid)",
  "top_k": "integer (optional, default: 10)",
  "rerank": "boolean (optional, default: false)",
  "rewrite_query": "boolean (optional, default: false)"
}
```

**Pandaria 使用方式：**
- `q`：用户当前消息或压缩后的上下文摘要
- `entity_id`：`ctx.tenant_id`
- `search_mode`：`"hybrid"`
- `top_k`：`5`

**响应：**
```json
{
  "data": {
    "results": [
      {
        "id": "hex_id",
        "content": "记忆文本内容",
        "score": 0.95,
        "source": "memory",
        "memory_type": "fact",
        "is_latest": true
      }
    ],
    "search_mode": "hybrid"
  }
}
```

**Pandaria 只消费 `results[].content`。** 其余字段用于调试/日志。

### 2.3 `GET /v1/profiles/{entity_id}` — 获取用户画像

v0.2.0 中 `EmeraldMemoryStore.recall()` 不调用此接口（使用 `search`）。此接口留给 Pandaria 的 `on_session_start` hook 预加载画像使用。

**响应：**
```json
{
  "data": {
    "entity_id": "...",
    "static": [{"content": "..."}],
    "dynamic": [{"content": "..."}],
    "memory_count": 42
  }
}
```

---

## 3. Entity 映射策略

| Pandaria 字段 | Emerald 字段 | 说明 |
|---|---|---|
| `ctx.tenant_id` | `entity_id` | 用户/租户级标识，跨 session 共享记忆 |
| `ctx.session_id` | `metadata.session_id` | Session 级追踪，不影响搜索范围 |
| `ctx.model` | `metadata.model` | 记录使用的 LLM 模型 |

**决策依据：**
- `entity_id = tenant_id` 允许同一用户在不同 session 之间共享长期记忆
- `session_id` 放入 `metadata` 仅用于审计和调试
- 这是 v0.2.0 的确定方案（选项 A），已记录在案

---

## 4. 对话格式

### 4.1 Pandaria 输出格式

Pandaria 的 turn transcript 使用 Markdown bold speaker 标签：

```markdown
**User**: 你好，我想了解 TypeScript 泛型
**Assistant**: TypeScript 泛型允许你创建可复用的类型安全组件...
**User**: 和接口有什么区别？
**Assistant**: 主要区别在于泛型是参数化类型，而接口是结构契约...
```

### 4.2 Emerald 处理

当 `content_type="conversation"` 时，Emerald 的 `ConversationChunker` 自动识别 `**User**:` / `**Assistant**:` 格式：
- 每轮对话分割为独立 chunk
- `metadata.speaker` 提取为 `"User"` / `"Assistant"`（不含 `**`）
- 多段落内容保持完整

**注意：** 发送时不要额外包裹 JSON 或格式化标记。直接将 Markdown 字符串作为 `content` 字段发送。

---

## 5. Rust 实现

### 5.1 文件结构

```
crates/agent-core/
├── src/
│   └── memory/
│       ├── mod.rs          # 导出 EmeraldMemoryStore
│       ├── store.rs        # MemoryStore trait (已有)
│       ├── types.rs        # MemoryContext, MemoryError (已有)
│       └── emerald.rs      # ★ 新增
```

### 5.2 完整代码

```rust
// crates/agent-core/src/memory/emerald.rs

use async_trait::async_trait;
use reqwest::Client;
use serde_json::Value;

use super::store::{MemoryError, MemoryStore};
use super::types::MemoryContext;

/// HTTP adapter bridging Pandaria's `MemoryStore` trait to Emerald REST API.
///
/// All Pandaria-specific logic lives here. Emerald receives generic HTTP calls
/// with no knowledge of the caller's runtime.
pub struct EmeraldMemoryStore {
    client: Client,
    base_url: String,
    api_key: String,
}

impl EmeraldMemoryStore {
    pub fn new(base_url: impl Into<String>, api_key: impl Into<String>) -> Self {
        Self {
            client: Client::new(),
            base_url: base_url.into().trim_end_matches('/').to_string(),
            api_key: api_key.into(),
        }
    }

    fn entity_id(&self, ctx: &MemoryContext) -> String {
        // Entity mapping: tenant_id = entity, session_id in metadata.
        ctx.tenant_id.clone()
    }
}

#[async_trait]
impl MemoryStore for EmeraldMemoryStore {
    /// Send turn content to Emerald.
    ///
    /// Merges Pandaria session context into metadata so Emerald stores it
    /// verbatim without interpretation.
    async fn remember(
        &self,
        ctx: &MemoryContext,
        content: &str,
        metadata: &Value,
    ) -> Result<(), MemoryError> {
        let entity_id = self.entity_id(ctx);
        let url = format!("{}/v1/memories", self.base_url);

        let mut meta = metadata.clone();
        if let Some(obj) = meta.as_object_mut() {
            obj.insert("session_id".to_string(), serde_json::json!(ctx.session_id));
            obj.insert("model".to_string(), serde_json::json!(ctx.model));
        }

        let body = serde_json::json!({
            "content": content,
            "entity_id": entity_id,
            "content_type": "conversation",
            "metadata": meta,
        });

        let response = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .header("Content-Type", "application/json")
            .json(&body)
            .timeout(std::time::Duration::from_secs(5))
            .send()
            .await
            .map_err(|e| MemoryError::StoreError(format!("HTTP error: {}", e)))?;

        if !response.status().is_success() {
            let status = response.status();
            let text = response.text().await.unwrap_or_default();
            return Err(MemoryError::StoreError(
                format!("Emerald error ({}): {}", status, text)
            ));
        }

        // Optionally parse response to validate memory_ids were created.
        // v0.2.0: fire-and-forget; don't block on response parsing.
        Ok(())
    }

    /// Retrieve relevant memories from Emerald.
    ///
    /// Returns a Vec<String> of memory content texts, ready to be injected
    /// into the LLM context window.
    async fn recall(
        &self,
        ctx: &MemoryContext,
        query: &str,
    ) -> Result<Vec<String>, MemoryError> {
        let entity_id = self.entity_id(ctx);
        let url = format!("{}/v1/search", self.base_url);

        let body = serde_json::json!({
            "q": query,
            "entity_id": entity_id,
            "search_mode": "hybrid",
            "top_k": 5,
        });

        let response = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .header("Content-Type", "application/json")
            .json(&body)
            .timeout(std::time::Duration::from_secs(3))
            .send()
            .await
            .map_err(|e| MemoryError::StoreError(format!("HTTP error: {}", e)))?;

        if !response.status().is_success() {
            let status = response.status();
            let text = response.text().await.unwrap_or_default();
            return Err(MemoryError::StoreError(
                format!("Emerald error ({}): {}", status, text)
            ));
        }

        let data: Value = response
            .json()
            .await
            .map_err(|e| MemoryError::StoreError(format!("JSON parse error: {}", e)))?;

        let results = data
            .get("data")
            .and_then(|d| d.get("results"))
            .and_then(|r| r.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|item| {
                        item.get("content").and_then(|c| c.as_str()).map(String::from)
                    })
                    .collect::<Vec<String>>()
            })
            .unwrap_or_default();

        Ok(results)
    }

    /// v0.2.0: no-op.
    ///
    /// Emerald's auto-forgetting engine handles time-based expiration,
    /// but does NOT react to Pandaria session deletion.
    /// Future: call Emerald's explicit forget API when available.
    async fn forget_session(&self, _ctx: &MemoryContext) -> Result<(), MemoryError> {
        Ok(())
    }
}
```

### 5.3 mod.rs 更新

```rust
// crates/agent-core/src/memory/mod.rs

pub mod emerald;
pub use emerald::EmeraldMemoryStore;
```

---

## 6. 错误处理策略

| 场景 | 行为 | 日志 |
|---|---|---|
| `remember()` HTTP 超时 (5s) | `MemoryError::StoreError`，Pandaria 静默丢弃 | `error!` |
| `remember()` 非 2xx 响应 | `MemoryError::StoreError`，Pandaria 静默丢弃 | `error!` + 响应体 |
| `recall()` HTTP 超时 (3s) | 返回空列表，不阻塞 Agent | `warn!` |
| `recall()` 非 2xx 响应 | 返回空列表，不阻塞 Agent | `warn!` + 响应体 |
| `recall()` JSON 解析失败 | 返回空列表 | `error!` |

**原则：** 记忆系统是辅助设施，不应阻塞 Agent 主流程。`remember()` 失败丢失一轮记忆是可接受的；`recall()` 失败不注入记忆上下文也是可接受的。

---

## 7. Hook 联动（Pandaria 侧配置）

Pandaria 的 `MemoryHookDispatcher` 在三个 hook 点调用 `MemoryStore`：

| Hook 点 | 调用方法 | 超时 | 失败行为 |
|---|---|---|---|
| `on_turn_end` | `remember(content, metadata)` | 5s | 静默丢弃 |
| `on_context` | `recall(query)` | 3s | 返回空，不注入 |
| `on_compact_end` | `remember(summary, metadata)` | 5s | 静默丢弃 |

**`on_context` 的 `query` 构造建议：**
- 默认：用户当前消息文本
- 增强：最近 3 轮对话的拼接摘要
- 避免：空字符串（Emerald 会返回空结果）

---

## 8. 测试要求

### 8.1 Pandaria 侧单元测试

使用 `wiremock` 或 `mockito` 搭建 mock Emerald HTTP server：

```rust
#[tokio::test]
async fn test_remember_posts_correct_body() {
    // Mock server expects POST /v1/memories
    // Verify: entity_id in body, content_type="conversation",
    //         metadata contains session_id and model
}

#[tokio::test]
async fn test_recall_returns_content_list() {
    // Mock server returns search response with 2 results
    // Verify: Vec<String> length == 2, content matches
}

#[tokio::test]
async fn test_recall_empty_results_on_error() {
    // Mock server returns 500
    // Verify: returns empty Vec, does not panic
}
```

### 8.2 Pandaria-Emerald 集成测试

需要 Emerald 服务运行（本地或 Docker）：

```rust
#[tokio::test]
async fn test_e2e_remember_then_recall() {
    let store = EmeraldMemoryStore::new("http://localhost:8000", "em_test_key");
    let ctx = MemoryContext {
        tenant_id: "test_tenant".into(),
        session_id: "sess_001".into(),
        model: "claude-sonnet-4".into(),
    };

    // 1. Remember
    store.remember(&ctx, "**User**: hello\n**Assistant**: hi", &json!({}))
        .await
        .expect("remember should succeed");

    // 2. Recall
    let results = store.recall(&ctx, "hello")
        .await
        .expect("recall should succeed");

    assert!(!results.is_empty(), "should recall the remembered content");
    assert!(results[0].contains("hello"));
}
```

---

## 9. 环境变量

Pandaria 侧需要新增配置项：

```toml
# Pandaria 的 config.toml / 环境变量
EMERALD_BASE_URL = "http://localhost:8000"  # 默认
EMERALD_API_KEY = "em_xxx"                   # 必需
```

---

## 10. 验收清单

### Pandaria 侧（本 spec 的范围）

- [ ] `crates/agent-core/src/memory/emerald.rs` 编译通过
- [ ] `EmeraldMemoryStore` 实现 `MemoryStore` trait
- [ ] `remember()` 成功 POST 到 Emerald `/v1/memories`
- [ ] `recall()` 成功 POST 到 Emerald `/v1/search` 并返回 `Vec<String>`
- [ ] `entity_id` 使用 `tenant_id`（不含 session）
- [ ] `metadata` 包含 `session_id` 和 `model`
- [ ] `content_type` 设置为 `"conversation"`
- [ ] 超时和错误处理符合 §6 要求
- [ ] mock-based 单元测试通过
- [ ] 与真实 Emerald 的 E2E 测试通过（如果 Emerald v0.2.0 已部署）

### Emerald 侧（已冻结，供参考）

- [x] `POST /v1/memories` 接受任意 `entity_id` 字符串
- [x] `metadata` 字段完整透传，不丢失
- [x] `content_type="conversation"` 识别 `**User**:` / `**Assistant**:` 格式
- [x] `POST /v1/search` 返回结构稳定（`results[].content` 保证存在）
- [x] 搜索按 `entity_id` 精确过滤

---

## 11. 变更历史

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.0 | 2026-05-27 | 初始版本。基于 Emerald v0.2.0 接口冻结状态编写。 |

---

**End of Spec**
