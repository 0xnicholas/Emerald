# 开发计划：将 MEMANTO 借鉴点落地到 Emerald

> **目标**：吸收 MEMANTO 实验验证的工程洞察（大 k 召回、即时可检索、信任模型），同时坚守 Emerald 的图谱优先、全自动、时序完整性原则。
>
> **版本**：v0.1  
> **制定日期**：2026-06-28

---

## 总体策略

不复制 MEMANTO 的闭源 Moorcheh 引擎，也不把 Emerald 改成向量优先。而是：

1. 在**混合搜索层**做召回和重排优化；
2. 在**管线层**增加“快速通道”，让原始记忆先可搜、后完善；
3. 在**数据模型层**补充 provenance / validation / 年龄衰减信任模型；
4. 在**关系/冲突层**增加可选的人工确认兜底；
5. 在**体验层**补充 MEMORY.md 同步和更细的作用域。

---

## 里程碑与优先级

| 阶段 | 主题 | 优先级 | 状态 | 关键产出 |
|---|---|---|---|---|
| Phase 1 | 扩大默认召回与动态截断 | P0 | ✅ 已完成 | 搜索默认 k 提升、动态阈值、基准回归 |
| Phase 2 | 即时可检索路径（Fast Lane） | P0 | ✅ 已完成 | 新写入记忆在 <100ms 内可搜 |
| Phase 3 | 信任模型（provenance / validation / 衰减） | P1 | ✅ 已完成 | 每个记忆节点带信任分，影响排序和画像 |
| Phase 4 | 内部类型标签扩展 | P1 | ✅ 已完成 | 提取阶段自动产出更细类型，不暴露给 API |
| Phase 5 | 可选交互式冲突确认 | P2 | ✅ 已完成 | 高影响冲突返回 `requires_resolution` |
| Phase 6 | 每日摘要 / MEMORY.md 同步 | P2 | ✅ 已完成 | 会话/项目记忆可导出为 Markdown |
| Phase 7 | 多层作用域与 JWT Session Token | P3 | ✅ 已完成 | 支持 agent/session/project 作用域 |

---

## Phase 1：扩大默认召回与动态截断

### 背景
MEMANTO 消融研究显示，`top_k` 从 10 提到 40 是 LongMemEval 最大单项收益来源（+20.4%）。Emerald 当前默认 k 偏小，容易漏掉关键片段。

### 任务
1. **修改默认搜索参数**
   - 文件：`emerald/core/search.py`
   - 将默认 `top_k` 从 10 提升到 **30**；保留按实体/场景覆盖能力。
   - 在混合搜索中把向量召回和图谱扩展解耦：向量召回 k 放大，图谱扩展独立 budget。

2. **引入动态截断**
   - 文件：`emerald/core/search.py`
   - 增加 `score_gap_truncation`：当相邻结果分数差 > 0.15 时提前截断，避免固定 k 引入噪音。
   - 增加 `min_confidence` 阈值过滤。

3. **重排层增强**
   - 文件：`emerald/core/ranking.py`（新建或扩展现有）
   - 融合分数 = 向量相似度 × 图谱关系折扣 × 时序新鲜度 × 信任分（为 Phase 3 预留接口）。

4. **API/SDK 参数透传**
   - 文件：`emerald/api/routes/search.py`、`emerald/sdk/client.py`
   - `search(..., top_k=30, dynamic_truncation=True, min_confidence=None)`。

### 验收标准
- 单元测试：默认 `top_k=30`，动态截断在 mock 数据上正确生效。
- 集成测试：`tests/integration/test_search.py` 中验证返回数量范围。
- 基准回归：运行 `scripts/run_benchmarks.py`，LongMemEval / LoCoMo 分数不下降；若可能，提升 ≥2 pp。

---

## Phase 2：即时可检索路径（Fast Lane）

### 背景
Emerald 当前管线阶段多，写入到可检索有明显延迟。MEMANTO 的“零摄入延迟”体验证明Agent 对即时反馈敏感。

### 任务
1. **Fast Lane 数据模型**
   - 文件：`emerald/models/memory.py` 或 `emerald/db/schemas.py`
   - 新增 `MemoryStage` 枚举：`fast_lane`、`extracted`、`indexed`、`archived`。
   - 新增 `fast_lane_embedding` 字段或单独表，存储原始/粗分块嵌入。

2. **Fast Lane 写入路径**
   - 文件：`emerald/core/engine.py`、`emerald/pipeline/ingestion.py`
   - `add()` 收到内容后：
     1. 立即做简单分块（按段落或 256-token 滑窗）；
     2. 立即写入 pgvector 的 `fast_lane` 索引；
     3. 返回 `memory_id`，状态为 `fast_lane`。
   - 后台 Celery/异步任务继续执行：提取事实 → 建图谱关系 → 生成画像 → 标记为 `indexed`。

