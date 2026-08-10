# 真实嵌入模型选型调研（2026-08-10）

> 调研日期：2026-08-10 · 目的：为 v0.5.0 绝对分数基准报告（ADR-0001）选定真实嵌入模型
> 分支：`research/embedding-model-options` · issue #12 · 本票仅调研，不写产品代码
> 方法：优先官方一手来源（OpenAI 官方博客/帮助中心、DeepSeek 官方 API 文档、fastembed 官方文档与源码、BGE 官方模型卡与论文）；未能访问的页面显式标注于 §8。

## 1. 结论速览

| 选项 | 价格（每 1M tokens） | 质量信号 | 数据出口 | 需要 API Key | 切换成本 |
|---|---|---|---|---|---|
| **OpenAI text-embedding-3-small**（现状默认） | $0.02（官方 2024-01 公布值，2026 现值未能复核） | MTEB 62.3 / MIRACL 44.0 | 文本出网至 OpenAI | 是（OPENAI_API_KEY） | 零（已接入） |
| **OpenAI text-embedding-3-large** | $0.13（官方 2024-01 公布值，2026 现值未能复核） | MTEB 64.6 / MIRACL 54.9（OpenAI 最佳） | 文本出网至 OpenAI | 是 | 仅改 env（`OPENAI_EMBEDDING_MODEL`）；dims 3072 与既有 1536 列需确认 |
| **DeepSeek embedding API** | 不存在 | — | — | — | 不可行（2026-08-10 无公开 embedding 端点） |
| **fastembed 本地 bge-small-en-v1.5**（现状降级路径） | 免费（MIT） | 英文专用、512 token 截断；质量低于 API 模型 | 零出口 | 否 | 仅改 env（`BGE_MODEL_PATH`）；dims 384 |
| **fastembed 本地 bge-small-zh-v1.5** | 免费（MIT） | 中文专用、512 token 截断 | 零出口 | 否 | 仅改 env；dims 512 |
| **bge-m3 本地（sentence-transformers/FlagEmbedding 加载）** | 免费（MIT） | 中英多语言、8192 tokens；MIRACL dev 67.8（dense）> OpenAI-3 54.9（论文口径） | 零出口 | 否 | 高：**不在 fastembed 支持列表**，需走 PyTorch 路径；dims 1024；需 GPU 才划算 |

## 2. OpenAI text-embedding-3-small / text-embedding-3-large

**当前状态**：仍是 OpenAI 当前一代 embedding 模型。OpenAI 帮助中心 Embeddings FAQ（11 天前更新）仍以二者为「newest embedding models」（https://help.openai.com/en/articles/6824809-embeddings-frequently-asked-questions）；Azure 官方模型页（2026-07-23 更新）仍列二者且注明「`text-embedding-3-large` is the latest and most capable embedding model」（https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models）。

**能力（Azure 官方模型页，2026-07-23 更新，URL 同上）**：

| 模型 | 最大输入 | 输出维度 | MTEB 平均 | MIRACL 平均 |
|---|---|---|---|---|
| text-embedding-3-small | 8,192 tokens | 1,536 | 62.3 | 44.0 |
| text-embedding-3-large | 8,192 tokens | 3,072 | 64.6 | 54.9 |

- 单次调用最多 2,048 条输入（Azure 官方模型页）；输出 L2 归一化；支持 Matryoshka `dimensions` 截断参数（https://help.openai.com/en/articles/6824809-embeddings-frequently-asked-questions 、https://openai.com/index/new-embedding-models-and-api-updates/）。
- 官方发布价（2024-01-25 博客，https://openai.com/index/new-embedding-models-and-api-updates/）：3-small $0.00002/1k tokens（$0.02/1M），3-large $0.00013/1k tokens（$0.13/1M）。
- 数据政策：默认「API 发送的数据不用于训练或改进 OpenAI 模型」（同上博客）；但**记忆文本会上行到 OpenAI 服务器**——私有化部署/数据边界敏感用户需权衡。
- 限流（RPM/TPM）：**未能复核**（platform.openai.com 对本调研工具返回 403，见 §8）。
- Azure OpenAI 提供区域化部署（数据驻留选项）与独立计价，可作为替代通道，本次未核对其价格明细。

