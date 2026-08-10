# StackOne Pilot 验证记录（issue #6，ADR-0004）

> 验证日期：2026-08-09 · 验证对象：commit `6514c20`（Pilot 代码基线）
> 结论：**有条件通过** — 绑定/Webhook/凭证安全路径验证通过；同步路径因 Pilot 代码缺陷
> （P1×3）与核心管线既有缺陷（P0×3）无法端到端跑通，需修复后复验。
> 验证方式：真实凭据联调（StackOne 单 key Basic 模式）+ 明确标注的 mock 替代。
> **本票不修改产品代码**（仅验证与记录）；验证脚本见文末附录。

---

## 1. 验证范围与方法

| 路径 | 方法 | 真实凭据 / mock |
|---|---|---|
| 绑定（含单 key Basic） | 真实 StackOne API + 真实 DB（PG/Redis/Neo4j） | **真实**（`.env.local` 单 key） |
| 同步（事件驱动摄入→管线→可检索） | 真实 HubAdapter + 真实管线 + FakeHub 内容源 | **部分 mock**（理由见 §3.2） |
| Webhook（验签→增量摄入） | 真实 `StackOneHubClient` 验签实现 + 真实路由 + 真实 DB | **真实**（本地签名构造） |
| 凭证安全 | 代码审计 + DB schema 检查 + 响应检查 | — |

本地环境：Postgres（migration 008 已应用）、Redis、Neo4j（docker）、Celery worker
（真实进程，prefork）。

---

## 2. 验证结果明细

### 2.1 绑定路径（真实凭据）— ✅ 有条件通过

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| B1 | 单 key Basic 模式（key 作 username，secret 留空）鉴权 | ✅ PASS | `GET /accounts` → 200；secret 为空时客户端正常初始化（仅缺 key_id 时告警，无错误路径） |
| B2 | `create_connect_session` 端点路径正确 | ✅ PASS | 请求到达 StackOne，返回业务错误而非 404/401（端点存在） |
| B3 | 绑定记录落库（真实 PG） | ✅ PASS | `upsert_binding` → `source_bindings` 行写入，`sync_status=active` |
| B4 | 实体作用域正确 | ✅ PASS | 实体 A 的绑定对实体 B 不可见（isolation 检查）；本实体可见 |
| B5 | 绑定删除 | ✅ PASS | `delete_binding` 行删除生效 |
| B6 | 同步状态持久化（seen 去重表） | ✅ PASS | `sync_metadata` JSONB 读写往返一致 |
| B7 | 连接会话创建（真实 OAuth 全链路） | ⚠️ 受阻 | StackOne 返回 400：`provider 'googledrive' does not have any default auth config` —— **StackOne 账户侧未配置 connector auth config**（上轮已知，外部阻塞，非 Emerald 代码缺陷） |

### 2.2 同步路径（mock 内容源 + 真实管线）— ❌ 未通过（P1 + P0 缺陷）

**mock 替代与理由**：真实账户链接受 B7 外部阻塞（StackOne 侧无 auth config），无法产生真实
Drive/Notion 内容；故用 `FakeHub`（与测试同构的 ConnectionHub 内存实现）提供列表/内容，
**其余全部为真实产品代码**（HubAdapter、binding_store、PipelineOrchestrator、Celery worker、
Neo4j、搜索）。FakeHub 仅替换 hub 的 HTTP 往返，不改变适配/摄入/管线/检索行为。

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| S1 | 事件 → `handle_event` → 摄入（生产路径） | ❌ FAIL | **P1-1**：`handle_event` 把 binding 的**内部 UUID** 当 entity_id 传给管线，而管线按 `external_id` 解析 → `Entity not found`，摄入全部失败 |
| S2 | 以 external_id 摄入（upload.py 同款约定） | ✅ PASS | list→fetch→pipeline 提交成功，2 项 ingested |
| S3 | etag 去重（同 etag 二次事件跳过） | ✅ PASS | 2nd 事件 ingested=0 skipped=2 |
| S4 | etag 变化重摄入 | ✅ PASS | 更新后 ingested=1 skipped=1 |
| S5 | 管线链（extract→chunk→embed→index） | ❌ FAIL | **P0-1**：`extract_task`/`chunk_task`/`embed_task` 调用 `run_async(_run_x)(self, ...)`，但 `_run_x` 签名不含 `self` → TypeError，所有异步管线任务失败（2026-05-26 引入，先于 Pilot） |
| S6 | fast-lane 即时可检索 | ❌ FAIL | **P0-2**：fast-lane 落库时 embedding 以裸 list 传入 asyncpg jsonb 参数 → `DataError: 'list' object has no attribute 'encode'`，fast_lane_chunks 零写入 |
| S7 | 文档/记忆可检索（混合搜索） | ❌ FAIL | 由 S5/S6 导致：管线未完成，无内容可检索 |
| S8 | 兜底同步任务（Celery Beat sweep） | ⚠️ 同 S5 | `sync_all_bindings_task` 走同一 `ingest_account`（P1-1）与管线（P0-1），同样失败 |

