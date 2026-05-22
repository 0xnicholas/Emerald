# Emerald 测试计划

## 当前状态

| 指标 | 数值 |
|---|---|
| 总测试数 | 132 |
| 测试文件 | 18 |
| 通过率 | 132/132 (100%) |
| 源码文件 | 79 |
| 有直接测试的模块 | 17 |
| 覆盖率缺口 | ~30 个模块无独立单元测试 |

### 当前测试分布

| 层 | 测试数 | 覆盖模块 |
|---|---|---|
| 提取器 | 15 | text, url, code (缺失: pdf, image, audio, video) |
| 分块器 | 30 | text, conversation, markdown, code, pdf |
| 核心引擎 | 36 | engine(6), relationship(6), profile(9), search(8), forget(9) |
| API | 9 | memories, search, profile, health, 404 |
| SDK | 11 | add, search, profile, roundtrip, auth |
| 连接器 | 14 | OAuth flow, sync, webhook, encrypt, registry, pipeline |
| 基准 | 15 | temporal(4), relationship(3), search(3), profile(3), isolation(2) |

---

## Part 1: 补缺测试计划

### 1.1 单元测试缺口（高优先级）

#### 嵌入引擎 (`emerald/core/embedder.py`) — 0 tests

| 测试 | 说明 |
|---|---|
| `test_mock_embedder_deterministic` | 相同输入产生相同向量 |
| `test_mock_embedder_dimension` | 向量维度正确 |
| `test_mock_embedder_different_inputs` | 不同输入产生不同向量 |
| `test_mock_embedder_empty_list` | 空列表返回空列表 |
| `test_openai_provider_raises_not_implemented` | 缺 API key 时优雅失败 |

#### 图存储 (`emerald/core/graph.py`) — 0 独立单元测试

| 测试 | 说明 |
|---|---|
| `test_create_memory_returns_id` | 创建返回 UUID |
| `test_create_memory_sets_defaults` | is_latest=True, valid_from 正确 |
| `test_get_memory_found` | 按 ID 查询成功 |
| `test_get_memory_not_found` | 不存在的 ID 返回 None |
| `test_list_latest_excludes_expired` | valid_until 过期的不返回 |
| `test_list_latest_respects_limit` | limit 参数生效 |
| `test_update_is_latest_with_replaced_by` | replaced_by 正确记录 |
| `test_memory_entity_isolation` | entity_id 不同的记忆隔离 |

#### 向量存储 (`emerald/core/vector.py`) — 0 独立单元测试

| 测试 | 说明 |
|---|---|
| `test_store_and_search` | 存储后可搜索到 |
| `test_cosine_similarity_identical` | 相同向量 cos=1.0 |
| `test_cosine_similarity_orthogonal` | 正交向量 cos=0 |
| `test_search_respects_entity_id` | 只返回指定实体 |
| `test_search_respects_top_k` | top_k 限制 |
| `test_search_empty_store` | 空存储返回空 |

#### 注册表 (`emerald/pipeline/extraction/registry.py`, `chunking/registry.py`) — 0 独立单元测试

| 测试 | 说明 |
|---|---|
| `test_register_and_get` | 注册后可按 content_type 获取 |
| `test_register_overwrite` | 同类型覆盖 |
| `test_get_unsupported_raises` | 未注册类型抛异常 |
| `test_extract_delegates` | extract() 正确委派给注册的提取器 |
| `test_chunk_fallback_to_text` | 未注册类型 fallback 到 text chunker |

#### 异常体系 (`emerald/core/exceptions.py`) — 0 tests

| 测试 | 说明 |
|---|---|
| `test_emerald_error_base` | 基类可捕获所有子类 |
| `test_extraction_error_retryable` | retryable 标记正确 |
| `test_not_found_error_message` | 消息包含 resource type 和 id |
| `test_content_too_large_error` | 消息包含实际和限制大小 |

### 1.2 错误路径测试（高优先级）

#### 提取器失败路径

