# Totem Pilot 验证记录（issue #6，ADR-0004）

> 验证日期：2026-08-10 · 验证对象：**当前 Totem 源码**（commit `cdd962a`，含 admin API/OpenAPI 面）
> + **当前 Emerald 源码**（本票改动：`TotemHubClient` 替换 `StackOneHubClient`）
> 结论：**通过（PASS，25/25）**——绑定、同步、Webhook 契约、真实管线全链路验证通过。
>
> **本票内容**：接入目标从 StackOne 改为 Totem（同团队内部项目，功能对齐 StackOne，ADR-0004
> 更新）；实现 `TotemHubClient`（`emerald/sources/totem.py`，删除 `stackone.py`）、适配层
> feishu provider profile、事件归一化（标准 §8.2）；并完成 Pilot 验证。
>
> 验证方式：**真实 Totem 服务 + mock Feishu 上游**（Totem 自带 `MockFeishuServer`，仅替换
> 飞书 HTTP 往返；OAuth 授权流、token 交换、动作执行、审计全部为 Totem 真实代码）。
> 管线侧：真实 PG/Redis/Neo4j + 真实 Celery worker（prefork）。**不再依赖任何 StackOne 账户**。

---

## 1. 验证范围与方法

| 路径 | 方法 | 真实 / mock |
|---|---|---|
| 绑定（tenant/key/creds/oauth/allowlist） | 真实 Totem admin API + 真实 PG（totem） | **真实**（dev key，全信任模型 ADR-0010） |
| OAuth 授权流（authorize → callback → connection） | 真实 Totem flow 代码 | **部分 mock**（飞书上游 = MockFeishuServer，理由见下） |
| 同步（search_docs → get_doc_content → 管线 → 可检索） | 真实 Totem RPC + 真实 HubAdapter + 真实管线/Celery worker | **部分 mock**（同上；内容源为 mock 飞书文档） |
| Webhook 契约（§8.3 验签 + §8.2 归一化） | 真实 `TotemHubClient.verify_webhook`/`parse_event` | 本地构造签名（契约级） |
| 凭证安全 | 代码审计 + 契约核对 | — |

**mock 替代与理由**：真实飞书账号需要企业自建应用 + 真人授权，非本票可自证。
MockFeishuServer 是 Totem 仓库自带的 Seam B（T6/T7 测试即用同一 mock），OAuth 页/回调/
token 交换/文件搜索/内容读取均为标准 HTTP 语义，不改变 Totem 的治理/执行/审计行为。

本地环境：Totem pilot 服务（`src/server/compose.ts`，端口 3001，同一 docker PG）+ mock
Feishu（3999）；Emerald：PG（Postgres.app，migration 已应用）+ Redis(6379) + Neo4j(docker) +
Celery worker（真实进程，prefork concurrency=2）。

## 2. 验证结果明细

### 2.1 绑定路径（真实 admin API + 真实 DB）— ✅ 通过

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| B1 | 创建 tenant（emerald） | ✅ PASS | `POST /admin/tenants` → 201，tenant id 落库 |
| B2 | 创建 actions-scope key | ✅ PASS | `POST /admin/tenants/{id}/keys {scope: actions}` → 201，返回 `tt_dev_*` key（仅此一次） |
| B3 | 注册飞书 App Credentials | ✅ PASS | `POST /admin/tenants/{id}/feishu-creds` → `{ok: true}`（secret 加密存储，Totem ADR-0004/issue #15） |
| B4 | oauth/start 返回授权 URL | ✅ PASS | `{authorizationUrl}` 指向 mock 飞书 authorize 页 |
| B5 | 授权页重定向（302 + code/state） | ✅ PASS | mock 302 → `http://localhost:3001/oauth/callback/feishu?code=...&state=...` |
| B6 | OAuth 回调创建 connection | ✅ PASS | 真实 flow：code 交换 → connection 落库 → 200「Authorization complete」 |
| B7 | connection 可见 | ✅ PASS | `GET /admin/tenants/{id}/connections` → 1 connection |
| B8 | allowlist 设置（只读动作） | ✅ PASS | `search_docs get_doc_content get_doc_metadata test_connection` → `{ok: true}` |

