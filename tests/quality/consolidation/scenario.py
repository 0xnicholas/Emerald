"""Deterministic consolidation quality scenario (B6 T4, ticket #45).

One corpus definition, one metric definition, one runner — shared by the
in-memory aggregate gate (test_consolidation.py) and the real-storage
Neo4j variant (test_neo4j_consolidation_variants.py) so both backends
execute the exact same scenario against the same thresholds.

Corpus (spec #41 / ticket #45): three duplicate groups (the same content
stated three times with different ages and confidence — mock embeddings
only make identical strings similar, so a duplicate group uses identical
content as the deterministic stand-in; real paraphrase recall is a D2
calibration item, not a quality gate) + the full veto-guardrail
counter-example set (profile-protected pair, contradiction pair, cross-
type pair, UPDATES-edge pair — every one must survive untouched) +
unrelated signal memories. Mock embeddings, rule-only path (no LLM),
backdated timestamps — every outcome is a pure function of the backdated
ages, so the suite never depends on the wall clock.

Expected outcome (ticket #45 / ADR-0006):

- each duplicate group of three converges on its newest member as the
  single representative — 6 members merged through ``mark_consolidated``
  (reason ``consolidated``, replaced_by = representative), 3
  representatives remain latest;
- every veto-guardrail pair is kept as-is (exempt_profile /
  exempt_contradiction / exempt_type / exempt_updates) and every signal
  memory survives untouched — 10 memories never merge;
- retrieval changes exactly: representatives and all survivors stay
  searchable, merged members stop being retrievable.

Metrics (all must pass for the suite to be green):

- consolidation recall rate  >= 0.95 (duplicate groups converge)
- mis-merge rate            == 1.0 (HARD GATE: a mis-merge is silent
  information loss — merged content stays in the graph but stops being
  retrievable — so there is no threshold tolerance; any single
  mis-merge fails the suite)
- retrieval retention rate  >= 0.95 (surviving signals still searchable)

Pre/post retrieval sets are asserted exactly (acceptance criterion 2):
before consolidation every corpus memory is searchable by id; afterwards
only the merged members are gone and every survivor stays searchable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from emerald.core.forget import ForgetEngine
from emerald.core.graph import GraphStore
from emerald.core.search import SearchMode, SearchOrchestrator

Backdate = Callable[[str, int], Awaitable[None]]

RECALL_THRESHOLD = 0.95
RETENTION_THRESHOLD = 0.95
# Mis-merge is a hard gate (spec #41: 误并率 = 0 硬门): silent
# information loss gets no threshold tolerance.
MIS_MERGE_HARD_GATE = 1.0

GROUP_CONFIDENCES = [0.3, 0.4, 0.45]  # oldest → newest
# Oldest → newest; confidences rise with recency (all below the profile
# static threshold 0.5, so no group member is ever profile-protected) and
# both representative-selection keys point at the newest member: trust
# desc → created_at desc → id asc.
GROUP_AGES = [90, 30, 1]

# Three duplicate groups: identical restatements at different ages.
GROUPS = [
    "用户住在北京",
    "用户日常工作使用 Python",
    "用户周末喜欢去爬山",
]

# Veto-guardrail counter-examples (each pair must survive untouched):
# - profile pair: one side carries importance >= 0.7 (the shared
#   is_protected single point, B5) → exempt_profile;
# - contradiction pair: the rules classify 搬到 as an UPDATES step →
#   exempt_contradiction (embeddings forced identical below, the
#   deterministic stand-in for a high-similarity paraphrase);
# - cross-type pair: fact vs preference → exempt_type;
# - updates-edge pair: joined by an UPDATES relationship → a temporal
#   chain, exempt_updates.
PROFILE_CONTENT = "用户养了一只猫"
PROFILE_CONFIDENCES = [0.9, 0.4]
CONTRADICTION_NEW = "用户住在广州"
CONTRADICTION_OLD = "用户搬到深圳"
CROSS_TYPE_CONTENT = "用户每天通勤一小时"
UPDATES_CONTENT = "用户使用 Linux 服务器"

# Unrelated signal memories — never candidates, must survive untouched.
SIGNALS = ["用户喜欢喝绿茶", "用户喜欢阅读技术书籍"]

EXPECTED_MERGED = 6  # 3 groups × 2 merged members
EXPECTED_REPRESENTATIVES = 3
EXPECTED_SURVIVORS = 13  # 3 representatives + 8 veto members + 2 signals


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
class ConsolidationCorpus:
    """Memory ids and contents of the deterministic consolidation corpus."""

    entity_id: str
    groups: dict[str, list[str]]  # content → member ids, oldest first
    profile_pair: list[str]
    contradiction_pair: list[str]
    cross_type_pair: list[str]
    updates_pair: list[str]
    signals: list[str]
    contents: dict[str, str]

    @property
    def representatives(self) -> list[str]:
        """The newest member of each duplicate group."""
        return [members[-1] for members in self.groups.values()]

    @property
    def merged(self) -> list[str]:
        """Every duplicate member that must be consolidated (all but the
        representatives)."""
        return [mid for members in self.groups.values() for mid in members[:-1]]

    @property
    def veto_members(self) -> list[str]:
        """Every member of the four veto-guardrail counter-example pairs."""
        return [
            *self.profile_pair,
            *self.contradiction_pair,
            *self.cross_type_pair,
            *self.updates_pair,
        ]

    @property
    def all_ids(self) -> list[str]:
        return [
            *self.merged,
            *self.representatives,
            *self.veto_members,
            *self.signals,
        ]


async def seed_consolidation_corpus(
    store: GraphStore,
    vector: Any,
    embedder: Any,
    entity_id: str,
    *,
    backdate: Backdate,
) -> ConsolidationCorpus:
    """Seed the deterministic corpus: memories, the UPDATES edge,
    embeddings, ages.

    Memories are created through the graph store (precise control over
    confidence and memory_type) and indexed into the vector store with
    the mock embedder — the same record a full pipeline ingest would
    produce, without the rule-based relationship inference possibly
    classifying corpus members mid-seed (the corpus is the consolidation
    scenario's input, not the ingestion pipeline's).
    """
    contents: dict[str, str] = {}

    async def create(
        content: str,
        *,
        memory_type: str = "fact",
        confidence: float,
        days: int,
    ) -> str:
        mid = await store.create_memory(
            content,
            entity_id=entity_id,
            memory_type=memory_type,
            confidence=confidence,
        )
        await backdate(mid, days)
        contents[mid] = content
        return mid

    groups: dict[str, list[str]] = {}
    for content in GROUPS:
        groups[content] = [
            await create(content, confidence=confidence, days=age)
            for age, confidence in zip(GROUP_AGES, GROUP_CONFIDENCES, strict=True)
        ]

    profile_pair = [
        await create(PROFILE_CONTENT, confidence=PROFILE_CONFIDENCES[0], days=1),
        await create(PROFILE_CONTENT, confidence=PROFILE_CONFIDENCES[1], days=1),
    ]
    contradiction_pair = [
        await create(CONTRADICTION_NEW, confidence=0.4, days=1),
        await create(CONTRADICTION_OLD, confidence=0.4, days=1),
    ]
    cross_type_pair = [
        await create(CROSS_TYPE_CONTENT, memory_type="fact", confidence=0.4, days=1),
        await create(
            CROSS_TYPE_CONTENT,
            memory_type="preference",
            confidence=0.4,
            days=1,
        ),
    ]
    updates_pair = [
        await create(UPDATES_CONTENT, confidence=0.4, days=1),
        await create(UPDATES_CONTENT, confidence=0.4, days=1),
    ]
    await store.create_relationship(updates_pair[0], updates_pair[1], "UPDATES")

    signals = [
        await create(SIGNALS[0], confidence=0.4, days=30),
        await create(SIGNALS[1], confidence=0.4, days=1),
    ]

    for mid, content in contents.items():
        embedding = (await embedder.embed([content]))[0]
        await vector.store(mid, content, embedding, entity_id=entity_id)

    # Contradiction pair: force identical stored embeddings — the
    # deterministic stand-in for a high-similarity paraphrase. The rule
    # layer vetoes the pair regardless of the vector layer.
    forced = (await embedder.embed([CONTRADICTION_NEW]))[0]
    await vector.store(contradiction_pair[0], CONTRADICTION_NEW, forced, entity_id=entity_id)
    await vector.store(contradiction_pair[1], CONTRADICTION_OLD, forced, entity_id=entity_id)

    return ConsolidationCorpus(
        entity_id=entity_id,
        groups=groups,
        profile_pair=profile_pair,
        contradiction_pair=contradiction_pair,
        cross_type_pair=cross_type_pair,
        updates_pair=updates_pair,
        signals=signals,
        contents=contents,
    )


@dataclass
class ConsolidationResult:
    """One run's metrics plus the exact merged/survivor sets."""

    recall: Metric
    mis_merge: Metric
    retrieval: Metric
    merged: set[str]
    survivors: set[str]


