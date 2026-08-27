# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] — M3（v0.7.0 目标）

### Fixed

- **搜索 filters 不约束图扩展（#52 走查缺陷 C·S2）**：`_expand_relationships` / `_expand_multihop` 不接收 filters——空间过滤种子正确但扩展邻居泄漏跨空间记忆（实测选「走查空间」返回 3 条中 2 条 tag=default/None 混入，S2「选=仅该空间」被突破）。filters 现穿透两个扩展路径，扩展邻居与种子同过 `_passes_filters`；回归测试 ×2（关系扩展 EXTENDS / 多跳共享提及桥）
- **rag 态结构性无供给（#52 走查缺陷 A·S1）**：`_search_rag` 只查带 document_id 的向量块，但全库三处 `vector.store` 调用均不传 document_id——上传只提取为记忆，hybrid 的 RAG 半边自 45d5de3 从未接通（非回归）。新增 `rag_index_task`（链位 embed→rag_index→index）：原始文本经非 LLM `TextChunker` 分块 + 嵌入 + `VectorStore.store_document_chunks`（按 document_id 幂等替换，确定性 chunk_id `{doc}:rag:{i}`，RAG 态可见 / memory 态不可见）写入；无 document_id 的管线（sources 事件）自动跳过；hybrid 自此两类皆可回（Mock 嵌入下 RAG 为词汇级命中，语义命中另受嵌入环境约束）
- **documents 状态机断裂 → `/v1/files` 永远空（#52 走查缺陷 B）**：upload 创建 `Document(status=queued)`，管线完成后只更新 pipeline_jobs，documents.status 无任何写入方（库内实测全停 queued）。postprocess 收尾时经 `_pipeline_document_id` 反查 document_id 并 `_mark_document_done`（status='done' + chunk_count=RAG 块数）；失败仅告警不阻断管线收尾
- **`/v1/spaces` 全系 500（#52 走查 S2）**：Neo4j 后端返回 `neo4j.time.DateTime`，`SpaceResponse`（Pydantic v2）拒绝非原生 datetime → 创建/列表/更新全必 500。`GraphStore._native_dt` 辅助（沿 search.py `to_native` 惯例）统一四个构 dict 位点；回归测试补 neo4j DateTime 真对象过 schema（既有 spaces 测试全内存态，此类无法捕获）
- **连接面板误判健康栈为异常（#52 黑盒走查首报）**：`/v1/health` 契约 status=`ok`（全探测通过）/`degraded`（任一失败），但 web 连接面板硬判 `=== "healthy"`（API 从不返回的值）——一切健康时也报「API 返回异常状态: ok」。改为接受契约值 `ok`（兼容保留 healthy）；顺带修健康端点硬编码版本串 `0.3.0` → `emerald.__version__` 单一事实源（同步 0.5.0 → 0.6.0 对齐 pyproject）
- compose neo4j 健康检查改 HTTP 探测（wget :7474）：cypher-shell CLI 间歇性超 10s 超时（JVM 冷启动）误判 unhealthy，会拦住依赖链容器重启（本次 `up -d frontend` 实踩）
- `GET /v1/pipelines/{id}` 命中即 500：response_model 顶层字段 × 实际 {data,meta} 信封错配，新增 PipelineStatusEnvelope + 回归测试 ×3（issue #52 冒烟发现；D2 轮询依赖端点）
- compose worker/beat 起不来：`-A emerald.pipeline.tasks` 错指（celery app 在 `emerald.pipeline.celery`）既有死路径；同批：引擎镜像四重构建去重（仅 api 构建，worker/beat/mcp 复用）、redis 归一 8.0-alpine
- Benchmark CI 专红（2026-08-14 起）：单测 forget_communities 被 workflow 共享 Redis 的 `profile:<entity>` 跨测试缓存污染（本地无 Redis 故绿）；engine fixture 与 communities scenario 显式注入 `ProfileManager(redis_client=False)` 恢复密闭性

### Added

- **chat OpenAI 兼容后端支持（#52 走查 §3.2 预告项落地）**：web chat edge route 新增 `OPENAI_BASE_URL` / `OPENAI_MODELS` / `OPENAI_DEFAULT_MODEL` 环境变量（默认不设 = OpenAI 官方行为不变）；模型列表经 `GET /api/chat` 运行时下发（C4 选择器不再烘死在内建列表，standalone 生产构建兼容）；compose frontend 服务补两个插值变量透传——同时修正 chat key 注入路径事实：frontend 走 compose 插值（宿主根 `.env`/shell）而非 `.env.docker`（引擎侧 env_file）。以 DeepSeek 验证：deepseek-chat 流式透传、记忆/画像注入接龙、C3 降级态回归均绿

- **Web 核心循环补全（issue #53，计划 `docs/plans/web-core-loop-completion-v0.7.0.md`）**——apps/web 三批补全，满足 `docs/web-core-loop-standard.md` 发布门：
  - **H 基建**：全服务端口改绑 127.0.0.1，仅 nginx :80 对外（H1）；baseUrl 同源默认（空=相对路径，Server URL 留空合法）；compose 切 standalone runner 生产构建 + `docker-compose.dev.yml` 显式 dev override（H2）；修复 Dockerfile deps 阶段 `--only=production` 致 runner 链路不可构建；移除未用依赖 `@supermemory/memory-graph`
  - **I 摄入**：Add Memory 弹窗三 tab 真实落库——Note 直存、Link 存 URL+title+description（D1 元数据记忆）、File 走 `POST /v1/upload`（multipart）+ `getPipelineStatus` 轻量轮询（2s 阶段显示 / done 报告记忆数 / failed 显式报错 / 3 分钟有界放弃）（D2）；Space 选择器经 container_tag 生效；修复 dashboard 快速保存失效 key 错位（I1）
  - **C 对话**：盘活 `/api/chat` 代理——SSE 流式打字机（C2）；无 key 返回 `{degraded:true}` 结构化降级 + 气泡「记忆检索模式」badge（C3/D4）；模型选择器真实发送并修剪为 gpt-4o/gpt-4o-mini（C4/D4）；profile.static 按 importance top10/~1500 字符注入 system prompt 且置于 memories 之前（P3/D5）；OPENAI_API_KEY 仅经 env 注入 frontend 容器（D3）
  - 验证：web 生产构建零错误；compose 双形态 config 合法；引擎测试零回归（18 项既有环境失败与基线 17de549 一致）；质量套件 62 passed

- **B3 NER 提及层（issue #21–#28）**——提取后解析命名事物为图节点，为图谱深度打物理基底：
  - **提及（Mention）节点**（ADR-0005）：`(:Memory)-[:MENTIONS]->(:Mention)` 是非事实引用类别（非第四种关系），去重键 `(entity_id, 规范形式, 类型)`，表层别名累积（「谷歌」「GOOGLE」解析到同一 Google 节点），mention_count 计数，创建/重复附加幂等
  - **规则提取 + 封闭分类法**：`RuleMentionExtractor`（无 LLM 确定性路径）+ 封闭类型分类法（person/organization/location/technology/concept，域外回退 concept）+ 置信度门槛（低置信丢弃，无节点无边）
  - **实体隔离**：提及节点实体作用域；跨实体同名不共节点；Neo4j Cypher 分支双实现覆盖
  - **时序集成**：UPDATES 取代时旧记忆保留 MENTIONS 边（历史节点）；遗忘时剪除边并剪除孤立提及节点（原子事务）
  - **跨实体隔离**：`get_memories_mentioning` 实体作用域、类型无关规范形式匹配、mention id 精确匹配
  - 结构模板占位符空格归一化（中/拉丁公司名共享模板，issue #28）
  - 质量套件 `tests/quality/mentions/`（4a 精度 / 4b 解析 / 4c 分类法 / 4d 隔离 / 4e 遗忘 / 4f 更新 + Neo4j 变体），确定性语料 + mock 嵌入 + 规则路径
