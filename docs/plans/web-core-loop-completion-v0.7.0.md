# Web 核心循环补全计划（v0.7.0）

> **定位**：Wayfinder 图 #46「Web 核心循环审计与补全计划」的目的地交付物。差距判定 = 现状事实清单（白盒）× 标尺（黑盒验收单）的交叉结论；本计划即「可直接执行」的补全范围，补全成果随 v0.7.0 与 B3-B6 同发。执行不在本图内（另行 handoff）。
>
> **输入**：
> - 现状事实清单：`docs/verification/web-core-loop-audit-2026-08-15.md`（分支 `research/web-core-loop-audit`，issue #48）
> - 审计标尺：`docs/web-core-loop-standard.md`（issue #47，v0.7.0 起 web 侧发布门）
> - 接缝决议：issue #49（核心四走 TS SDK `@emerald/sdk`；EmeraldClient 瘦身 REST-only；chat LLM 走 web 侧代理；鉴权维持 localStorage key + Bearer；Server URL 同源默认）
>
> **日期**：2026-08-15（issue #50，grilling 决议 Q1-Q4）

---

## 1. 差距判定表（条款 × 判定）

| 条款 | 判定 | 依据（file:line 见事实清单） |
|---|---|---|
| I1 快速笔记 | 🟡 修复 | 落库真实（`addMemory`，dashboard-view.tsx:376）；但保存后失效的 query key 为 `["search-demo"]`，hook 实际 key 为 `["search"]`（dashboard-view.tsx:379 vs use-search-memories.ts:23）→「最近保存」不即时刷新 |
| I2 弹窗 Note | 🔴 补全 | 4 个渲染点均未传 `onAdd` → 假保存（add-memory-modal.tsx:97-101） |
| I3 弹窗 Link | 🔴 补全 | 同上；`extract-url` 仅预览，保存路径死 |
| I4 弹窗 File | 🔴 补全 | EmeraldClient 无 upload 方法；引擎 `POST /v1/upload`（202 + pipeline_id）未被 web 引用 |
| I5 诚实反馈 | 🔴 补全 | 三 tab 均弹「Memory saved!」后关闭，不落库 |
| S1 三态 | 🟡 随 I4 | memory 态 ✅；rag/hybrid 态无内容来源——web 唯一 RAG 摄入入口是 I4 |
| S2 Spaces 过滤 | 🟢 达标 | `container_tag` 过滤已实现（memories/page.tsx:117-119） |
| S3 摄入→可搜 | 🟡 随 I2-I4 | 引擎管线（排队→提取→分块→嵌入→索引）异步完成后可语义命中；黑盒可过，前提是摄入入口真实 |
| P1 画像可见 | 🟢 达标 | StatFactsCard + stats 卡片 |
| P2 画像新鲜度 | 🟢 达标 | 引擎 ingest 时失效画像缓存（engine.py:236）；web 侧 react-query staleTime 10s |
| P3 画像注入对话 | 🔴 补全 | 死 route 的 system prompt 只注 memories 不注 profile（app/api/chat/route.ts:41-54）；随 C 环盘活一并落地 |
| C1 真 LLM | 🔴 补全 | `formatMemoryResponse` 模板回复；`/api/chat` route 全仓 0 前端调用 |
| C2 流式 | 🔴 补全 | route 已 `stream:true`，前端无消费 |
| C3 无 key 降级 | 🔴 补全 | route 有降级文案但无显式降级态标记，UI 不标识 |
| C4 模型选择器 | 🔴 补全 | 纯装饰（chat-interface.tsx:124-135）；route 已接受 `model` 参数 |
| H1 同源 | 🔴 补全 | baseUrl 硬编码 `http://localhost:8000`（api.ts:308-315）；`NEXT_PUBLIC_EMERALD_API_URL` 0 处读取；**且 compose 发布 10 个端口，违反「仅 :80 对外」** |
| H2 生产构建 | 🔴 补全 | compose `target: development` + `npm run dev`；Dockerfile standalone runner 阶段闲置 |
| H3 key 获取 | 🟢 达标 | Settings 文档化 `docker exec emerald-api python scripts/seed_dev_api_key.py` |

## 2. 范围决议（Q1-Q4）

- **Q1 零降级**：I4 与 C 环（含 P3）全部进 v0.7.0，标尺条款不折损。理由：I4 一项解锁 I4/S1-rag/I5 三条款且是 S 环 rag 态唯一内容来源；C 环不做则「对话环完成 = 真 LLM 回答 + 显式降级」为空文，四环闭环名不副实。
- **Q2 S 环无独立补全项**：S1-memory/S2/S3 引擎侧已达标；S 环红色部分全部由 I4 解锁。I1 的 key 错位为 trivial 内含修复。标尺外项判定见 §4。
- **Q3 H 组落地**：① 端口收敛——全部服务改绑 `127.0.0.1:`（本机调试保留），`3000` 随 H2 取消发布，**仅 80 对外**；② 登录页 Server URL **保留字段、空值=同源相对路径**（显式填远端是合法拓扑，非违规）；③ compose 默认切生产，加显式 `docker-compose.dev.yml` override 恢复 dev 工作流。②③ 预答 #51 的 H1/H2 设计题。
- **Q4 分批与门票**：三批执行（§3）；v0.7.0 发布门清单票待 #51 完成后一并毕业（门清单引用 #51 锁定的验收反馈形态，避免返工）。

