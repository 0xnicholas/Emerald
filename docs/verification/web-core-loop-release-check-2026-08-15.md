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
| 连接测试在健康栈上报「API 返回异常状态: ok」（2026-08-27 黑盒走查首报） | 面板判 `status === "healthy"`，而 `/v1/health` 契约值为 `ok`/`degraded`——API 从不返回 healthy | 判定改接受 `ok`（`536369a`）；顺带健康端点版本串 0.3.0 硬编码 → `emerald.__version__`；compose neo4j 探测 cypher-shell → wget :7474（JVM 冷启动间歇超时误判 unhealthy 拦依赖链重启） |
| `GET /v1/pipelines/{id}` 命中即 500 | 路由 `response_model=PipelineStatusResponse`（顶层字段）× 实际返回 `{data,meta}` 信封 → ResponseValidationError；既有测试无该端点功能用例 | `PipelineStatusEnvelope`（沿 keys.py 惯例）+ 回归测试 ×3（`ed4ab9e`） |
| worker/beat 起不来（Exited 2） | compose `-A emerald.pipeline.tasks` 错——celery app 在 `emerald.pipeline.celery:celery_app`；既有死路径 | 改 `-A emerald.pipeline.celery`（`b2adbc8`） |
| 引擎镜像四重构建 | api/worker/beat/mcp 各自 `build:` 同一 Dockerfile | 仅 api 构建 + `image: emerald-api:latest` 复用（`b2adbc8`） |
| Benchmark CI 专红（本地绿） | workflow 共享 Redis 的 `profile:<entity>` 跨测试缓存污染 forget_communities 画像豁免 | fixture/scenario 显式 `ProfileManager(redis_client=False)`（`3199851`） |
| fastembed 下向量写入必败 | engine 三处读私有 `embedder._model`：OpenAI 是字符串侥幸，Fastembed 是 TextEmbedding 对象 → 落库 asyncpg DataError；嵌入缓存键同受 object repr 地址漂移影响 | `provider_model_name()` 只返回 str + 回归 ×5（`59d4ed2`） |

## 3. 环境限制（非缺陷，黑盒走查时需注意）

1. **rag 态语义命中（修正 2026-08-15 下午）**：`embeddings.embedding` 列定长 `vector(1536)`（migration 002），而 fastembed 全系无 1536 维模型，且 `bge_model_path`（sentence-transformers 路径）被 local 工厂错喂 FastembedProvider 模型名参数——**本地语义嵌入在当前 schema 下结构性不可写**（此前「或镜像安装 fastembed」的替代方案不成立，已证伪）。本地回退 Mock（1536 维，确定性非语义）可支撑摄入/搜索/画像全流程与词汇级命中。**S1-rag/hybrid 语义条款走查必须配 OPENAI_API_KEY**（text-embedding-3-small，schema 原生 1536）。→ 本地嵌入锁死 1536 是待立项的引擎议题（动态维度或本地 1536 模型引入，涉及 schema/索引权衡）。
2. **C1 真 LLM / OpenAI 兼容后端（更新 2026-08-27）**：chat edge route 已支持 OpenAI 兼容后端——`OPENAI_BASE_URL` / `OPENAI_MODELS` / `OPENAI_DEFAULT_MODEL` 环境变量（§3.2 预告的「小改动」已落地）。本机当前配置 DeepSeek（根 `.env`：key + `OPENAI_BASE_URL=https://api.deepseek.com/v1` + `OPENAI_MODELS=deepseek-chat,deepseek-reasoner`），C1/C2/P3 真 LLM 路径可走。**注意 chat key 的注入路径与引擎不同**：frontend 容器用 compose 插值（根 `.env` / shell），不是 `.env.docker`（那是引擎侧 env_file）——此前「填 .env.docker」的指引对 chat 环节不生效，已修正 §5。**嵌入不受此覆盖**：DeepSeek 无 embeddings API，`EMBEDDING_PROVIDER=local`（Mock）不变，S1-rag 语义命中与 I4 语义搜仍受 §3.1 约束（需 OpenAI 嵌入 key 或本地 1536 维方案落地）。
3. **数据状态**：2026-08-15 下午已 `down -v` 全新重起（干净卷），四环 Mock 态全绿；走查 rag 语义前需配 key 并再次清卷（Mock 与真嵌入向量空间不同）。