def make_orchestrator(
    store: GraphStore,
    vector: Any,
    embedder: Any,
) -> SearchOrchestrator:
    """SearchOrchestrator wired to the deterministic graph + vector pair."""
    return SearchOrchestrator(graph=store, vector=vector, embedder=embedder)


async def search_ids(
    orchestrator: SearchOrchestrator,
    q: str,
    entity_id: str,
) -> list[str]:
    """Memory-mode search; returns the result memory ids.

    The suite queries exact corpus contents and asserts presence/absence
    by id across the whole entity pool, not ranking quality (ranking is
    guarded by the other sections). Duplicate groups share identical
    content, so members are distinguished by id, never by content.
    Search scores are ``cosine × trust``, so a low-trust memory can rank
    below fuzzy matches on its own exact query and get dropped by gap
    truncation — probing the full pool with truncation off keeps the
    assertions exact: present iff latest, absent iff merged.
    """
    response = await orchestrator.search(
        q,
        entity_id=entity_id,
        search_mode=SearchMode.MEMORY,
        top_k=50,
        dynamic_truncation=False,
    )
    return [result.id for result in response.results]


async def run_consolidation(
    store: GraphStore,
    vector: Any,
    orchestrator: SearchOrchestrator,
    corpus: ConsolidationCorpus,
) -> ConsolidationResult:
    """Run the scenario and return the three metrics with hard asserts.

    Exact pre/post retrieval-set assertions (acceptance criterion 2):
    baseline search must surface every corpus memory by id; afterwards
    representatives and every survivor stay searchable and the merged
    members are gone. The mis-merge hard gate is enforced inline per
    veto/signal memory and by the metric threshold (rate must be 1.0).
    """
    recall = Metric("consolidation_recall", RECALL_THRESHOLD)
    mis_merge = Metric("mis_merge_rate", MIS_MERGE_HARD_GATE)
    retrieval = Metric("retrieval_retention_rate", RETENTION_THRESHOLD)
    entity_id = corpus.entity_id

    async def retrievable(mid: str) -> bool:
        content = corpus.contents[mid]
        found = await search_ids(orchestrator, content, entity_id)
        return mid in found

    # Baseline: before consolidation, every corpus memory is retrievable
    # by id (duplicate groups surface all their members).
    for mid in corpus.all_ids:
        assert await retrievable(mid), f"Baseline retrieval failed for {corpus.contents[mid]!r}"

    merged_count = await ForgetEngine(graph=store, vector_store=vector).consolidate_duplicates(
        entity_id
    )
    assert merged_count == EXPECTED_MERGED, (
        f"consolidate_duplicates merged {merged_count} memories, expected {EXPECTED_MERGED}"
    )

    # Exact graph state (acceptance criterion 2): every group converged
    # on its newest representative; every veto/signal memory untouched.
    for content, members in corpus.groups.items():
        representative = members[-1]
        rep_memory = await store.get_memory(representative)
        assert rep_memory is not None and rep_memory["is_latest"] is True
        for mid in members[:-1]:
            memory = await store.get_memory(mid)
            assert memory is not None and memory["is_latest"] is False, (
                f"group member {content!r} ({mid}) not merged"
            )
            assert memory["replaced_by"] == representative, (
                f"group member {content!r} replaced_by={memory.get('replaced_by')}, "
                f"expected {representative}"
            )

    survivors = set(corpus.representatives) | set(corpus.veto_members) | set(corpus.signals)
    merged = set(corpus.merged)
    assert len(merged) == EXPECTED_MERGED
    assert len(survivors) == EXPECTED_SURVIVORS

    # Metric 1 — consolidation recall: each duplicate group converges
    # (exactly the representative stays latest) and every merged member
    # is archived with replaced_by pointing at its group representative.
    for content, members in corpus.groups.items():
        representative = members[-1]
        states = [await store.get_memory(mid) for mid in members[:-1]]
        ok = all(
            [m is not None and m["is_latest"] is False for m in states]
        )
        rep_memory = await store.get_memory(representative)
        ok = ok and rep_memory is not None and rep_memory["is_latest"] is True
        recall.record(ok)
        assert ok, f"duplicate group {content!r} did not converge"
    for content, members in corpus.groups.items():
        representative = members[-1]
        for mid in members[:-1]:
            memory = await store.get_memory(mid)
            ok = memory is not None and memory["replaced_by"] == representative
            recall.record(ok)
            assert ok, f"merged member {content!r} does not point at its representative"

    # Metric 2 — mis-merge hard gate: no veto-guardrail pair member and
    # no signal memory may be merged, archived, or re-pointed.
    for mid in [*corpus.veto_members, *corpus.signals]:
        memory = await store.get_memory(mid)
        assert memory is not None, f"mis-merge: {corpus.contents[mid]!r} missing"
        ok = memory["is_latest"] is True and memory.get("replaced_by") is None
        mis_merge.record(ok)
        assert ok, f"mis-merge: {corpus.contents[mid]!r} was consolidated"
    assert mis_merge.numerator == mis_merge.denominator, "mis-merge hard gate failed"

    # Metric 3 — retrieval retention: representatives and every survivor
    # stay searchable; merged members vanish from retrieval.
    for mid in corpus.representatives:
        ok = await retrievable(mid)
        retrieval.record(ok)
        assert ok, f"representative {corpus.contents[mid]!r} not retrievable"
    for mid in corpus.merged:
        ok = not await retrievable(mid)
        retrieval.record(ok)
        assert ok, f"merged member {corpus.contents[mid]!r} still retrievable"
    for mid in [*corpus.veto_members, *corpus.signals]:
        ok = await retrievable(mid)
        retrieval.record(ok)
        assert ok, f"survivor {corpus.contents[mid]!r} not retrievable"

    return ConsolidationResult(
        recall=recall,
        mis_merge=mis_merge,
        retrieval=retrieval,
        merged=merged,
        survivors=survivors,
    )
