"""Duplicate detection and veto guardrails (B6 T1, ticket #42) — vector
candidate generation (optimization layer) + a pure rule guardrail
decision layer (no LLM).

The consolidation strategy (B6, ADR-0006) converges near-duplicate
active facts of one entity into a single representative memory. This
module is the detection half. Vector similarity only *generates
candidates* — it never decides. Whether a candidate pair is merged is
always decided by rules (AGENTS.md: 图谱优先 — the vector layer is an
optimization, the graph/rule layer is the authority):

- **entity isolation** (ADR-0002): both memories belong to the same
  entity — a convergence never reaches across entities;
- **both ``is_latest=true``**: history never re-enters consolidation;
- **identical ``memory_type``**: cross-type pairs never merge;
- **profile / high-importance exemption**: reuses the ``is_protected``
  single point from ``emerald.core.community`` (B5 #38) — memories the
  entity profile references or that carry importance ≥ threshold are
  exempt;
- **contradiction veto**: reuses the relationship engine's deterministic
  rule classifier (``RelationshipEngine.rule_classify``) — a pair the
  rules would classify as UPDATES is a timeline step, not a duplicate;
- **UPDATES-edge veto**: an existing UPDATES relationship between the
  pair marks a temporal chain — merging would destroy timeline
  semantics (AGENTS.md §6).

Representative selection is a deterministic total order: trust score
desc → created_at desc → memory id asc.

Determinism contract (spec #41 story 6): the decision layer
(``decide_pair``, ``select_representative``) is a pure function of its
inputs — explicit parameters, no I/O, no clock. ``DuplicatesDetector``
does the I/O and takes ``now`` explicitly; the same graph, vector store
and ``now`` always yield the same verdicts, so the quality suite (T4,
#45) can assert decisions exactly.

The strategy (T3, #44) consumes verdicts and lands them via the
``mark_consolidated`` seam (T2, #43). Internal module — no public API
surface (AGENTS.md: 禁止 API 泄漏).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

from emerald.core.community import (
    IMPORTANCE_THRESHOLD,
    MemoryFeatures,
    is_protected,
)
from emerald.core.graph import GraphStore
from emerald.core.profile import ProfileManager
from emerald.core.relationship import RelationshipEngine, RelationType
from emerald.core.trust import compute_trust_score
from emerald.core.vector import VectorStore

logger = structlog.get_logger(__name__)

# Cosine similarity at/above which a vector hit becomes a candidate.
# Deliberately conservative: only near-exact restatements merge. The D2
# data gate was downgraded to parameter calibration (ADR-0006) — the
# value is tuned from data via DuplicateConfig, not hard-wired forever.
SIMILARITY_THRESHOLD = 0.9

# Per-memory vector search width (the optimization layer's approximation
# of the candidate pool; also a calibration knob).
CANDIDATE_TOP_K = 20

# Per-entity scale guard on the latest-memory pool (mirrors B5 #37).
DEFAULT_MAX_MEMORIES = 1000


class DuplicateAction(StrEnum):
    """Per-pair consolidation action (B6 T1, #42).

    The vocabulary is exactly the metric label set T3 (#44) reports
    (``emerald_consolidate_duplicates_total``): consolidated / keep /
    exempt_profile / exempt_type / exempt_contradiction /
    exempt_updates. ``keep`` also covers the defense-in-depth vetoes
    that can never fire on real candidates (entity isolation, history
    participation) — they are reported via the verdict's ``reason``.
    """

    CONSOLIDATE = "consolidated"
    KEEP = "keep"
    EXEMPT_PROFILE = "exempt_profile"
    EXEMPT_TYPE = "exempt_type"
    EXEMPT_CONTRADICTION = "exempt_contradiction"
    EXEMPT_UPDATES = "exempt_updates"


@dataclass(frozen=True)
class DuplicateCandidate:
    """One candidate pair with every piece of context the decision needs.

    Assembled by ``DuplicatesDetector`` (which does all the I/O); the
    decision layer consumes it as-is, so ``decide_pair`` is a pure
    function — no graph reads, no vector reads, no clock at decision
    time. ``memory_a`` / ``memory_b`` are the full graph records;
    ``features_*`` carry the protection context (profile reference /
    importance); ``trust_*`` the precomputed trust scores;
    ``has_updates_edge`` / ``contradiction`` the structural and semantic
    veto signals.
    """

    memory_a: dict[str, Any]
    memory_b: dict[str, Any]
    similarity: float
    features_a: MemoryFeatures
    features_b: MemoryFeatures
    trust_a: float
    trust_b: float
    has_updates_edge: bool = False
    contradiction: bool = False

    @property
    def ids(self) -> tuple[str, str]:
        """The pair as (smaller id, larger id) — the canonical order,
        independent of which side is ``memory_a``."""
        a_id: str = self.memory_a["id"]
        b_id: str = self.memory_b["id"]
        return (a_id, b_id) if a_id <= b_id else (b_id, a_id)


@dataclass(frozen=True)
class DuplicateVerdict:
    """One pair's decision with the evidence behind it (T3 logging).

    ``representative_id`` is set iff the pair consolidates; ``reason``
    names the veto that fired for every non-consolidate verdict:
    ``entity_isolation`` / ``history_participation`` / ``memory_type`` /
    ``contradiction`` / ``updates_edge`` / ``protected``.
    """

    candidate: DuplicateCandidate
    action: DuplicateAction
    representative_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class DuplicateConfig:
    """Detection thresholds — the D2 data-calibration seam (ADR-0006).

    ``similarity_threshold`` gates candidate generation; ``candidate_top_k``
    bounds per-memory search width; ``max_memories`` is the per-entity
    scale guard; ``importance_threshold`` is shared with the B5
    protection predicate (``is_protected``).
    """

    similarity_threshold: float = SIMILARITY_THRESHOLD
    candidate_top_k: int = CANDIDATE_TOP_K
    max_memories: int = DEFAULT_MAX_MEMORIES
    importance_threshold: float = IMPORTANCE_THRESHOLD

    def __post_init__(self) -> None:
        if not 0.0 < self.similarity_threshold <= 1.0:
            raise ValueError(f"similarity_threshold must be in (0, 1]: {self.similarity_threshold}")
        if self.candidate_top_k < 1:
            raise ValueError(f"candidate_top_k must be >= 1: {self.candidate_top_k}")
        if self.max_memories < 1:
            raise ValueError(f"max_memories must be >= 1: {self.max_memories}")
        if not 0.0 <= self.importance_threshold <= 1.0:
            raise ValueError(f"importance_threshold must be in [0, 1]: {self.importance_threshold}")


def _coerce_created_at(value: Any) -> datetime:
    """Normalize a stored timestamp (Neo4j DateTime / str / datetime) to
    aware UTC; missing or unparseable values sort as the epoch start."""
    fallback = datetime.min.replace(tzinfo=UTC)
    if value is None:
        return fallback
    if hasattr(value, "to_native"):
        value = value.to_native()
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    if not isinstance(value, datetime):
        return fallback
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def select_representative(memories: list[dict[str, Any]], trust_scores: dict[str, float]) -> str:
    """Pick the representative of a duplicate group — deterministic total
    order: trust score desc → created_at desc → memory id asc.

    Pure function of its inputs (trust scores are passed in, never
    computed here — callers compute them with an explicit ``now`` so the
    decision has no clock dependence). Raises ``ValueError`` on an empty
    input.
    """
    if not memories:
        raise ValueError("select_representative requires at least one memory")

    def key(memory: dict[str, Any]) -> tuple[float, float, str]:
        mid: str = memory["id"]
        trust = trust_scores.get(mid, 0.0)
        created_epoch = _coerce_created_at(memory.get("created_at")).timestamp()
        return (-trust, -created_epoch, mid)

    representative: str = sorted(memories, key=key)[0]["id"]
    return representative


def decide_pair(
    candidate: DuplicateCandidate,
    *,
    importance_threshold: float = IMPORTANCE_THRESHOLD,
) -> DuplicateVerdict:
    """Apply the veto guardrails to one candidate pair — pure decision,
    no I/O, no clock; the same candidate always yields the same verdict.

    Rules, in fixed priority order:

    1. **entity isolation** — different entities → ``keep``
       (``entity_isolation``); defense-in-depth: candidates are generated
       per entity, but the decision never trusts the generator;
    2. **history participation** — either side ``is_latest=false`` →
       ``keep`` (``history_participation``); history never re-enters
       consolidation;
    3. **memory type** — different ``memory_type`` → ``exempt_type``;
    4. **protection** — either memory is profile-referenced or carries
       importance ≥ ``importance_threshold`` (the shared ``is_protected``
       single point) → ``exempt_profile``;
    5. **contradiction** — the relationship rules classify the pair as
       UPDATES (either direction) → ``exempt_contradiction``; a timeline
       step is not a duplicate;
    6. **UPDATES edge** — an existing UPDATES relationship between the
       pair → ``exempt_updates``;
    7. otherwise → ``consolidated`` with ``representative_id`` from the
       deterministic total order.

    The guardrail order follows the spec #41 / ADR-0006 enumeration
    (实体隔离 / is_latest / memory_type / 画像引用豁免 / 矛盾否决 /
    UPDATES 边否决). All vetoes keep the pair unmerged — the order only
    decides which ``exempt_*`` label wins when several vetoes fire, and
    that label is what the T3 strategy (#44) reports in
    ``emerald_consolidate_duplicates_total``.
    """
    a, b = candidate.memory_a, candidate.memory_b

    if a.get("entity_id") != b.get("entity_id"):
        return DuplicateVerdict(candidate, DuplicateAction.KEEP, reason="entity_isolation")
    if not (a.get("is_latest", True) and b.get("is_latest", True)):
        return DuplicateVerdict(candidate, DuplicateAction.KEEP, reason="history_participation")
    if a.get("memory_type") != b.get("memory_type"):
        return DuplicateVerdict(candidate, DuplicateAction.EXEMPT_TYPE, reason="memory_type")
    if is_protected(candidate.features_a, importance_threshold) or is_protected(
        candidate.features_b, importance_threshold
    ):
        return DuplicateVerdict(candidate, DuplicateAction.EXEMPT_PROFILE, reason="protected")
    if candidate.contradiction:
        return DuplicateVerdict(
            candidate, DuplicateAction.EXEMPT_CONTRADICTION, reason="contradiction"
        )
    if candidate.has_updates_edge:
        return DuplicateVerdict(candidate, DuplicateAction.EXEMPT_UPDATES, reason="updates_edge")

    representative_id = select_representative(
        [a, b],
        {a["id"]: candidate.trust_a, b["id"]: candidate.trust_b},
    )
    return DuplicateVerdict(
        candidate, DuplicateAction.CONSOLIDATE, representative_id=representative_id
    )


class DuplicatesDetector:
    """Candidate generation + guardrail decisions for one entity (B6 T1).

    Optimization layer: per latest memory, the vector store returns the
    top-k most similar stored embeddings; hits at/above the configured
    similarity threshold become undirected candidate pairs. The decision
    is never made by similarity — ``decide_pair`` applies the rules.

    Deterministic: fixed sorted iteration, pair set deduplicated and
    sorted, explicit ``now`` (trust's age decay and any future
    time-dependent signal use it) — the same graph, vector store and
    ``now`` yield the same verdicts on every run, so the quality suite
    can assert them exactly (spec #41 story 6).
    """

    def __init__(
        self,
        graph: GraphStore | None = None,
        vector: VectorStore | None = None,
        profile_manager: ProfileManager | None = None,
        config: DuplicateConfig | None = None,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self.vector = vector or VectorStore(use_db=False)
        self._profile_manager = profile_manager
        self.config = config or DuplicateConfig()

    async def detect(
        self, entity_id: str, *, now: datetime | None = None
    ) -> list[DuplicateVerdict]:
        """Detect near-duplicate candidate pairs and decide each one.

        Loads the entity's latest memories (capped by ``max_memories``,
        newest first), reads their stored embeddings, queries the vector
        store for similar embeddings per memory, assembles candidate
        pairs with their full decision context (trust with the explicit
        ``now``, protection features from the entity profile, UPDATES
        edges, rule-based contradiction), and returns one verdict per
        pair in deterministic order (sorted by pair ids). Empty graphs
        and single-memory graphs yield no verdicts.
        """
        now = now or datetime.now(UTC)
        memories = await self.graph.list_forget_candidates(
            entity_id, limit=self.config.max_memories + 1
        )
        if len(memories) > self.config.max_memories:
            logger.info(
                "duplicates.detect.memory_cap",
                entity_id=entity_id,
                max_memories=self.config.max_memories,
            )
            memories = memories[: self.config.max_memories]

        by_id = {m["id"]: m for m in memories}
        ids = sorted(by_id)
        if len(ids) < 2:
            return []

        embeddings = await self.vector.get_embeddings(ids)
        missing = [mid for mid in ids if mid not in embeddings]
        if missing:
            logger.info(
                "duplicates.detect.missing_embeddings",
                entity_id=entity_id,
                count=len(missing),
            )

        pairs = await self._generate_pairs(ids, embeddings, entity_id)
        if not pairs:
            return []

        features = await self._protection_features(entity_id, by_id, now)
        trust = {mid: compute_trust_score(by_id[mid], now=now) for mid in ids}
        updates_edges = await self._updates_edges(ids, by_id)

        verdicts = []
        for first, second, score in pairs:
            a, b = by_id[first], by_id[second]
            contradiction = (
                RelationshipEngine.rule_classify(a["content"], b["content"]) is RelationType.UPDATES
                or RelationshipEngine.rule_classify(b["content"], a["content"])
                is RelationType.UPDATES
            )
            candidate = DuplicateCandidate(
                memory_a=a,
                memory_b=b,
                similarity=score,
                features_a=features.get(first, MemoryFeatures()),
                features_b=features.get(second, MemoryFeatures()),
                trust_a=trust.get(first, 0.0),
                trust_b=trust.get(second, 0.0),
                has_updates_edge=(first, second) in updates_edges,
                contradiction=contradiction,
            )
            verdicts.append(
                decide_pair(candidate, importance_threshold=self.config.importance_threshold)
            )

        logger.info(
            "duplicates.detect",
            entity_id=entity_id,
            latest=len(ids),
            candidates=len(pairs),
            consolidated=sum(1 for v in verdicts if v.action is DuplicateAction.CONSOLIDATE),
        )
        return verdicts

    async def _generate_pairs(
        self,
        ids: list[str],
        embeddings: dict[str, list[float]],
        entity_id: str,
    ) -> list[tuple[str, str, float]]:
        """Vector candidate generation — the optimization layer.

        Per memory (sorted id order), the vector store returns the top-k
        nearest stored embeddings; only hits whose chunk id is in the
        pool (memory embeddings — RAG chunks are excluded by
        construction) at/above the similarity threshold become candidate
        pairs. Pairs are undirected, deduplicated (keeping the highest
        observed similarity) and returned sorted by (smaller id, larger
        id, similarity) — a deterministic set.
        """
        pairs: dict[tuple[str, str], float] = {}
        for mid in ids:
            embedding = embeddings.get(mid)
            if embedding is None:
                continue  # no stored embedding → cannot query, cannot be hit
            hits = await self.vector.search(
                embedding,
                entity_id=entity_id,
                top_k=self.config.candidate_top_k,
                memory_only=True,  # RAG chunks must never consume the budget
            )
            for chunk_id, _text, score in hits:
                if chunk_id not in embeddings or chunk_id == mid:
                    continue
                if score < self.config.similarity_threshold:
                    continue
                key = (min(mid, chunk_id), max(mid, chunk_id))
                pairs[key] = max(pairs.get(key, 0.0), score)
        return sorted((a, b, score) for (a, b), score in pairs.items())

    async def _protection_features(
        self, entity_id: str, by_id: dict[str, dict[str, Any]], now: datetime
    ) -> dict[str, MemoryFeatures]:
        """Per-memory protection context: profile references + importance.

        Mirrors B5's feature assembly (``forget._community_features``,
        #39): the entity's static/dynamic profile facts mark their source
        memories profile-referenced with the fact's importance. The
        decision layer applies the shared ``is_protected`` predicate —
        this is the exemption single point both maintenance strategies
        use. ``ProfileManager.compute`` is called with the detector's
        explicit ``now`` (B6 #42) so protection does not drift with the
        wall clock: same graph + same ``now`` → same profile → same
        verdicts.
        """
        features: dict[str, MemoryFeatures] = {mid: MemoryFeatures() for mid in by_id}
        if self._profile_manager is None:
            self._profile_manager = ProfileManager(graph=self.graph)
        profile = await self._profile_manager.compute(entity_id, now=now)
        for fact in profile.static:
            if fact.memory_id not in features:
                continue
            current = features[fact.memory_id]
            features[fact.memory_id] = replace(
                current,
                profile_referenced=True,
                importance=max(current.importance, float(fact.importance)),
            )
        for fact in profile.dynamic:
            if fact.memory_id not in features:
                continue
            current = features[fact.memory_id]
            features[fact.memory_id] = replace(
                current,
                profile_referenced=True,
                importance=max(current.importance, float(fact.relevance)),
            )
        return features

    async def _updates_edges(
        self, ids: list[str], by_id: dict[str, dict[str, Any]]
    ) -> set[tuple[str, str]]:
        """Existing UPDATES relationships between pool members (both
        directions) — the temporal-chain veto signal, read once per
        entity via the B4 neighbor primitive."""
        neighbors = await self.graph.get_relationship_neighbors(ids, ["UPDATES"])
        edges: set[tuple[str, str]] = set()
        for mid, adjacent in neighbors.items():
            for edge in adjacent:
                other = edge["id"]
                if other in by_id:
                    edges.add((min(mid, other), max(mid, other)))
        return edges
