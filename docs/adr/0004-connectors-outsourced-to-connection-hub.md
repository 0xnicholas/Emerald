# 连接器外包给连接中心（Totem 内部动作层）

v0.4.0 起 Emerald 自研连接器（`emerald/connectors/`，2,194 行：GitHub/Gmail/Google Drive/Notion 的 OAuth、凭证加密、webhook 接收与续期、Celery 定时同步）。2026-08-09 审视决定：**连接器不是核心生意，停止自写；改为接入统一连接中心**，Emerald 只维护「数据源绑定」（授权关系 + 数据源身份）。

2026-08-10 决策更新（issue #6）：**连接中心从 StackOne（外部托管云）改为 Totem（同团队内部项目，`../totem`）**。Totem 是自托管多租户动作层：schema-first 动作 + MCP/REST 双消费面 + 每连接 allowlist + 全量审计，v1 upstream 为 Feishu Docs，功能与 StackOne 对齐（认证 Bearer + `x-connection-id`、`{action, args}` RPC、七码错误、`{data, next}` 列表、预记录的 webhook 契约——见 Totem `docs/standards/consumption-standard.md`）。**不再考虑接入 StackOne**（外部账户/连接器配置阻塞、数据出域、零维护目标不如内部自托管）。

已确认的决策链（2026-08-09 基线 + 08-10 更新）：

- 需求形状 = 战略聚焦/零维护（即使只有 4 个 provider 也迁）→ **部署形态 = 内部自托管 Totem**（同团队运营；数据不出域；无外部依赖；替代原「StackOne 托管云起步」）
- 同步模型 = **不变**：webhook 事件驱动（v1 订阅留在 Emerald 侧，直连上游事件只当「铃铛」，见 Totem ADR-0011）+ Celery Beat 定时兜底（经 Totem action 拉取）。Totem v1 无 webhook 投递面，v2 平台投递落地后换入口、处理层零改动（标准 §8）
- 旧代码 = Pilot 验证一个 provider 全链路后一次性删除（issue #7，与 Totem 接入时间点绑定）
- 领域术语从「连接器（Connector）」改为「数据源绑定（Source Binding）」

已否决：SaaS 长尾需求假设（实际需求是战略聚焦）；外部托管云（数据边界与外部阻塞）；双轨并行（维护债不消）；立即全删（无退路）。本决策为功能三问 gate 的第四类：「成本削减/战略聚焦」——显式记录理由，不视为绕过 gate。

**实体映射（pilot）**：一个 Totem tenant 对应一个 Emerald 部署（`TOTEM_TENANT_ID`）；实体的已授权账号 = tenant 内的 connection（`hub_account_id` = connection id）。Totem 无 origin_owner 层级（内部平台，租户即项目，见 Totem CONTEXT.md）。