### 2.3 Webhook 路径（真实验签实现）— ✅ 通过

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| W1 | 有效签名接受 | ✅ PASS | HMAC-SHA256（raw body, base64url）→ 200 |
| W2 | 篡改 body 拒绝 | ✅ PASS | 401 |
| W3 | 缺签名拒绝 | ✅ PASS | 401 |
| W4 | 缺 webhook secret 时 fail-closed | ✅ PASS | 拒绝所有投递 |
| W5 | `parse_event` 归一化（event/account/provider/origin_owner） | ✅ PASS | 容错字段映射正确 |
| W6 | 路由级端到端（真实 client + 真实 DB 绑定） | ✅ PASS | 有效签名 → 200 + 摄入统计；篡改/缺失 → 401 |
| W7 | 事件→增量摄入路由 | ⚠️ 受 S1 影响 | 验签与路由正确，但摄入落管线时触发 P1-1/P0-1 |

### 2.4 凭证安全 — ✅ 通过

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| C1 | `source_bindings` 无任何凭证列 | ✅ PASS | 列集合：entity_id/provider/hub_account_id/sync_status/last_synced_at/error_message/sync_metadata/id/created_at/updated_at |
| C1b | 「密钥仅存加密形式」承诺的归属 | ✅ PASS | Emerald 侧为零真（vacuous）：凭证存储/加密/token 刷新是连接中心契约职责（ADR-0004 §2），Emerald 表结构与代码均不落凭证，故无 Emerald 侧加密存储义务；StackOne 侧的加密存储不在本票可验证范围 |
| C2 | API 响应不泄露密钥/Token | ✅ PASS | connect 仅返回 auth_link_url/session_id/provider；webhook 返回摄入统计；`ConnectSession.token` 不序列化 |
| C3 | 凭证仅存 hub 侧 | ✅ PASS | OAuth/凭证/token 刷新职责在 StackOne（ADR-0004 契约）；Emerald 只存授权关系 |
| C4 | 签名比较恒定时间 | ✅ PASS | `hmac.compare_digest` |

---

## 3. 遗留问题清单

### P0 — 核心管线既有缺陷（先于 Pilot 引入，阻塞一切异步摄入）

> 状态（2026-08-10）：**已全部修复**，真实 worker 端到端复验通过（见 §6）。

1. **P0-1 Celery 任务/helper 签名错配**（`emerald/pipeline/tasks.py`，2026-05-26 `16d4fa4` 引入）
   `extract_task`/`chunk_task`/`embed_task` 以 `run_async(_run_x)(self, ...)` 调用，但
   `_run_extract/_run_chunk/_run_embed` 签名不含 `self` → TypeError。
   影响：**所有**异步管线任务失败（upload 路径同样受影响），Pilot 同步承诺无法兑现。
   现有测试只验证任务签名（`celery_app` 单测），未在真实 worker 上执行链，故未暴露。
   **修复**：移除三处调用点的 `self` 实参；新增任务包装器执行级测试
   （`tests/pipeline/test_tasks.py`，直接调用 task 函数 + mock 内部件）。
2. **P0-2 fast-lane embedding 落库类型错误**（`emerald/core/fast_lane.py`）
   `embedding` 参数（list[float]）直接作 JSONB 绑定参数 → asyncpg DataError。
   影响：fast_lane_chunks 从不落库，「即时可检索」失效。
   **修复**：写入侧 `json.dumps` 序列化后绑定（真实 PG 实测：`WRITE json string: OK`，
   读取侧 asyncpg 自动解码回 list，另加 str 归一化防御）；新增 DB 路径单测
   （`tests/core/test_fast_lane.py` 捕获绑定参数断言为 JSON 字符串）。
   复验：链完成后 `fast_lane_chunks` 落库 1 行（embedding 为 384/1536 维 list）。
