"""Community detection (B5, ticket #37) — deterministic label propagation.

The detector partitions an entity's latest memories (is_latest=true) into
**communities** — structurally interlinked clusters over relationship
edges (UPDATES / EXTENDS / DERIVES_FROM, both directions) and mention
bridges (two memories referencing the same Mention node). It is the
first stage of the community forgetting strategy (spec #36): a pure
structural partition ``memory_id → community_id``, consumed by the
activity scoring / decision layer (#38) and the ``forget_communities``
strategy (#39). Internal module — no public API surface.

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
        adjacency = await self._build_adjacency(entity_id, nodes)
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

    async def _build_adjacency(self, entity_id: str, nodes: list[str]) -> dict[str, set[str]]:
        """Build the undirected adjacency of the node set.

        Relationship edges: one batch read via the B4 neighbor primitive,
        filtered to same-entity, is_latest=true neighbors. Mention
        bridges: per-node mention reads assembled into an in-process
        inverted index; memories sharing a Mention node become neighbors
        (nodes iterate in sorted order, so index members are ordered and
        the built adjacency is deterministic).
        """
        node_set = set(nodes)
        adjacency: dict[str, set[str]] = {nid: set() for nid in nodes}

        neighbors = await self.graph.get_relationship_neighbors(nodes, RELATIONSHIP_TYPES)
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
            for mention in await self.graph.get_memory_mentions(nid):
                if mention.get("entity_id") != entity_id:
                    continue  # defense-in-depth: mentions are entity-scoped
                mention_index.setdefault(mention["id"], []).append(nid)
        for members in mention_index.values():
            for i, first in enumerate(members):
                for second in members[i + 1 :]:
                    adjacency[first].add(second)
                    adjacency[second].add(first)

        return adjacency

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