- **B4 多跳图谱推理（issue #29–#35）**——图谱遍历成为 `search` 的深度参数，三类边 + 提及桥：
  - **实体中心检索**：`search(about=...)` 按提及（规范形式或 mention id）返回实体上下文池内提及该事物的全部最新记忆，跨所有表层形式；纯图谱操作，跳过 RAG/fast-lane
  - **共享主体串联**：`Memory-MENTIONS->Mention<-MENTIONS-Memory` 一跳桥接（同实体同提及节点互为兄弟）
  - **关系链式**：沿 UPDATES/EXTENDS/DERIVES_FROM 双向行走，链式推导（D2←D1←A 查 A 时 D2 以 depth 2 浮现）；每跳实体隔离；环路安全（visited 集合，浅层深度优先）
  - **历史节点处理**：is_latest=False 仅在沿 UPDATES 被踩到时浮出并标记，从不主动搜历史、从不穿越历史
  - **路径透明**：每个多跳结果携带 `path`（memory/mention 节点 + 关系边）与 `depth`（跳数）；种子 depth 0 空路径；REST（POST/GET）+ SDK 一致
  - **排名**：信任分 × 0.85^depth 折扣，`(-score, depth)` 排序——同分种子在前；遗留一层关系扩展同样标注 depth=1 + 单边路径
  - **深度语义**：默认 0（现状不变，显式 opt-in），上限 4（REST `le=4` + 引擎 clamp）
  - **可观测性**：`emerald_search_hops` 直方图 + `emerald_multihop_paths_returned_total` 计数 + 每次多跳查询 `search.multihop` 日志（depth/seeds/paths_returned）；depth=0 零排放
  - 质量套件 `tests/quality/multihop/`（5a 实体中心 / 5b 串联 / 5c 关系链 / 5d 路径透明 / 5e 环路安全 + Neo4j 变体），聚合门（quality.yml）登记新 section
  - CONTEXT.md 新增「提及」「实体中心检索」「多跳推理」术语；ADR 评估结论：多跳作为 search 参数决策可逆，不立 ADR-0006
- **B5 社区检测器（issue #37，spec #36 T1）**——确定性标签传播，为社区遗忘提供纯结构划分：
  - `emerald/core/community.py`：`CommunityDetector.detect(entity_id) → {memory_id: community_id}`，沿 UPDATES/EXTENDS/DERIVES_FROM（双向）与共享提及桥划分社区；异步标签传播（多数原则 + 度数/ID 双 tie-break 保住稠密簇不被单桥节点合并）
  - **确定性契约**：固定节点序 + 固定邻居序 + 确定性 tie-break——同图同输入必得同划分（质量套件可精确断言）
  - **实体隔离 + 历史排除**：仅 is_latest=true 的实体自有记忆参与结构；跨实体边过滤、历史节点既非成员也非粘合
  - **零新增图存储方法**：邻接全部经由 B4 既有读取原语（`list_forget_candidates` / `get_relationship_neighbors` / `get_memory_mentions` 倒排索引），双后端可用，无 Neo4j GDS 依赖
  - **规模护栏**：每实体记忆上限 + 迭代上限，护栏触达时结构化日志
  - 单元测试 `tests/unit/test_community.py`（链/星/环路/双团+桥接/提及簇合成图 + 确定性 + 隔离 + 护栏，18 例）
- **B5 社区活性评分与决策（issue #38，spec #36 T2）**——纯函数层把划分变成每社区行动：
  - `score_communities`：活性分 = 加权信号（平均置信度 + 最近触达指数衰减 30 天半衰期 + 内部边密度 + 画像引用占比），纯结构/统计信号，不调 LLM
  - `find_bridge_memories`：邻居跨越 ≥2 社区的边界节点；`decide_communities` 决策矩阵：低于阈值 → 整社区遗忘；含画像引用或高 importance 记忆的社区豁免（exempt_profile）；持桥接记忆的低活性社区部分遗忘（exempt_bridge：桥接记忆保留、其余遗忘——所在社区不整体遗忘）；健康社区 keep
  - `forgotten_memories`：决策到遗忘集的纯投影（T3 落地接缝）；豁免标签仅在改变结局时打出
  - 确定性：全部纯函数形态（显式传 `now`，无 I/O）；单元测试 `tests/unit/test_community_decisions.py` 决策矩阵 25 例全绿
- **B5 forget_communities 策略（issue #39，spec #36 T3）**——第四个自动遗忘策略上线：
  - `ForgetEngine.forget_communities(entity_id=None)`：枚举实体 → 检测社区（T1）→ 评分决策（T2）→ 整社区经既有 `mark_expired` 接缝遗忘（reason=`community_forgotten`；MENTIONS 边剪除与孤立提及节点剪除随既有接缝自动生效）
  - 豁免生效：活跃社区、桥接记忆（及边界端点）、画像引用/高 importance 社区原样保留；单实体运行不影响其他实体；单次运行内同社区连续处理
  - 可观测性：每社区决策结构化日志（entity_id/community_id/size/activity_score/action）+ `emerald_forget_communities_total` 指标（按 action：forgotten / exempt_bridge / exempt_profile / keep）
  - Celery Beat 日级调度 `forget_communities_task`；修复既有三个遗忘策略 beat 条目指向未注册任务名的问题（`forget_expired`→`forget_expired_task` 等），并新增 beat 回归测试断言所有条目指向已注册任务
  - `build_adjacency` 从检测器提为模块级函数（T1/T3 共用接缝，零重复逻辑）
  - 引擎级单元测试 `tests/unit/test_forget_communities.py` 10 例（精确遗忘集、桥接存活不变式、画像豁免、提及剪除、实体隔离、指标、幂等/确定性）；顺带修复 T1 一条刀口边缘测试（3-clique 桥接合并依赖 UUID 顺序 → 改为路径结构）
- **B5 确定性质量套件 + Neo4j 变体 + 聚合门（issue #40，spec #36 T4）**——社区遗忘的遗忘有效性进入独立侧质量门（ADR-0001）：
  - `tests/quality/communities/`：确定性语料（两个过期社区 + 活跃社区 + 桥接记忆 + 画像引用信号）+ mock 嵌入 + 规则路径（无 LLM）+ 时间回拨，沿用既有遗忘套件的 Metric 类门槛模式
  - 三项门槛全过：社区淘汰率 ≥ 0.95（过期社区作为簇整体消失，仅桥接记忆与一个边界端点按 spec 故事 7 存活）、信号存活率 ≥ 98%、检索保留率 ≥ 95%
  - 遗忘前后检索结果集断言精确：基线 19 条全部可检索，遗忘后仅过期社区成员消失（9 条），全部信号仍可检索；全池探针（top_k 覆盖实体池 + 关闭动态截断）避开 trust×cosine 评分对低置信信号的排序干扰
  - 同一场景定义（corpus + Metric + runner 共享模块）在真实 Neo4j 上实跑同场景：Cypher 分支（检测邻接、mark_expired reason=community_forgotten、画像豁免、get_memory 检索过滤）；Neo4j 不可达时 skip 不红门，CI `quality-temporal` 任务 compose 实跑
  - 聚合门（`.github/workflows/quality.yml`）登记新 section（第 6 节）；quality marker 描述同步更新
- **B6 consolidate_duplicates 策略（issue #44，spec #41 T3）**——第五个自动维护策略（日级 5AM，遗忘批次之后）：
  - `ForgetEngine.consolidate_duplicates(entity_id=None)`：枚举实体 → 向量候选（T1 #42）→ 规则护栏决策 → 经 `mark_consolidated` 原子接缝落地（T2 #43，reason=`consolidated`，边重连随接缝自动生效）
  - 重复组收敛为单代表：CONSOLIDATE 对连成的连通分量按确定性全序（信任分 desc → created_at desc → id asc）选组代表，成员仅当自身与代表的 pair 判定为 CONSOLIDATE 时才并入——护栏否决（画像/矛盾/UPDATES 边/类型）绝不被第三方成员绕过（误并率 = 0 硬门）
  - 实体隔离（ADR-0002）；空图/单记忆图零副作用；单记忆失败不中断同实体其余合并，单实体失败不中断扫描
  - 可观测性：每 pair 决策结构化日志（entity_id/memory_a/memory_b/similarity/action/reason/representative_id）+ 每次落地合并日志 + `emerald_consolidate_duplicates_total` 指标（action：consolidated / keep / exempt_profile / exempt_type / exempt_contradiction / exempt_updates，与 `DuplicateAction` 词汇一致）
  - Celery Beat 日级调度 `consolidate_duplicates_task`（排在遗忘批次条目之后）；`ForgetEngine` 新增 `vector_store`/`duplicate_config` 注入（D2 参数校准接缝）；`ForgetStrategy` 新增 CONSOLIDATE
  - 引擎级单元测试 `tests/unit/test_consolidate_duplicates.py` 14 例（收敛/组内否决分裂/双组独立收敛/画像与 UPDATES 豁免保留/实体隔离/空图/指标按 action/失败隔离×2/幂等/确定性）；beat 回归测试新增条目指向与顺序断言