**对报告的意义**：3-large 是 OpenAI 阵营的最高质量选项，且与现有代码同 API——仅改一个环境变量即可跑报告。基准语料规模（约百级事实 + 查询）下，即使按 $0.13/1M，单次报告成本可忽略（量级估算 <$1，非官方数字）。

## 3. DeepSeek：截至 2026-08-10 无公开 embedding API

- 官方 API 文档（https://api-docs.deepseek.com/ ）完整 API Reference 仅五个端点：Chat Completions、Responses API、FIM Completion、List Models、Get User Balance（https://api-docs.deepseek.com/api/create-chat-completion ）。**无 `/embeddings` 端点**。
- 模型列表仅两个对话模型：`deepseek-v4-flash`、`deepseek-v4-pro`（https://api-docs.deepseek.com/ 、https://api-docs.deepseek.com/quick_start/pricing ）。
- 计价页无 embedding 计价行；对话计价（cache miss）：flash $0.14/1M 输入 / $0.28/1M 输出，pro $0.435/1M 输入 / $0.87/1M 输出（https://api-docs.deepseek.com/quick_start/pricing ）。该页同时公告近期将大幅上调价格。
- **结论**：DeepSeek embedding API 不存在，不能作为绝对分数报告的候选；若未来上线需重新调研。也意味着「LLM 用 DeepSeek、嵌入用 OpenAI」的双厂商局面在 2026-08-10 无解。

## 4. fastembed 本地模型（现状降级路径）

fastembed 官方支持模型表（https://qdrant.github.io/fastembed/examples/Supported_Models/ ）与源码注册表（https://github.com/qdrant/fastembed/blob/main/fastembed/text/onnx_embedding.py ）一致，与 Emerald 相关的可选模型：

| 模型 | 维度 | 大小 | 语言 | 许可证 |
|---|---|---|---|---|
| BAAI/bge-small-en-v1.5（现状默认） | 384 | 0.067 GB | 英文，512 token 截断 | MIT |
| BAAI/bge-small-zh-v1.5 | 512 | 0.090 GB | 中文，512 token 截断 | MIT |
| BAAI/bge-base-en-v1.5 | 768 | 0.21 GB | 英文 | MIT |
| BAAI/bge-large-en-v1.5 | 1024 | 1.20 GB | 英文 | MIT |
| mixedbread-ai/mxbai-embed-large-v1 | 1024 | 0.64 GB | 英文 | Apache-2.0 |
| intfloat/multilingual-e5-large | 1024 | 2.24 GB | 多语言 | MIT |

- 特性：ONNX Runtime 推理、无 PyTorch 依赖；支持 CPU 线程与可选 CUDA GPU（https://qdrant.github.io/fastembed/examples/FastEmbed_GPU/ ）；模型首次下载后走本地缓存目录，完全离线（fastembed 源码 `OnnxTextEmbedding.__init__`，https://github.com/qdrant/fastembed/blob/main/fastembed/text/onnx_embedding.py ）。
- 免费、MIT/Apache-2.0、无 API Key、**零数据出口**——是私有化部署用户唯一无妥协选项。
- 质量：英文小模型（bge-small-en-v1.5）在检索任务上明显低于 API 模型。可验证的代理数据（bge-m3 论文 Table 5，NarrativeQA nDCG@10）：bge-large-en-v1.5（更大的英文本地模型）27.3 vs text-embedding-3-large 51.6（https://ar5iv.labs.arxiv.org/html/2402.03216 ）。
- 中文场景：C-MTEB 检索（C-Pack 论文 Table 2，https://ar5iv.labs.arxiv.org/html/2309.07597 ）：BGE (base) 69.53 vs OpenAI ada-002 52.00——本地中文模型在中文检索上显著强于（当时的）OpenAI 通用模型；而 bge-small-en-v1.5 是**英文专用**模型，对 Emerald 基准的中文语料（见 `tests/benchmarks/test_memory_benchmarks.py`）语义能力存疑。