3. **P0-3 asyncpg 连接与 Celery prefork 事件循环绑定**（`emerald/db/session.py` + 任务内 `asyncio.run`）
   共享 engine 的连接池跨任务事件循环复用 → `got Future attached to a different loop`。
   **修复（三项联动）**：
   - `SessionFactory._build_engine` 支持 worker 模式（`EMERALD_CELERY_WORKER=1` → NullPool）；
     `celery.py` 的 `worker_process_init` 设置该标志并 `rebuild_for_worker()`（处理 fork 前已建的
     pooled engine），`task_prerun` 保留 dispose 作为纵深防御。
   - Redis 客户端 per-loop 重建：`emerald/db/redis.py` 新增 `ensure_redis_for_loop()`，以
     **强引用**记录绑定 loop（`id()` 会被复用，实测踩中）；`DistributedLock` 及 worker 可达的
     `get_redis_client` 调用点（profile/engine/embedder）全部改为 loop-aware 获取，保持
     fail-open/fail-soft 语义。
   - Neo4j driver per-task 生命周期：`tasks.py` 新增 `_neo4j_driver_for_loop()` 上下文，
     `_run_index`/`_run_postprocess` 及四个 beat 任务（forget×3/reconcile）各自在任务 loop 内
     init/close；删除 worker_process_init 里绑定死循环的 neo4j 初始化。
   **连带修复**：无 API key 时 fallback 的 `MockEmbeddingProvider` 维度 384 → 1536
   （对齐 `embeddings.embedding Vector(1536)`；此前无 key 部署在 index 阶段必失败）。
   复验：真实 prefork worker（concurrency=2）多任务跨 loop 运行，链状态 `done`，
   PG 状态写入、fast-lane、pgvector（1 行）、Neo4j（1 节点）全部落库（§6）。
   测试：`tests/db/test_session_factory.py`（NullPool 语义）、`tests/db/test_redis_lifecycle.py`
   （跨 loop 重建）、`tests/pipeline/test_celery_signals.py`（信号注册）。

### P1 — Pilot 代码缺陷（本票验证范围内）

> 状态（2026-08-10）：**已全部修复**，测试复验通过（见 §7）。

4. **P1-1 `handle_event`/`tasks.py` 传错 entity_id 约定**
   `binding.entity_id` 是内部 UUID（FK 到 entities.id），而
   `PipelineOrchestrator.process_async`/`default_content_cb` 按 `external_id` 解析实体
   （upload.py 即传 external_id）。修复：适配层把内部 UUID 解析为 external_id 后再入管线
   （或统一实体解析约定，需 ADR 级决策）。
   同时暴露：`get_binding_by_account` 用 `scalar_one_or_none`，同一 hub_account_id 跨实体
   重复绑定时抛 `MultipleResultsFound`。
   **修复**：新增 `binding_store.get_entity_external_id`（内部 UUID → external_id 查询），
   `HubAdapter.handle_event` 与 `sources/tasks.py::_run_sync_all` 摄入前解析；binding 对应
   实体缺失时 fail-soft（`entity for binding not found` 错误，不崩溃）。`get_binding_by_account`
   改为取首个匹配并记 warning，不再抛 `MultipleResultsFound`。
5. **P1-2 `list_accounts` 对裸 JSON list 响应崩溃**（`emerald/sources/stackone.py:110`）
   真实 API 返回 `[]`（非 `{"data": []}`），`resp.get("data", ...)` 在 list 上调用 →
   AttributeError。**`/v1/sources/refresh` 以 500 崩溃**（路由级已复现）。
   无 happy-path 测试覆盖（现有测试仅覆盖 503 错误路径）。
   **修复**：先判 `isinstance(resp, list)` 直接取用，否则 `data`/`results` 键二选一；
   新增 `tests/sources/test_hub_client.py` 裸 list 与空 list 两个 happy-path 用例。