### 2.2 同步路径（真实 Totem RPC + 真实管线）— ✅ 通过

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| S1 | `create_connect_session`（admin 面） | ✅ PASS | 返回 authorizationUrl；session id = tenant id（Totem 无 session token，ADR-0007 单跳转） |
| S2 | `list_accounts`（admin 面） | ✅ PASS | connections → HubAccount（id = connection id，provider = feishu） |
| S3 | `search_docs` 列表 envelope | ✅ PASS | `{data: [2 items], next: null}`（标准 §7）；doc_id/title/doc_type 完整 |
| S4 | `get_doc_content` 内容拉取 | ✅ PASS | 按 `doc_id` 返回正文（markdown 风格标题保留） |
| P1 | 实体落库 | ✅ PASS | `entities` 行（external_id = totem-pilot-*） |
| P2 | 绑定落库 | ✅ PASS | `source_bindings` 行（hub_account_id = connection id） |
| P3 | 真实管线摄入（search→fetch→extract→chunk→embed→index→postprocess） | ✅ PASS | ingested=2 failed=0；`graph.memory.created` ×2、`relationship.infer.complete`（各 1 关系） |
| P4 | 去重重扫（v1 无版本字段 → 按 doc_id 水位） | ✅ PASS | 重扫 ingested=0 skipped=2（seen 持久化生效） |
| P5 | 管线链完成 | ✅ PASS | `pipeline_jobs.status = done` ×2，memory_count=1，fact_extraction_status=success |
| P6 | fast-lane 即时可检索 | ✅ PASS | `fast_lane_chunks` 4 行（本实体；1536 维 jsonb） |
| P7 | 向量落库 | ✅ PASS | `embeddings` 2 行（1536 维 pgvector） |
| P8 | 图谱写入 | ✅ PASS | Neo4j `Memory` 节点 2 个（per-task driver 生命周期正常） |
| A1 | Totem 审计可见 | ✅ PASS | `GET /admin/tenants/{id}/audit?action=search_docs` → 3 行（S3+P3+P4 每次 RPC 全量审计） |

### 2.3 Webhook 契约（标准 §8，预记录 v2 契约）— ✅ 通过

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| W1 | 有效签名接受 | ✅ PASS | HMAC-SHA256（raw body, base64url）`x-totem-signature` → True（常量时间比较） |
| W2 | 篡改 body 拒绝 | ✅ PASS | 签名不匹配 → False |
| W3 | `parse_event` §8.2 归一化 | ✅ PASS | `{event, tenant_id, connection_id, record_type, record_id, provider}` → HubEvent（event_type/account_id/origin_owner_id 正确映射） |

> v1 说明：Totem v1 无 webhook 投递面（ADR-0011），事件订阅留在 Emerald 侧（上游事件 →
> `/v1/sources/webhook` 铃铛 → 归一化 §8.2 → 入队 → 经 Totem action 读写）；本票按标准 §8
> 契约实现验签与负载形状，v2 平台投递落地后只换入口。

### 2.4 凭证安全 — ✅ 通过（契约核对）

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| C1 | `source_bindings` 无任何凭证列 | ✅ PASS | 列集合不变（entity_id/provider/hub_account_id/sync_status/last_synced_at/error_message/sync_metadata/…） |
| C1b | 「密钥仅存加密形式」承诺的归属 | ✅ PASS | Emerald 侧为零真（vacuous）：凭证存储/加密/token 刷新是连接中心契约职责（ADR-0004 §2），Totem 侧加密存储（master key 派生每租户密钥）不在本票验证范围 |
| C2 | key 分工 | ✅ PASS | actions-scope key 只用于 `POST /actions/rpc`；admin-scope key 仅绑定生命周期两调用（oauth/start、connections），不用于日常 RPC（Totem ADR-0010 全信任模型红线） |
| C3 | 响应不泄露密钥 | ✅ PASS | connect 仅返回 authorizationUrl；审计查询返回动作名/状态/耗时，无 token |
| C4 | 签名比较恒定时间 | ✅ PASS | `hmac.compare_digest` |

## 3. 遗留问题清单