## 4. 引擎门（质量套件）

- `tests/quality/`：62 passed / 5 skipped（skips 全为「Neo4j 不在 bolt:7688」——CI 提供变体，本地环境性）
- CI（push `d30e5c0` 后）：Quality Suites ✅ / Security Scan ✅ / Benchmarks 🔴（2026-08-14 起既有红，B5 时期，先于本次改动；非门项，待独立排查）
- 全量 API 套件回归：`test_pipeline_status_envelope` 3 passed；openapi drift 5 passed（spec 已再生成提交）

## 5. 黑盒走查清单（人工执行，结果回填本节）

环境两档：**A 配 key**（当前已配 DeepSeek：根 `.env` 三变量（chat）+ `.env.docker`（引擎）不变；换 OpenAI 则根 `.env` 改 key 并删 BASE_URL/MODELS 两行 → `down -v` → `up -d` → 迁移+种子 key，全条款可走）；**B 无 key**（根 `.env` 清空 OPENAI_API_KEY → `up -d frontend`，跳过标 🄚 的 LLM 项）。
注：当前 DeepSeek 配置下，C1/C2/P3/C4 按 🄚 走（真 LLM）；S1-rag 语义与 I4 语义搜受 §3.1 约束仍为 Mock 态（词汇级命中可验，改写语义命中不可验）；模型选择器预期为 deepseek-chat / deepseek-reasoner（OPENAI_MODELS 下发）。
浏览器 ≥1280px，登 http://localhost：Server URL **留空**，API Key `em_dev_test_key_001`，Entity ID `dev_user`。

| # | 操作 | 预期 | 结果 |
|---|---|---|---|
| I1 | Dashboard 快速笔记输入「我偏好深色主题」→ Save | toast 成功；「最近保存」**不刷新即现** | |
| I2 | Add Memory 弹窗 Note：「我每周三健身」→ Save → 搜索「健身」 | 保存真提示；命中 | |
| I3 | 弹窗 Link：粘任一 URL → 等预览卡 → Save → 搜标题词 | 命中（元数据记忆） | |
| I4 🄚 | 弹窗 File：选 txt/pdf → Upload | toast 阶段更新 →「已索引 N 条记忆」；搜文件内容词命中 | |
| I5 | DevTools Console：`localStorage.setItem('emerald_api_key','em_invalid');location.reload()` → 保存笔记 | 红色失败 toast 带详情，**无假成功**（验完改回） | |
| S1 🄚 | 搜索页三态：搜「健身」（memory）/搜文件内容词（rag）/同词 | 三态各自命中对应类型；hybrid 两类皆回 | |
| S2 | 空间选择器新建 space → Link 保存到该 space → 搜索选该 space vs 不选 | 选=仅该空间；不选=全池 | |
| S3 | 新笔记保存 → toast 后立即搜 | 可搜往返 | |
| P1 | Dashboard | 静态事实卡 + 统计数字 | |
| P2 | 保存「我是后端工程师主要写 Python」→ 回 Dashboard（≤10s） | 画像静态层新现该事实 | |
| P3 🄚 | Chat 问「我是谁？」「我用什么语言？」 | 回答基于画像/记忆，非套话（降级态下至少携带检索记忆） | |
| C1 🄚 | Chat 问需记忆的问题（如「我每周几健身？」） | 回答引用检索内容，非固定模板 | |
| C2 🄚 | 同上观察 | 打字机流式呈现 | |
| C3 | Chat 随便问（无 key 态） | 气泡「记忆检索模式｜未配置 AI key」badge + 降级文案 | |
| C4 | 模型选择器 | 列表 = 部署配置下发（OPENAI_MODELS，当前 deepseek-chat/reasoner；默认部署为 GPT-4o/Mini）；切换后问答正常 | |
| H1 | 全程 DevTools Network | 请求全为相对路径（/v1/*、/api/chat），无 localhost:8000 | |
| H2 | 页面右下角 | 无 Next.js dev overlay（N 标志）、无热重载 | |
| H3 | Settings 页 | 可见 `docker exec … seed_dev_api_key.py` 文档化命令 | |

全绿 = #52 可关，v0.7.0 web 门放行。🄚 = 需 OPENAI_API_KEY（S1-rag 语义命中另受本地嵌入结构性限制约束——配 key 后走 openai 嵌入即真语义）。