3. **搜索层合并 Fast Lane**
   - 文件：`emerald/core/search.py`
   - `search()` 同时查询 `indexed` 记忆和 `fast_lane` 原始段。
   - 对 fast_lane 结果打标签 `source: fast_lane`，并在最终排序中轻度降权（如 0.9×）。

4. **生命周期管理**
   - 文件：`emerald/core/garbage_collection.py`（新建）
   - fast_lane 原始段在对应记忆进入 `indexed` 后 24h 归档或删除，避免数据膨胀。

### 验收标准
- 端到端测试：写入后 100ms 内 `search()` 能返回该内容。
- 集成测试：fast_lane 结果在后台任务完成后不再出现（被 indexed 记忆替代）。
- 性能测试：高并发写入不阻塞搜索。

---

## Phase 3：信任模型（provenance / validation / 年龄衰减）

### 背景
MEMANTO 的 `compute_confidence()` 虽然简单，但覆盖了来源、验证、年龄、矛盾等维度。Emerald 需要把信任度作为图谱的一等公民。

### 任务
1. **schema 扩展**
   - 文件：`emerald/models/memory.py`、`migrations/`
   - 在 Memory/Fact 节点上增加字段：
     - `provenance`: `explicit_statement` | `inferred` | `validated` | `observed` | `imported` | `corrected`
     - `validation_count`: int
     - `validated_at`: datetime
     - `contradiction_detected`: bool
   - Neo4j 节点属性同步更新。

2. **信任分计算**
   - 文件：`emerald/core/trust.py`（新建）
   - 实现 `compute_trust_score(memory)`：
     - provenance 基础权重；
     - validation_count 加成（每次 +0.03，上限 +0.15）；
     - 按类型年龄衰减：`preference` / `episodic` >30 天 -0.1、>90 天 -0.2，`fact` 不衰减；
     - contradiction 标记 ×0.3；
     - superseded 状态 → 0。

3. **集成到搜索与画像**
   - 文件：`emerald/core/search.py`、`emerald/core/profile.py`
   - 搜索重排把信任分作为因子。
   - 画像生成时对高信任事实加权，低信任事实降级到“动态/临时”区域。

4. **验证接口**
   - 文件：`emerald/api/routes/memories.py`、`emerald/sdk/client.py`
   - 新增 `POST /v1/memories/{id}/validate`：递增 `validation_count`，更新 `validated_at`。

### 验收标准
- 单元测试：每个 provenance/validation/年龄/矛盾场景的信任分符合预期。
- 集成测试：低信任记忆在搜索结果中排在高信任记忆之后。
- 画像测试：高信任偏好优先进入静态画像。

---

## Phase 4：内部类型标签扩展

### 背景
MEMANTO 定义了 13 种记忆类型。Emerald 当前只有 fact / preference / episodic。更多内部类型能提升过滤、画像和冲突检测质量，但不应暴露给用户。

### 任务
1. **扩展内部类型枚举**
   - 文件：`emerald/core/constants.py` 或 `emerald/models/types.py`
   - 新增内部类型：`decision`、`commitment`、`goal`、`instruction`、`learning`、`error`、`observation`、`relationship`、`context`、`artifact`。
   - 公共 SDK/API 不暴露这些类型，仍然只接受内容。

2. **提取器增强**
   - 文件：`emerald/pipeline/chunking/fact_extractor.py`
   - 在 LLM prompt 中要求对每个事实输出 `type` 字段，支持新类型。
   - 失败时降级为 `fact`。

3. **类型驱动的内部逻辑**
   - 文件：`emerald/core/search.py`、`emerald/core/conflict.py`
   - `decision`/`commitment` 类记忆在冲突检测中提高权重。
   - `error` 类型用于相似错误推荐。
   - `learning` 类型在画像中归入“动态经验”。

### 验收标准
- 单元测试：提取器对示例输入产出正确内部类型。
- 不破坏公共 API：SDK 用户仍然不需要指定类型。

---

## Phase 5：可选交互式冲突确认

### 背景
Emerald 当前自动解决冲突（Update 关系 + `is_latest`）。MEMANTO 的交互式冲突确认适合作为高影响事实的兜底机制。

### 任务
1. **冲突分级**
   - 文件：`emerald/core/conflict.py`
   - 新增 `impact_score`：根据涉及记忆类型（fact/preference/decision）和置信度判断影响等级。

2. **自动解决 vs 提示**
   - 文件：`emerald/core/relationship.py`、`emerald/core/engine.py`
   - 默认仍自动解决；
   - 当 `impact_score >= HIGH` 且新事实置信度 ≥ 0.9 时，不自动覆盖，改为标记 `requires_resolution`。

3. **API 暴露**
   - 文件：`emerald/api/routes/memories.py`
   - `POST /v1/memories` 响应中新增可选字段 `conflicts_pending: [...]`。
   - 新增 `POST /v1/conflicts/{id}/resolve`：支持 `keep_old`、`keep_new`、`keep_both`、`manual`。