| 测试 | 说明 |
|---|---|
| `test_pdf_extractor_missing_pymupdf` | 缺 PyMuPDF 时抛 ExtractionError(not retryable) |
| `test_image_extractor_missing_pillow` | 缺 Pillow 时优雅失败 |
| `test_audio_extractor_missing_whisper` | 缺 faster-whisper 时优雅失败 |
| `test_video_extractor_missing_ffmpeg` | 缺 ffmpeg 时优雅失败 |
| `test_pdf_single_page_failure_not_blocking` | 单页失败不阻塞整体管线 |

#### 嵌入失败路径

| 测试 | 说明 |
|---|---|
| `test_embed_batch_partial_failure` | 批次中单个失败的重试 |

#### 管线失败路径

| 测试 | 说明 |
|---|---|
| `test_pipeline_extraction_failure_marks_failed` | 提取失败 → status=failed |
| `test_pipeline_retry_exhausted` | 重试耗尽后死信处理 |

### 1.3 边缘场景测试（中优先级）

| 测试 | 说明 |
|---|---|
| `test_add_extremely_long_text` | 100KB+ 文本不崩溃 |
| `test_add_special_characters_only` | 纯 emoji/符号正确处理 |
| `test_add_zero_width_characters` | 零宽字符不影响分块 |
| `test_search_empty_query` | 空查询不崩溃 |
| `test_search_very_long_query` | 长查询截断或处理 |
| `test_concurrent_add_same_entity` | 并发 add 不产生竞态 |
| `test_memory_type_auto_classification` | 事实/偏好/情节自动分类 |

### 1.4 SDK 负面测试（中优先级）

| 测试 | 说明 |
|---|---|
| `test_client_no_api_key_uses_env` | 从环境变量读取 |
| `test_client_invalid_base_url` | 错误 URL 抛连接错误 |
| `test_client_timeout` | 超时正确处理 |
| `test_client_close_twice_safe` | 重复 close 不崩溃 |

### 1.5 禁止暴露内部操作测试（AGENTS.md 硬性要求）

| 测试 | 说明 |
|---|---|
| `test_sdk_has_no_graph_methods` | SDK 不暴露 create_memory/update_is_latest |
| `test_sdk_has_no_relationship_methods` | SDK 不暴露 classify_relation/create_update_relation |
| `test_api_no_graph_endpoints` | API 无 /v1/graph 或 /v1/relationships 路由 |

### 1.6 预估新增测试数量

| 类别 | 新增测试 | 累计 |
|---|---|---|
| 单元测试缺口 (embedder, graph, vector, registry, exceptions) | 30 | 30 |
| 错误路径 | 10 | 40 |
| 边缘场景 | 7 | 47 |
| SDK 负面 | 4 | 51 |
| 禁止暴露检查 | 3 | 54 |
| **总计** | **54** | **132 + 54 = 186** |

---

## Part 2: 质量门禁计划

### 2.1 分层门禁

#### Gate 1: 提交前（pre-commit）

| 检查 | 工具 | 阈值 |
|---|---|---|
| 代码格式 | ruff format | 0 diff |
| Lint | ruff check | 0 errors |
| 类型检查 | mypy (strict) | 0 errors |
| 单元测试 | pytest (标记 `unit`) | 100% pass, < 5s |
| 禁止模式检查 | 自定义 grep | SDK/API 无内部暴露 |

```bash
# pre-commit hook 等价命令
ruff format --check emerald/ tests/
ruff check emerald/ tests/
python3 -m pytest tests/ -m "unit" -x --tb=short
```

#### Gate 2: PR 合并前（CI）

| 检查 | 工具 | 阈值 |
|---|---|---|
| 全量测试 | pytest | 100% pass |
| 覆盖率（行） | pytest-cov | ≥ 80% |
| 覆盖率（分支） | pytest-cov | ≥ 70% |
| 基准测试 | pytest (标记 `benchmark`) | 100% pass |
| 画像计算速度 | benchmark | < 100ms |
| 集成测试 | pytest (标记 `integration`) | 100% pass |

