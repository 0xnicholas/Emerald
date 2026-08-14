"""Deterministic community-forgetting scenario (B5 T4, ticket #40).

One corpus definition, one metric definition, one runner — shared by the
in-memory aggregate gate (test_community_forgetting.py) and the
real-storage Neo4j variant (test_neo4j_community_variants.py) so both
backends execute the exact same scenario against the same thresholds.

Corpus (spec #36 / ticket #40): two expired communities (stale, low
confidence, 120 days old, densely interlinked) + one active community
(recent, high confidence) + one bridge memory connecting the stale pair
+ one profile-referenced signal community. Mock embeddings, rule-only
path (no LLM), backdated timestamps — every outcome is a pure function
of the backdated ages, so the suite never depends on the wall clock.

Expected outcome (the documented bridge invariant, see
tests/unit/test_forget_communities.py):

- the two expired communities are eliminated as clusters — 9 of their 11
  members are forgotten through ``mark_expired`` with reason
  ``community_forgotten``;
- the bridge memory and exactly one of its two boundary endpoints
  survive (bridge exemption, spec #36 story 7). Which endpoint survives
  depends on memory-id ordering and is deliberately not pinned — the
  count and the set shape are the invariant;
- the active community (activity keep) and the profile-referenced signal
  community (exempt_profile) survive untouched.

Metrics (all must pass for the suite to be green):

- community elimination rate >= 0.95 (expired communities gone as clusters)
- signal survival rate       >= 0.98 (active/bridge/profile signals latest)
- retrieval retention rate   >= 0.95 (surviving signals still searchable)

Pre/post retrieval sets are asserted exactly (acceptance criterion 2):
before forgetting every corpus memory is searchable; afterwards only the
expired-community memories are gone and every signal stays searchable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from emerald.core.forget import ForgetEngine
from emerald.core.graph import GraphStore
from emerald.core.search import SearchMode, SearchOrchestrator

Backdate = Callable[[str, int], Awaitable[None]]

ELIMINATION_THRESHOLD = 0.95
SURVIVAL_THRESHOLD = 0.98
RETRIEVAL_THRESHOLD = 0.95

STALE_AGE_DAYS = 120
PROFILE_AGE_DAYS = 90
ACTIVE_AGE_DAYS = 1

# Expected outcome invariants (see module docstring).
EXPECTED_FORGOTTEN_COUNT = 9
EXPECTED_SURVIVOR_COUNT = 10  # bridge + boundary endpoint + active 5 + profile 3

STALE_A_CONTENTS = [
    "Alpha 部署脚本放在仓库根目录",
    "Alpha 后端服务用 Go 重写",
    "Alpha 数据迁移在七月完成",
    "Alpha 压测报告已归档",
    "Alpha 结项复盘记录",
]
STALE_B_CONTENTS = [
    "Beta 登录模块改用 OAuth",
    "Beta 支付回调曾出现重复通知",
    "Beta 灰度发布只覆盖小部分用户",
    "Beta 性能瓶颈在数据库连接池",
    "Beta 结项时下线了旧接口",
]
BRIDGE_CONTENT = "Alpha 和 Beta 共用同一套 CI 模板"
ACTIVE_CONTENTS = [
    "Gamma 正在设计新的推荐排序",
    "Gamma 本周完成了向量检索压测",
    "Gamma 与设计团队对齐了交互稿",
    "Gamma 刚确定了下个迭代范围",
    "Gamma 正在迁移到新的部署平台",
]
PROFILE_CONTENTS = [
    "用户偏好 Kotlin 胜过 Java",
    "Kotlin 项目随手笔记一",
    "Kotlin 项目随手笔记二",
]

# Stale confidences 0.15..0.19 — trust stays below the profile's static
# threshold (0.5), so the expired communities are never profile-exempt.
STALE_CONFIDENCES = [0.15 + 0.01 * i for i in range(5)]


class Metric:
    """Count pass/fail outcomes; assert the pass-rate threshold at the end."""

    def __init__(self, name: str, threshold: float) -> None:
        self.name = name
        self.threshold = threshold
        self.numerator = 0
        self.denominator = 0

    def record(self, ok: bool) -> None:
        self.denominator += 1
        if ok:
            self.numerator += 1

    @property
    def rate(self) -> float:
        if self.denominator == 0:
            return 1.0
        return self.numerator / self.denominator

    def assert_threshold(self) -> None:
        assert self.rate >= self.threshold, (
            f"{self.name}: {self.rate:.4f} < {self.threshold} ({self.numerator}/{self.denominator})"
        )


@dataclass(frozen=True)
class CommunityCorpus:
    """Memory ids and contents of the deterministic community corpus."""

    entity_id: str
    stale_a: list[str]
    stale_b: list[str]
    bridge: str
    active: list[str]
    profile_signal: list[str]
    contents: dict[str, str]

    @property
    def boundary_endpoints(self) -> tuple[str, str]:
        """The bridge's two neighbors — one of them survives by mandate."""
        return (self.stale_a[0], self.stale_b[0])

    @property
    def stale_pool(self) -> list[str]:
        return [*self.stale_a, *self.stale_b]

    @property
    def all_ids(self) -> list[str]:
        return [
            *self.stale_a,
            *self.stale_b,
            self.bridge,
            *self.active,
            *self.profile_signal,
        ]


