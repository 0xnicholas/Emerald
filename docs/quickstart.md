# Emerald 5 分钟快速入门

> **目标：** 在 5 分钟内从 clone 仓库到运行第一个 memory-powered 应用。
>
> **前置：** Docker、Python 3.12+、curl。
>
> **学完你将：** 启动 Emerald 全栈、添加第一个记忆、触发时序更新、读取画像。

---

## 1. 启动全栈（2 分钟）

```bash
# 1. 克隆并进入仓库
git clone https://github.com/your-org/Emerald.git
cd Emerald

# 2. 准备环境变量
cp .env.example .env
# 默认配置已可用。生产部署请修改 POSTGRES_PASSWORD、NEO4J_AUTH 等。

# 3. 启动全栈（API + Worker + Beat + Postgres + Neo4j + Redis + MinIO + MCP）
docker compose up -d
# 等待 ~30 秒，所有服务就绪
docker compose ps
# 期望：8 个服务全部状态 healthy
```

## 2. 健康检查 + API Key（30 秒）

```bash
# 检查 API 服务
curl http://localhost:8000/v1/health
# 期望：{"status":"healthy","version":"0.3.0",...}

# 生成开发用 API Key
python scripts/seed_dev_api_key.py
# 期望输出：em_xxxxxxxx  (复制备用)
```

将 API key 存为环境变量：

```bash
export EMERALD_API_KEY="em_xxxxxxxx"
export EMERALD_BASE_URL="http://localhost:8000"
```

## 3. 第一个记忆（1 分钟）

### 3.1 纯文本记忆（cURL）

```bash
curl -X POST http://localhost:8000/v1/memories \
  -H "Authorization: Bearer $EMERALD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Alex 在 Stripe 担任产品经理，负责支付基础设施。",
    "entity_id": "user_alex"
  }'
```

**期望响应：**

```json
{
  "memory_ids": ["mem_abc123"],
  "pipeline_status": "completed",
  "memory_count": 1
}
```

如果设置了 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`，系统会**自动从这条文本提取多条结构化事实**：

```bash
# 用更长的对话测试 LLM 事实提取
curl -X POST http://localhost:8000/v1/memories \
  -H "Authorization: Bearer $EMERALD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "刚和 Alex 聊了下，他说他在 Stripe 做 PM，要领导一个 5 人支付团队。最近搬到西雅图了。",
    "entity_id": "user_alex"
  }'
```

**提取的多条事实：**
- Alex 在 Stripe 做 PM（fact, confidence=0.9）
- Alex 领导 5 人支付团队（fact, EXTENDS 上一条）
- Alex 最近搬到西雅图（fact, confidence=0.85）

### 3.2 Python SDK（推荐生产使用）

```python
# pip install emerald-sdk  # 或 git+https://github.com/your-org/Emerald.git#subdirectory=emerald/sdk
from emerald.sdk import EmeraldClient

client = EmeraldClient()

# 添加记忆
result = await client.add(
    content="Alex 偏好用 TypeScript 写后端",
    entity_id="user_alex"
)
print(result.memory_ids)

# 关闭客户端
await client.close()
```

## 4. 触发时序更新（30 秒）

第一次：Alex 在 Google
第二次：Alex 跳槽到 Stripe
查询「Alex 在哪工作？」应该返回 Stripe，不是 Google

```bash
# 第 1 天
curl -X POST http://localhost:8000/v1/memories \
  -H "Authorization: Bearer $EMERALD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"content":"Alex 在 Google 担任高级工程师","entity_id":"user_alex"}'

# 第 30 天（同一 entity_id）
curl -X POST http://localhost:8000/v1/memories \
  -H "Authorization: Bearer $EMERALD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"content":"Alex 刚加入 Stripe，担任产品经理","entity_id":"user_alex"}'

# 查询（应返回 Stripe，不是 Google）
curl -X POST http://localhost:8000/v1/search \
  -H "Authorization: Bearer $EMERALD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q":"Alex 在哪里工作","entity_id":"user_alex","search_mode":"memory"}'
```

**期望行为：**
- 第一条记忆 `is_latest=False`（被取代）
- 第二条记忆 `is_latest=True`
- 第二条记忆创建 UPDATES 关系指向第一条
- 搜索「Alex 在哪里工作」返回第二条（Stripe），不返回第一条（Google）

## 5. 读取画像（30 秒）

```bash
curl http://localhost:8000/v1/profiles/user_alex \
  -H "Authorization: Bearer $EMERALD_API_KEY"
```

**期望响应：**

```json
{
  "entity_id": "user_alex",
  "profile": {
    "static": [
      "Alex 在 Stripe 担任产品经理",
      "Alex 领导 5 人支付团队",
      "Alex 住在西雅图",
      "Alex 偏好 TypeScript"
    ],
    "dynamic": [
      "Alex 最近搬到西雅图"
    ]
  },
  "computed_at": "2026-06-21T..."
}
```

**首次调用 ~500ms（冷启动），后续 ~50ms（Redis 缓存）。**

## 6. Python SDK 端到端示例

复制这个完整脚本到 `test_emerald.py`：

```python
"""Emerald 5-minute smoke test."""
import asyncio
from emerald.sdk import EmeraldClient


