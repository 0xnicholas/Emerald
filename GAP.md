# GAP.md — 与 Supermemory 的对照差距清单

> **定位**：这是 Emerald 与参照系（Supermemory）对照的**差距清单的唯一权威文件**（AGENTS.md 引用）。
> - `docs/comparison-supermemory.md` 是**深度对照文档**（能力逐项对比、历史叙事），本文件只保留结论性的差距条目。
> - `docs/roadmap.md` 是**计划**（主题/工作项/依赖），本文件不做进度追踪。
> - 参照系声明（AGENTS.md）：Supermemory 自称在 LongMemEval、LoCoMo、ConvoMem 三项基准上最优（未经本仓库验证，Emerald 不背书）。Emerald 的度量体系独立于参照系，见 `docs/adr/0001`。
> - **差距清单不是进度指标**：新投入须独立辩护（功能三问 gate），不得以「Supermemory 有」为理由。

**更新日期**：2026-08-14（B5 交付后 + B6 立项 ADR-0006）。依据：`docs/comparison-supermemory.md`（2026-06-21 v2 + 08-14 增补）、`docs/roadmap.md`。

---

## 一、已完成闭合的差距

| 差距 | 闭合方式 | 依据 |
|---|---|---|
| 事实提取（多事实分解/类型分类/置信度/摘要） | ✅ LLM 驱动（DeepSeek 优先，OpenAI 降级），M1/M2 | comparison §1 |
| 关系推断 LLM-first | ✅ LLM-first + bigram 预滤 + 规则降级（2026-06） | comparison §10 P2 |
| 图谱搜索遍历 | ✅ 从 depth=1 扩展到多跳图谱推理（B4，issue #29–#35）：`about=` 实体中心检索 + 共享主体桥 + UPDATES/EXTENDS/DERIVES_FROM 双向链式（depth ≤ 4）+ 路径透明 + 历史标记 | comparison §2（08-14 增补） |
| NER 实体抽取层 | ✅ B3（issue #21–#28）：提及（Mention）图节点（ADR-0005），跨表层解析，实体隔离，遗忘/更新集成 | comparison §1.3、§10 P2 |
| 高级遗忘策略（B5） | ✅ 社区检测 + 活性评分决策 + forget_communities 策略 + 确定性质量套件（issue #36–#40，2026-08-14） | roadmap 主题 B |
| Cross-encoder 重排序 | ✅ 三级降级链（M2） | roadmap 未解决项 |
| TypeScript SDK v1 | ✅ M2（`sdk/typescript/`，对齐 Python SDK） | comparison §10 P1 |
| v2 API 实质改进 | ✅ M2：分页/限流/错误码在 v1 落地，v2 别名下线 | comparison §10 P1 |
| 本地嵌入 | ✅ fastembed（ONNX，无 PyTorch）——Emerald 优势 | comparison 总览 |
| 双写一致性 | ✅ ReconciliationEngine | comparison 总览 |
| 真实嵌入绝对分报告 | 🟡 **部分**：bge-m3 已发布（7/7，Aggregate 0.943）；第二模型对照待补 | comparison §10 P0 |

## 二、待做差距（阻塞采用 / 生产部署）

| 优先级 | 差距 | 状态 | 依据 |
|---|---|---|---|
| **P1** | 框架集成生态（仅 Pandaria） | ⚪ 2026-08-23 决议：LangChain.js（C2）取消，框架集成全部待真实用户信号再启动 | comparison §10 P1、roadmap 未解决项 |
| **P1** | 第二模型嵌入对照（text-embedding-3-large 等） | 🟡 需真实 API 可达；D1 小尾巴 | comparison §10 P0 |
| **P1** | 负载测试验证（Locust 基础设施已有，压测验证待 D2/D3） | 🟡 依赖 k8s 实操验证（A2） | production-readiness §5 |
| **P2** | 记忆整合（近重复活跃事实无损收敛，B6） | 🟡 已立项（ADR-0006，2026-08-14；spec 见 issue #41） | roadmap 主题 B |
| **P2** | 细粒度实体链接（提及 ↔ 外部知识库 ID，如 Wikidata） | ⚪ 未启动；B3 定界：跨实体提及合并永久 out | comparison §1.3 |
| **P2** | 正式安全审计 | 🟡 M2 部分完成（0 P0/P1）；M5 计划中 | production-readiness §7 |
| **P3** | API 文档 overhaul 余项（教程、SDK 对照示例——A5 范围） | 🟡 OpenAPI 自动化 ✅；教程与对照待 A5（原依赖 C2，2026-08-23 解除） | production-readiness §10 |

## 三、延后（有用户信号再启动）

| 差距 | 延后原因 |
|---|---|
| Vercel AI SDK / Mastra 集成 | M3 精简决议（2026-08-13）：零用户时的生态投资赌注，待信号 |
| Java SDK / Go SDK | 按需启动（开放决策） |
| CrewAI / n8n 等长尾生态 | 长期生态建设 |
| 消费者产品（Web App / 浏览器插件 / Raycast） | 定位不同（B2B vs B2C），非差距——ADR-0003：web UI 是产品层，不在基础设施对比范围 |