- **B6 确定性质量套件 + Neo4j 变体 + 聚合门（issue #45，spec #41 T4）**——整合有效性的独立侧质量门（ADR-0001）：
  - `tests/quality/consolidation/`：确定性语料（3 个重复组 × 相同内容不同年龄——mock 嵌入只有相同字符串才相似，重复组用相同内容作确定性替身，真实 paraphrase 召回为 D2 校准项；+ 4 组否决护栏反例：画像保护/矛盾/跨类型/UPDATES 边 + 2 条无关信号记忆，共 19 条）+ 规则路径（无 LLM）+ 时间回拨
  - 三项门槛全过：整合召回率 1.000 ≥ 0.95（3 组各收敛为单代表，6 条被并、3 代表存活）、**误并率 = 0 硬门**（10 条豁免/信号记忆原样保留，rate 必须 1.0）、检索保留率 1.000 ≥ 95%
  - 整合前后检索结果集按**记忆 id** 精确断言（重复组内容相同，成员只能按 id 区分）：基线 19 条全可检索；整合后代表与全部幸存者仍可检索、被并者从检索消失；被并者 replaced_by 指向组代表（可审计）
  - 同一场景定义（corpus + Metric + runner 共享模块）在真实 Neo4j 上实跑同场景：Cypher 分支（候选读取、UPDATES 边否决、画像豁免、mark_consolidated 单语句事务、get_memory 检索过滤）；Neo4j 不可达时 skip 不红门，CI `quality-temporal` 任务 compose 实跑
  - 聚合门（`.github/workflows/quality.yml`）登记新 section（第 7 节）；quality marker 描述同步更新；质量门 67 项全绿（含 Neo4j 变体实跑）

### Changed

- **统一 search 接入**：`SearchResult` 新增 `depth`/`path` 字段（`PathStep`）；`_memory_to_result` 补 tags 消除向量/about 与 keyword 路径结果漂移；GET 路由补 `is_latest`；SDK `SearchResult` 对齐 REST（path/depth/container_tag/tags）
- 遗留关系扩展改用 `get_relationship_neighbors`（含边类型），补实体隔离过滤
- **C2 LangChain.js 集成与 C6 demo 取消**（2026-08-23 决议，issue #54/#55 关闭为 not planned）：框架集成属生态投资，无真实用户信号不投入；v0.7.0 生态可发布物清零，M3 收敛为 B3 ✅ + B4 ✅ + A5，里程碑改题「图谱深化与文档」

### Documentation

- **A5 API 文档 overhaul（issue #56，v0.7.0 可发布物）**：
  - `docs/api/rest-guide.md` 重构为三层结构（快速入门 → 核心四 → 进阶/管理），核心四每端点给 cURL + Python SDK + TypeScript SDK 三段示例；补齐此前未文档化的 16 个操作（PATCH/validate 记忆、profile config ×3、memory.md 导出、conflicts resolve、extract-url、sessions ×2、Spaces ×4、keys ×3），openapi.yaml 全部 34 个操作入文
  - 修正三处文档偏差：`top_k` 默认 10 → 30、`/v1/files` 改游标分页、`AddMemoryRequest` 补 `idempotency_key`/`container_tag`/`valid_until` 等字段
  - `docs/api/sdk-guide.md` 新增「Python ↔ TypeScript 方法对照」节与双语言示例；`sdk/typescript/README.md` 补 `SearchOptions`（含 `about`/`depth`）/ `AddOptions` / `UploadOptions` 字段表与多跳示例
  - 明确管理扩展端点（keys/sessions/conflicts/spaces 等）为 REST-only，SDK 不暴露（AGENTS.md 原则 7）

### Fixed (docs)

- OpenAPI 顶层 tags 声明漂移：声明 6 个 tag（含已退役的 Connectors）vs 实际使用 12 个——`scripts/generate_openapi.py` EXTRA_INFO 更新为 12 个 tag 并重新生成 `docs/api/openapi.yaml`（drift 门恢复真实约束力）

### Test baseline

- 全量：`1158 passed / 18 failed`（2026-08-23 复跑，7ffffd4；可选提取依赖 ×17 + docker 镜像 ×1；LLM 重写 flake 偶发——`test_rewrite_query_noop_for_long_query` 依赖真实 LLM 行为非确定，与 v0.6.0 基线同源）；质量门 67 项全绿（含 Neo4j 变体实跑）

## [0.6.0] — 2026-08-11

### Removed

- **自研连接器退役（ADR-0004 契约阶段，issue #7）**——`emerald/connectors/`（2,194 行：gmail/github/google_drive/notion 的 OAuth、凭证加密、webhook 接收与续期、Celery 定时同步）及配套全部移除：
  - 路由 `/v1/connectors/*`（connect/callback/webhook/status/revoke）、`Connector` 模型、`OAuthStateStore`、`emerald/api/error_codes.py` 的 CONNECTOR 类目与 `emerald/core/exceptions.py` 的 Connector 异常；`pipeline/celery.py` 移除 5 项 beat 任务（renew_webhooks + 4× provider 同步）；`.coveragerc` omit 条目清理；依赖移除 `cryptography`（仅被旧凭证加密使用）
  - 测试：`tests/connectors/`、4 个 provider e2e、`test_connectors`、`test_oauth_state_store`、`test_exceptions` 连接器用例；OpenAPI 重新生成（26 paths / 34 operations）
  - 迁移 `009_drop_connectors`：删除 `connectors` 表（数据绑定已由 `source_bindings` 承接，ADR-0004）
  - 保留：`ConnectionHub` 抽象 + `TotemHubClient`、`/v1/sources/*` 绑定路由、事件驱动摄入；web 集成页改接 `/v1/sources`（feishu）；docs 全量收敛（rest-guide/api-design/data-model/deployment/README/roadmap）
  - 测试基线：`828 passed / 18 failed`（可选提取依赖×17 + docker 镜像×1），连接器 e2e 基线 6 项随删除消失，无新增失败

## [0.5.0] — 2026-08-11

### Fixed

- **fix(relationships): 规则矛盾检测误伤无关记忆**（2026-08-11 基准发现，产品级缺陷）——`_is_contradictory` 只要新文本含单字「不」就判 UPDATES（取代），且重叠守卫仅要求共享主语：一条含「不」的意见事实（“覆盖率不能低于 80%”）曾把实体其余 19 条事实全部标记过期。修复：① 否定词触发需 ≥2 个实质共享 bigram（排除主语片段）；② 强信号词表收紧——移除「新」（“新壁纸”使 13 条无关事实被取代）、「现在」的裸词判定改为保留（更新链闭合依赖，见下）；③ 主语提取只取文本开头的英文专名（句中 Python/Vim 是内容词，误当主语会丢弃其 bigram）；④ 「刚」保留（“会议刚改到周三”）。质量套件三节（时序 65 例 / 遗忘 / 图谱 61 例）全绿；Fact Recall 基准从 0.133 → 0.933，Distractor Resistance 从 0.0 → 0.6。
- **fix(benchmarks): 真实嵌入跑分被 Redis 旧缓存污染**——`engine._embed` 缓存键为纯文本哈希（不含模型标识），此前 mock 跑分写入的 128 维向量在真实跑分时被当作缓存命中（`vector.store dims=128` 而嵌入器产出 1024），主向量库全程使用 mock 数据。修复：缓存键纳入模型标识（`{model_id}|{text}`），MockEmbeddingProvider 暴露 `_model`；跑分前清空历史 `emb:*` 键。
- **fix(benchmarks): 单模型绝对分报告渲染**——`benchmark_to_markdown.py --absolute` 无第二模型时列标题硬编码 `text-embedding-3-large`、Δ 列恒为 —。修复：缺失模型列显示 —，Δ 退化为「模型 − mock 基线」（单模型报告的信息量补回），模型列名从报告 config 读取。

### Added