## 3. 补全项分批（进 v0.7.0）

### 批 1：H 基建（先行——验收环境必须先真实）

| # | 项 | 覆盖 | 要点 |
|---|---|---|---|
| H-1 | 端口收敛 | H1 | postgres/neo4j/redis/minio/api/mcp 改绑 `127.0.0.1:`；frontend 3000 取消发布（nginx 内部代理）；仅 nginx 80 对外 |
| H-2 | 同源默认 | H1 | `getClient()` baseUrl 默认改相对路径（空 = 同源）；登录页 Server URL 空值走相对；localStorage 覆盖保留 |
| H-3 | 生产构建 | H2 | compose `target: runner`，去 `command`/bind mounts；新增 `docker-compose.dev.yml`（显式 `-f` 叠加恢复 dev） |
| H-4 | 依赖卫生 | — | 移除 `@supermemory/memory-graph`（声明未使用，0 import） |

### 批 2：I 摄入

| # | 项 | 覆盖 | 要点 |
|---|---|---|---|
| I-1 | 弹窗三 tab 真实落库 | I2/I3/I5 | 4 个渲染点接线保存；Note 直存文本；Link/File 保存语义与降级路径 → #51 设计 |
| I-2 | File 上传接线 | I4、S1-rag、I5 | `@emerald/sdk`（`sdk/typescript`，已存在）`upload` 方法：multipart → 202 + pipeline_id；管线完成反馈（toast vs `getPipelineStatus` 轮询）→ #51 设计 |
| I-3 | 修复失效 key | I1 | `["search-demo"]` → `["search"]`（一行） |

### 批 3：C 对话（含 P3）

| # | 项 | 覆盖 | 要点 |
|---|---|---|---|
| C-1 | 盘活 `/api/chat` | C1/C2 | 前端 `handleSend` 从 `formatMemoryResponse` 模板改为调 route + 流式消费（SSE）；检索记忆随请求注入（现状 topK:8 hybrid 保留） |
| C-2 | 模型选择器接线 | C4 | 所选 model 随请求发送（route 已接受）；或删选择器——取向 → #51 |
| C-3 | 无 key 显式降级 | C3 | route 返回结构化降级标记（非仅文案）；UI 显式标识降级态；降级 UX 形态 → #51 |
| C-4 | 画像注入 system prompt | P3 | route 的 system prompt 注入 `getProfile` 静态事实（引擎原则 5 的 web 落地）；注入格式 → #51 |

每项执行时携带：差距依据（§1 file:line，经事实清单）、验收条款映射（标尺）、设计决议（#51 并入后）。

## 4. 出图项（显式记录，不进 v0.7.0）

| 项 | 事实 | 处置 |
|---|---|---|
| type/tag 客户端过滤 | 只过滤已返回 top-50，非服务端过滤 | 出图记录（标尺明示不含；行为诚实仅浅） |
| @提及搜索 | 走普通 memory 搜索，未用 B4 `search(about=)` 实体中心检索 | 出图，未来单独立票（引擎能力已交付，纯接线） |
| 命令面板搜索 | 可用 | 出图记录，无动作 |
| `"default"` 哨兵 vs ADR-0002 | 行为合规（default = 无过滤 = 全池），仅字面量张力 | 记债出图（无用户可见损害） |
| Settings JSON 导出 | `search("", topK:500)` 客户端拼接，未经 memory.md 端点 | 出图记录（标尺无导出条款） |
| v0.7.0 发布门清单票 | 引擎 B3-B6 门 + web 门 | 待 #51 后毕业（Q4 决议） |

## 5. 遗留设计题 → #51 净表

| # | 题 | 备注 |
|---|---|---|
| D1 | I2/I3 保存语义：Link 存什么（预览抽取结果 vs 原文 vs URL+摘要）；Note 的 contentType | 弹窗三 tab 共用保存路径 |
| D2 | I4 反馈形态：toast「处理中」 vs pipeline_id 轮询显式状态 | I5 诚实反馈范围 |
| D3 | chat key 来源：env（route 现状 `OPENAI_API_KEY`）vs web 设置页 | C3 联动 |
| D4 | C3 降级 UX 形态 + C4 模型选择器接线 or 移除 | 标尺 C4 二选一 |
| D5 | P3 注入格式：profile 静态事实如何进 system prompt（截断策略、字段选择） | 引擎原则 5 落地 |
| — | H1/H2 两题已由 #50 Q3 预答（相对路径 + runner/standalone + dev override） | 从 #51 净表划去 |
