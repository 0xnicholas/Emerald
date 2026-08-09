# 连接器外包给连接中心（StackOne 托管云起步）

v0.4.0 起 Emerald 自研连接器（`emerald/connectors/`，2,194 行：GitHub/Gmail/Google Drive/Notion 的 OAuth、凭证加密、webhook 接收与续期、Celery 定时同步）。2026-08-09 审视决定：**连接器不是核心生意，停止自写；改为接入统一连接中心 StackOne**，Emerald 只维护「数据源绑定」（授权关系 + 数据源身份）。

已确认的决策链：需求形状 = 战略聚焦/零维护（即使只有 4 个 provider 也迁）→ 部署形态 = 托管云起步（数据边界让步：连接器是可选渠道，不启用则不出域；适配器可替换，客户要求时再切 self-hosted——注意 StackOne self-hosted 仅限 Enterprise 计划）→ 同步模型 = webhook 事件驱动增量 + Celery Beat 定时兜底 → 旧代码 = Pilot 验证一个 provider 全链路后一次性删除。领域术语从「连接器（Connector）」改为「数据源绑定（Source Binding）」。

已否决：SaaS 长尾需求假设（实际需求是战略聚焦）；self-hosted 起步（与零维护目标冲突、成本不透明）；双轨并行（维护债不消）；立即全删（无退路）。本决策为功能三问 gate 的第四类：「成本削减/战略聚焦」——显式记录理由，不视为绕过 gate。