6. **P1-3 `sources.py` 用 stdlib logging 传 structlog kwargs**
   `logger.warning("hub_connect_session_failed", error=...)`（83 行）、
   `logger.info("hub_event_received", event_type=...)`（111–114 行）、
   `logger.warning("hub_list_accounts_failed", error=...)`（174 行）→ stdlib `_log()`
   TypeError。**connect/refresh 的 502 错误路径实际以 500 + 未处理异常崩溃**
   （FailHub 模拟已复现）；`info` 调用在 root logger 为 INFO 时同样崩溃
   （当前因 root 默认 WARNING 而静默跳过，属潜伏缺陷）。
   **修复**：路由 logger 改用 structlog；新增路由级用例（`_FailingHub`）
   断言 connect/refresh 的 hub 失败返回 502 而非 500。

### 外部阻塞（非 Emerald 代码）

7. **StackOne 账户缺 provider auth config**：`googledrive does not have any default auth config`
   → 真实 OAuth 链路无法完成，需在 StackOne 控制台配置 connector auth config 后复验
   （上轮会话已知，Pilot 验收的硬前提）。

---

## 4. 结论

**有条件通过（CONDITIONAL PASS）**：

- ✅ **通过**：单 key Basic 鉴权、connect session 端点、绑定落库与实体作用域、删除、
  去重状态持久化、webhook 验签（含篡改/缺失/fail-closed）、事件解析归一化、
  webhook 路由端到端、凭证安全（无凭证列、无泄露、恒定时间比较）。
- ❌ **未通过**：同步端到端（事件→摄入→管线→可检索）。根因是 P1-1（Pilot 缺陷）
  与 P0-1/P0-2（核心管线既有缺陷），叠加外部阻塞 B7（StackOne 侧配置）。

**解除 #7（T4b 自研连接器退役）阻塞的条件**：
1. 修复 P1-1（entity_id 约定）→ 事件驱动摄入能进入管线；
2. 修复 P0-1/P0-2/P0-3（管线链 + fast-lane + worker 循环）→ 内容可检索；
3. 复验 S1/S5/S6/S7 全绿；
4. StackOne 侧配置 provider auth config（外部，可与上述并行）。

P1-2/P1-3 不阻塞退役（refresh 路由与错误路径独立于自研连接器删除范围），但应在退役前
作为独立修复项排期。

---

## 5. 测试基线确认

- `tests/sources/` + `tests/connectors/`：**105 passed**（Pilot 相关全绿）。
- 全量：`796 passed, 42 failed, 23 skipped`。42 个失败与文档化基线一致，无新增失败：
  - issue #2 基线（Starlette 1.x 惰性路由枚举 + OpenAPI 漂移）：`test_route_completeness`×3、`test_openapi_drift`×2，同根因的 `test_no_internal_exposure`×2 —— 共 7 个
  - issue #3 基线（v2 路由过期测试 + /v1/files 旧分页签名）：`test_api_versioning`×3、`test_list_files`×7、`test_upload_authorization`(v2)×1 —— 共 11 个
  - 可选提取依赖缺失（faster_whisper / OCR / 图像预处理等，README 声明需 `.[extraction]`）：`test_audio_extractor`×4、`test_image_extractor`×4、`test_pdf_extractor`×5、`test_video_extractor`×2、`test_url_extractor`×1、`test_error_paths`×1 —— 共 17 个
  - 环境依赖 e2e（自研连接器 OAuth 测试需 Redis 初始化，T4b 退役范围内；docker image 测试需本地构建镜像）：`test_github_e2e`×3、`test_gdrive_e2e`×3、`test_production_image`×1 —— 共 7 个
- `git diff 6514c20...HEAD` 仅两个文档文件（本票零产品代码改动）。

---

## 附录：验证脚本与复现命令

脚本位于 `/tmp/emerald_verify/`（不入库）：
- `verify_live.py` — 真实凭据：Basic 鉴权、connect session、webhook 验签、DB 绑定/作用域/删除
- `verify_webhook_route.py` — 路由级 webhook（真实 client + 真实 DB）
- `verify_sync.py` — 同步路径（FakeHub 内容源 + 真实管线/worker）
- `verify_refresh_route.py` — `/v1/sources/refresh` 路由级复现 P1-2
- `verify_connect_502.py` — FailHub 复现 P1-3（502 路径 TypeError）
- `verify_chain_real.py` — P0 修复后真实 worker 全链复验（§6）
- `probe_*.py` — 辅助探针（entity 约定、fast-lane、日志级别）

