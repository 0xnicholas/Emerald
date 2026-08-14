"""Community detection and policy (B5, tickets #37/#38) — deterministic
structural partitioning, activity scoring and forgetting decisions.

The detector (#37) partitions an entity's latest memories (is_latest=true)
into **communities** — structurally interlinked clusters over relationship
edges (UPDATES / EXTENDS / DERIVES_FROM, both directions) and mention
bridges (two memories referencing the same Mention node). It is the
first stage of the community forgetting strategy (spec #36): a pure
structural partition ``memory_id → community_id``, consumed by the
activity scoring / decision layer (#38) and the ``forget_communities``
strategy (#39). Internal module — no public API surface.

The policy layer (#38) turns a partition into per-community actions via
pure functions: ``score_communities`` computes an activity score from
structural/statistical signals only (no LLM), ``find_bridge_memories``
marks boundary nodes spanning ≥2 communities, and ``decide_communities``
applies the decision rules — below threshold forget the whole
community; profile-referenced or high-importance communities exempt;
bridge-carrying communities exempt so the bridge survives.

Determinism contract (spec #36, story 8): the same graph and the same
input yield the same partition on every run. Fixed node order (sorted
memory ids), fixed neighbor order, deterministic tie-breaks, bounded
sweeps — nothing about the graph is mutated.

Algorithm: asynchronous label propagation (Raghavan et al. 2007) with
two tie-breaks that keep dense clusters intact:

1. Majority rule: a node adopts the most frequent label among its
   neighbors.
2. On ties it prefers the highest-degree neighbor (dense cores win over
   periphery and bridge nodes), then the smallest memory id (total
   order, deterministic).

The degree preference is what keeps two dense clusters separate even
when joined by a single bridge node: inside a cluster the bridge (low
degree, foreign label) can never win a tie against cluster members, and
once a cluster consolidates, majority keeps the bridge's label out —
the synthetic two-cliques-plus-bridge case stays two communities.

Adjacency is read exclusively through existing GraphStore primitives
(B4 traversal reuse, spec #36): ``list_forget_candidates`` for the node
set, one batch ``get_relationship_neighbors`` for relationship edges
(filtered to same-entity, is_latest=true), and per-node
``get_memory_mentions`` reads assembled into an in-process inverted
mention → memories index for bridges. Zero new graph store methods, no
Neo4j GDS dependency — works identically on the Neo4j and in-memory
backends.

Entity isolation (ADR-0002): only the given entity's memories are ever
loaded; cross-entity relationship edges are filtered out and mention
nodes are entity-scoped at the graph seam. Historical memories
(is_latest=false) never participate in community structure — they are
neither members nor neighbors (spec #36: 历史节点不参与结构).

Scale guards (spec #36): the node set is capped at ``max_memories`` per
entity (newest first, per the store's ordering) and propagation stops
after ``max_iterations`` sweeps even when not converged; both guards log
when they engage. No LLM calls, no randomness.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

from emerald.core.graph import GraphStore

logger = structlog.get_logger(__name__)

# Relationship edges that define community structure (B4 #32 reuse).
RELATIONSHIP_TYPES = ["UPDATES", "EXTENDS", "DERIVES_FROM"]

# Guard defaults: bound propagation sweeps and the per-entity node count
# so a dense or oversized pool cannot degrade into unbounded work
# (spec #36: 迭代上限 + 每实体规模护栏).
DEFAULT_MAX_ITERATIONS = 20
DEFAULT_MAX_MEMORIES = 1000


async def build_adjacency(
    graph: GraphStore,
    entity_id: str,
    nodes: list[str],
) -> dict[str, set[str]]:
    """Build the undirected adjacency of a node set (B5 #37/#39 seam).

    Relationship edges: one batch read via the B4 neighbor primitive,
    filtered to same-entity, is_latest=true neighbors. Mention bridges:
    per-node mention reads assembled into an in-process inverted index;
    memories sharing a Mention node become neighbors (nodes iterate in
    sorted order, so index members are ordered and the built adjacency
    is deterministic). Used by the detector (#37) and by the
    forget_communities strategy (#39) for scoring / bridge detection.
    """
    node_set = set(nodes)
    adjacency: dict[str, set[str]] = {nid: set() for nid in nodes}

    neighbors = await graph.get_relationship_neighbors(nodes, RELATIONSHIP_TYPES)
    for nid, edges in neighbors.items():
        for neighbor in edges:
            if neighbor.get("entity_id") != entity_id:
                continue  # ADR-0002: never cross the entity boundary
            if not neighbor.get("is_latest", True):
                continue  # history never participates in structure
            neighbor_id = neighbor["id"]
            if neighbor_id in node_set:
                adjacency[nid].add(neighbor_id)

    mention_index: dict[str, list[str]] = {}
    for nid in nodes:
        for mention in await graph.get_memory_mentions(nid):
            if mention.get("entity_id") != entity_id:
                continue  # defense-in-depth: mentions are entity-scoped
            mention_index.setdefault(mention["id"], []).append(nid)
    for members in mention_index.values():
        for i, first in enumerate(members):
            for second in members[i + 1 :]:
                adjacency[first].add(second)
                adjacency[second].add(first)

    return adjacency


class CommunityDetector:
    """Deterministic in-process community detection over an entity's pool."""

    def __init__(
        self,
        graph: GraphStore | None = None,
        *,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_memories: int = DEFAULT_MAX_MEMORIES,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self.max_iterations = max_iterations
        self.max_memories = max_memories

    async def detect(self, entity_id: str) -> dict[str, str]:
        """Partition the entity's latest memories into communities.

        Returns ``{memory_id: community_id}`` covering exactly the
        entity's is_latest=true memories. Community ids are deterministic
        relabels (``c0``, ``c1``, ...) ordered by each community's
        smallest memory id; key iteration order follows the sorted node
        order. Partition relationships are the contract — ids and
        numbering are internal.
        """
        nodes = await self._load_nodes(entity_id)
        if not nodes:
            return {}
        adjacency = await build_adjacency(self.graph, entity_id, nodes)
        labels, converged = self._propagate(nodes, adjacency)
        if not converged:
            logger.info(
                "community.detect.iteration_cap",
                entity_id=entity_id,
                max_iterations=self.max_iterations,
                nodes=len(nodes),
            )
        partition = self._relabel(nodes, labels)
        logger.info(
            "community.detect",
            entity_id=entity_id,
            nodes=len(nodes),
            communities=len(set(partition.values())),
        )
        return partition

    async def _load_nodes(self, entity_id: str) -> list[str]:
        """Load the participant node set: the entity's is_latest=true memories.

        ``list_forget_candidates`` returns exactly the latest memories
        (including ones whose valid_until passed but are not yet
        archived — the spec's structural criterion is is_latest, not
        validity). Sorted by memory id for the fixed node order.
        """
        memories = await self.graph.list_forget_candidates(entity_id, limit=self.max_memories + 1)
        if len(memories) > self.max_memories:
            logger.info(
                "community.detect.memory_cap",
                entity_id=entity_id,
                max_memories=self.max_memories,
            )
            memories = memories[: self.max_memories]
        return sorted({m["id"] for m in memories})

    def _propagate(
        self, nodes: list[str], adjacency: dict[str, set[str]]
    ) -> tuple[dict[str, str], bool]:
        """Asynchronous label propagation in fixed orders.

        Sweeps the fixed node order; each node adopts the majority label
        of its (sorted) neighbors. Ties prefer the highest-degree
        neighbor, then the smallest memory id. Isolated nodes keep their
        own label. Returns (labels, converged) — converged is False when
        the iteration cap was hit first.
        """
        labels = {nid: nid for nid in nodes}
        degree = {nid: len(adjacency[nid]) for nid in nodes}

        for _ in range(self.max_iterations):
            changed = False
            for nid in nodes:
                neighbors = sorted(adjacency[nid])
                if not neighbors:
                    continue  # isolated node keeps its own label
                freq: Counter[str] = Counter(labels[nb] for nb in neighbors)
                max_count = max(freq.values())
                winners = {label for label, count in freq.items() if count == max_count}
                if len(winners) == 1:
                    new_label = next(iter(winners))
                else:
                    candidates = [nb for nb in neighbors if labels[nb] in winners]
                    candidates.sort(key=lambda nb: (-degree[nb], nb))
                    new_label = labels[candidates[0]]
                if new_label != labels[nid]:
                    labels[nid] = new_label
                    changed = True
            if not changed:
                return labels, True
        return labels, False

    def _relabel(self, nodes: list[str], labels: dict[str, str]) -> dict[str, str]:
        """Relabel communities to ``c0``, ``c1``, ... deterministically.

        Communities are ordered by their smallest member memory id —
        members are appended in sorted node order, so each group's first
        element is its minimum.
        """
        groups: dict[str, list[str]] = {}
        for nid in nodes:
            groups.setdefault(labels[nid], []).append(nid)
        ordered = sorted(groups.values(), key=lambda members: members[0])
        partition: dict[str, str] = {}
        for index, members in enumerate(ordered):
            community_id = f"c{index}"
            for nid in members:
                partition[nid] = community_id
        return partition


# ---------------------------------------------------------------------------
# B5 T2 (#38): activity scoring + decision rules — pure functions.
#
# Scoring is a weighted blend of structural/statistical signals (spec #36:
# 纯结构/统计信号，不调 LLM): mean confidence, recency of the newest
# touch (last_accessed_at, falling back to created_at), internal edge
# density, and the fraction of members referenced by the entity profile
# or carrying high importance. Decision rules: score below threshold →
# forget the whole community; profile-referenced / high-importance
# communities exempt; bridge-carrying communities exempt so the bridge
# (a boundary node spanning ≥2 communities) survives — keeping the
# graph connected and multi-hop paths intact (spec #36 story 7).
# ---------------------------------------------------------------------------

# Score below this threshold → the whole community is forgotten (#38).
ACTIVITY_THRESHOLD = 0.5

# A memory with profile-fact importance at/above this counts as protected.
IMPORTANCE_THRESHOLD = 0.7

# Recency half-life in days (mirrors ProfileManager's decay shape).
RECENCY_HALF_LIFE_DAYS = 30.0


class CommunityAction(StrEnum):
    """Per-community forgetting action (B5 T2, #38).

    ``forgotten`` / ``exempt_profile`` / ``exempt_bridge`` / ``keep`` —
    the same vocabulary T3 (#39) reports in metrics and per-decision logs
    (spec #39: 指标按 action：forgotten / exempt_bridge / exempt_profile).
    """

    FORGET = "forgotten"
    EXEMPT_PROFILE = "exempt_profile"
    EXEMPT_BRIDGE = "exempt_bridge"
    KEEP = "keep"


@dataclass(frozen=True)
class MemoryFeatures:
    """Per-memory structural/statistical features consumed by the policy.

    Built by the caller from graph records + profile facts (T3, #39):
    ``confidence`` from the memory, ``created_at`` / ``last_accessed_at``
    for recency, ``profile_referenced`` / ``importance`` from the
    entity's static/dynamic profile facts.
    """

    confidence: float = 0.5
    created_at: datetime | None = None
    last_accessed_at: datetime | None = None
    profile_referenced: bool = False
    importance: float = 0.0


@dataclass(frozen=True)
class ActivityWeights:
    """Weights of the activity-score components (sum should be 1.0)."""

    confidence: float = 0.3
    recency: float = 0.3
    density: float = 0.2
    profile: float = 0.2

    def __post_init__(self) -> None:
        weights = (self.confidence, self.recency, self.density, self.profile)
        if any(weight < 0 for weight in weights):
            raise ValueError(f"activity weights must be non-negative: {self}")
        if sum(weights) <= 0:
            raise ValueError(f"activity weights must not sum to zero: {self}")


@dataclass(frozen=True)
class CommunityVerdict:
    """Per-community decision with the evidence behind it (T3 logging)."""

    community_id: str
    action: CommunityAction
    activity_score: float
    size: int
    bridge_memory_ids: tuple[str, ...]
    protected_memory_ids: tuple[str, ...]


def _as_datetime(value: Any, *, fallback: datetime) -> datetime:
    """Coerce a timestamp (Neo4j DateTime / str / datetime) to aware UTC."""
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


def _is_protected(feature: MemoryFeatures, importance_threshold: float) -> bool:
    """Profile-referenced or high-importance — the protection predicate.

    Single source of truth shared by the score's profile component and
    the decision layer's exemption rule (spec #36: 画像引用数（高
    importance 或画像 static/dynamic 引用）).
    """
    return feature.profile_referenced or feature.importance >= importance_threshold


def _recency(now: datetime, features: dict[str, MemoryFeatures], members: list[str]) -> float:
    """Recency of the community's newest touch, exponential decay."""
    newest: datetime | None = None
    for mid in members:
        feat = features.get(mid)
        if feat is None:
            continue
        for stamp in (feat.last_accessed_at, feat.created_at):
            if stamp is None:
                continue
            candidate = _as_datetime(stamp, fallback=now)
            if newest is None or candidate > newest:
                newest = candidate
    if newest is None:
        # No timestamp anywhere — unknown age must never make a
        # community forgettable, so it counts as fresh.
        return 1.0
    days_ago = max(0.0, (now - newest).total_seconds() / 86400.0)
    return float(2.0 ** (-days_ago / RECENCY_HALF_LIFE_DAYS))


def _internal_edge_count(adjacency: dict[str, set[str]], members: list[str]) -> int:
    """Count undirected edges with both endpoints inside the community."""
    count = 0
    for i, first in enumerate(members):
        neighbors = adjacency.get(first, set())
        for second in members[i + 1 :]:
            if second in neighbors:
                count += 1
    return count


def score_communities(
    partition: dict[str, str],
    adjacency: dict[str, set[str]],
    features: dict[str, MemoryFeatures],
    *,
    now: datetime,
    weights: ActivityWeights | None = None,
    importance_threshold: float = IMPORTANCE_THRESHOLD,
) -> dict[str, float]:
    """Compute an activity score per community, in [0, 1].

    Pure function of its inputs (``now`` included — callers pass it
    explicitly so the same inputs always yield the same scores). The
    score blends, per community:

    - **confidence**: mean member confidence;
    - **recency**: exponential decay (30-day half-life) of the newest
      member touch time (last_accessed_at, else created_at, else ``now``);
    - **density**: fraction of possible internal edges present
      (0 for singletons);
    - **profile**: fraction of members that are profile-referenced or
      carry importance ≥ ``importance_threshold`` (the protection
      predicate shared with the decision layer).

    ``adjacency`` must be symmetric; members missing from ``features``
    score as defaults. Returned scores are rounded to 6 decimals.
    """
    weights = weights or ActivityWeights()
    groups: dict[str, list[str]] = {}
    for mid, community_id in partition.items():
        groups.setdefault(community_id, []).append(mid)
    for members in groups.values():
        members.sort()

    scores: dict[str, float] = {}
    for community_id in sorted(groups):
        members = groups[community_id]
        size = len(members)

        confidences = [
            max(0.0, min(1.0, features[mid].confidence)) for mid in members if mid in features
        ]
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.5

        recency = _recency(now, features, members)

        density = 0.0
        if size >= 2:
            density = (2.0 * _internal_edge_count(adjacency, members)) / (size * (size - 1))

        protected = sum(
            1
            for mid in members
            if mid in features and _is_protected(features[mid], importance_threshold)
        )
        profile_fraction = protected / size

        score = (
            weights.confidence * mean_confidence
            + weights.recency * recency
            + weights.density * density
            + weights.profile * profile_fraction
        )
        scores[community_id] = round(min(1.0, score), 6)
    return scores


def find_bridge_memories(
    partition: dict[str, str],
    adjacency: dict[str, set[str]],
) -> set[str]:
    """Return memories whose neighbors span ≥2 distinct communities.

    A bridge is a boundary node connecting two (or more) communities —
    forgetting it would fracture the graph and break multi-hop paths, so
    the decision layer exempts its community (spec #36 story 7). Only
    neighbors present in the partition count.
    """
    bridges: set[str] = set()
    for mid in sorted(partition):
        neighbor_communities = {
            partition[neighbor] for neighbor in adjacency.get(mid, set()) if neighbor in partition
        }
        if len(neighbor_communities) >= 2:
            bridges.add(mid)
    return bridges


def decide_communities(
    partition: dict[str, str],
    adjacency: dict[str, set[str]],
    features: dict[str, MemoryFeatures],
    scores: dict[str, float],
    *,
    activity_threshold: float = ACTIVITY_THRESHOLD,
    importance_threshold: float = IMPORTANCE_THRESHOLD,
) -> dict[str, CommunityVerdict]:
    """Apply the decision rules and return one verdict per community.

    Pure function: given the partition, adjacency, per-memory features
    and precomputed scores, the same inputs always produce the same
    verdicts (deterministic ordering and tuples; no I/O, no time).

    Rules, in priority order:

    1. a community containing a profile-referenced or high-importance
       (importance ≥ ``importance_threshold``) memory is exempt —
       ``exempt_profile``, the whole community kept;
    2. otherwise, a low-activity community (score <
       ``activity_threshold``) holding a bridge memory is partially
       forgotten — ``exempt_bridge``: the bridge memories are kept
       (spec #36: 桥接记忆豁免并保留), the remaining members are
       forgotten by the strategy (所在社区不整体遗忘);
    3. otherwise, a low-activity community is forgotten wholesale —
       ``forgotten``;
    4. healthy communities (score ≥ threshold) are ``keep``.

    Exemption labels only fire when they change the outcome: a healthy
    community with bridges or profile references is a plain ``keep``.
    Every verdict reports its score, size, sorted bridge ids and sorted
    protected ids for T3 observability. A community missing from
    ``scores`` scores 0 (defensively forgettable unless exempt).
    """
    bridges = find_bridge_memories(partition, adjacency)

    groups: dict[str, list[str]] = {}
    for mid, community_id in partition.items():
        groups.setdefault(community_id, []).append(mid)

    verdicts: dict[str, CommunityVerdict] = {}
    for community_id in sorted(groups):
        members = sorted(groups[community_id])
        score = scores.get(community_id, 0.0)

        protected = sorted(
            mid
            for mid in members
            if mid in features and _is_protected(features[mid], importance_threshold)
        )
        community_bridges = sorted(mid for mid in members if mid in bridges)

        if score < activity_threshold:
            if protected:
                action = CommunityAction.EXEMPT_PROFILE
            elif community_bridges:
                action = CommunityAction.EXEMPT_BRIDGE
            else:
                action = CommunityAction.FORGET
        else:
            action = CommunityAction.KEEP

        verdicts[community_id] = CommunityVerdict(
            community_id=community_id,
            action=action,
            activity_score=score,
            size=len(members),
            bridge_memory_ids=tuple(community_bridges),
            protected_memory_ids=tuple(protected),
        )
    return verdicts


def forgotten_memories(
    partition: dict[str, str],
    verdicts: dict[str, CommunityVerdict],
) -> set[str]:
    """The memories a strategy forgets for the given verdicts (T3 seam).

    Pure projection of the decision rules:

    - ``forgotten`` → every member;
    - ``exempt_bridge`` → every member except the bridge memories
      (the community is not wholly forgotten; the bridge survives);
    - ``exempt_profile`` / ``keep`` → nothing.
    """
    members_by_community: dict[str, set[str]] = {}
    for mid, community_id in partition.items():
        members_by_community.setdefault(community_id, set()).add(mid)

    forgotten: set[str] = set()
    for community_id, members in members_by_community.items():
        verdict = verdicts.get(community_id)
        if verdict is None:
            continue
        if verdict.action is CommunityAction.FORGET:
            forgotten |= members
        elif verdict.action is CommunityAction.EXEMPT_BRIDGE:
            forgotten |= members - set(verdict.bridge_memory_ids)
    return forgotten