- **真实嵌入绝对分报告发布（roadmap M2 #12/#13）**——首个绝对分报告 `docs/benchmarks/absolute-scores-2026-08-11.md`：
  - **模型口径变更**（2026-08-11）：发布环境无法直连 api.openai.com（网络层不可达，IPv4/IPv6 均超时），改用 **SiliconFlow 网关的 BAAI/bge-m3**（1024 维）作为真实嵌入模型。`OpenAIProvider` 新增 `base_url` 参数 + `settings.openai_base_url`（默认 api.openai.com，兼容网关）；维度映射支持 `bge-m3` / `BAAI/bge-m3` → 1024；`run_benchmarks.py --embedding-model` 显式路径接线 base_url。OpenAI 官方 3-small/3-large 双列仍是首选口径（网络可达时按原流程）。
  - **结果**：7/7 维度通过（100%），Aggregate **0.943**；发布门槛 7/7（每维 ≥ mock 基线，Fact Recall 0.933 vs 0.167、Distractor 0.600 vs 0.200——真实语义嵌入 vs mock 的差距实证）；通过门槛达标（矛盾链 1.000，等权均分 0.898 ≥ 0.70）。
  - mock 基线同步更新（0.792，规则修复后语义）并重新入库。
  - 新增测试：`OpenAIProvider` base_url 默认/自定义、bge-m3 维度映射、CLI 接线（+5 例）；`tests/unit/test_embedder.py` fixture 隔离真实 Redis（修复 4 个环境依赖基线失败）。

### Security

- **安全审计（roadmap M2 #14）完成 — 0 个 P0/P1 漏洞**（报告落 `docs/verification/security-audit-2026-08.md`）：
  - **依赖扫描**：pip-audit 2.10.1 双模式（venv 实装 + 干净环境最新约束解析）均 0 已知漏洞；CI 门禁由 warning 升级为**硬失败**（移除 `|| echo ::warning` 兜底），PYSEC-2024-1 豁免保留。
  - **Secret 检测**：Gitleaks 全历史（237 commits）**零真实泄漏**——原始扫描 31 个命中逐项核验全部为 dev 占位凭据（`.env.*` / config.py 默认值 / CI 沙箱 / 开发脚本），无 API key/token/私钥/生产连接串。修复三个配置缺陷：① 连接串规则 `[^@]+` 跨行贪婪误报（Go 否定字符类含 `\n`）→ 改为 `[^@\n]+`；② `[allowlist.rules]` map 结构与 `paths` 共存时被 gitleaks 8.24.3/8.30.1 静默丢弃 → 迁移官方 `[allowlist] regexes` 字段 + 示例/测试配置文件路径豁免；③ gitleaks-action 仅扫 push commit range（`base^..HEAD`），全历史从未被 CI 覆盖 → 新增 `secret-scan-full-history` job（固定 gitleaks 8.30.1）。
  - **API 层清单五项**（CORS / 实体隔离 / 鉴权边界 / 限流 / 上传+Webhook 验签）：4 项达标；**发现并修复 1 项**——`POST /v1/extract-url` 无鉴权执行出站 HTTP fetch（未认证 SSRF 面 + 资源滥用，`follow_redirects=True`）→ 挂载 `api_key_auth` + `rate_limit`，新增回归测试 `tests/api/test_extract_auth.py`（2 例：401 前置拦截断言 httpx 零调用 / 认证后正常提取），OpenAPI 重新生成。
  - 观察项 5 条（Redis 不可用时限流 fail-open、authorize_entity 测试便利 no-op、tests/docs 目录豁免偏宽等）记录于报告 §5，不阻塞。

### Added

- **结构化数据（JSON/CSV）分块与自动检测**（spec issue #1）：
  - 新增 `json`/`csv` 分块器——JSON 按顶层结构（数组元素/对象键）分块，小元素合并为有界批次；CSV 每块携带表头，行按字符上限分批；畸形输入（JSON 解析失败、CSV 字段数不一致）记录 warning 并回退到 text 分块，不阻断管线。
  - `content_type` 缺省时自动嗅探：可解析为 dict/list 的 JSON、分隔符与字段数（逐行校验）一致的 CSV 走结构化分块；显式声明（含显式 `text`）永远优先，现有显式调用行为不变。
  - 结构化块携带来源元数据（记录索引/键/行范围），随记忆存入图谱（`chunk_source` 命名空间，不覆盖调用方 metadata），检索结果可溯源到原始记录。
  - MIME → 管线内容类型解析（`emerald/pipeline/mime.py`）：上传与外部源携带的 `application/json`、`text/csv`、`application/pdf` 等 MIME 字符串正确解析到短类型，修复了此前上传路径在提取阶段即失败的问题。
  - `.json`/`.csv` 文件扩展名加入上传 MIME 检测。
  - 默认提取器/分块器注册表加入 `json`/`csv`；注册表断言测试同步更新（README 承诺 vs 实现的持续守卫）。

### Tests

- **嵌入模型参数化与双模型两列报告**（issue #18，T2）— 真实嵌入基准支持按参数选模型，双模型对照落地：
  - `scripts/run_benchmarks.py` 新增 `--embedding-model`（默认 `text-embedding-3-small`，未指定时行为与现状一致走 provider factory）；显式指定时直接构造对应 `OpenAIProvider`，维度自动映射（3-small → 1536、3-large → 3072）并写入 JSON 报告 `config.embedding_dim`，下游不再猜维度。
  - `scripts/benchmark_to_markdown.py` 新增双模式：`--dual --small <json> [--large <json>] --output <md>` 渲染每维度 3-small / 3-large 两列 + 差值（Δ）；`--large` 缺失（某模型跑失败）时该列以 — 呈现并显式告警，不整体崩溃；单报告模式输出与旧版字节一致（CI mock 路径不受影响）。
  - `scripts/run_real_benchmarks.sh` 依次跑 3-small、3-large 两次并合并渲染 `docs/benchmarks/real-llm-results.md`；3-large 失败时回退单列报告继续完成，DeepSeek LLM 关系分类流程保持不变。
  - 渲染层单元测试（`tests/benchmarks/test_benchmark_to_markdown.py`）：两列都存在 / 单列缺失 / 单模型缺维度 / 旧报告无 `embedding_model` 字段 / CLI 双模式与单模式兼容；CLI 选型测试（`tests/benchmarks/test_run_benchmarks_cli.py`）：3-large→3072、3-small→1536、默认走 factory、mock 不受影响。

- **独立侧质量套件**（ADR-0001，roadmap M2）— `tests/quality/temporal/` 三 section + CI 聚合门（workflow `quality-temporal`）：
  - **时序正确性**（ticket #9）：25 更新链取代 + 20 时间过期 + 12 显式冲突分流 + 10 保留用例；4 指标聚合门——取代正确率 ≥99%、过期抑制率 ≥99%、保留正确率 ≥98%、分流准确率 ≥95%。冲突分流覆盖高影响（internal_type=decision → PENDING_CONFLICT）与低影响（自动 UPDATES）双路径及 keep_old/keep_new/keep_both/manual 四种 resolve 动作。
  - **遗忘有效性**（ticket #10）：噪音过滤（25 旧噪音 + 5 近期保留）、情节衰减（20 旧 episodic 归档，图谱瘦身率 50–90% 区间断言）、噪音注入对抗语料两档（50% 与 80% 噪音比，各 60 条）、信号保留（引擎全链路 12 信号，清理后检索保持率）。4 指标聚合门——噪音清除率 ≥95%、信号存活率 ≥98%（误删 ≤2%）、检索保持率 ≥95%、瘦身率区间。
  - **图谱关系精度**（ticket #11）：61 例标注语料类型判定（25 UPDATES / 18 EXTENDS / 18 NONE）、20 例方向与语义、原子性不变量扫描（UPDATES 边 ⟺ target 归档且 replaced_by 指向 source，违规 =0）、跨实体隔离（图关系 + 检索双向断言）。4 指标聚合门——类型判定 ≥95%、方向 ≥98%、原子性违规 =0%、泄漏 =0%。
  - 确定性语料 + mock 嵌入 + 规则路径（`use_llm=False`）；Neo4j 真实存储变体（`test_neo4j_quality_variants.py`，不可达时 skip，CI 聚合门在 compose 服务下覆盖 Cypher 分支）。三节指标各自全绿才通过聚合门，互不抵消。
- **fix(graph): in-memory `create_update_relation` 缺少 source 存在性检查** — 质量套件原子性场景发现：Cypher 分支以 `MATCH (new)` 守卫缺失 source 的更新为 no-op，in-memory 分支却仍会归档 target（幻影归档）。已补齐存在性检查，两后端行为一致。
- **fix(tests): `test_pipeline_tasks` 顺序依赖** — forget 类任务测试依赖真实 Neo4j driver loop（`_neo4j_driver_for_loop`），全量套件按目录顺序运行时行为不一致。已 mock driver loop，单元测试不再依赖外部服务。