async def seed_community_corpus(
    store: GraphStore,
    vector: Any,
    embedder: Any,
    entity_id: str,
    *,
    backdate: Backdate,
) -> CommunityCorpus:
    """Seed the deterministic corpus: memories, edges, embeddings, ages.

    Memories are created through the graph store (precise control over
    confidence and memory_type), linked with EXTENDS edges, backdated via
    the caller-provided ``backdate`` hook, and indexed into the vector
    store with the mock embedder — the same record a full pipeline ingest
    would produce, without the rule-based relationship inference possibly
    archiving corpus members mid-seed (the corpus is the forgetting
    scenario's input, not the ingestion pipeline's).
    """
    contents: dict[str, str] = {}

    async def create(content: str, *, memory_type: str, confidence: float, days: int) -> str:
        mid = await store.create_memory(
            content,
            entity_id=entity_id,
            memory_type=memory_type,
            confidence=confidence,
        )
        await backdate(mid, days)
        contents[mid] = content
        return mid

    async def link(first: str, second: str) -> None:
        await store.create_relationship(first, second, "EXTENDS")

    async def clique(
        contents_: list[str],
        *,
        confidences: list[float],
        memory_type: str,
        days: int,
    ) -> list[str]:
        ids = [
            await create(
                content,
                memory_type=memory_type,
                confidence=confidence,
                days=days,
            )
            for content, confidence in zip(contents_, confidences, strict=True)
        ]
        for i, first in enumerate(ids):
            for second in ids[i + 1 :]:
                await link(first, second)
        return ids

    stale_a = await clique(
        STALE_A_CONTENTS,
        confidences=STALE_CONFIDENCES,
        memory_type="fact",
        days=STALE_AGE_DAYS,
    )
    stale_b = await clique(
        STALE_B_CONTENTS,
        confidences=STALE_CONFIDENCES,
        memory_type="fact",
        days=STALE_AGE_DAYS,
    )
    bridge = await create(
        BRIDGE_CONTENT,
        memory_type="fact",
        confidence=0.2,
        days=STALE_AGE_DAYS,
    )
    await link(bridge, stale_a[0])
    await link(bridge, stale_b[0])

    # Active community: recent high-confidence observations. Observation
    # type is deliberately not profile-eligible (static needs fact/
    # preference, dynamic needs episodic) so its keep decision comes from
    # activity alone, not from a profile reference.
    active = await clique(
        ACTIVE_CONTENTS,
        confidences=[0.8] * len(ACTIVE_CONTENTS),
        memory_type="observation",
        days=ACTIVE_AGE_DAYS,
    )

    # Profile-referenced signal: an old, low-activity chain whose first
    # member is a static profile fact — the whole community is exempt
    # even though its activity score is below threshold.
    profile_signal = [
        await create(
            PROFILE_CONTENTS[0],
            memory_type="fact",
            confidence=0.9,
            days=PROFILE_AGE_DAYS,
        ),
        await create(
            PROFILE_CONTENTS[1],
            memory_type="fact",
            confidence=0.2,
            days=PROFILE_AGE_DAYS,
        ),
        await create(
            PROFILE_CONTENTS[2],
            memory_type="fact",
            confidence=0.2,
            days=PROFILE_AGE_DAYS,
        ),
    ]
    await link(profile_signal[0], profile_signal[1])
    await link(profile_signal[1], profile_signal[2])

    for mid, content in contents.items():
        embedding = (await embedder.embed([content]))[0]
        await vector.store(mid, content, embedding, entity_id=entity_id)

    return CommunityCorpus(
        entity_id=entity_id,
        stale_a=stale_a,
        stale_b=stale_b,
        bridge=bridge,
        active=active,
        profile_signal=profile_signal,
        contents=contents,
    )