复现环境：本地 PG（migration 008）+ Redis(6380) + Neo4j(docker) + Celery worker（prefork）。

---

## 6. P0 修复后真实 worker 复验（2026-08-10）

P0-1/P0-2/P0-3 修复后，用**真实 prefork worker**（concurrency=2，同一进程内多任务跨
事件循环交替执行）对异步摄入全链复验：

| 检查项 | 结果 | 证据 |
|---|---|---|
| 链完成（extract→chunk→embed→index→postprocess） | ✅ PASS | `pipeline_jobs.status = done`（此前止步于 extracting/TypeError） |
| worker 内 PG 状态写入（`_update_status`/`_update_fact_extraction_status`） | ✅ PASS | `memory_count=1, fact_extraction_status=success`（NullPool 修复） |
| fast-lane 落库（P0-2） | ✅ PASS | `fast_lane_chunks` 1 行，embedding 为 list（jsonb 往返正确） |
| 向量落库 | ✅ PASS | `embeddings` 1 行（1536 维，对齐 schema） |
| 图谱写入 | ✅ PASS | Neo4j `Memory` 节点 1 个（per-task driver 生命周期修复） |
| 跨 loop Redis（`ensure_redis_for_loop`） | ✅ PASS | 多任务交替（child 2 跑 extract+embed+postprocess）无 loop 冲突 |
| postprocess（关系推断+画像刷新+fast-lane 归档） | ✅ PASS | `relationship.infer.complete`，链正常 done，无静默降级 |

修复内容见 §3 P0 条目；新增测试 12 个（task 包装器×3、fast-lane DB 路径×2、worker 信号×3、
session factory×3、redis 生命周期×2，其中 1 个并入现有文件计数）。全量基线不变：
`808 passed / 42 failed`（42 与 §5 文档化基线逐项一致，无新增失败）。

**P0 全部关闭后**，解除 #7 的剩余条件为：P1-1/P1-2/P1-3 修复（Pilot 缺陷）+
StackOne 侧 auth config 配置（外部），然后复验同步路径 S1/S5/S6/S7。

---

## 7. P1 修复后复验（2026-08-10）

P1-1/P1-2/P1-3 修复后，以测试级复验（真实 StackOne 联调仍受外部 auth config
阻塞，见 §3 外部阻塞）：

| 检查项 | 结果 | 证据 |
|---|---|---|
| S1' 事件 → `handle_event` → 摄入（entity_id 约定） | ✅ PASS | `tests/sources/test_adapter.py::test_handle_event_resolves_internal_uuid_to_external_id`：binding 持内部 UUID 时，content sink 收到 external_id（`user_1`），摄入成功；`test_handle_event_unknown_entity_returns_error`：实体缺失 fail-soft |
| S8' 兜底同步任务（Celery Beat sweep）entity_id 约定 | ✅ PASS | `tests/sources/test_sync_tasks.py`：`_run_sync_all` 摄入前解析 external_id；缺失实体记 error 不中断 sweep |
| 重复绑定容错 | ✅ PASS | `tests/sources/test_binding_store.py`：同一 hub_account_id 双绑定返回首个，无 `MultipleResultsFound` |
| S1' 路由级（webhook → 摄入） | ✅ PASS | 既有 `test_webhook_accepts_valid_signature` 保持绿（entity_id 经 sink 捕获） |
| P1-2 refresh 裸 list | ✅ PASS | `tests/sources/test_hub_client.py`：裸 `[...]` 与空 `[]` 均正常解析 |
| P1-3 502 错误路径 | ✅ PASS | `tests/sources/test_routes.py::test_connect_hub_failure_returns_502_not_500`、`test_refresh_hub_failure_returns_502_not_500`：hub 失败返回 502，不再以 500 崩溃 |

**新增测试 10 个**（adapter×2、sync_tasks×2、binding_store×2、hub_client×2、routes×2）。
全量基线：`818 passed / 42 failed`（42 与 §5 文档化基线逐项一致，无新增失败）。

**P1 全部关闭后**，解除 #7 的剩余条件仅剩：StackOne 侧 provider auth config 配置
（外部，§3 外部阻塞）+ 真实账户端到端复验 S1/S5/S6/S7。
