# 数据源绑定架构（原连接器）

> **2026-08-09 决策（ADR-0004）**：连接器外包给连接中心 StackOne。本文档描述新架构；
> 旧的自研连接器（`emerald/connectors/`）在 Pilot 验证后删除。

---

## 1. 架构概览

```
┌──────────────────────────────────────────────────────┐
│                   连接中心（StackOne）                 │
│  OAuth 流程 / 凭证管理 / token 刷新 / webhook 续期      │
│  native + synthetic 事件 · 470+ 连接器（统一 API）      │
└──────────────┬───────────────────────┬───────────────┘
               │ webhook 事件（推送）     │ action RPC（按需拉内容）
               ▼                       ▼
┌──────────────────────────────────────────────────────┐
│                   Emerald 摄入适配层                   │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ 绑定管理      │  │ 事件接收器    │  │ HubAdapter │  │
│  │ (Source      │  │ (webhook     │  │ (统一拉取   │  │
│  │  Binding)    │  │  端点+签名)   │  │  映射为     │  │
│  │              │  │              │  │  Document) │  │
│  └──────────────┘  └──────────────┘  └────────────┘  │
│                                                      │
│  Celery Beat 定时兜底同步（防丢事件）                    │
└──────────────────────────┬───────────────────────────┘
                           ▼
                    Emerald 处理管线
                 （提取 → 分块 → 嵌入 → 图谱）
```

## 2. 职责划分

| 职责 | 归属 |
|---|---|
| OAuth 授权流程、凭证存储与加密、token 刷新 | 连接中心（StackOne） |
| provider 差异抹平（统一 API / 数据模型） | 连接中心（StackOne） |
| webhook 注册、续期、重试、日志 | 连接中心（StackOne） |
| 数据源绑定（授权关系 + 数据源身份） | Emerald（新概念，见 CONTEXT.md） |
| 事件接收（webhook 端点 + 签名验证） | Emerald |
| 内容拉取与映射（action 结果 → Document → 管线） | Emerald（HubAdapter） |
| 增量去重、兜底同步调度 | Emerald |

## 3. 同步语义

- **事件驱动**：StackOne webhook 推送变更事件（native + synthetic）→ Emerald 事件接收器 → HubAdapter 拉取变更内容 → 进管线
- **定时兜底**：Celery Beat 定期全量/增量核对，防丢事件
- **初始全量**：首次绑定后触发一次全量拉取

## 4. 部署形态

- 当前：StackOne 托管云（Starter 免费额度起步）。数据边界让步：连接器是可选渠道，不启用则无数据出域
- 未来：客户要求时切换 self-hosted（StackOne Enterprise 计划），适配器层可替换

## 5. 迁移计划

1. Pilot：实现 HubAdapter + 绑定管理 + 事件接收，选一个 provider（Drive 或 Notion）跑通全链路
2. 验证通过后：删除 `emerald/connectors/`（2,194 行）及对应测试、路由、`.coveragerc` omit 条目
3. `/v1/connectors/*` API 语义迁移为数据源绑定管理（connect session → 绑定记录）
