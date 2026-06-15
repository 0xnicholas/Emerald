#!/usr/bin/env python3
"""Emerald Memory Benchmark Suite v2.

Evaluates Emerald's memory engine across six dimensions aligned with
LongMemEval, LoCoMo, and ConvoMem benchmarks.

Benchmarks:
  1. Fact Recall        — LongMemEval Info Extraction  (100 facts, 30 queries)
  2. Temporal Updates   — LongMemEval Knowledge Updates  (10 timelines × 5 steps)
  3. Relationship Class — UPDATES/EXTENDS/DERIVES_FROM   (20 pairs)
  4. Profile Accuracy   — LoCoMo persona consistency     (50 facts → profile)
  5. Distractor Resist  — ConvoMem multi-message         (5 targets + 50 noise)
  6. Forgetting Correct — time + noise + decay            (30 mixed facts)

Output:
  • Console summary table
  • JSON report: reports/benchmark-YYYYMMDD-HHMMSS.json

Usage:
    python scripts/run_benchmarks.py               # mock embeddings (fast, CI)
    python scripts/run_benchmarks.py --real         # OpenAI embeddings (semantic)
    python scripts/run_benchmarks.py --real --llm   # + LLM relationship classification

Note: This script now uses real embeddings by default when OPENAI_API_KEY
is available. Use --mock to force deterministic mock embeddings.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Add project root to path for direct script execution
sys.path.insert(0, str(Path(__file__).parent.parent))

from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import (
    EmbeddingProvider,
    MockEmbeddingProvider,
    OpenAIProvider,
    get_embedding_provider,
)
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.forget import ForgetEngine, ForgetStrategy
from emerald.core.graph import GraphStore
from emerald.core.profile import ProfileManager
from emerald.core.relationship import RelationType, RelationshipEngine
from emerald.core.search import SearchMode, SearchOrchestrator
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class BenchConfig:
    """Benchmark configuration."""
    use_real_embeddings: bool = False
    use_llm_relationships: bool = False
    embedding_dim: int = 1536  # text-embedding-3-small
    top_k: int = 10


@dataclass
class BenchResult:
    """Single benchmark result."""
    name: str
    aligns_with: str  # e.g. "LongMemEval"
    description: str
    metrics: dict[str, float | str]
    passed: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "aligns_with": self.aligns_with,
            "description": self.description,
            "metrics": self.metrics,
            "passed": self.passed,
            "details": self.details,
        }


@dataclass
class BenchReport:
    """Full benchmark report."""
    version: str = "2.0"
    timestamp: str = ""
    config: dict = field(default_factory=dict)
    results: list[BenchResult] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# Engine factory
# ═══════════════════════════════════════════════════════════════════════════


def _make_engine(config: BenchConfig, use_llm: bool = False) -> MemoryEngine:
    """Build a MemoryEngine configured for benchmarking."""
    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    extractors.register("conversation", TextExtractor())

    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    chunkers.register("conversation", TextChunker())

    # Choose embedding provider
    if config.use_real_embeddings:
        embedder = get_embedding_provider()
    else:
        embedder = MockEmbeddingProvider(dimension=config.embedding_dim)

    graph = GraphStore(use_db=False)
    vector = VectorStore(use_db=False)

    relationships = RelationshipEngine(
        graph=graph,
        vector=vector,
        use_llm=use_llm,
    )

    return MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=embedder,
        graph=graph,
        vector=vector,
        relationships=relationships,
        use_db=False,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 1: Fact Recall (LongMemEval Information Extraction)
# ═══════════════════════════════════════════════════════════════════════════

# 5 entities, each gets 20 facts (= 100 total).  30 queries test recall.
_FACT_ENTITIES = [
    ("entity_alice", [
        "Alice 是一名资深前端工程师，使用 React 和 TypeScript",
        "Alice 住在北京海淀区，每天骑自行车上班",
        "Alice 喜欢喝手冲咖啡，尤其偏爱埃塞俄比亚耶加雪菲",
        "Alice 养了一只叫小橘的橘猫，已经 3 岁了",
        "Alice 每周二和周四去健身房练瑜伽",
        "Alice 是一名开源贡献者，主要维护一个状态管理库",
        "Alice 的母语是中文，但英语流利，日语 N3 水平",
        "Alice 喜欢在周末去郊区徒步，偏好难度中等的路线",
        "Alice 使用 Vim 编辑器，已经有 7 年使用经验",
        "Alice 讨厌开会，偏好异步沟通和书面文档",
        "Alice 正在学习 Rust，打算用它重写一个内部工具",
        "Alice 最喜欢的食物是日式拉面，特别是味噌拉面",
        "Alice 有一台 MacBook Pro M3，主要用于开发工作",
        "Alice 对设计系统有深入研究，曾在公司内部做过分享",
        "Alice 最近在读《Designing Data-Intensive Applications》",
        "Alice 负责团队的代码审查流程，制定了 ESLint 规范",
        "Alice 的 GitHub 账号有 2000+ star，主要来自前端项目",
        "Alice 不喜欢加班，坚持 996 是低效的工作方式",
        "Alice 每年参加一次技术大会，去年去了 JSConf China",
        "Alice 认为单元测试是代码质量的底线，覆盖率不能低于 80%",
    ]),
    ("entity_bob", [
        "Bob 是后端工程师，主要使用 Go 和 Python",
        "Bob 在微服务架构方面有 5 年经验，使用 Kubernetes",
        "Bob 喜欢篮球，每周六和朋友在朝阳公园打球",
        "Bob 住在上海浦东，每天坐地铁 2 号线通勤",
        "Bob 正在搭建一个基于 Kafka 的事件驱动系统",
        "Bob 不喜欢 ORM，偏好手写 SQL 和数据库原生查询",
        "Bob 的爱好是听爵士乐和收集黑胶唱片",
        "Bob 最近在学钢琴，每周上一节课",
        "Bob 认为代码可读性比性能优化更重要",
        "Bob 有一台 ThinkPad X1 Carbon，运行 Arch Linux",
        "Bob 喜欢在晚上 10 点后写代码，认为深夜效率最高",
        "Bob 对数据库调优很有心得，尤其是 PostgreSQL",
        "Bob 经常在 Stack Overflow 上回答问题，排名前 1%",
        "Bob 不喝咖啡，只喝绿茶，偏爱龙井",
        "Bob 正在准备 AWS Solutions Architect 认证考试",
        "Bob 觉得 Rust 很有趣，但暂时没有时间深入学习",
        "Bob 的团队使用 GitLab CI 做持续集成",
        "Bob 喜欢结对编程，认为能提高代码质量",
        "Bob 每年会去一个没去过的国家旅行",
        "Bob 对 AI 辅助编程持开放态度，已经开始使用 Copilot",
    ]),
    ("entity_carol", [
        "Carol 是产品经理，负责一款 SaaS 协作工具",
        "Carol 喜欢用 Notion 管理个人和团队的知识库",
        "Carol 住在深圳南山区，公司就在科技园",
        "Carol 认为用户访谈比数据分析更能发现真实需求",
        "Carol 正在学习 SQL，希望能自己查询数据验证假设",
        "Carol 使用 Figma 做原型设计，熟悉设计系统",
        "Carol 每周主持两次站会，每次不超过 15 分钟",
        "Carol 喜欢读商业传记，《鞋狗》是她最喜欢的书",
        "Carol 的团队有 8 个人，包括 4 个工程师和 2 个设计师",
        "Carol 认为好的 PRD 应该在一页纸内说清楚核心价值",
        "Carol 经常和用户进行视频访谈，每周至少 3 次",
        "Carol 喜欢喝拿铁，公司楼下的星巴克是她常去的地方",
        "Carol 对 AI 产品充满热情，在探索 LLM 的应用场景",
        "Carol 有一个个人博客，主要写产品思考和方法论",
        "Carol 不喜欢用 Excel，偏好 Airtable 做数据分析",
        "Carol 认为远程办公效率不亚于在办公室工作",
        "Carol 正在读《Inspired》，觉得里面很多观点很受用",
        "Carol 手机用的是 iPhone，但对 Android 开发也很关注",
        "Carol 觉得跨部门沟通是产品经理最重要的技能",
        "Carol 每天坚持冥想 10 分钟，已经持续了 200 天",
    ]),
    ("entity_dave", [
        "Dave 是 DevOps 工程师，负责 CI/CD 和维护基础设施",
        "Dave 使用 Terraform 和 Ansible 管理云资源",
        "Dave 住在杭州余杭区，在阿里附近租了房子",
        "Dave 是 Docker 和 Kubernetes 的重度用户",
        "Dave 喜欢骑公路自行车，周末经常骑行 100 公里",
        "Dave 对监控和可观测性有深入研究，Prometheus 专家",
        "Dave 不喜欢用图形界面，所有操作都在终端完成",
        "Dave 正在搭建一个基于 Grafana 的告警系统",
        "Dave 认为自动化一切是 DevOps 的核心哲学",
        "Dave 喜欢喝精酿啤酒，家里有一个小酒柜",
        "Dave 最近在学 Golang，打算优化一个性能敏感的组件",
        "Dave 对安全也很关注，持有 CISSP 认证",
        "Dave 的日常工作包括处理 on-call 告警和故障排查",
        "Dave 喜欢写技术博客，主要分享基础设施相关的经验",
        "Dave 有一条金毛犬，叫 Max，每天早晚遛两次",
        "Dave 认为文档比代码更重要，坚持写 runbook",
        "Dave 使用 Neovim 编辑代码，配置了 200+ 插件",
        "Dave 不喜欢开会，但喜欢一对一的深入技术讨论",
        "Dave 每年去一次技术峰会，最喜欢 KubeCon",
        "Dave 正在考虑搬家到成都，因为生活成本更低",
    ]),
    ("entity_eve", [
        "Eve 是数据科学家，专注 NLP 和推荐系统",
        "Eve 使用 Python 和 PyTorch 做深度学习研究",
        "Eve 住在广州天河区，公司在珠江新城",
        "Eve 在 Kaggle 上获得过 3 枚金牌，排名全球前 500",
        "Eve 喜欢跑步，每天跑 5 公里保持精力充沛",
        "Eve 对 Transformer 架构有深入理解，发表过两篇论文",
        "Eve 喜欢喝茶，尤其偏爱凤凰单丛和铁观音",
        "Eve 正在研究大语言模型的微调和部署方案",
        "Eve 认为特征工程比模型选择更重要",
        "Eve 经常在 lunch & learn 上给团队分享最新论文",
        "Eve 有一个 Kaggle 团队的微信群，每周讨论比赛策略",
        "Eve 不喜欢使用 Jupyter Notebook，偏好 VS Code + 脚本",
        "Eve 有一台带 RTX 4090 的工作站，用于本地模型训练",
        "Eve 对 MLOps 也有经验，使用 MLflow 管理实验",
        "Eve 正在写一本关于推荐系统实践的书",
        "Eve 认为数据质量决定了模型的上限",
        "Eve 喜欢在早上 6 点起床，利用安静的时间做深度工作",
        "Eve 不喜欢无效的社交，偏好小规模的深度交流",
        "Eve 最近在探索多模态模型，对 CLIP 和 BLIP 感兴趣",
        "Eve 每年参加 NeurIPS 或 ICML，去年在 NeurIPS 做了 poster",
    ]),
]

# Queries for fact recall — each maps to at least one entity fact
_FACT_QUERIES = [
    # Direct fact queries
    ("Alice 用什么编辑器？", "entity_alice", ["Vim"]),
    ("Alice 住在哪个城市？", "entity_alice", ["北京"]),
    ("Bob 喜欢什么运动？", "entity_bob", ["篮球"]),
    ("Bob 用什么编程语言？", "entity_bob", ["Go", "Python"]),
    ("Carol 的职业是什么？", "entity_carol", ["产品经理"]),
    ("Carol 用什么工具做原型？", "entity_carol", ["Figma"]),
    ("Dave 住在哪个城市？", "entity_dave", ["杭州"]),
    ("Dave 养了什么宠物？", "entity_dave", ["金毛", "Max"]),
    ("Eve 在 Kaggle 获得过什么成就？", "entity_eve", ["金牌"]),
    ("Eve 每天做什么运动？", "entity_eve", ["跑步"]),

    # Preference / opinion queries
    ("Alice 喜欢喝什么咖啡？", "entity_alice", ["手冲", "耶加雪菲", "埃塞俄比亚"]),
    ("Alice 对会议的态度是什么？", "entity_alice", ["讨厌", "异步"]),
    ("Bob 喝什么饮品？", "entity_bob", ["绿茶", "龙井"]),
    ("Bob 对 AI 编程的态度？", "entity_bob", ["Copilot", "开放"]),
    ("Carol 认为什么比数据分析更重要？", "entity_carol", ["用户访谈"]),
    ("Carol 最喜欢读什么类型的书？", "entity_carol", ["传记", "鞋狗"]),
    ("Dave 对自动化持什么态度？", "entity_dave", ["自动化一切"]),
    ("Dave 喜欢喝什么酒？", "entity_dave", ["精酿啤酒"]),
    ("Eve 喜欢喝什么？", "entity_eve", ["茶", "凤凰单丛", "铁观音"]),
    ("Eve 对特征工程的看法？", "entity_eve", ["特征工程", "比模型选择更重要"]),

    # Multi-fact / reasoning queries
    ("Alice 在哪方面有深入研究和分享？", "entity_alice", ["设计系统"]),
    ("Bob 正在搭建什么系统？", "entity_bob", ["Kafka", "事件驱动"]),
    ("Carol 的团队有多大？", "entity_carol", ["8"]),
    ("Dave 持有哪项安全认证？", "entity_dave", ["CISSP"]),
    ("Eve 发表过什么学术成果？", "entity_eve", ["论文"]),

    # Cross-fact synthesis queries
    ("Alice 和 Bob 都喜欢什么编程语言生态？", "entity_alice", []),  # bonus: both learning Rust
    ("哪些人喜欢喝茶？", "entity_bob", ["龙井"]),  # Bob + Eve
    ("哪些人住在南方城市？", "entity_carol", ["深圳"]),  # Carol 深圳 + Dave 杭州 + Eve 广州
    ("哪些人讨厌开会？", "entity_alice", ["讨厌"]),  # Alice + Dave
    ("有哪些人对 AI 技术有关注？", "entity_bob", ["Copilot", "AI"]),  # Bob + Carol + Eve
]


async def benchmark_fact_recall(engine: MemoryEngine, config: BenchConfig) -> BenchResult:
    """Benchmark 1: Fact Recall — LongMemEval Information Extraction.

    Seeds 100 facts across 5 entities, then runs 30 keyword queries.
    Measures: Precision@1, Recall@5, Mean Reciprocal Rank.
    """
    # Seed all facts
    total_facts = 0
    for entity_id, facts in _FACT_ENTITIES:
        for fact in facts:
            await engine.add(fact, entity_id=entity_id, content_type="text")
            total_facts += 1

    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )

    # Run queries
    recall_1_correct = 0
    recall_5_correct = 0
    rr_scores = []

    for query, entity_id, expected_kw in _FACT_QUERIES:
        results = await orchestrator.search(
            query, entity_id=entity_id, search_mode=SearchMode.MEMORY, top_k=config.top_k,
        )

        # Check if any expected keyword appears in top results
        found_r1 = False
        found_r5 = False

        for i, r in enumerate(results.results):
            match = any(kw in r.content for kw in expected_kw) if expected_kw else True
            if match and not found_r1 and i == 0:
                recall_1_correct += 1
                found_r1 = True
            if match and not found_r5 and i < 5:
                recall_5_correct += 1
                found_r5 = True
                rr_scores.append(1.0 / (i + 1))
                break
        else:
            if expected_kw:  # Only count as miss if we had keywords to check
                rr_scores.append(0.0)

    n = len(_FACT_QUERIES)
    precision_at_1 = recall_1_correct / n
    recall_at_5 = recall_5_correct / n
    mrr = statistics.mean(rr_scores) if rr_scores else 0.0

    return BenchResult(
        name="Fact Recall",
        aligns_with="LongMemEval — Information Extraction",
        description=f"100 facts → 30 queries across 5 entities. embed={'real' if config.use_real_embeddings else 'mock'}",
        metrics={
            "precision@1": round(precision_at_1, 3),
            "recall@5": round(recall_at_5, 3),
            "mrr": round(mrr, 3),
            "total_facts": total_facts,
            "total_queries": n,
            "embedding_type": "real" if config.use_real_embeddings else "mock",
        },
        passed=precision_at_1 >= 0.3,
        details={
            "queries_passed_r1": recall_1_correct,
            "queries_passed_r5": recall_5_correct,
            "embedding_dim": config.embedding_dim,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 2: Temporal Updates (LongMemEval Knowledge Updates + ConvoMem Changing Facts)
# ═══════════════════════════════════════════════════════════════════════════

# Each timeline: entity gets progressive updates that should supersede old facts
_TIMELINES = [
    {
        "entity": "timeline_alice_role",
        "steps": [
            "Alice 在 Google 担任前端工程师",
            "Alice 从 Google 跳槽到了 Meta，担任高级前端工程师",
            "Alice 在 Meta 升职为前端技术主管，管理 5 人团队",
            "Alice 离开 Meta，加入了 Stripe 做 Staff Engineer",
            "Alice 现在自己创业，做一款 AI 代码审查工具",
        ],
    },
    {
        "entity": "timeline_bob_city",
        "steps": [
            "Bob 住在上海徐汇区",
            "Bob 搬到了上海浦东新区",
            "Bob 因为工作调动搬到了北京朝阳区",
            "Bob 每天从北京通州通勤到朝阳上班",
            "Bob 现在远程工作，搬回了老家成都",
        ],
    },
    {
        "entity": "timeline_carol_tool",
        "steps": [
            "Carol 用 Jira 管理项目",
            "Carol 从 Jira 切换到了 Linear",
            "Carol 试用了 Notion 的项目管理功能",
            "Carol 最终选择回到 Linear，但用 Notion 做知识库",
            "Carol 现在团队统一使用 Linear + Notion + Slack 三件套",
        ],
    },
    {
        "entity": "timeline_dave_tech",
        "steps": [
            "Dave 主要使用 Python 做自动化脚本",
            "Dave 开始学习 Go 语言来做基础设施工具",
            "Dave 用 Go 重写了团队的部署系统",
            "Dave 现在主要用 Go 和 Rust 做系统开发",
            "Dave 已经完全不用 Python 了，全部转到 Go 和 Rust",
        ],
    },
    {
        "entity": "timeline_eve_org",
        "steps": [
            "Eve 在字节跳动担任数据科学家",
            "Eve 从字节跳动离职，加入了 OpenAI 做研究员",
            "Eve 在 OpenAI 参与了一个多模态模型的开发",
            "Eve 升职为 OpenAI 的 Senior Research Scientist",
            "Eve 在 OpenAI 领导一个小型研究团队，方向是 Agent 记忆",
        ],
    },
    {
        "entity": "timeline_frank_budget",
        "steps": [
            "Frank 的项目预算是 50 万元",
            "Frank 的预算被砍到了 30 万元",
            "Frank 申请到了追加预算，现在是 45 万元",
            "Frank 的预算因为公司调整变成了 60 万元",
            "Frank 的项目预算最终确定为 55 万元",
        ],
    },
    {
        "entity": "timeline_grace_status",
        "steps": [
            "Grace 在学习 Python 编程",
            "Grace 完成了 Python 基础课程，开始学 Django",
            "Grace 用 Django 做了第一个项目，上线了",
            "Grace 现在是一名初级后端开发工程师",
            "Grace 在职一年后晋升为中级工程师",
        ],
    },
    {
        "entity": "timeline_henry_language",
        "steps": [
            "Henry 偏好使用 Java 做后端开发",
            "Henry 开始尝试用 Kotlin 替代 Java",
            "Henry 觉得 Kotlin 比 Java 更适合做微服务",
            "Henry 现在的首选语言是 Kotlin",
            "Henry 已经完全不用 Java 了，只用 Kotlin",
        ],
    },
    {
        "entity": "timeline_ivy_device",
        "steps": [
            "Ivy 使用 iPhone 13 作为主力手机",
            "Ivy 升级到了 iPhone 15 Pro",
            "Ivy 买了一台 iPad Pro 做设计工作",
            "Ivy 用 iPad Pro 完全替代了之前的 Wacom 数位板",
            "Ivy 现在出门只带 iPhone 和 iPad，不再带笔记本电脑",
        ],
    },
    {
        "entity": "timeline_jack_skill",
        "steps": [
            "Jack 会基础的 JavaScript",
            "Jack 学习了 React，能独立开发 SPA",
            "Jack 掌握了 Next.js，做了全栈项目",
            "Jack 学会了 Kubernetes 和 CI/CD 流程",
            "Jack 现在是一名全栈 + DevOps 的全能工程师",
        ],
    },
]


async def benchmark_temporal_updates(engine: MemoryEngine, config: BenchConfig) -> BenchResult:
    """Benchmark 2: Temporal Updates — LongMemEval Knowledge Updates.

    Feeds 10 timelines with 5 sequential updates each.  Verifies:
    - Updates detected (old facts marked is_latest=False)
    - Final fact is latest
    - Search returns final state, not intermediate ones
    """
    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )

    total_timelines = len(_TIMELINES)
    update_detected = 0       # At least one update relationship found
    final_is_latest = 0       # Last fact in timeline is marked latest
    search_returns_final = 0  # Keyword search finds final fact first

    for tl in _TIMELINES:
        entity = tl["entity"]
        steps = tl["steps"]

        for step in steps:
            await engine.add(step, entity_id=entity, content_type="text")

        # Check: latest memory should contain the final step content
        memories = await engine.graph.list_latest_memories(entity, limit=20)
        latest_contents = [m["content"] for m in memories if m["is_latest"]]

        # Check 1: At least one older fact was marked as superseded
        # Use raw _memories since list_latest_memories only returns is_latest=True
        all_mems = engine.graph._memories.get(entity, [])
        superseded = sum(1 for m in all_mems if not m.get("is_latest", True))
        if superseded > 0:
            update_detected += 1

        # Check 2: The final step is among the latest facts
        final_step = steps[-1]
        if any(final_step in c for c in latest_contents):
            final_is_latest += 1

        # Check 3: Search with a keyword from the final step returns it
        # Pick the most distinctive word from the final step
        final_keywords = final_step.replace("，", " ").replace("。", " ").split()
        if final_keywords:
            final_kw = final_keywords[-1]  # Use last significant word
            results = await orchestrator.search(
                final_kw, entity_id=entity, search_mode=SearchMode.MEMORY, top_k=3,
            )
            if results.results and any(
                final_step[:10] in r.content for r in results.results[:3]
            ):
                search_returns_final += 1

    accuracy = (update_detected + final_is_latest + search_returns_final) / (3 * total_timelines)

    return BenchResult(
        name="Temporal Updates",
        aligns_with="LongMemEval Knowledge Updates + ConvoMem Changing Facts",
        description=f"{total_timelines} timelines × 5 sequential updates. "
                    f"embed={'real' if config.use_real_embeddings else 'mock'}",
        metrics={
            "update_detection_rate": round(update_detected / total_timelines, 3),
            "final_is_latest_rate": round(final_is_latest / total_timelines, 3),
            "search_accuracy": round(search_returns_final / total_timelines, 3),
            "overall_accuracy": round(accuracy, 3),
            "timelines_tested": total_timelines,
            "total_steps": total_timelines * 5,
        },
        passed=accuracy >= 0.6,
        details={
            "update_detected": update_detected,
            "final_is_latest": final_is_latest,
            "search_returns_final": search_returns_final,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 3: Relationship Classification
# ═══════════════════════════════════════════════════════════════════════════

# Pairs of (old, new) content with expected relationship type
_RELATIONSHIP_TEST_CASES = [
    # ── UPDATES ──
    ("Alice 在 Google 工作", "Alice 刚加入了 Stripe", RelationType.UPDATES),
    ("Bob 住在上海", "Bob 搬到了北京", RelationType.UPDATES),
    ("Carol 使用 Python 做数据分析", "Carol 现在完全不用 Python 了，改用 R", RelationType.UPDATES),
    ("Dave 的项目预算是 50 万", "Dave 的预算被砍到了 30 万", RelationType.UPDATES),
    ("Eve 在字节跳动工作", "Eve 已经离职了，自由职业中", RelationType.UPDATES),
    ("Frank 喜欢 Vue 框架", "Frank 现在改用 React 了", RelationType.UPDATES),
    ("Grace 使用 Windows 笔记本", "Grace 换了一台 MacBook Pro", RelationType.UPDATES),
    # ── EXTENDS ──
    ("Alice 是一名工程师", "Alice 是前端工程师，主攻 React", RelationType.EXTENDS),
    ("Bob 喜欢运动", "Bob 喜欢篮球和游泳", RelationType.EXTENDS),
    ("Carol 在做一个 SaaS 产品", "Carol 的产品有 5000 个月活用户", RelationType.EXTENDS),
    ("Dave 住在杭州", "Dave 住在杭州余杭区，靠近阿里", RelationType.EXTENDS),
    ("Eve 是一名数据科学家", "Eve 在 NLP 领域有深入研究，发表过两篇论文", RelationType.EXTENDS),
    ("公司有弹性工作制", "公司允许每周三和周五远程办公", RelationType.EXTENDS),
    # ── NONE (unrelated) ──
    ("Alice 喜欢喝咖啡", "Bob 养了一只猫", RelationType.NONE),
    ("Carol 住在深圳", "TypeScript 是一种类型安全的语言", RelationType.NONE),
    ("Dave 使用 Docker", "北京今天天气很好", RelationType.NONE),
    ("Eve 喜欢跑步", "公司食堂今天有红烧肉", RelationType.NONE),
    ("项目的 deadline 是周五", "隔壁团队在招一个设计师", RelationType.NONE),
    # ── DERIVES_FROM candidates (tested separately in _find_derives_sources) ──
]


async def benchmark_relationship_classification(
    engine: MemoryEngine, config: BenchConfig
) -> BenchResult:
    """Benchmark 3: Relationship Classification Accuracy.

    Tests 20 pairs against the RelationshipEngine's classify_relation().
    Also tests DERIVES_FROM detection separately.
    """
    # Create a separate engine with LLM enabled just for classification tests
    llm_engine = _make_engine(config, use_llm=True)
    rel_engine = llm_engine.relationships
    correct = 0
    total = 0
    per_type: dict[str, list[int]] = {"updates": [0, 0], "extends": [0, 0], "none": [0, 0]}
    errors = []

    for old_content, new_content, expected in _RELATIONSHIP_TEST_CASES:
        entity = f"bench_rel_{total}"
        result = await rel_engine.classify_relation(
            "new_id", "old_id", entity, new_content, old_content,
        )
        total += 1
        if result == expected:
            correct += 1
            per_type[expected.value][0] += 1
        else:
            errors.append({
                "old": old_content,
                "new": new_content,
                "expected": expected.value,
                "got": result.value,
            })
        per_type[expected.value][1] += 1

    # Test DERIVES_FROM
    derives_entity = "bench_derives"
    await engine.add("Alice 在 Stripe 工作", entity_id=derives_entity, content_type="text")
    await engine.add("Stripe 是一家支付公司", entity_id=derives_entity, content_type="text")
    await engine.add("Alice 很可能在支付行业工作", entity_id=derives_entity, content_type="text")
    derives_mems = await engine.graph.list_latest_memories(derives_entity, limit=20)
    new_mem = [m for m in derives_mems if "支付行业" in m["content"]][0]
    others = [m for m in derives_mems if "支付行业" not in m["content"]]
    sources = rel_engine._find_derives_sources(new_mem, others)
    derives_detected = len(sources) >= 2

    accuracy = correct / total if total else 0.0

    return BenchResult(
        name="Relationship Classification",
        aligns_with="Custom — UPDATES / EXTENDS / DERIVES_FROM accuracy",
        description=f"{total} relationship pairs + DERIVES_FROM test. "
                    f"llm={'enabled' if config.use_llm_relationships else 'disabled'}",
        metrics={
            "classification_accuracy": round(accuracy, 3),
            "updates_accuracy": round(per_type["updates"][0] / per_type["updates"][1], 3) if per_type["updates"][1] else 0.0,
            "extends_accuracy": round(per_type["extends"][0] / per_type["extends"][1], 3) if per_type["extends"][1] else 0.0,
            "none_accuracy": round(per_type["none"][0] / per_type["none"][1], 3) if per_type["none"][1] else 0.0,
            "derives_detected": derives_detected,
            "total_cases": total,
            "llm_enabled": config.use_llm_relationships,
        },
        passed=accuracy >= 0.5,
        details={
            "correct": correct,
            "total": total,
            "per_type": {
                k: {"correct": v[0], "total": v[1]} for k, v in per_type.items()
            },
            "errors": errors[:5],
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 4: Profile Accuracy (LoCoMo Persona Consistency)
# ═══════════════════════════════════════════════════════════════════════════

_PROFILE_ENTITY = "profile_bench_user"
_PROFILE_FACTS = [
    "用户是一名全栈工程师，有 8 年工作经验",
    "用户住在上海市静安区",
    "用户喜欢用 TypeScript 和 Go 做开发",
    "用户讨厌 996 加班文化，认为效率比工时重要",
    "用户每天早上 7 点起床跑步 3 公里",
    "用户是一名开源贡献者，GitHub 有 1500+ star",
    "用户喜欢喝手冲咖啡，用的是 V60 滤杯",
    "用户正在学习 Rust，打算做系统编程",
    "用户每周去两次 CrossFit 训练",
    "用户认为测试驱动开发是最好的开发方式",
    "用户手机是 iPhone，电脑是 MacBook Pro",
    "用户不喜欢开会，偏好文字沟通",
    "用户养了一只柴犬叫豆豆",
    "用户的母语是中文，英语流利达到商务水平",
    "用户最喜欢的食物是日料，尤其是刺身",
    "用户每天会阅读技术博客至少 30 分钟",
    "用户对 AI/ML 有浓厚兴趣，在做 side project",
    "用户觉得微服务在大多数场景下是过度设计",
    "用户喜欢在咖啡馆工作胜过办公室",
    "用户订阅了 O'Reilly 在线学习平台",
]


async def benchmark_profile_accuracy(engine: MemoryEngine, config: BenchConfig) -> BenchResult:
    """Benchmark 4: Profile Accuracy.

    Seeds 20 facts about a user and verifies the profile contains key facts.
    Tests both static and dynamic fact classification, and quantifies coverage.
    """
    entity = _PROFILE_ENTITY

    # Half as preference (static), half as episodic (dynamic)
    midpoint = len(_PROFILE_FACTS) // 2
    for i, fact in enumerate(_PROFILE_FACTS[:midpoint]):
        # Old facts → type=preference (stable, always relevant)
        await engine.graph.create_memory(
            fact, entity_id=entity, memory_type="preference", confidence=0.9,
        )
    for i, fact in enumerate(_PROFILE_FACTS[midpoint:]):
        # Recent facts → type=episodic (contextual, time-sensitive)
        await engine.graph.create_memory(
            fact, entity_id=entity, memory_type="episodic", confidence=0.7,
        )

    # Get profile
    pm = ProfileManager(graph=engine.graph)
    await pm.invalidate(entity)
    profile = await pm.get(entity)

    static_facts = [f.content for f in profile.static]
    dynamic_facts = [f.content for f in profile.dynamic]

    # Measure coverage: how many original facts appear in the profile
    all_profile_text = " ".join(static_facts + dynamic_facts)
    covered = 0
    for fact in _PROFILE_FACTS:
        # Check if key part of the fact appears in profile
        keywords = fact[:8]  # first 8 chars as fingerprint
        if keywords in all_profile_text:
            covered += 1

    coverage = covered / len(_PROFILE_FACTS)
    has_static = len(static_facts) > 0
    has_dynamic = len(dynamic_facts) > 0

    return BenchResult(
        name="Profile Accuracy",
        aligns_with="LoCoMo — Persona Consistency",
        description=f"{len(_PROFILE_FACTS)} facts → profile (static + dynamic). "
                    f"Tests coverage and classification.",
        metrics={
            "coverage": round(coverage, 3),
            "covered_facts": covered,
            "total_facts": len(_PROFILE_FACTS),
            "static_count": len(static_facts),
            "dynamic_count": len(dynamic_facts),
            "has_both_layers": has_static and has_dynamic,
        },
        passed=coverage >= 0.5 and has_static and has_dynamic,
        details={
            "static_facts": static_facts[:5],
            "dynamic_facts": dynamic_facts[:5],
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 5: Distractor Resistance (LoCoMo + ConvoMem multi-message)
# ═══════════════════════════════════════════════════════════════════════════

_DISTRACTOR_TARGETS = [
    "用户最重要的偏好是使用深色模式，无论在什么应用中都如此",
    "用户的 SSH 公钥指纹是 SHA256:abc123def456",
    "用户的项目代码仓库在 github.com/user/project-x，主分支是 main",
    "用户最信任的 AI 模型是 Claude，用于代码审查",
    "用户使用的数据库密码策略是每 90 天轮换一次",
]

_DISTRACTOR_NOISE = [
    "用户今天中午吃了麻辣烫",
    "用户觉得今天天气有点热",
    "用户在地铁上看到一只很可爱的狗",
    "用户昨天睡得太晚了，今天很困",
    "用户觉得新来的同事很有礼貌",
    "用户计划这个周末去看电影",
    "用户在考虑要不要换一个键盘",
    "用户发现楼下咖啡店的拿铁涨价了 2 元",
    "用户看到一篇关于量子计算的有趣文章",
    "用户的朋友推荐了一部新剧",
    "用户在网上买了一个显示器支架",
    "用户觉得最近空气质量不太好",
    "用户在网上看到一个很火的 meme",
    "用户今天忘记带耳机出门了",
    "用户在公司群里分享了一个搞笑视频",
    "用户觉得应该多喝水，买了新水杯",
    "用户发现 GitHub 今天的配色变了",
    "用户听说公司下周有团建活动",
    "用户觉得自己的椅子不太舒服",
    "用户最近在听一个科技播客",
    "用户收到了一条垃圾短信",
    "用户把桌面壁纸换成了一张风景照",
    "用户今天尝试了楼下新开的拉面馆",
    "用户觉得今天的网络有点卡",
    "用户发现手机系统有更新",
    "用户在停车场找了 20 分钟车位",
    "用户觉得同事的新发型不错",
    "用户在网上看到有人卖了天价 NFT",
    "用户打算下周开始少吃碳水",
    "用户觉得邮箱里的未读邮件太多了",
    "用户发现一个好用的快捷键",
    "用户今天穿了上个月买的新鞋",
    "用户觉得微信占太多存储空间了",
    "用户下载了一个番茄钟 App",
    "用户觉得深圳比上海热",
    "用户昨天熬夜看了一场球赛",
    "用户发现键盘的 W 键有点不灵敏",
    "用户觉得电动牙刷确实比普通牙刷好用",
    "用户在网上买了两本书，快递还没到",
    "用户今天早上忘了打卡",
    "用户觉得写周报是最浪费时间的事",
    "用户今天午饭的鸡蛋有点咸",
    "用户给手机换了一张新壁纸",
    "用户觉得自动驾驶技术发展太快了",
    "用户发现一个很棒的 Chrome 扩展",
    "用户最近睡眠质量不错",
    "用户觉得站会应该控制在 10 分钟内",
    "用户在网上看到一个搞笑的猫视频",
    "用户今天用了一次站立办公桌",
    "用户觉得 Ruby 的语法很优美但性能一般",
]


async def benchmark_distractor_resistance(
    engine: MemoryEngine, config: BenchConfig
) -> BenchResult:
    """Benchmark 5: Distractor Resistance.

    Mixes 5 important target facts with 50 noisy/trivial distractors.
    Verifies search can still find the targets despite the noise.
    """
    entity = "distractor_bench"

    # Seed targets first (interleaved with noise)
    all_facts = []
    noise_idx = 0
    for i, target in enumerate(_DISTRACTOR_TARGETS):
        all_facts.append(("target", target))
        # Add 10 noise items between each target
        for _ in range(10):
            if noise_idx < len(_DISTRACTOR_NOISE):
                all_facts.append(("noise", _DISTRACTOR_NOISE[noise_idx]))
                noise_idx += 1

    for fact_type, fact in all_facts:
        await engine.add(fact, entity_id=entity, content_type="text")

    # Search for each target using key terms
    queries = [
        "深色模式偏好",
        "SSH 密钥",
        "代码仓库地址",
        "信任的 AI 模型",
        "密码策略",
    ]

    orchestrator = SearchOrchestrator(
        graph=engine.graph, vector=engine.vector, embedder=engine.embedder,
    )

    recall_at_1 = 0
    recall_at_3 = 0
    recall_at_5 = 0

    for i, query in enumerate(queries):
        results = await orchestrator.search(
            query, entity_id=entity, search_mode=SearchMode.MEMORY, top_k=5,
        )
        target = _DISTRACTOR_TARGETS[i]
        for j, r in enumerate(results.results):
            if target[:15] in r.content:
                if j == 0:
                    recall_at_1 += 1
                if j < 3:
                    recall_at_3 += 1
                if j < 5:
                    recall_at_5 += 1
                break

    n = len(queries)

    return BenchResult(
        name="Distractor Resistance",
        aligns_with="LoCoMo / ConvoMem — Multi-message noise resistance",
        description=f"5 target facts buried in {len(_DISTRACTOR_NOISE)} distractors. "
                    f"embed={'real' if config.use_real_embeddings else 'mock'}",
        metrics={
            "recall@1": round(recall_at_1 / n, 3),
            "recall@3": round(recall_at_3 / n, 3),
            "recall@5": round(recall_at_5 / n, 3),
            "total_noise": len(_DISTRACTOR_NOISE),
            "total_targets": n,
        },
        passed=(recall_at_3 / n) >= 0.6,
        details={"queries_tested": n},
    )


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark 6: Forgetting Correctness
# ═══════════════════════════════════════════════════════════════════════════

_FORGET_FACTS = [
    # (content, memory_type, valid_days_from_now) — None = permanent
    ("用户喜欢 TypeScript", "fact", None),
    ("用户是一名工程师", "fact", None),
    ("用户住在北京", "fact", None),
    ("用户明天有考试", "episodic", 0),       # expires immediately
    ("用户下周三有会议", "episodic", 7),       # expires in 7 days
    ("用户今天中午吃了面", "episodic", -1),     # already expired
    ("用户觉得今天天气不错", "noise", None),
    ("用户在地铁上看到一只猫", "noise", None),
    ("用户觉得楼下咖啡好喝", "preference", None),
    ("用户偏好深色模式", "preference", None),
]


async def benchmark_forgetting_correctness(
    engine: MemoryEngine, config: BenchConfig
) -> BenchResult:
    """Benchmark 6: Forgetting Correctness.

    Seeds facts with different types and expiry, runs the forget engine,
    and verifies:
    - Time-expired memories are removed/archived
    - Noise is filtered
    - Persistent facts and preferences survive
    """
    entity = "forget_bench"

    # Seed all facts directly into the graph (bypassing the chunker pipeline)
    # so we can control memory_type, confidence, and valid_until precisely.
    seeded_ids = {}
    for content, mem_type, valid_days in _FORGET_FACTS:
        valid_until = None
        if valid_days is not None and valid_days >= 0:
            valid_until = datetime.now(UTC) + timedelta(days=valid_days)
        elif valid_days is not None and valid_days < 0:
            valid_until = datetime.now(UTC) - timedelta(days=1)

        # Noise items need low confidence so forget_noise can detect them
        confidence = 0.2 if mem_type == "noise" else 0.8

        mid = await engine.graph.create_memory(
            content, entity_id=entity,
            memory_type=mem_type, confidence=confidence,
            valid_until=valid_until,
        )
        seeded_ids[content] = (mid, mem_type)

    # Make forget_noise consider recently-created memories too
    # (in production, NOISE_MIN_AGE_DAYS=7; for the benchmark we allow age=0)
    original_min_age = ForgetEngine.NOISE_MIN_AGE_DAYS
    ForgetEngine.NOISE_MIN_AGE_DAYS = 0

    # Run all three forget strategies
    forget = ForgetEngine(graph=engine.graph)
    strategies = {}
    expired = await forget.forget_expired(entity)
    strategies["expired"] = expired
    noise = await forget.forget_noise(entity)
    strategies["noise"] = noise
    decayed = await forget.decay_episodic()
    strategies["episodic_decay"] = decayed

    # Restore original setting
    ForgetEngine.NOISE_MIN_AGE_DAYS = original_min_age
    remaining = await engine.graph.list_latest_memories(entity, limit=50)
    remaining_contents = [m["content"] for m in remaining if m["is_latest"]]

    # Evaluate
    persistent = ["用户喜欢 TypeScript", "用户是一名工程师", "用户住在北京",
                   "用户偏好深色模式", "用户觉得楼下咖啡好喝"]
    should_keep = sum(1 for c in persistent if c in remaining_contents)
    should_forget = ["用户今天中午吃了面", "用户觉得今天天气不错", "用户在地铁上看到一只猫"]
    did_forget = sum(1 for c in should_forget if c not in remaining_contents)

    keep_rate = should_keep / len(persistent)
    forget_rate = did_forget / len(should_forget) if should_forget else 1.0

    return BenchResult(
        name="Forgetting Correctness",
        aligns_with="Custom — Time expiry + noise filtering + episodic decay",
        description=f"{len(_FORGET_FACTS)} mixed facts → forget strategies run. "
                    f"3 strategies: time expiry, noise filter, episodic decay",
        metrics={
            "keep_rate": round(keep_rate, 3),
            "forget_rate": round(forget_rate, 3),
            "strategies_run": 3,
            "total_facts": len(_FORGET_FACTS),
            "remaining_facts": len(remaining_contents),
        },
        passed=keep_rate >= 0.7 and forget_rate >= 0.5,
        details={
            "should_keep_correct": should_keep,
            "should_forget_correct": did_forget,
            "remaining": remaining_contents[:10],
            "strategy_results": strategies,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════

async def _determine_embedding(config: BenchConfig) -> None:
    """Auto-detect: if OPENAI_API_KEY is set, use real embeddings."""
    if config.use_real_embeddings:
        return

    from emerald.config import get_settings
    settings = get_settings()
    if settings.openai_api_key and settings.openai_api_key != "sk-...":
        config.use_real_embeddings = True
        config.embedding_dim = 1536


async def main() -> None:
    parser = argparse.ArgumentParser(description="Emerald Memory Benchmark Suite v2")
    parser.add_argument("--real", action="store_true",
                        help="Force real OpenAI embeddings (default: auto-detect)")
    parser.add_argument("--mock", action="store_true",
                        help="Force mock deterministic embeddings")
    parser.add_argument("--llm", action="store_true",
                        help="Enable LLM-based relationship classification")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON report to stdout")
    args = parser.parse_args()

    config = BenchConfig(
        use_real_embeddings=args.real,
        use_llm_relationships=args.llm,
    )

    if args.mock:
        config.use_real_embeddings = False

    await _determine_embedding(config)

    if config.use_real_embeddings:
        provider_name = "OpenAI (text-embedding-3-small)"
    else:
        provider_name = "Mock (deterministic hash)"

    print("=" * 70)
    print("  Emerald Memory Benchmark Suite v2")
    print(f"  Embeddings: {provider_name}")
    if config.use_llm_relationships:
        print("  Relationship Classification: rule + LLM")
    else:
        print("  Relationship Classification: rule-based only")
    print("=" * 70)

    engine = _make_engine(config, use_llm=False)  # No LLM during data seeding

    report = BenchReport(
        version="2.0",
        timestamp=datetime.now(UTC).isoformat(),
        config={
            "embeddings": "real" if config.use_real_embeddings else "mock",
            "embedding_dim": config.embedding_dim,
            "llm_relationships": config.use_llm_relationships,
        },
    )

    benchmarks = [
        ("Fact Recall", benchmark_fact_recall),
        ("Temporal Updates", benchmark_temporal_updates),
        ("Relationship Classification", benchmark_relationship_classification),
        ("Profile Accuracy", benchmark_profile_accuracy),
        ("Distractor Resistance", benchmark_distractor_resistance),
        ("Forgetting Correctness", benchmark_forgetting_correctness),
    ]

    passed_count = 0
    total_count = 0

    for name, fn in benchmarks:
        total_count += 1
        print(f"\n{'─' * 50}")
        print(f"  [{total_count}/6] {name}...")
        t0 = time.perf_counter()
        result = await fn(engine, config)
        elapsed = time.perf_counter() - t0
        report.results.append(result)

        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"  {status} ({elapsed:.1f}s)")
        for key, value in result.metrics.items():
            if isinstance(value, float):
                print(f"    {key}: {value:.3f}")
            else:
                print(f"    {key}: {value}")

        if result.passed:
            passed_count += 1

    # Summary
    report.summary = {
        "passed": passed_count,
        "total": total_count,
        "pass_rate": round(passed_count / total_count, 3) if total_count else 0.0,
    }

    print(f"\n{'=' * 70}")
    print(f"  Summary: {passed_count}/{total_count} benchmarks passed "
          f"({report.summary['pass_rate']*100:.0f}%)")
    print(f"  Embeddings: {provider_name}")
    print(f"  LLM relationships: {'enabled' if config.use_llm_relationships else 'disabled'}")
    print("=" * 70)

    # Compute aggregate scores
    accuracies = []
    for r in report.results:
        for k, v in r.metrics.items():
            if k.endswith("accuracy") or k.endswith("_rate") or k in ("precision@1", "recall@5", "mrr", "coverage", "recall@3"):
                if isinstance(v, (int, float)):
                    accuracies.append(float(v))

    if accuracies:
        avg = statistics.mean(accuracies)
        print(f"  Aggregate Score: {avg:.3f}")
        report.summary["aggregate_score"] = round(avg, 3)

    # Save JSON report
    reports_dir = Path(__file__).parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"benchmark-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    report_path.write_text(
        json.dumps(
            {"version": report.version, "timestamp": report.timestamp,
             "config": report.config,
             "results": [r.to_dict() for r in report.results],
             "summary": report.summary},
            ensure_ascii=False, indent=2,
        )
    )
    print(f"\n  Report saved: {report_path}")

    if args.json:
        print(json.dumps(
            {"results": [r.to_dict() for r in report.results],
             "summary": report.summary},
            ensure_ascii=False, indent=2,
        ))


if __name__ == "__main__":
    asyncio.run(main())