- **路由枚举适配 Starlette 1.x 惰性路由**（issue #2）— `include_router` 在 Starlette 1.x 下注册惰性 `_IncludedRouter`（无 `path` 属性），`app.routes` 简单过滤得到空集。`tests/api/test_route_completeness.py` 与 `tests/negative/test_no_internal_exposure.py` 改为递归展开惰性路由（`effective_candidates()`），在无引擎 stub 与有引擎两种形态下枚举实际路由面；v2 泄漏守卫从恒真断言修复为真实前缀检查。同步重新生成 `docs/api/openapi.yaml`（含 sources/spaces/extract-url 路由与 memories 的 patch/delete 方法），OpenAPI 漂移测试回归绿，`generate_openapi.py --check` 通过。
- **清理过期 API 测试**（issue #3）— v0.4.0 下线 v2 路由后残留的 v2 断言（`test_api_versioning.py` 三处、`test_upload_authorization.py` 一处）改为断言 v2 返回 404 或删除；`/v1/files` 测试从偏移分页（`page`）签名迁移到游标分页（`page_token` + `page_size`），断言新响应结构（`pagination.next_page_token`/`has_more`），新增无效游标 token → 422 行为测试。产品路由代码零改动。
- **矛盾链对抗场景（第 7 维度）**（issue #17，T1）— 基准套件新增 Contradiction Chain 维度，补足 Temporal Updates 的深度覆盖：
  - `scripts/run_benchmarks.py` 新增第 7 个场景函数 `benchmark_contradiction_chain`（与现有场景同构：同签名、同 `BenchResult` 返回）：5 条链 × 5 轮连续取代（6 步/链），每轮构造对同一事实的完全矛盾新事实（结构模板换填充 / 数值变更 / 矛盾措辞三类语料，规则分类器在 mock 下确定性输出 UPDATES）。
  - 每轮验证四件事：旧事实 `is_latest` 翻转为 False 且 `replaced_by` 指向新事实、UPDATES 边从新事实指向旧事实、最新事实按精确文本查询命中 top-1、过期事实不再被召回。指标：`latest_recall@1` / `expired_exclusion_rate` / `is_latest_flip_rate` / `update_relation_rate` / `overall_accuracy`（mock 下全部 1.0，无 API 依赖）。
  - 报告链路接入：JSON 报告（7 维度）与 `benchmark_to_markdown.py` 渲染（含双模型对照模式的每维度列）均包含该维度得分与通过状态。
  - 单元测试（`tests/benchmarks/test_memory_benchmarks.py` 新增 `TestContradictionChain`）：5 轮取代后 is_latest 翻转与 replaced_by 链、召回正确性（最终事实 top-1、过期事实排除）、每轮恰好一条 UPDATES 边、场景函数在 mock 嵌入下确定性（四项指标 == 1.0）。
- **双门槛评估纯函数**（issue #19，T3）— 绝对分报告的双门槛判定落地为无 IO 纯函数：
  - `scripts/benchmark_gates.py` 新增 `evaluate_gates(report, mock_baseline) -> GateResults`：发布门槛（每维真实分数 ≥ 对应 mock 基线）与通过门槛（矛盾链 ≥ 80% 且 7 维等权均分 ≥ 70%，等权默认）独立判定，互不掩盖；维度分数取与报告表格一致的 key metric（复用 `_pick_key_metric`），门槛结论与读者在报告中看到的分数同源。
  - 维度集合不一致、缺矛盾链维度、维度无可比指标时抛 `GateEvaluationError` 并指明维度；两门槛均为 ≥ 语义（恰好 0.8 / 恰好 0.7 即通过）。
  - mock 基线获取：`load_mock_baseline()` 默认读库内已入库的 `docs/benchmarks/mock-baseline.json`（已生成入库，含全部 7 维度；`reports/` 被 gitignore 不能作基线）；缺文件 / 非法 JSON / 缺 `results` 列表均有明确报错与指引。
  - CLI：`python scripts/benchmark_gates.py <report.json> [--baseline <mock.json>]` 输出两门槛逐维结论，退出码 0/1/2（双通过 / 门槛失败 / 评估错误），可接入发布流程。
  - 单元测试（`tests/benchmarks/test_benchmark_gates.py`，25 例）：双通过 / 单维低于基线 / 基线侧与报告侧缺维度 / 缺 results / 缺矛盾链 / 无可比指标 / 非对象条目 / metrics 为空 / 维度重名 / 两侧选中指标不一致 / 临界分边界（矛盾链恰好 0.8 通过、均分恰好 0.7 通过、0.699 不通过，均分比较带 1e-9 浮点容差）/ 基线加载错误路径 / CLI 退出码与 --json 输出。
  - 文档同步：`docs/roadmap.md` 双门槛公式由过时的「6 维加权均分」更正为 #16/#19 决议的「7 维等权均分 ≥ 70%」（等权默认）；`_pick_key_metric` 升为公共 `pick_key_metric`（跨脚本契约）。
- **绝对分报告落地接线与 README 死链修复**（issue #20，T4）— 报告生成接入双门槛评估：
  - `scripts/benchmark_to_markdown.py` 新增 `--absolute` 模式（`--absolute --small <json> [--large <json>] --baseline <mock.json> --output <md>`）：渲染日期命名绝对分报告——每维度三列对比（3-small / 3-large / mock 基线 + Δ）、双门槛结论（发布门槛逐维对比 + 通过门槛矛盾链/均分明细，复用 `evaluate_gates` 逐模型独立判定，两模型各自一行结论）、矛盾链维度说明、独立侧套件引用（`tests/quality/temporal/`）与 ADR-0001 引用；`--large` 缺失时该列以 — 呈现且仅评估 small 门槛；基线维度集合不一致时抛 `GateEvaluationError` 明确报错（不静默漏列），CLI 退出码 2。
  - `scripts/run_real_benchmarks.sh` 接线：跑分后自动生成 `docs/benchmarks/absolute-scores-<YYYY-MM-DD>.md`（日期命名、可多期共存、可回溯）；中间产物（双列对照、DeepSeek 报告，及 CI 的 mock-results.md）统一输出到 gitignored 的 `reports/`，不再污染 `docs/`；无 `OPENAI_API_KEY`（provider factory 回退，非真实 OpenAI 嵌入）时跳过绝对分报告并告警；结尾打印入库提醒（审阅 → git add → README 加链接）。
  - `docs/benchmarks/README.md`「已发布的报告」死链清理：移除从未生成的 `mock-results.md` / `real-llm-results.md` / `real-llm-deepseek-results.md` 三个链接，改链已入库的 `mock-baseline.json`，写明绝对分报告发布流程；真实嵌入跑分不进 CI，由维护者手动跑并提交入库。
  - 渲染层单元测试（`tests/benchmarks/test_benchmark_to_markdown.py` 新增 6 例）：三列对比 + 双门槛结论渲染 / 单模型门槛失败点名（含数字）/ large 缺失容错 / 基线缺维度报错 / CLI `--absolute` 写文件 / 基线不匹配退出码 2。

### Changed

- **连接中心接入目标改为 Totem（issue #6，ADR-0004）** — 不再考虑接入 StackOne（外部托管云
  的外部阻塞/数据出域），改为接入同团队内部项目 Totem（`../totem`，内部自托管多租户动作层，
  v1 upstream = Feishu Docs，功能对齐 StackOne）：
  - `emerald/sources/totem.py`（新）— `TotemHubClient` 实现 `ConnectionHub` 契约：admin 面
    （`oauth/start`、connections 列表，admin-scope key）+ actions RPC（`{action, args}`、
    Bearer + `x-connection-id`）+ 七码错误映射（`retryable`/`retryAfterSeconds` 透出）+
    Webhook 预记录契约（§8.3：HMAC-SHA256 raw body、base64url、`x-totem-signature` 常量时间
    比较）+ 事件归一化（§8.2 平台负载形状）。删除 `stackone.py`。
  - 适配层 feishu provider profile（`search_docs`/`get_doc_content`、`{data, next}` 列表
    envelope、`doc_id` 参数映射）；v1 无版本字段 → 去重水位退化为 doc_id（修复无版本场景
    下 seen 永不匹配的缺陷）；`connection.created/updated/deleted` 生命周期事件纳入
    `handle_event`。
  - 路由 `VALID_PROVIDERS` → `{feishu}`；webhook 端点保留（v1 直连上游订阅「铃铛」，Totem
    ADR-0011；v2 平台投递换入口零改动）；配置/环境变量 `TOTEM_*`（`HUB_PROVIDER=totem`）。
  - **Pilot 验证通过（25/25）**：真实 Totem（当前源码 + mock Feishu 上游）+ 真实管线/Celery
    worker/DB，见 `docs/verification/totem-pilot-verification.md`；旧 StackOne 验证记录保留为
    历史（头部 supersede 注明）。
  - 顺带修复：`PipelineOrchestrator` 显式 import `emerald.pipeline.celery`——此前任何未先
    import celery app 的进程提交任务会解析到 celery 默认 amqp broker（`shared_task` 解析到
    默认 app），提交全部失败（P0-3 同族，API lifespan 恰有覆盖、脚本路径暴露）。
  - OpenAPI 规范重新生成（`docs/api/openapi.yaml`）。