1. **v1 扫描原语局限（非缺陷，已文档化）**：Totem v1 无 list-all 动作，`search_docs`（标题
   搜索）是唯一扫描原语，且输出无版本字段。适配层按 doc_id 水位去重（无版本 → 重复内容
   不重扫）；宽查询 `" "` 通过 schema（minLength 1）但命中面有限。生产策略待定：v2 列表
   cursor 落地后（标准 §7）或连接器事件投递后（标准 §8/ADR-0011）可补齐全量扫描。
2. **`process_async` 提交进程需 import `emerald.pipeline.celery`（本票顺带修复）**：任何直接
   调用 `PipelineOrchestrator.process_async` 的进程（如脚本）若不 import 配置了 redis broker
   的 celery app，`shared_task` 会解析到 celery 默认 app（amqp://guest@localhost:5672）导致
   提交失败。API lifespan 的 `instrument_all()` 恰好覆盖了 API 进程；本票在
   `orchestrator.py` 显式 import（防御性，P0-3 同族）。
3. **真实飞书账户端到端（外部，非阻塞）**：真实企业飞书账号 + 真人授权的最终确认未做；
   由 mock Feishu 上游 + 真实 Totem 治理链替代（与 StackOne 期 mock 基准同构）。Totem
   v2 支持多上游/平台投递后复验。

## 4. 结论

**通过（PASS，25/25）**：

- ✅ 绑定全链路（tenant/key/creds/oauth/connection/allowlist，真实 admin API + 真实 DB）
- ✅ 同步全链路（真实 Totem RPC + 真实 HubAdapter + 真实管线/worker + 去重 + 图谱 + 审计）
- ✅ Webhook 契约（标准 §8.3 验签 + §8.2 归一化，v2 迁移入口就位）
- ✅ 凭证安全（无凭证列、key 分工、无泄露、恒定时间比较）
- ✅ 不再依赖 StackOne：无外部账户、无连接器配置阻塞、无数据出域

**解除 #7（T4b 自研连接器退役）阻塞的条件**：本 Pilot 通过后，删除 `emerald/connectors/`
（2,194 行）及其测试/路由/`.coveragerc` omit 条目的条件已满足（与 Totem 接入时间点绑定，
见 roadmap）。

## 5. 测试基线确认

- `tests/sources/`：**46 passed**（Totem 契约：RPC envelope/Bearer/x-connection-id、七码错误
  映射、list envelope、admin 端点、§8 webhook、feishu 适配层）。
- 全量（`pytest tests/ --ignore=tests/mcp`）：**924 passed / 24 failed / 24 skipped**。
  24 个失败与文档化基线逐项一致，无新增失败：
  - 可选提取依赖缺失（faster_whisper / OCR / 图像预处理等，README 声明需 `.[extraction]`）：
    audio×4、image×4、pdf×5、video×2、url×1、error_paths×1 —— 17 个
  - 环境依赖 e2e（自研连接器 OAuth 测试需 Redis 初始化，T4b 退役范围内；docker image 测试需
    本地构建镜像）：github_e2e×3、gdrive_e2e×3、production_image×1 —— 7 个
  （issue #2/#3 的路由/版本化基线 18 项已在先前提交修复，不再计入。）
- OpenAPI 规范已重新生成（`docs/api/openapi.yaml`，provider 描述更新）。

## 附录：验证脚本与复现命令

脚本位于 `/tmp/totem-pilot/`（不入库）：
- `serve.mts` — 启动当前 Totem 源码（:3001，同一 docker PG）+ MockFeishuServer（:3999，seed
  2 篇文档）；`npx tsx serve.mts`（脚本曾临时置于 totem 仓库根，已删除）
- `pilot.py` — 全部 25 项检查：onboarding → hub 契约 → 真实管线摄入 → 产物/审计验证；
  `.venv/bin/python pilot.py`

复现环境：totem 的 docker PG（5433）+ Emerald 本地 PG（5432）+ Redis(6379) + Neo4j(docker) +
Celery worker（prefork, concurrency=2）。

> 注意：pilot 每次运行创建一个新 tenant/connection（dev 库，可重复）。admin key 为
> Totem compose 默认 dev 占位 key（`tt_dev_admin_change_me`），仅限本地。