## 5. bge-m3：质量高但不在 fastembed 支持列表

- 官方模型卡/仓库（https://github.com/FlagOpen/FlagEmbedding/tree/master/research/BGE_M3 、https://huggingface.co/BAAI/bge-m3 ）：1024 维、最长 8,192 tokens、100+ 语言、dense+sparse+colbert 三合一、MIT 许可证。
- 质量（技术报告，https://arxiv.org/abs/2402.03216 ；表格见 https://ar5iv.labs.arxiv.org/html/2402.03216 ）：
  - MIRACL dev（nDCG@10，多语言含中英文）：bge-m3 dense 67.8 / dense+sparse 68.9 / 全部 70.0；同期 **OpenAI text-embedding-3-large 54.9**；
  - MKQA（Recall@100，跨语言）：bge-m3 dense 75.1 vs OpenAI-3 69.5；
  - NarrativeQA（nDCG@10）：bge-m3 dense 48.7 vs text-embedding-3-large 51.6。
  - 注：2024-07-01 官方修正过 MIRACL 数值（上调，结论不变），见上述仓库 README News。
- **关键限制**：fastembed 当前官方支持列表（§4 表格）**不包含 bge-m3**——docs 页面与源码 `onnx_embedding.py` 均无此模型。用 `fastembed.TextEmbedding("BAAI/bge-m3")` 会直接 `ValueError`（源码 `TextEmbedding.__init__`，https://github.com/qdrant/fastembed/blob/main/fastembed/text/text_embedding.py ）。要用需走 sentence-transformers / FlagEmbedding（PyTorch），或 `add_custom_model` 自注册 ONNX（需自行导出/下载模型文件，fastembed 未提供官方 ONNX 源）。

## 6. 对比表汇总

| 选项 | 价格 | 质量信号（检索） | 时延/资源 | 数据出口 | Key | 切换成本 |
|---|---|---|---|---|---|---|
| OpenAI 3-small | $0.02/1M（2024 官方值） | MTEB 62.3 / MIRACL 44.0 | API；批次 2048；已有 retry/缓存 | 有 | 要 | 零（现状） |
| OpenAI 3-large | $0.13/1M（2024 官方值） | MTEB 64.6 / MIRACL 54.9 | 同上，向量 3072 维存储更大 | 有 | 要 | 低（env + 维度/存储确认） |
| DeepSeek embedding | 不存在 | — | — | — | — | 不可行 |
| fastembed bge-small-en-v1.5 | 免费 | 英文专用；远低于 API 模型（代理数据：bge-large-en-v1.5 NarrativeQA 27.3 vs 3-large 51.6） | ONNX CPU 毫秒级/批；67MB 内存占用 | 零 | 否 | 低（env） |
| fastembed bge-small-zh-v1.5 | 免费 | 中文专用；512 token 截断 | 同上，90MB | 零 | 否 | 低（env） |
| bge-m3 本地 | 免费 | 多语言；MIRACL 67.8（dense）> OpenAI-3 54.9（论文口径） | 需 PyTorch；模型 ~2.2GB 级；建议 GPU | 零 | 否 | 高（依赖 + 维度 + 存储） |

## 7. 建议（供绝对分数报告选择）

**主选：OpenAI text-embedding-3-large。** 理由：OpenAI 阵营最高质量（MTEB 64.6 / MIRACL 54.9，官方与 Azure 2026-07 文档均确认在售）；与现状代码同 API，切换仅改 `OPENAI_EMBEDDING_MODEL`；报告语料量级下成本可忽略。代价：数据出口 + 向量 3072 维（需确认 `Vector(1536)` 存储列约束，见 §9）。

