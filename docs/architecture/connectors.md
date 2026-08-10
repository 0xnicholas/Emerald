# 数据源绑定架构（原连接器）

> **2026-08-09 决策（ADR-0004）**：连接器外包给连接中心。**2026-08-10 更新（issue #6）**：
> 连接中心实现从 StackOne 改为 **Totem**（同团队内部项目，`../totem`；契约见 Totem
> `docs/standards/consumption-standard.md`）。本文档描述新架构；旧的自研连接器
> （`emerald/connectors/`）在 Pilot 验证后删除（issue #7）。

---

## 1. 架构概览

> 连接中心是抽象概念：Totem 是当前实现（ADR-0004），可替换。Emerald 所有接入代码只依赖 `ConnectionHub` 接口。

```
┌──────────────────────────────────────────────────────┐
│              连接中心（Connection Hub）                │
│  当前实现：Totem（内部自托管动作层）· 可替换（抽象接口隔离） │
│  v1 upstream：Feishu Docs · OAuth/凭证/token 刷新/审计  │
│  MCP + REST Actions RPC（{action, args}，Bearer +     │
│  x-connection-id，allowlist 强制，七码错误，{data,next}）│
└──────────────┬───────────────────────┬───────────────┘
               │ 事件（v1：Emerald 直连    │ action RPC（按需拉内容）
               │ 上游订阅，只当「铃铛」）   ▼
               ▼                       ┌───────────────────────────────┐
┌──────────────────────────────────────│        Emerald 摄入适配层       │
│          Emerald 事件接收器           │                               │
│  （自有订阅 + 标准 §8 验签/归一化）     │  ┌─────────────┐ ┌──────────┐  │
│  记录/入队，不直接读写飞书             │  │ 绑定管理     │ │HubAdapter│  │
│                                     │  │ (Source     │ │(统一拉取  │  │
│                                     │  │  Binding)   │ │ 映射为    │  │
│                                     │  │             │ │ Document)│  │
│                                     │  └─────────────┘ └──────────┘  │
│                                     │                               │
│                                     │  Celery Beat 定时兜底同步（防漏） │
└──────────────────────────────────────┴───────────────────────────────┘
                           ▼
                    Emerald 处理管线
                 （提取 → 分块 → 嵌入 → 图谱）
```

## 2. 职责划分

| 职责 | 归属 |
|---|---|
| OAuth 授权流程、凭证存储与加密、token 刷新 | 连接中心（Totem；每 connection 一个授权飞书账号） |
| 动作注册表、参数校验、执行边界、审计 | 连接中心（Totem；allowlist fail-closed，全量审计） |
| provider 差异抹平（统一动作/数据模型） | 连接中心（Totem；v1 upstream = Feishu Docs） |
| webhook 订阅（v1 直连上游，只当「铃铛」） | Emerald（v2 平台投递后换入口，Totem ADR-0011 / 标准 §8） |
| 事件接收（验签 + 归一化为标准 §8.2 负载） | Emerald（标准 §8.3 签名契约已按 v2 契约实现） |
| 数据源绑定（授权关系 + 数据源身份） | Emerald（新概念，见 CONTEXT.md） |
| 内容拉取与映射（action 结果 → Document → 管线） | Emerald（HubAdapter） |
| 增量去重、兜底同步调度 | Emerald |

## 3. 同步语义

- **事件驱动**：v1 订阅留在 Emerald 侧——上游事件到 `/v1/sources/webhook`（「铃铛」：记录 + 入队），事件触发的飞书读写全部经 Totem action（Totem ADR-0011）；v2 平台投递落地后，事件入口换成平台 webhook，处理层零改动
- **定时兜底**：Celery Beat 定期经 Totem RPC 增量扫描（`search_docs` + 本地 seen 水位）→ 防漏事件；429 按 `retryAfterSeconds` 退避
- **初始全量**：首次绑定后触发一次拉取（宽查询 + doc_id 去重）

## 4. 部署形态

- 当前：Totem 自托管（同团队内部部署，`TOTEM_URL`/`TOTEM_API_KEY`/`TOTEM_ADMIN_KEY`/`TOTEM_TENANT_ID`）。数据不出域；无外部账户/连接器配置阻塞
- 绑定生命周期用 admin-scope key（oauth/start + connections 列表；等价平台管理员，Totem ADR-0010 全信任模型）；日常 RPC 一律 actions-scope key

## 5. 迁移计划

1. ~~Pilot：实现 HubAdapter + 绑定管理 + 事件接收，选一个 provider 跑通全链路~~ **已重做（2026-08-10，issue #6）**：接入目标从 StackOne 改为 **Totem**；Pilot 验证记录见 [Totem Pilot 验证记录](../verification/totem-pilot-verification.md)（真实 Totem + mock Feishu 上游，25/25 检查通过）。旧 [StackOne Pilot 验证记录](../verification/stackone-pilot-verification.md) 保留为历史
2. ~~验证结论：有条件通过~~ 已由 Totem Pilot 取代（2026-08-10 决策：不再考虑接入 StackOne，其外部阻塞与账号配置问题一并消除）
3. 验证通过后：删除 `emerald/connectors/`（2,194 行）及对应测试、路由、`.coveragerc` omit 条目（T4b，issue #7，与 Totem 接入时间点绑定）
4. `/v1/connectors/*` API 语义迁移为数据源绑定管理（connect session → 绑定记录）