async def main():
    client = EmeraldClient()

    entity = "demo_user"

    # 1. 添加多个记忆
    print("→ 添加 3 条记忆...")
    await client.add(
        content="Alice 是 ACME 公司的 CTO，专注于分布式系统。",
        entity_id=entity,
    )
    await client.add(
        content="Alice 偏好用 Go 写后端服务，喜欢简洁的代码风格。",
        entity_id=entity,
    )
    await client.add(
        content="Alice 最近在评估 Kafka vs Pulsar 做消息队列。",
        entity_id=entity,
    )

    # 2. 触发时序更新
    print("→ 触发时序更新（CTO → CEO）...")
    await client.add(
        content="Alice 刚升任 ACME 公司 CEO。",
        entity_id=entity,
    )

    # 3. 搜索
    print("→ 搜索 'Alice 的职位'...")
    result = await client.search(
        q="Alice 的职位",
        entity_id=entity,
        search_mode="memory",
        top_k=3,
    )
    for r in result.results:
        print(f"  [{r.score:.2f}] {r.content}")

    # 4. 读取画像
    print("→ 读取画像...")
    profile = await client.profile(entity_id=entity)
    print(f"  静态事实 ({len(profile.profile.static)} 条):")
    for fact in profile.profile.static[:5]:
        print(f"    • {fact}")
    print(f"  动态事实 ({len(profile.profile.dynamic)} 条):")
    for fact in profile.profile.dynamic[:3]:
        print(f"    • {fact}")

    await client.close()
    print("\n✓ 完成！")


if __name__ == "__main__":
    asyncio.run(main())
```

运行：

```bash
python test_emerald.py
```

**期望输出（近似）：**

```
→ 添加 3 条记忆...
→ 触发时序更新（CTO → CEO）...
→ 搜索 'Alice 的职位'...
  [0.92] Alice 刚升任 ACME 公司 CEO。
  [0.45] Alice 是 ACME 公司的 CTO，专注于分布式系统。  # 历史记忆（is_latest=False）
→ 读取画像...
  静态事实 (4 条):
    • Alice 是 ACME 公司的 CEO
    • Alice 专注于分布式系统
    • Alice 偏好用 Go 写后端服务
    • Alice 喜欢简洁的代码风格
  动态事实 (1 条):
    • Alice 最近在评估 Kafka vs Pulsar 做消息队列

✓ 完成！
```

---

## 7. 下一步

| 目标 | 文档 |
|---|---|
| 理解记忆 vs RAG、三种记忆类型、三种关系 | [`concepts.md`](concepts.md) |
| 系统架构全景 | [`architecture/overview.md`](architecture/overview.md) |
| 完整 REST API | [`api/rest-guide.md`](api/rest-guide.md) |
| Python SDK 完整参考 | [`api/sdk-guide.md`](api/sdk-guide.md) |
| 部署到生产（K8s、灾备） | [`architecture/deployment.md`](architecture/deployment.md) |
| 与 Supermemory 能力对比 | [`comparison-supermemory.md`](comparison-supermemory.md) |
| 项目路线图 | [`roadmap.md`](roadmap.md) |

## 8. 常见问题

### Q1: 启动后 API 报 500 错误？

检查服务依赖：

```bash
docker compose logs api | grep -i error
docker compose logs postgres | tail -20
docker compose logs neo4j | tail -20
```

最常见原因：Postgres/Neo4j 还没完全启动。等待 30 秒后重试。

### Q2: LLM 事实提取没生效？

检查 `.env`：

```bash
grep DEEPSEEK_API_KEY .env
# 或
grep OPENAI_API_KEY .env
```

必须设置其中一个。如果都没设置，系统走降级路径——整段文本作为一个 chunk，记忆类型默认 `fact`。

### Q3: 搜索结果不符合预期？

```bash
# 1. 检查记忆是否被遗忘（is_latest=False）
curl http://localhost:8000/v1/memories/mem_xxx \
  -H "Authorization: Bearer $EMERALD_API_KEY"

# 2. 尝试不同 search_mode
curl -X POST http://localhost:8000/v1/search -d '{"q":"...","entity_id":"...","search_mode":"memory"}' ...
curl -X POST http://localhost:8000/v1/search -d '{"q":"...","entity_id":"...","search_mode":"rag"}' ...
curl -X POST http://localhost:8000/v1/search -d '{"q":"...","entity_id":"...","search_mode":"hybrid"}' ...

# 3. 启用 rerank 提升精度
curl -X POST http://localhost:8000/v1/search -d '{"q":"...","entity_id":"...","rerank":true}' ...
```

### Q4: 如何重置所有数据？

```bash
docker compose down -v  # ⚠️ 删除所有 volume（包括 Postgres/Neo4j 数据）
docker compose up -d
```

### Q5: 怎么连接 MCP 客户端（如 Claude Desktop）？

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

详见 [README.md MCP Server 部分](../README.md#mcp-server)。