### Fixed

- **API 进程级联调暴露的两个真实缺陷（issue #6 补验）** — Totem Pilot 的 API 级联调
  （真实 API Key + 真实管线端到端，此前从未跑通）暴露：
  - **key 作用域实体约定错配**：`api_key_auth` 以实体内部 UUID 作 `state.entity_id`，
    而 API 公共约定（upload.py、schema 示例、管线 external_id 约定）均为 external_id
    → key 鉴权下搜索/上传永远找不到管线摄入的内容。修复：auth 经 join 取 external_id
    入 state；sources 路由在触达 bindings 表前经新增的
    `binding_store.get_entity_internal_id` 解析 external → internal。
  - **API 引擎默认内存存储**：`create_app` 构建 `MemoryEngine` 未传 `use_db=True`
    （默认 False）→ 搜索/记忆读写全在进程内，管线写入 DB 的内容 API 永远看不到。
    修复：默认引擎显式 DB 存储（graph/vector/fast-lane `use_db=True`），与
    `scripts/persistent_server.py` 对齐。
  - 修复后 API 级联调 10/10 通过，含**混合搜索实际检索召回**（"Pilot Plan" 2 hits、
    中文查询 5 hits）。

### Fixed

- **MIME 解析一致性：text/markdown 提取器缺口**（issue #4）— `text/markdown`（及 `application/markdown`）经 MIME 解析到 `markdown` 后无对应提取器，MIME 路径摄入在提取阶段抛 `UnsupportedContentType`。修复：默认提取器注册表补注册 `markdown → TextExtractor`（与 json/csv 同款先例；Markdown 结构由 `MarkdownChunker` 负责，提取阶段为纯文本）。注册表守卫测试的 extractor 类型集合同步包含该别名；新增 `text/markdown` 提取 + 按标题层级分块（H1/H2 分离断言）与 MIME 族别名（`text/markdown`、`application/markdown`）用例。无新增公共 API 面；README 内容类型计数 9→10 对齐。

### Added

- **API Key 管理端点（issue #5，admin 权限，生产 onboarding 路径）** — 取代 seed 脚本成为生产 onboarding 面（seed 脚本标注仅开发环境）：
  - `POST /v1/keys` — 创建：admin 权限，实体作用域限定调用者自身实体（外部 id 解析为内部 UUID 后与调用者比对，跨实体 403）；权限级别 read/write/admin（422 拒绝未知权限）、可选过期时间；明文 key（`em_` 前缀）仅在创建响应出现一次，服务端只存 SHA-256 哈希与 8 字符前缀。
  - `GET /v1/keys` — 列出：admin 权限，游标分页（`page_token`/`page_size`，复用 `PageToken` 与 files 列表同款 keyset 查询），返回元数据（key_id/前缀/权限/过期/最后使用/状态），不含哈希。
  - `DELETE /v1/keys/{key_id}` — 吊销：admin 权限，软删除（`is_active=False`）；鉴权查询本就过滤 `is_active=True`，吊销后下一请求即 401（含过期 key 401 既有行为）。
  - 新增 `require_admin_permission` 依赖（403 无 admin）；`emerald/api/schemas/keys.py` 请求/响应模型；OpenAPI 重新生成（30 paths / 39 operations），路由完整性守卫测试收录 `/v1/keys` 与 `/v1/keys/{key_id}`；SDK 零新增方法（负面暴露测试保持全绿）。
  - 测试（`tests/api/test_keys.py` 16 例 + `tests/unit/test_auth.py` +3 例）：admin 403 / 明文一次性返回与哈希存储断言（捕获 `session.add` 记录）/ 跨实体 403 / 实体不存在 404 / 非法权限 422 / 过期与吊销 401（auth 单元层 + 真实路由层双覆盖）/ 列表无哈希与分页结构 / 吊销 204 与 is_active 翻转 / 实体隔离 / key 不存在 404 / 畸形请求体 422（非 500）/ naive 过期时间强制 UTC。集成指南 §2 重写为管理端点流程 + bootstrap 指引（首个 admin key 带外创建）。

## [0.4.0] — 2026-07-03

> 合并 M1（部署加固、OTel、基准、CI 自动化）与 M2（API / SDK / 安全加固）全部工作项，发布 v0.4.0。M1 细节见 `git log --grep=feat\(m1\)`；M2 细节见 `git log --grep=feat\(m2\)`。本节仅列摘要。

### Security

- **P0: Cross-entity upload authorization** — `POST /v1/upload` now enforces entity authorization via `_authorize_entity(request, entity_id)` before any I/O. Previously, any authenticated key with `write` permission could upload files into any entity's namespace, breaking per-entity isolation. The check runs *before* the MinIO PUT, so a malicious request never produces a stored object.

### Added

- **P1.2a: `add()` override parameters** — `engine.add()`, the REST `/v1/memories` route, and the SDK `EmeraldClient.add()` now accept direct `memory_type`, `confidence`, and `valid_until` arguments. Precedence: explicit arg > `metadata` dict > chunker default. Lets an onboarding form that has just captured a structured preference skip the LLM classification step.
- **P1.2b: `pipeline_status` fact-extraction metadata** — `GET /v1/pipelines/{id}` now returns `fact_extraction_status` (`success` / `failed` / `skipped`) and `memory_count` so clients can render "extracted N facts" progress. Pipeline job model + Alembic migration `007_add_pipeline_fact_extraction_status` add the columns. Tasks write the column only in `index_task` (the previous duplicate write in `chunk_task` was dead code that index_task overwrote unconditionally).
- **P1.2c: SDK typed exceptions** — New `emerald.sdk.exceptions` module exposes `EmeraldAuthError` (401/403), `EmeraldNotFoundError` (404), `EmeraldValidationError` (422, carries `field_errors`), `EmeraldRateLimitError` (429, carries `retry_after`), `EmeraldServerError` (5xx), `EmeraldNetworkError` (connection/DNS failures). All inherit from `EmeraldError`. The old `httpx.HTTPStatusError` is no longer surfaced to callers.
- **P1.2d: SDK async context manager** — `EmeraldClient` now implements `__aenter__` / `__aexit__`. Use `async with EmeraldClient(...) as client:` and the underlying httpx connection is closed automatically.
- **P2.1: OAuth state in Redis with TTL** — `/v1/connectors/{provider}/connect` and `/callback` now persist OAuth state tokens in Redis (`emerald:oauth_state:{token}`) with a 10-minute TTL via the new `OAuthStateStore`. Replaces the in-process dict that broke multi-worker deployments. `consume()` uses Redis `GETDEL` for atomic read+delete; older redis-py clients fall back to non-atomic get+delete. TTL is configurable via `OAUTH_STATE_TTL_SECONDS` env var. When Redis is unavailable, the route fails with **503** (loud failure) rather than silently accepting tokens that won't work across workers.
- **P2.2: CORS production hardening** — `CORS_ALLOWED_ORIGINS` default is now empty (most restrictive). A bare `*` is **rejected at startup in production** via a Pydantic validator; the dev environment still allows `*` for local browser testing. Prevents the failure mode where a permissive CORS default leaks data via a stolen API key.
- **P3: OpenAPI auto-generation** — `docs/api/openapi.yaml` is now generated by `scripts/generate_openapi.py` from the running FastAPI app. The script is idempotent and supports `--check` mode for CI. A new `tests/api/test_openapi_drift.py` (5 tests) fails CI if the published spec drifts from the actual routes.

### Fixed