```bash
python3 -m pytest tests/ -v --cov=emerald --cov-report=term --cov-fail-under=80
python3 -m pytest tests/benchmarks/ -v
```

#### Gate 3: 发布前（CD）

| 检查 | 工具 | 阈值 |
|---|---|---|
| 全量测试 × Python 版本矩阵 | tox | 3.12, 3.13 全通过 |
| 内存泄漏检查 | pytest + memray | 无泄漏 |
| 安全扫描 | bandit | 0 high/medium |
| 依赖漏洞 | pip-audit | 0 critical |

### 2.2 覆盖率目标

| 模块 | 行覆盖率目标 | 分支覆盖率目标 | 当前估算 |
|---|---|---|---|
| `emerald/core/` | 90% | 80% | ~70% |
| `emerald/pipeline/` | 85% | 75% | ~75% |
| `emerald/api/` | 85% | 75% | ~60% |
| `emerald/sdk/` | 90% | 80% | ~80% |
| `emerald/connectors/` | 80% | 70% | ~50% |
| `emerald/models/` | 70% | — | ~30% |
| **整体** | **80%** | **70%** | **~60%** |

### 2.3 基准指标（回归检测）

| 基准 | 目标 | 当前 | 回归阈值 |
|---|---|---|---|
| 画像计算 (50 memories) | < 100ms | ~5ms | > 150ms |
| 文本摄入 (1KB) | < 500ms | ~10ms | > 1s |
| 混合搜索 P99 | < 500ms | ~2ms | > 1s |
| 关系推断 (10 memories) | < 200ms | ~5ms | > 500ms |
| 实体隔离 (零泄露) | 0 cross-entity hits | 0 | > 0 |

### 2.4 测试标记体系

在 `pyproject.toml` 中注册标记：

```toml
[tool.pytest.ini_options]
markers = [
    "unit: 单元测试，不依赖外部服务",
    "integration: 集成测试，需要多模块协作",
    "benchmark: 基准测试，含性能断言",
    "slow: 耗时 > 1s 的测试",
    "e2e: 端到端测试，需要完整环境",
]
```

### 2.5 测试组织结构

```
tests/
├── unit/                         # 纯单元测试（无外部依赖）
│   ├── test_embedder.py
│   ├── test_exceptions.py
│   ├── test_graph_store.py
│   ├── test_vector_store.py
│   ├── test_extractor_registry.py
│   ├── test_chunker_registry.py
│   └── test_config.py
├── pipeline/                     # 提取器/分块器测试（已有）
│   └── ...
├── core/                         # 核心模块测试（已有）
│   └── ...
├── integration/                  # 集成测试
│   ├── test_pipeline_e2e.py
│   ├── test_error_recovery.py
│   └── test_concurrent.py
├── api/                          # API 测试（已有）
│   └── ...
├── sdk/                          # SDK 测试（已有）
│   └── ...
├── connectors/                   # 连接器测试（已有）
│   └── ...
├── benchmarks/                   # 基准测试（已有）
│   └── ...
└── negative/                     # 负面/禁止测试
    ├── test_no_internal_exposure.py
    └── test_edge_cases.py
```

---

## Part 3: 实施顺序

### 第一批（P0 — 本 phase 完成）

1. **单元测试缺口** — embedder, graph, vector, registry, exceptions (30 tests)
2. **禁止暴露检查** — SDK/API 无内部操作暴露 (3 tests)

### 第二批（P1 — 下一 phase）

3. **错误路径** — extractor 失败, embedding 失败, 管线恢复 (10 tests)
4. **SDK 负面测试** — 无 key, 错误 URL, 超时 (4 tests)

### 第三批（P2）

5. **边缘场景** — 长文本, 特殊字符, 并发 (7 tests)
6. **编写 CI 配置** — GitHub Actions / tox 矩阵

### 第四批（按需）

7. **覆盖率工具配置** — `.coveragerc` + pytest-cov CI 集成
8. **安全扫描** — bandit + pip-audit
