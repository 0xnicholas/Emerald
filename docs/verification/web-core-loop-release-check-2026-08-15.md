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
| **S1：rag 态/hybrid 的 RAG 半边结构性为空（2026-08-27 走查第二报）** | `_search_rag` 查询 `require_document_id=True` 的向量块，但全代码库三处 `vector.store` 调用（engine 同步路径 / pipeline `index_task` / reconciliation）均不传 `document_id`——上传文档只提取为记忆，RAG 块无写入方（自 45d5de3 起从未接通，非回归）。连带 web 搜索 rag tab 永远空 | ✅ 已修并复验（2026-08-29，见 §5）：`45f7565` `VectorStore.store_document_chunks` 幂等写入基座 + `f41abfe` `rag_index_task`（embed→rag_index→index 链位，确定性 chunk_id `{doc}:rag:{i}`）；复验 rag 态命中 + hybrid 两类皆回 |
| **B：`/v1/files` 永远空列表（2026-08-27 走查发现）** | upload 创建 `Document(status="queued")`，管线完成后只更新 pipelines 表状态，`documents.status` 无任何写入方 → 默认 `status_filter=done` 永远过滤为空 | ✅ 已修并复验（2026-08-29）：`f41abfe` postprocess 经 `_pipeline_document_id` 反查并 `_mark_document_done`；复验 status=done + chunk_count=RAG 块数（`_run_index` 返回 dict 透传 `rag_chunk_count`，否则被丢弃——本次复验补修，见 CHANGELOG） |
| **S2：空间过滤泄漏（2026-08-27 走查第三报）** | 种子结果经 `_passes_filters` 过滤，但 `_expand_relationships(memory_results, entity_id, top_k)` 与 `_expand_multihop` 不接收 filters——图扩展邻居绕过 `container_tag` 过滤 | ✅ 已修并复验（2026-08-29，含对照实验）：`2d60a9e` filters 穿透两个扩展路径；复验植入跨空间 EXTENDS/DERIVES_FROM 边（图谱直查确认），无过滤时跨空间邻居浮现（证明扩展候选存在）、选空间后 0 泄漏（depth=0/1/2 三档均验） |
| 连接测试在健康栈上报「API 返回异常状态: ok」（2026-08-27 黑盒走查首报） | 面板判 `status === "healthy"`，而 `/v1/health` 契约值为 `ok`/`degraded`——API 从不返回 healthy | 判定改接受 `ok`（`536369a`）；顺带健康端点版本串 0.3.0 硬编码 → `emerald.__version__`；compose neo4j 探测 cypher-shell → wget :7474（JVM 冷启动间歇超时误判 unhealthy 拦依赖链重启） |
| `GET /v1/pipelines/{id}` 命中即 500 | 路由 `response_model=PipelineStatusResponse`（顶层字段）× 实际返回 `{data,meta}` 信封 → ResponseValidationError；既有测试无该端点功能用例 | `PipelineStatusEnvelope`（沿 keys.py 惯例）+ 回归测试 ×3（`ed4ab9e`） |
| worker/beat 起不来（Exited 2） | compose `-A emerald.pipeline.tasks` 错——celery app 在 `emerald.pipeline.celery:celery_app`；既有死路径 | 改 `-A emerald.pipeline.celery`（`b2adbc8`） |
| 引擎镜像四重构建 | api/worker/beat/mcp 各自 `build:` 同一 Dockerfile | 仅 api 构建 + `image: emerald-api:latest` 复用（`b2adbc8`） |
| Benchmark CI 专红（本地绿） | workflow 共享 Redis 的 `profile:<entity>` 跨测试缓存污染 forget_communities 画像豁免 | fixture/scenario 显式 `ProfileManager(redis_client=False)`（`3199851`） |
| fastembed 下向量写入必败 | engine 三处读私有 `embedder._model`：OpenAI 是字符串侥幸，Fastembed 是 TextEmbedding 对象 → 落库 asyncpg DataError；嵌入缓存键同受 object repr 地址漂移影响 | `provider_model_name()` 只返回 str + 回归 ×5（`59d4ed2`） |

## 3. 环境限制（非缺陷，黑盒走查时需注意）