@dataclass
class ScenarioResult:
    """One run's metrics plus the exact forgotten/survivor sets."""

    elimination: Metric
    survival: Metric
    retrieval: Metric
    forgotten: set[str]
    survivors: set[str]


def make_orchestrator(
    store: GraphStore,
    vector: Any,
    embedder: Any,
) -> SearchOrchestrator:
    """SearchOrchestrator wired to the deterministic graph + vector pair."""
    return SearchOrchestrator(graph=store, vector=vector, embedder=embedder)


async def search_contents(
    orchestrator: SearchOrchestrator,
    q: str,
    entity_id: str,
) -> list[str]:
    """Memory-mode search; returns the result contents.

    The suite queries exact corpus contents and asserts presence/absence
    across the whole entity pool, not ranking quality (ranking is guarded
    by the other sections). Search scores are ``cosine × trust``, so a
    low-confidence signal (bridge 0.2, profile notes 0.2) can rank below
    high-trust fuzzy matches on its own exact query and get dropped by
    gap truncation — probing the full pool with truncation off keeps the
    assertions exact: present iff latest, absent iff forgotten.
    """
    response = await orchestrator.search(
        q,
        entity_id=entity_id,
        search_mode=SearchMode.MEMORY,
        top_k=50,
        dynamic_truncation=False,
    )
    return [result.content.strip() for result in response.results]