- **P1-1: 事件驱动摄入 entity_id 约定错配**（issue #6 验证遗留）— `handle_event` 与兜底同步任务 `sync_all_bindings_task` 把 binding 的内部 UUID（FK 到 `entities.id`）当作 `entity_id` 传入管线，而管线按 `external_id` 解析实体 → 每次事件驱动摄入都 `Entity not found`。修复：适配层经 `binding_store.get_entity_external_id` 将内部 UUID 解析为 external_id 后再入管线；binding 对应实体已删除时 fail-soft（记录错误，不崩溃）。同时修复 `get_binding_by_account`：同一 hub_account_id 跨实体重复绑定时不再抛 `MultipleResultsFound`，改为取首个并记 warning。
- **P1-2: `StackOneHubClient.list_accounts` 对裸 JSON list 响应崩溃**（issue #6 验证遗留，历史记录）— 真实 API 返回 `[]`（非 `{"data": []}`），`resp.get("data", ...)` 在 list 上调用 → AttributeError，`/v1/sources/refresh` 500。修复：同时容忍 `[...]` 与 `{"data": [...]}`/`{"results": [...]}` 两种响应形状。（2026-08-10 起接入目标改为 Totem，该客户端已删除；修复经验保留在 `TotemHubClient` 的响应形状容错中。）
- **P1-3: `/v1/sources` 路由 stdlib logging 传 structlog kwargs**（issue #6 验证遗留）— `sources.py` 的 connect/refresh 错误路径用 stdlib logger 调用 `logger.warning(..., error=...)` → TypeError，502 错误路径实际以 500 崩溃。修复：改用 structlog logger。
- **OpenAPI path / endpoint gaps** — the published spec was missing 6 v1 endpoints (`POST /memories/{id}/validate`, `GET /profiles/{id}/memory.md`, `GET/PUT/DELETE /profiles/{id}/config`, `POST /sessions`, `GET /sessions/verify`, `POST /conflicts/{id}/resolve`). Auto-generation eliminates this class of bug permanently.
- **v2 routes removed** — v2 was a strict subset of v1 throughout v0.3.x; for v0.4.0 we drop the `/v2` prefix entirely. All improvements (error codes, pagination, rate-limit headers, OpenAPI auto-gen) land directly on `/v1/*`. `tests/api/test_v2_route_parity.py` is replaced by `tests/api/test_route_completeness.py`, which fails if any v1 route is missing or undocumented.
- **Chunked `fact_extraction_status` write removed** — `chunk_task` used to write `fact_extraction_status` to the DB; `index_task`'s `finally` block overwrote that value unconditionally, making the chunk write dead. The write is removed; `index_task` is now the single source of truth. `tests/pipeline/test_chunk_task_no_fact_status.py` pins the contract.
- **`chunk_count` field removed from `PipelineStatus`** — the field was declared in the schema and SDK but always returned `0` (the `pipeline_jobs` table doesn't track it), misleading clients. Removed from the Pydantic schema, the SDK dataclass, the route, and the docs.

### Changed (refactor)

- **N5: Centralised `_authorize_entity`** — five route modules (`memories`, `search`, `profiles`, `conflicts`, `upload`) all had a copy of the same 4-line helper. The helper now lives once in `emerald/api/dependencies.py` as `authorize_entity`; routes import and alias it as `_authorize_entity` for backward compatibility with the security test patches.
- **N1: Shared `engine` and `clean_settings` fixtures** — extracted from the 5+ test files that had built their own in-memory engine, plus a `clean_settings` fixture that strips env vars and forces pydantic-settings to use only model defaults. Both live in `tests/conftest.py`.
- **I2: SDK `upload()` reuses the shared httpx client** — previously each `upload()` call built a new `httpx.AsyncClient` (with a 120s timeout) just for one request. Now the shared client handles the call with a per-request `timeout=` override. Cuts the TLS handshake per upload.
- **I3: Flattened `_raise_for_status`** — the SDK's error-mapping helper was 30 lines of nested `isinstance` / `body.get()` calls; refactored to delegate to three small helpers (`_extract_error_message`, `_extract_retry_after`, `_extract_field_errors`).
- **I4: `datetime` import moved to top of `emerald/sdk/client.py`** — no more local import inside `add()`.
- **I5: `_resolve_override` helpers** — `engine._index` had three nested if-blocks to apply the explicit-arg > metadata > chunker precedence; now delegates to `_resolve_override()` and `_resolve_override_valid_until()` (the second parses ISO 8601 strings for `valid_until`).
- **N2: `OAuthStateStore` moved to `emerald/api/_state_store.py`** — the storage abstraction no longer lives in the connector route file, making it independently testable and reusable.

### Tests

- **657 tests pass, 1 skipped, 0 failures** (was 601 before this work). New files:
  - `tests/api/test_upload_authorization.py` (4 tests, including a new end-to-end test using the real `authorize_entity` helper)
  - `tests/api/test_openapi_drift.py` (5 tests)
  - `tests/api/test_v2_route_parity.py` (5 tests)
  - `tests/api/test_oauth_state_store.py` (15 tests, including a runtime 503 test that catches silent in-memory fallback regressions)
  - `tests/api/test_cors_validation.py` (6 tests)
  - `tests/pipeline/test_chunk_task_no_fact_status.py` (2 tests)
  - `tests/sdk/test_add_overrides.py` (7 tests, including 2 precedence tests)
  - `tests/sdk/test_exceptions_and_context.py` (15 tests)
  - `tests/sdk/test_pipeline_status_fields.py` (5 tests)

### Migration notes

- **Alembic migration `007_add_pipeline_fact_extraction_status`** — adds `pipeline_jobs.fact_extraction_status` (String(20), nullable) and `pipeline_jobs.memory_count` (Integer, default 0). Run `alembic upgrade head` before deploying.
- **`CORS_ALLOWED_ORIGINS=*` rejected in production** — existing prod deployments using a wildcard must set an explicit list before upgrading. The new validator fails the startup if `EMERALD_ENV=production` and the wildcard is present.
- **SDK exception types** — existing callers catching `httpx.HTTPStatusError` must catch `EmeraldError` (or a specific subclass) instead. The broad base catches everything.
- **OAuth state tokens** — no client action required; the in-memory dict is gone. Existing in-flight OAuth flows at the moment of upgrade will see their state tokens discarded (they'll need to restart the flow).
- **v2 API removed** — clients pointing at `/v2/*` must switch to the corresponding `/v1/*` path. The v1 path was always a strict superset, so the only change is dropping the `v2` prefix from URLs. The published `docs/api/openapi.yaml` is now single-version.

### Earlier in this release (2026-06-02 to 2026-06-22)

> 这批 M3 图谱智能增强 + 基准升级 + 生产基础设施工作在 v0.3.0 之后、M2 之前完成，与上面 M1 / M2 同属于 v0.4.0 的内容。

### Added

#### M3 — Graph Intelligence 补齐
- **LLM 事实提取** (`emerald/pipeline/chunking/fact_extractor.py`)：DeepSeek V4-Flash 驱动的多事实分解、类型分类（fact/preference/episodic）、置信度评分、summary 生成
- **图谱搜索遍历** (`emerald/core/search.py:_expand_relationships`)：沿 EXTENDS / DERIVES_FROM 关系双向深度=1 遍历，`expansion_factor=0.85`
- **首选项强化** (`emerald/core/engine.py:_strengthen_preferences`)：重复偏好 +0.05 置信度（上限 0.95）
- **关系推断 LLM 化** (`emerald/core/relationship.py`)：DeepSeek 优先，OpenAI 降级
- **语义去重** (`emerald/core/engine.py:_check_duplicate`)：bigram 快速过滤 + LLM 边界判定
- **Cross-encoder 重排序升级** (`emerald/core/search.py`)：三级降级链（cached cross-encoder → embedding cosine → keyword boost），模型实例级缓存，支持 sentence-transformers 热加载
- **关系推断 LLM-first** (`emerald/core/relationship.py`)：LLM 优先分类 + 规则降级；新增 bigram 快速预滤跳过无关配对，避免浪费 LLM 调用
- **Profile config 端点** (`emerald/api/routes/v1/profiles.py`)：PUT/GET/DELETE `/v1/profiles/{entity_id}/config`，per-entity 画像配置覆写（Redis 持久化），ProfileManager 在 compute/merge 时旁加载
- **多因子画像评分** (`emerald/core/profile.py:_compute_importance`)：置信度 35% + 时近性 25% + 类型 20% + 关系 20%

#### API 增强
- `POST /v1/memories/batch` — 批量写入（最多 50 条）
- `GET /v1/graph/viewport` — 图谱可视化（节点+边）
- MongoDB 风格元数据过滤：`$and`/`$or`/`$gte`/`$lte`/`$eq`/`$ne`
- 查询改写 LLM 化：DeepSeek 语义扩展替代模式匹配

#### 本地嵌入
- **fastembed 支持** (`emerald/core/embedder.py`)：ONNX runtime，无 PyTorch 依赖，完全离线运行

#### 生产基础设施
- `ReconciliationEngine` (`emerald/core/reconciliation.py`)：后台修复 Neo4j 孤立节点（双写一致性补偿）
- Redis 分布式锁 (`emerald/core/lock.py`)：防止 Celery Beat 多实例并发执行
- Neo4j 生产配置：连接池 50、超时 30s、重试 30s
- CORS 生产加固：环境变量区分 wildcard 与严格模式
- `GraphStore.update_memory_confidence()`：原子置信度更新
- `GraphStore.get_related_memories()`：双向关系遍历
- `GraphStore.list_entity_ids()`：修复 ForgetEngine 生产环境失效

#### 基准测试
- 升级至 6 维度评估（Fact Recall / Temporal Updates / Relationship Class / Profile Accuracy / Distractor Resist / Forgetting Correctness）
- 对齐 LongMemEval / LoCoMo / ConvoMem 三大公开基准
- `scripts/run_benchmarks.py` 从 ~250 行扩展到 1154 行
- JSON 报告自动生成到 `reports/benchmark-YYYYMMDD-HHMMSS.json`
- `reports/` 已添加至 `.gitignore`

#### 文档
- `docs/comparison-supermemory.md` v2 重写（495 行）：对比矩阵完整反转——三项 P0 致命差距中两项已修复
- `docs/roadmap.md`：post-v0.3.0 战略路线图（4 主题、5 里程碑 v0.4-v0.8、依赖驱动、不锁死时间）
- `docs/superpowers/plans/2026-06-21-m1-v0.4.0-implementation.md`：M1 (v0.4.0) 实施计划（2228 行，TDD bite-sized 任务）— M1 完成后已归档为 `ARCHIVED-2026-06-21-m1-v0.4.0-implementation.md`
- 删除本地 `_references/supermemory-main` 仓库引用
- **2026-06-22：** 所有文档同步更新，生产就绪评估反映最新状态；过时 superpowers plans/specs 归档（10 份）

#### 2026-06-22 补齐（最后 3 项 Stub 清零）
- **Cross-encoder 重排序升级**：三级降级链（cached CE → embedding cosine → keyword boost）
- **关系推断 LLM-first**：LLM 优先 + bigram 预滤 + 规则降级
- **Profile config 端点**：PUT/GET/DELETE `/v1/profiles/{entity_id}/config`，per-entity 配置覆写（Redis 持久化）

### Fixed
- 异步阻塞修复：`emerald/api/routes/v1/upload.py` 改用 `asyncio.to_thread` 包裹 MinIO 同步调用
- 5 个测试失败修复：tracing、code chunker、API route leakage
- CORS 配置生产加固（移除硬编码 `allow_origins=["*"]`）
- stdlib logging 误用 structlog 关键字参数导致 OTel 缺失时导入崩溃
- `pipeline/tasks.py` 改用默认 registry 以避免空 registry 运行时失败
- 移除 dead code `raw_content_ref`，改进 dedup 归一化
- 恢复 `ConversationChunker.__init__` 中 `FactExtractor` 注入（在 merge 中丢失）
- `engine.add()` 与 `pipeline/tasks.py` 全面异步化
- 所有 chunker `chunk()` 方法统一改为 `async def`

### Test Coverage
- v0.3.0 → v0.4.0 测试数：484 → **657**（+173，+36%）
- 重点新增：
  - `tests/pipeline/test_fact_extractor.py`（11 tests，DeepSeekFactExtractor）
  - `tests/pipeline/test_semantic_text_chunker.py`（6 tests）
  - `tests/pipeline/test_conversation_chunker.py`（+49 tests）
  - `tests/unit/test_lock.py`（Redis 锁）
  - `tests/unit/test_reconciliation.py`（双写一致性）
  - `tests/unit/test_embedder.py`（fastembed）
  - `tests/core/test_search.py`（+193 行图谱遍历测试；+5 重排序测试）
  - `tests/core/test_profile_manager.py`（+8 测试：profile config CRUD + 效果验证）
  - M2 新增 9 个测试文件 / 56 测试（typed 异常、OpenAPI drift、OAuth state、CORS 校验、SDK override、chunk_task 守卫、v2 route parity → route completeness）
- 5 个测试失败 → 全部修复

## [0.3.0] — 2026-06-01

### Added

#### M2 — Full Content Type Support (Phase 3)
- Default extractor/chunker registry factories (`get_default_registry()`) for out-of-the-box content processing
- Comprehensive unit tests for PDF, Image, Audio, and Video extractors with graceful dependency-missing fallback
- URL and Code extractor test coverage expanded to 95%+
- Default registry integration tests verifying all 7 extractors and 5 chunkers are wired correctly

#### M3 — Graph Intelligence (Phase 4+5+7)
- `GraphStore.create_relationship()` for writing EXTENDS and DERIVES_FROM edges to the graph
- `RelationshipEngine` now persists EXTENDS and DERIVES_FROM relationships (was logging-only)
- DERIVES_FROM inference heuristic: new memories combining bigrams from 2+ existing memories trigger derivation
- 16 comprehensive tests for `RelationshipEngine` covering UPDATES atomicity, EXTENDS, DERIVES_FROM, and classification
- 11 tests for `ProfileManager` covering cache hit/miss, compute, static/dynamic facts, and latency (< 100ms)
- 10 tests for `ForgetEngine` covering time-based expiry, noise filtering, episodic decay, and strategy idempotency

#### M5 — API Completeness + SDK
- `DELETE /v1/memories/{id}` endpoint (soft delete — marks as `is_latest=False`)
- API version bumped to `0.3.0` across all surfaces
- SDK tests (25 passing) covering add/search/profile/upload/health/pipeline_status/get_memory

#### Phase 11 — Benchmarks
- Standalone benchmark runner (`scripts/run_benchmarks.py`) with quantitative metrics:
  - Temporal Fact Tracking (LongMemEval-style): accuracy
  - Relationship Classification: accuracy
  - Search Recall (LoCoMo-style): recall
  - MRR (Mean Reciprocal Rank)
  - Profile Computation Latency: cold/warm P50 and P99
  - Conversation Recall (ConvoMem-style): accuracy

#### Phase 12 — Observability
- Prometheus metrics endpoint at `/v1/metrics` via `prometheus-fastapi-instrumentator`

### Fixed
- `PipelineOrchestrator` and `MemoryEngine` now use default registries when none provided (previously created empty registries, causing runtime failures)
- `pipeline/tasks.py` now uses default registries for extract and chunk Celery tasks
- All 484 unit tests now pass (previously 2 tests failed due to missing `OPENAI_API_KEY` in CI)


## [0.2.0] — 2026-05-27

### Added

#### MCP Framework Integration
- MCP Server with `add`, `search`, and `profile` tools
- stdio and SSE transport support
- Docker Compose `mcp` service

#### Pandaria Integration
- HTTP Adapter Spec for Pandaria → Emerald integration
- Phase 2 interaction protocol and Phase 5 MCP setup
- `EmeraldMemoryStore` Rust SDK integration guide

#### v0.2.0 Quickstart Guide
- End-to-end setup documentation for Pandaria team

## [0.1.0] — 2026-05-25

### Added
- **Project skeleton**: FastAPI, SQLAlchemy, Neo4j, Redis, MinIO, Celery
- **Core pipeline**: extract → chunk → embed → index with async Celery chain
- **Text processing**: TextExtractor, TextChunker with sentence/paragraph overlap
- **Code processing**: CodeExtractor with AST-aware splitting via tree-sitter
- **7 extractors**: text, code, pdf, url, image, audio, video
- **5 chunkers**: text, code, markdown, pdf, conversation
- **MemoryEngine**: central orchestrator for content ingestion
- **RelationshipEngine**: rule-based UPDATES/EXTENDS/DERIVES_FROM classification
- **ProfileManager**: two-tier profile (static + dynamic) with Redis caching
- **ForgetEngine**: time expiry, noise filter, episodic decay
- **SearchOrchestrator**: hybrid search (memory + RAG) with query rewriting and reranking
- **REST API**: `POST /v1/memories`, `GET/POST /v1/search`, `GET /v1/profiles/{id}`, `POST /v1/upload`, `GET /v1/health`
- **Python SDK**: `EmeraldClient` with `add`, `search`, `profile`, `upload`
- **Connectors**: GitHub, Google Drive with OAuth and incremental sync
- **Database**: PostgreSQL + pgvector, Neo4j, Alembic migrations
- **Tests**: 400+ tests covering extraction, chunking, search, API, SDK