1. **rag 态语义命中（修正 2026-08-15 下午；再修正 2026-08-27）**：`embeddings.embedding` 列定长 `vector(1536)`（migration 002），而 fastembed 全系无 1536 维模型，且 `bge_model_path`（sentence-transformers 路径）被 local 工厂错喂 FastembedProvider 模型名参数——**本地语义嵌入在当前 schema 下结构性不可写**（此前「或镜像安装 fastembed」的替代方案不成立，已证伪）。本地回退 Mock（1536 维，确定性非语义）可支撑摄入/搜索/画像全流程与词汇级命中。~~S1-rag/hybrid 语义条款走查必须配 OPENAI_API_KEY~~（**2026-08-27 证伪**：配 key 也不行——rag 态无 document_id 块写入方，属 §2 缺陷而非嵌入环境限制，见缺陷表首条）。本地嵌入锁死 1536 是待立项的引擎议题（动态维度或本地 1536 模型引入，涉及 schema/索引权衡）。
2. **C1 真 LLM / OpenAI 兼容后端（更新 2026-08-27）**：chat edge route 已支持 OpenAI 兼容后端——`OPENAI_BASE_URL` / `OPENAI_MODELS` / `OPENAI_DEFAULT_MODEL` 环境变量（§3.2 预告的「小改动」已落地）。本机当前配置 DeepSeek（根 `.env`：key + `OPENAI_BASE_URL=https://api.deepseek.com/v1` + `OPENAI_MODELS=deepseek-chat,deepseek-reasoner`），C1/C2/P3 真 LLM 路径可走。**注意 chat key 的注入路径与引擎不同**：frontend 容器用 compose 插值（根 `.env` / shell），不是 `.env.docker`（那是引擎侧 env_file）——此前「填 .env.docker」的指引对 chat 环节不生效，已修正 §5。**嵌入不受此覆盖**：DeepSeek 无 embeddings API，`EMBEDDING_PROVIDER=local`（Mock）不变，S1-rag 语义命中与 I4 语义搜仍受 §3.1 约束（需 OpenAI 嵌入 key 或本地 1536 维方案落地）。
3. **数据状态**：2026-08-15 下午已 `down -v` 全新重起（干净卷），四环 Mock 态全绿；走查 rag 语义前需配 key 并再次清卷（Mock 与真嵌入向量空间不同）。

## 4. 引擎门（质量套件）

- `tests/quality/`：62 passed / 5 skipped（skips 全为「Neo4j 不在 bolt:7688」——CI 提供变体，本地环境性）
- CI（push `d30e5c0` 后）：Quality Suites ✅ / Security Scan ✅ / Benchmarks 🔴（2026-08-14 起既有红，B5 时期，先于本次改动；非门项，待独立排查）
- 全量 API 套件回归：`test_pipeline_status_envelope` 3 passed；openapi drift 5 passed（spec 已再生成提交）

## 5. 黑盒走查清单（人工执行，结果回填本节）

> **2026-08-27 执行记录**：由 agent 经 HTTP/构建产物/容器内检查代执行（A 档 DeepSeek 环境）；纯视觉项（I1/C3/C4 外观）标注「机制已验，视觉待抽查」。栈已运行、key 已种子、全流量经 :80。

环境两档：**A 配 key**（当前已配 DeepSeek：根 `.env` 三变量（chat）+ `.env.docker`（引擎）不变；换 OpenAI 则根 `.env` 改 key 并删 BASE_URL/MODELS 两行 → `down -v` → `up -d` → 迁移+种子 key，全条款可走）；**B 无 key**（根 `.env` 清空 OPENAI_API_KEY → `up -d frontend`，跳过标 🄚 的 LLM 项）。
注：当前 DeepSeek 配置下，C1/C2/P3/C4 按 🄚 走（真 LLM）；S1-rag 语义与 I4 语义搜受 §3.1 约束仍为 Mock 态（词汇级命中可验，改写语义命中不可验）；模型选择器预期为 deepseek-chat / deepseek-reasoner（OPENAI_MODELS 下发）。
浏览器 ≥1280px，登 http://localhost：Server URL **留空**，API Key `em_dev_test_key_001`，Entity ID `dev_user`。