async def run_community_forgetting(
    store: GraphStore,
    orchestrator: SearchOrchestrator,
    corpus: CommunityCorpus,
) -> ScenarioResult:
    """Run the scenario and return the three metrics with hard asserts.

    Exact pre/post retrieval-set assertions (acceptance criterion 2):
    baseline search must surface every corpus memory; afterwards only the
    expired-community memories are gone and every signal stays
    searchable.
    """
    elimination = Metric("community_elimination_rate", ELIMINATION_THRESHOLD)
    survival = Metric("signal_survival_rate", SURVIVAL_THRESHOLD)
    retrieval = Metric("retrieval_retention_rate", RETRIEVAL_THRESHOLD)
    entity_id = corpus.entity_id

    async def retrievable(mid: str) -> bool:
        content = corpus.contents[mid]
        found = await search_contents(orchestrator, content, entity_id)
        return content in found

    # Baseline: before forgetting, every corpus memory is retrievable.
    for mid in corpus.all_ids:
        assert await retrievable(mid), f"Baseline retrieval failed for {corpus.contents[mid]!r}"

    forgotten_count = await ForgetEngine(graph=store).forget_communities(entity_id)
    assert forgotten_count == EXPECTED_FORGOTTEN_COUNT, (
        f"forget_communities forgot {forgotten_count} memories, expected {EXPECTED_FORGOTTEN_COUNT}"
    )

    # Exact survivor shape on the stale side: the bridge plus exactly one
    # of its two boundary endpoints — nothing else may survive.
    stale_side = [*corpus.stale_pool, corpus.bridge]
    stale_survivors = {mid for mid in stale_side if (await store.get_memory(mid))["is_latest"]}
    endpoint_survivors = stale_survivors & set(corpus.boundary_endpoints)
    assert corpus.bridge in stale_survivors, "bridge memory was forgotten"
    assert len(endpoint_survivors) == 1, (
        f"expected exactly one boundary endpoint to survive, got {sorted(endpoint_survivors)}"
    )
    assert stale_survivors == endpoint_survivors | {corpus.bridge}, (
        f"unexpected stale survivors: {sorted(stale_survivors)}"
    )

    survivors = stale_survivors | set(corpus.active) | set(corpus.profile_signal)
    forgotten = set(corpus.all_ids) - survivors
    assert len(forgotten) == EXPECTED_FORGOTTEN_COUNT, (
        f"forgotten set has {len(forgotten)} members, expected {EXPECTED_FORGOTTEN_COUNT}"
    )
    assert len(survivors) == EXPECTED_SURVIVOR_COUNT, (
        f"survivor set has {len(survivors)} members, expected {EXPECTED_SURVIVOR_COUNT}"
    )

    # Auditability: every forgotten memory carries the community reason
    # and is archived through the mark_expired seam.
    for mid in sorted(forgotten):
        memory = await store.get_memory(mid)
        assert memory is not None and memory["is_latest"] is False
        assert memory["replaced_by"] == "community_forgotten"

    # Metric 1 — community elimination: each expired community is gone as
    # a cluster. The only permitted survivor is the bridge's boundary
    # endpoint (spec #36 story 7 mandates that survivor — the community
    # is still eliminated as a retrievable cluster).
    for members in (corpus.stale_a, corpus.stale_b):
        surviving = [mid for mid in members if mid in stale_survivors]
        ok = all(mid in corpus.boundary_endpoints for mid in surviving)
        elimination.record(ok)
        assert ok, f"expired community not eliminated: {sorted(surviving)}"

    # Metric 2 — signal survival: active community, profile-referenced
    # signal community and the bridge stay latest; plus the bridge
    # invariant sample (exactly one boundary endpoint survives).
    for mid in [*corpus.active, *corpus.profile_signal, corpus.bridge]:
        memory = await store.get_memory(mid)
        ok = memory is not None and memory["is_latest"] is True
        survival.record(ok)
        assert ok, f"signal {corpus.contents[mid]!r} was forgotten"
    survival.record(len(endpoint_survivors) == 1)
    assert len(endpoint_survivors) == 1

    # Metric 3 — retrieval retention: every surviving signal stays
    # searchable; a forgotten boundary endpoint vanishes from retrieval.
    for mid in [*corpus.active, *corpus.profile_signal, corpus.bridge]:
        ok = await retrievable(mid)
        retrieval.record(ok)
        assert ok, f"signal {corpus.contents[mid]!r} not retrievable after forgetting"
    for mid in corpus.boundary_endpoints:
        expected = mid in stale_survivors
        ok = (await retrievable(mid)) == expected
        retrieval.record(ok)
        assert ok, (
            f"boundary endpoint {corpus.contents[mid]!r} retrieval mismatch: survivor={expected}"
        )

    # Precise post-forgetting set (acceptance criterion 2): every
    # forgotten stale member is gone from retrieval.
    for mid in corpus.stale_pool:
        if mid in stale_survivors:
            continue
        assert not await retrievable(mid), (
            f"forgotten stale memory {corpus.contents[mid]!r} still retrievable"
        )

    return ScenarioResult(
        elimination=elimination,
        survival=survival,
        retrieval=retrieval,
        forgotten=forgotten,
        survivors=survivors,
    )