**对照/私有化选项：bge-m3 本地跑。** 理由：唯一同时满足「中文+英文」（对齐 Emerald 基准语料）、零出口、质量不低于 3-large 的选项（MIRACL 67.8 vs 54.9，论文口径）；MIT 免费。代价：**fastembed 不支持**，需 sentence-transformers/FlagEmbedding（PyTorch）路径，建议 GPU，1024 维存储。

**现状降级：fastembed bge-small-en-v1.5 保持为无 key 环境的兜底**（与 `emerald/core/embedder.py` 现有 fallback 逻辑一致），但不建议作为绝对分数报告的旗舰模型（英文专用 + 512 token 截断 + 质量差距）。

**否决：DeepSeek embedding**——2026-08-10 官方 API 不存在该端点；报告发布前若上线可复检。

## 8. 未能验证清单（显式标注）

- **OpenAI 现行（2026）美元单价与限流（RPM/TPM）**：`platform.openai.com/docs/pricing`、`/docs/guides/embeddings`、`developers.openai.com` 均返回 403，`openai.com/api/pricing` 跳转到 ChatGPT 商务页；r.jina.ai 与 Wayback Machine 抓取超时。本文引用的 $0.02/$0.13 为官方 2024-01-25 博客公布值，v0.5.0 报告发布前应人工复核。
- **bge-small-en-v1.5 的 MTEB 明细分**：HuggingFace 模型卡多次抓取超时（https://huggingface.co/BAAI/bge-small-en-v1.5 ），未获一手分数；本文仅用论文中 bge-large-en-v1.5 的 NarrativeQA 分作为本地模型质量代理。
- **bge-m3 更新后（2024-07-01 修正版）的 MIRACL 精确分**：官方仓库 README 的表格为图片，未能提取修正后数值；引用的 67.8/70.0 为技术报告 ar5iv 版本表格（论文有 2024-07-01 修订记录）。
- **fastembed 具体吞吐数字**（句子/秒）：官方文档无基准数字页，未验证；仅确认 CPU/GPU 两种运行路径存在。
- **Azure OpenAI 嵌入区域计价**：未核对（仅作通道提示，非主路径）。

## 9. 对 Emerald 切换的影响（本地代码调研）

- 入口：`emerald/core/embedder.py:330 get_embedding_provider()`——`openai` 分支用 `OPENAI_API_KEY` + `OPENAI_EMBEDDING_MODEL`；`bge/text2vec/local` 分支走 `FastembedProvider(BGE_MODEL_PATH)`。任何 fastembed 支持列表内的模型可经 env 直切（`BGE_MODEL_PATH=BAAI/bge-small-zh-v1.5` 等）。
- 维度约束：`OpenAIProvider` 维度表仅认 3-small/3-large（embedder.py:59-62，未知模型默认 1536）；`embedder.py:350` 注释明确向量列 `Vector(1536)`——换 384/512/1024 维模型（bge 系列/bge-m3）需核对 `emerald/core/vector.py` 与 `docs/architecture/data-model.md:376-377` 的维度登记。
- 基准脚本：`scripts/run_benchmarks.py` `--real` 经 `get_embedding_provider()` 取嵌入（line 125），报告头 `provider_name` 硬编码为 "OpenAI (text-embedding-3-small)"（line 1046，仅展示用）；`scripts/run_real_benchmarks.sh` 生成报告到 `docs/benchmarks/`。跑 3-large：设 `OPENAI_EMBEDDING_MODEL=text-embedding-3-large` 即可，无需改代码。
- 数据边界语境：连接器已外包至连接中心（ADR-0004，见 `docs/verification/stackone-pilot-verification.md` 头部 2026-08-10 决策），但**私有化部署用户的记忆文本出口敏感度不因此降低**——嵌入 API 仍直连外部厂商，这是本地 bge-m3 路线的核心价值。