4. **SDK 封装**
   - 文件：`emerald/sdk/client.py`
   - `add(..., require_confirmation_for_high_impact=True)`。

### 验收标准
- 单元测试：高影响冲突正确标记 `requires_resolution`，低影响冲突自动解决。
- 集成测试：端到端冲突确认流程通过。

---

## Phase 6：每日摘要 / MEMORY.md 同步

### 背景
MEMANTO 通过 `daily-summary` 和 `memory sync` 把记忆写回项目文件，方便 IDE/Agent 直接消费。Emerald 当前缺少这种“记忆写回”工作流。

### 任务
1. **会话摘要生成**
   - 文件：`emerald/services/summary_service.py`（新建）
   - 按 agent / entity / 日期聚合近期记忆；
   - 调用 LLM 生成 Markdown 摘要；
   - 输出到对象存储或本地路径。

2. **MEMORY.md 同步**
   - 文件：`emerald/connectors/memory_md.py`（新建）
   - 把高频/高信任事实写入项目根目录 `MEMORY.md`；
   - 支持增量更新，避免整文件重写。

3. **调度器**
   - 文件：`emerald/services/scheduler.py` 或复用 Celery beat
   - 默认每日 23:55 运行，可配置。

### 验收标准
- 集成测试：运行同步任务后，目标路径出现格式正确的 `MEMORY.md`。
- 内容测试：文件中只包含高信任、非私密的记忆（需增加隐私/敏感度过滤）。

---

## Phase 7：多层作用域与 JWT Session Token

### 背景
MEMANTO v2 用 `agent`/`session`/`project` 作用域 + JWT Session Token 做隔离。Emerald 当前只有 `entity_id`，未来多代理场景需要更细作用域。

### 任务
1. **作用域模型扩展**
   - 文件：`emerald/models/scope.py`（新建）
   - 定义 `ScopeType`：entity（默认）/ agent / session / project / task。
   - namespace 格式保持向后兼容：`emerald_{entity_id}` 为默认；新作用域映射到子命名空间。

2. **认证鉴权增强**
   - 文件：`emerald/api/auth.py`
   - 支持 JWT Session Token，payload 包含 `entity_id`、`scope_type`、`scope_id`、`exp`。
   - 保持 API Key 认证不变，Session Token 作为可选细粒度凭证。

3. **API 适配**
   - 文件：`emerald/api/dependencies.py`
   - `get_current_scope()` 依赖项，自动从 token 解析作用域并注入路由。

### 验收标准
- 单元测试：JWT 生成、解析、过期校验正确。
- 集成测试：同一 entity 下不同 agent 的记忆相互隔离。

---

## 跨阶段基础设施

### 测试
- 每个 Phase 必须补充单元测试 + 至少一个集成测试。
- 在 `tests/benchmarks/` 中增加 MEMANTO 风格召回-准确率曲线实验，验证 `top_k` 和动态截断效果。

### 可观测性
- 每个新路径记录结构化日志：entity_id、stage、latency、recall_count、trust_score。
- 新增指标：
  - `emerald_search_recall_k`
  - `emerald_fast_lane_latency_ms`
  - `emerald_memory_trust_score_distribution`

### 文档
- 更新 `docs/architecture/api-design.md`：新参数、新端点。
- 更新 `docs/integration-guide.md`：MEMORY.md 同步用法。
- 更新 `CHANGELOG.md`：按 Phase 记录。

---

## 风险与回退方案

| 风险 | 影响 | 回退方案 |
|---|---|---|
| Fast Lane 导致数据重复或搜索噪音 | 中 | 增加开关 `ENABLE_FAST_LANE`，默认关闭； fast_lane 结果强降权 |
| 默认 k 提升增加延迟/token | 中 | 按 plan tier / 环境配置 k 值；动态截断控制上限 |
| 信任模型排序改动影响现有用户 | 中 | 新增 `ranking_version` 参数，默认 v2；旧行为保留 |
| 交互式冲突确认破坏声明式体验 | 低 | 默认关闭，仅在 `require_confirmation_for_high_impact=True` 时启用 |
| JWT Session 改动认证层 | 中 | 作为 v2 API 前缀 `/v2/` 引入，v1 保持不变 |

---

## 建议执行顺序

1. **先启动 Phase 1 + Phase 3**：收益最大、改动相对独立，可并行。
2. **随后 Phase 2**：需要与管线深度集成，依赖 Phase 3 的信任分接口。
3. **再 Phase 4 + Phase 5**：依赖 Phase 3 的信任模型和冲突分级。
4. **最后 Phase 6 + Phase 7**：产品体验和认证层增强，优先级相对较低。

---

## 参考

- `docs/comparisons/memanto-analysis.md`
- `AGENTS.md`
- `docs/architecture.md`
