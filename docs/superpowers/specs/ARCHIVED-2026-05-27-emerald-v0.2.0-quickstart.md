# Emerald v0.2.0 快速启动指南（供 Pandaria 团队）

> **目标读者：** Pandaria 开发者  
> **用途：** 本地启动 Emerald v0.2.0 服务，供 `EmeraldMemoryStore` 连接测试  
> **前提：** Python 3.12+

---

## 方式一：内存模式（最快，30 秒启动）

不需要 Docker、PostgreSQL、Neo4j、Redis。所有数据存储在进程内存中，重启即丢失。

```bash
# 1. 克隆并切换到 v0.2.0 tag
git clone https://github.com/earendil-works/emerald.git
cd emerald
git checkout v0.2.0

# 2. 安装依赖（核心即可，不需要 extraction/mcp）
pip install -e "."

# 3. 启动内存模式服务器
python3 scripts/test_server.py
```

输出：
```
============================================================
Emerald Test Server (in-memory mode)
URL:    http://localhost:9999
APIKey: any string (auth bypassed)
Ctrl+C to stop
============================================================
```

**Pandaria 配置：**
```toml
emerald_base_url = "http://localhost:9999"
emerald_api_key  = "em_test"
```

---

## 方式二：Docker Compose（完整功能）

需要 Docker + Docker Compose。启动 PostgreSQL + Neo4j + Redis + MinIO + Emerald API + Celery Worker + MCP Server。

```bash
git clone https://github.com/earendil-works/emerald.git
cd emerald
git checkout v0.2.0

# 1. 配置环境变量（或直接用默认值）
cp .env.example .env
# 编辑 .env，设置 OPENAI_API_KEY（可选，不设则使用 mock 嵌入）

# 2. 启动全部服务
docker compose up -d

# 3. 运行数据库迁移
docker compose exec api alembic upgrade head

# 4. 验证服务
 curl http://localhost:8000/v1/health
```

**Pandaria 配置：**
```toml
emerald_base_url = "http://localhost:8000"
emerald_api_key  = "em_dev"   # .env 中配置的 API Key
```

---

## 快速验证（curl）

服务启动后，用以下命令验证接口可用：

```bash
# 1. Health Check
curl http://localhost:9999/v1/health

# 2. Remember — 保存对话
curl -s -X POST http://localhost:9999/v1/memories \
  -H "Authorization: Bearer em_test" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "**User**: hello\n**Assistant**: hi there",
    "entity_id": "tenant_test",
    "content_type": "conversation",
    "metadata": {"session_id": "sess_001", "model": "claude"}
  }'

# 3. Recall — 搜索记忆
curl -s -X POST http://localhost:9999/v1/search \
  -H "Authorization: Bearer em_test" \
  -H "Content-Type: application/json" \
  -d '{
    "q": "hello",
    "entity_id": "tenant_test",
    "search_mode": "hybrid",
    "top_k": 5
  }'

# 4. Profile — 获取画像
curl -s http://localhost:9999/v1/profiles/tenant_test \
  -H "Authorization: Bearer em_test"
```

---

## Pandaria E2E 测试

Pandaria 侧运行集成测试前，确保 Emerald 服务已启动，然后：

```bash
cd /path/to/pandaria

# 设置 Emerald 连接参数
export EMERALD_BASE_URL="http://localhost:9999"
export EMERALD_API_KEY="em_test"

# 运行 EmeraldMemoryStore 集成测试
cargo test --package agent-core emerald_memory_store::e2e
```

---

## 版本要求

| 组件 | 最低版本 | 说明 |
|---|---|---|
| Emerald | **v0.2.0** | `entity_id` 任意字符串、`metadata` 透传、conversation chunking |
| Python | 3.12+ | 必需 |
| Pandaria | `feat/v0.2.0-pandaria-integration` 或更高 | `EmeraldMemoryStore` 适配器 |

---

## 故障排查

| 问题 | 原因 | 解决 |
|---|---|---|
| `ModuleNotFoundError: No module named 'emerald'` | PYTHONPATH 未设置 | `cd emerald && pip install -e "."` |
| Neo4j 连接失败 | 数据库未启动 | 用内存模式（方式一），或启动 Docker Compose |
| `Couldn't connect to localhost:9999` | 服务器未启动 | 检查 `python3 scripts/test_server.py` 输出 |
| Pandaria `recall()` 返回空 | entity_id 不匹配 | 确保 `remember()` 和 `recall()` 使用相同 `tenant_id` |
| metadata 丢失 | Emerald 版本 < v0.2.0 | 必须 checkout `v0.2.0` tag |

---

**End of Guide**
