# Web 核心循环放行核查记录（#52）

> **定位**：issue #52（v0.7.0 发布门清单）的核查证据。分两部分：**可自动化核查**（本文件记录，2026-08-15）与**浏览器黑盒走查**（标尺全条款，留待人工执行——需浏览器 + 真实 LLM key 场景）。
>
> **环境**：单机 macOS Docker 25.0.3；`docker compose -f docker-compose.yml -f docker-compose.local.yml up -d`（local override 仅挪 postgres 调试端口至 5434——宿主 5433 被共机 Totem 栈占用，栈内流量不受影响）；`.env.docker` 取自 `.env.docker.example`，`EMBEDDING_PROVIDER=local`；未配置 OPENAI_API_KEY（对话环按 C3 降级态验收）。
>
> **姊妹文档**：标尺 `docs/web-core-loop-standard.md`；补全计划 `docs/plans/web-core-loop-completion-v0.7.0.md`；事实清单 `docs/verification/web-core-loop-audit-2026-08-15.md`。

## 1. 实起冒烟（全部流量经 `http://localhost`（:80，nginx）发出）

| 环节 | 命令/证据 | 结果 |
|---|---|---|
| 栈起 | 11 服务全 Up（api/frontend/worker/beat/mcp/nginx/postgres/neo4j/redis/minio/minio-init） | ✅ |
| H3 | `docker exec emerald-api python scripts/seed_dev_api_key.py` → `em_dev_test_key_001`（entity `dev_user`） | ✅ |
| 迁移 | `docker exec emerald-api alembic upgrade head` → 000…009 | ✅ |
| H1 | 下表全部请求仅经 :80，零硬编码主机 | ✅ |
| H2 | 首页 200 text/html；frontend 为 standalone runner 镜像（compose `target: runner`） | ✅ |
| I 环（add） | `POST /v1/memories`（「用户偏好 TypeScript 与函数式编程…」）→ 提取为 fact 落库 | ✅ |
| S 环（memory 态） | `POST /v1/search`（「编程语言偏好」，memory 态）→ 命中上述事实（score 0.057） | ✅ |
| P 环 | `GET /v1/profiles/dev_user` → static 含新事实（importance 0.69），管线后 `profile.refreshed.incremental`（worker 日志） | ✅ P1/P2 |
| I4（upload） | `POST /v1/upload`（text 文件）→ 202 + pipeline_id → worker 日志 `pipeline.index.complete memory_count=1` | ✅ |
| D2（轮询端点） | `GET /v1/pipelines/{id}` → `{data:{status:"done", memory_count:1}}` | ✅（修复后，见 §2） |
| S 环（rag 态） | 见 §3 环境限制 | 🟡 |
| C3（降级） | `POST /api/chat`（经 :80 → nginx → frontend edge route）→ `{"degraded":true,"content":…}` | ✅ |

对外端口面实测：仅 `:80` 公网监听；8000/8001/5434/6380/7474/7687/9002/9003 全部 `127.0.0.1` 绑定；frontend 无发布端口。

## 2. 冒烟暴露并修复的缺陷（本次提交）

| 缺陷 | 根因 | 修复 |
|---|---|---|
| `GET /v1/pipelines/{id}` 命中即 500 | 路由 `response_model=PipelineStatusResponse`（顶层字段）× 实际返回 `{data,meta}` 信封 → ResponseValidationError；既有测试无该端点功能用例 | `PipelineStatusEnvelope`（沿 keys.py 惯例）+ 回归测试 ×3（`ed4ab9e`） |
| worker/beat 起不来（Exited 2） | compose `-A emerald.pipeline.tasks` 错——celery app 在 `emerald.pipeline.celery:celery_app`；既有死路径 | 改 `-A emerald.pipeline.celery`（`b2adbc8`） |
| 引擎镜像四重构建 | api/worker/beat/mcp 各自 `build:` 同一 Dockerfile | 仅 api 构建 + `image: emerald-api:latest` 复用（`b2adbc8`） |

## 3. 环境限制（非缺陷，黑盒走查时需注意）

1. **rag 态语义命中**：dev 镜像未装 fastembed，`EMBEDDING_PROVIDER=local` 回退 `MockEmbeddingProvider`（确定性但非语义）——上传文档的向量已入库（`vector.store` 日志），但 rag 态语义查询无法真实命中。黑盒走查 S1-rag 时需：宿主 `.env.docker` 配 `OPENAI_API_KEY`（openai 嵌入），或镜像安装 fastembed。**S1-rag/hybrid 态在浏览器走查前必须重配嵌入后复验**。
2. **C1 真 LLM**：本机未配 OPENAI_API_KEY，对话环按 C3 降级态验收（已验）；C1/C2/P3 的真 LLM 路径需配 key 后在浏览器走查。
3. **数据残留**：volumes 含 2026-08-13 旧实体数据（Q3 Pilot Plan 等）与重复事实——B6 整合为日级调度，不阻断走查；如需干净环境 `docker compose down -v` 重起。

## 4. 引擎门（质量套件）

- `tests/quality/`：62 passed / 5 skipped（skips 全为「Neo4j 不在 bolt:7688」——CI 提供变体，本地环境性）
- CI（push `d30e5c0` 后）：Quality Suites ✅ / Security Scan ✅ / Benchmarks 🔴（2026-08-14 起既有红，B5 时期，先于本次改动；非门项，待独立排查）
- 全量 API 套件回归：`test_pipeline_status_envelope` 3 passed；openapi drift 5 passed（spec 已再生成提交）

## 5. 待办（黑盒走查清单 → 标尺条款映射）

浏览器（≥1280px）+ 重配嵌入（§3.1）后逐条走查：I1-I5 / S1-S3 / P1-P3 / C1-C4（配 key 与不配 key 两轮）/ H1-H3。全绿 = #52 可关，v0.7.0 web 门放行。