| # | 操作 | 预期 | 结果 |
|---|---|---|---|
| I1 | Dashboard 快速笔记输入「我偏好深色主题」→ Save | toast 成功；「最近保存」**不刷新即现** | 🟡 机制已验：POST /v1/memories 落库 + `use-memory-mutations` 失效 `search` 前缀（修复 379 行）；toast/不刷新即现为视觉项待抽查 |
| I2 | Add Memory 弹窗 Note：「我每周三健身」→ Save → 搜索「健身」 | 保存真提示；命中 | ✅ 摄入 done（重复内容 dedupe 幂等返回 duplicate）；搜「健身」命中（pos13/20，Mock 嵌入负分特征） |
| I3 | 弹窗 Link：粘任一 URL → 等预览卡 → Save → 搜标题词 | 命中（元数据记忆） | ✅ UI 同构三行内容（title\ndesc\nurl）落库 extracted_count=1；搜「Emerald 项目主页」命中（pos9/20） |
| I4 🄚 | 弹窗 File：选 txt/pdf → Upload | toast 阶段更新→「已索引 N 条记忆」；搜文件内容词命中 | ✅ txt 上传 202→轮询 done memory_count=1（~3s）→搜「锆石星轨」命中（词汇级，Mock 约束） |
| I5 | DevTools Console：`localStorage.setItem('emerald_api_key','em_invalid');location.reload()` → 保存笔记 | 红色失败 toast 带详情，**无假成功**（验完改回） | ✅ API 返 401 `{error_code:AUTH_INVALID_KEY, message, request_id}` 结构化错误；前端 toast.error(description) 消费路径在码（视觉待抽查） |
| S1 🄚 | 搜索页三态：搜「健身」（memory）/搜文件内容词（rag）/同词 | 三态各自命中对应类型；hybrid 两类皆回 | ✅ **复验过（2026-08-29）**：上传 txt 后 rag 态命中（source=rag，chunk `{doc}:rag:0`）；补记忆侧内容后 hybrid 同词两类皆回（rag + memory）；顺带 `/v1/files` 返回 status=done（缺陷 B 修复复验）。语义命中仍受 §3.1 约束（Mock 词汇级，预期内） |
| S2 | 空间选择器新建 space → Link 保存到该 space → 搜索选该 space vs 不选 | 选=仅该空间；不选=全池 | ✅ **复验过（2026-08-29）**：植入跨空间 EXTENDS/DERIVES_FROM 边（图谱直查确认存在，泄漏前提成立）；无过滤搜「力量训练」跨空间邻居浮现（对照证明扩展可见）；选「复验空间」depth=0/1/2 三档均 0 泄漏；不选=全池 ✅。`/v1/spaces` 创建/列表正常（1f527cc 修复复验） |
| S3 | 新笔记保存 → toast 后立即搜 | 可搜往返 | ✅ 保存（同步 done）→立即搜同内容命中（I2/I3/紫水晶连续验证） |
| P1 | Dashboard | 静态事实卡 + 统计数字 | ✅ GET /v1/profiles/dev_user：static 10 条 + dynamic + memory_count 17 |
| P2 | 保存「我是后端工程师主要写 Python」→ 回 Dashboard（≤10s） | 画像静态层新现该事实 | ✅ 同步管线 done 后 ≤5s 静态层新现「我是后端工程师，主要写 Python」（importance 0.69） |
| P3 🄚 | Chat 问「我是谁？」「我用什么语言？」 | 回答基于画像/记忆，非套话（降级态下至少携带检索记忆） | ✅ 画像 top10 注入后回答「主要用 Python 写代码的后端工程师」——基于画像非套话；未注入时诚实回答不知道（符合预期，注入由前端负责） |
| C1 🄚 | Chat 问需记忆的问题（如「我每周几健身？」） | 回答引用检索内容，非固定模板 | ✅ 记忆注入后回答「你每周三去健身」——引用检索内容 |
| C2 🄚 | 同上观察 | 打字机流式呈现 | ✅ SSE `chat.completion.chunk` 逐 token 下发（data: 行流，首 chunk role/delta 空串、后继逐段）；视觉打字机待抽查 |
| C3 | Chat 随便问（无 key 态） | 气泡「记忆检索模式｜未配置 AI key」badge + 降级文案 | ✅ 机制闭环：route `!apiKey → {degraded:true, content:检索记忆}` + chat-interface:239 消费/:467 badge 渲染；2026-08-15 冒烟实测 ✅（本档配 DeepSeek 无法实切 B 档，视觉待抽查） |
| C4 | 模型选择器 | 列表 = 部署配置下发（OPENAI_MODELS，当前 deepseek-chat/reasoner；默认部署为 GPT-4o/Mini）；切换后问答正常 | ✅ GET /api/chat 下发 `[deepseek-chat, deepseek-reasoner]` default=deepseek-chat；切 reasoner 问答正常（「1+1」→「2」）；选择器视觉待抽查 |
| H1 | 全程 DevTools Network | 请求全为相对路径（/v1/*、/api/chat），无 localhost:8000 | ✅ 全部走查流量经 :80 相对路径；构建产物 grep 仅命中 Server URL 输入框 placeholder（非请求 URL） |
| H2 | 页面右下角 | 无 Next.js dev overlay（N 标志）、无热重载 | ✅ standalone runner 生产构建（hashed chunks `/_next/static/...`，无 dev 标志；§1 实起证据） |
| H3 | Settings 页 | 可见 `docker exec … seed_dev_api_key.py` 文档化命令 | ✅ settings 页 bundle 内含完整命令文本（客户端渲染，SSR HTML 无——非缺陷） |

**门判定（2026-08-29 复验后）**：19 条中 19 过（含 3 条机制过/视觉待抽查）——S1/S2 阻断缺陷（A/B/C）均已修复并经 HTTP 层复验（含对照实验，见 §2/§5）。复验时新发现并补修一处：`_run_index` 返回 dict 丢弃上游 `rag_chunk_count` → `/v1/files` chunk_count 恒 0（透传修复，回归 13+64 项绿）。

全绿 = #52 可关，v0.7.0 web 门放行。🄚 = 需 OPENAI_API_KEY（S1-rag 语义命中另受本地嵌入结构性限制约束——配 key 后走 openai 嵌入即真语义；rag 态供给已接通，2026-08-29 复验）。
