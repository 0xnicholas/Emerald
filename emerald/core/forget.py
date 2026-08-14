"""Forget engine — automatic memory lifecycle management.

Five strategies, triggered by Celery Beat scheduled tasks:

1. Time-based expiry: valid_until passed → is_latest=False, expired_at=now
2. Contradiction resolution: handled by RelationshipEngine (Phase 4)
3. Noise filtering: confidence < 0.3, no references, > 7 days old → archive
4. Episodic decay: episodic memories > 90 days → archive
5. Community forgetting (B5, #39): low-activity communities forgotten
   wholesale — deterministic detection + scoring + decision (see
   emerald.core.community), bridge memories and profile-referenced /
   high-importance communities exempt.

Plus one maintenance strategy, triggered daily at 5 AM after the
forgetting batch (B6, ADR-0006):

6. Duplicate consolidation (B6, #44): near-duplicate active facts of an
   entity converge into a single representative — vector candidates +
   rule guardrails (emerald.core.duplicates, #42) landed through the
   atomic ``mark_consolidated`` seam (#43). Only memories that survived
   the forgetting batch (is_latest=true) are eligible.

Forgetting integration (B3 NER, #27): every strategy funnels through
GraphStore.mark_expired, which also removes the memory's MENTIONS edges
and prunes Mention nodes left with zero MENTIONS edges — the graph never
accumulates dead mention nodes. The UPDATES replacement path is separate
(update_is_latest) and keeps the replaced memory's historical edges (#26).

AGENTS.md: "没有遗忘，每句随意的话都会变成永久记忆。图谱膨胀，噪音累积，检索质量下降。遗忘不是 bug——它是一项特性。"
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import structlog

from emerald.core.community import (
    CommunityDetector,
    MemoryFeatures,
    build_adjacency,
    decide_communities,
    forgotten_memories,
    score_communities,
)
from emerald.core.duplicates import (
    DuplicateAction,
    DuplicateConfig,
    DuplicatesDetector,
    DuplicateVerdict,
    select_representative,
)
from emerald.core.graph import GraphStore
from emerald.core.metrics import consolidate_duplicates_total, forget_communities_total
from emerald.core.profile import ProfileManager
from emerald.core.vector import VectorStore

logger = structlog.get_logger(__name__)


class ForgetStrategy(str, Enum):
    TIME_EXPIRY = "time_expiry"
    CONTRADICTION = "contradiction"
    NOISE_FILTER = "noise_filter"
    EPISODIC_DECAY = "episodic_decay"
    COMMUNITY = "community_forgotten"
    CONSOLIDATE = "consolidated"


class ForgetEngine:
    """Manages automatic forgetting of memories.

    Each strategy queries the graph via GraphStore public APIs and marks
    memories as is_latest=False with appropriate metadata. Mention pruning
    (#27) rides along inside mark_expired: forgotten memories lose their
    MENTIONS edges and orphaned Mention nodes are pruned.
    """

    # Thresholds
    NOISE_MIN_AGE_DAYS = 7
    NOISE_MAX_CONFIDENCE = 0.3
    EPISODIC_ARCHIVE_DAYS = 90
    EPISODIC_REDUCE_WEIGHT_DAYS = 30

    def __init__(
        self,
        graph: GraphStore | None = None,
        profile_manager: ProfileManager | None = None,
        vector_store: VectorStore | None = None,
        duplicate_config: DuplicateConfig | None = None,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self._profile_manager = profile_manager
        # Consolidation (B6) reads embeddings and queries the vector store
        # through DuplicatesDetector; production passes VectorStore(use_db=True).
        self._vector_store = vector_store
        # The D2 data-calibration seam (ADR-0006): detection thresholds.
        self._duplicate_config = duplicate_config

    # ---- Time-based expiry (runs hourly) ----

    async def forget_expired(self, entity_id: str | None = None) -> int:
        """Mark memories past their valid_until as is_latest=False.

        Uses GraphStore public API so it works with both Neo4j and in-memory.
        """
        now = datetime.now(UTC)
        count = 0

        if entity_id:
            memories = await self.graph.list_forget_candidates(entity_id, limit=1000)
            count += await self._mark_expired(memories, now)
        else:
            # Scan all entities — in production this is done via Neo4j Cypher.
            # In-memory fallback iterates over all stored entities.
            all_entity_ids = await self._list_all_entity_ids()
            for eid in all_entity_ids:
                memories = await self.graph.list_forget_candidates(eid, limit=1000)
                count += await self._mark_expired(memories, now)

        if count:
            logger.info("forget.expired", count=count)
        return count

    async def _mark_expired(self, memories: list[dict], now: datetime) -> int:
        count = 0
        for m in memories:
            valid_until = m.get("valid_until")
            if valid_until is not None:
                # Neo4j returns neo4j.time.DateTime; convert to Python datetime
                if hasattr(valid_until, "to_native"):
                    valid_until = valid_until.to_native()
                if valid_until < now:
                    await self.graph.mark_expired(m["id"], reason="expired")
                    count += 1
        return count

    # ---- Noise filtering (runs daily at 3 AM) ----

    async def forget_noise(self, entity_id: str | None = None) -> int:
        """Archive low-confidence, old, unreferenced memories.

        Conditions:
        - confidence < NOISE_MAX_CONFIDENCE
        - created > NOISE_MIN_AGE_DAYS ago
        - is_latest=True (not already handled by another strategy)
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=self.NOISE_MIN_AGE_DAYS)
        count = 0

        target_entities = [entity_id] if entity_id else await self._list_all_entity_ids()

        for eid in target_entities:
            memories = await self.graph.list_forget_candidates(eid, limit=1000)
            for m in memories:
                confidence = m.get("confidence", 0.5)
                created_at = m.get("created_at", now)
                # Neo4j DateTime conversion
                if hasattr(created_at, "to_native"):
                    created_at = created_at.to_native()

                if confidence < self.NOISE_MAX_CONFIDENCE and created_at < cutoff:
                    await self.graph.mark_expired(m["id"], reason="noise_filtered")
                    count += 1

        if count:
            logger.info("forget.noise", count=count)
        return count

    # ---- Episodic decay (runs daily at 4 AM) ----

    async def decay_episodic(self) -> int:
        """Archive old episodic memories.

        > EPISODIC_ARCHIVE_DAYS: is_latest=False (archived)
        30-90 days: weight already reduced by search (not implemented yet)
        Only affects memory_type='episodic'.
        """
        now = datetime.now(UTC)
        archive_cutoff = now - timedelta(days=self.EPISODIC_ARCHIVE_DAYS)
        count = 0

        all_entity_ids = await self._list_all_entity_ids()
        for eid in all_entity_ids:
            memories = await self.graph.list_forget_candidates(eid, limit=1000)
            for m in memories:
                memory_type = m.get("memory_type", "fact")
                if memory_type != "episodic":
                    continue

                created_at = m.get("created_at", now)
                if hasattr(created_at, "to_native"):
                    created_at = created_at.to_native()

                if created_at < archive_cutoff:
                    await self.graph.mark_expired(m["id"], reason="episodic_decay")
                    count += 1

        if count:
            logger.info("forget.episodic_decay", count=count)
        return count

    # ---- Community forgetting (B5, #39) — runs daily ----

    async def forget_communities(self, entity_id: str | None = None) -> int:
        """Forget low-activity communities wholesale (B5, spec #36).

        Per entity: detect communities (deterministic label propagation,
        #37), score their activity and decide (pure structural/statistical
        signals, #38), then forget each forgotten community's members
        through the existing ``mark_expired`` seam with reason
        ``community_forgotten`` — MENTIONS edge removal and orphan
        mention pruning ride along automatically (#27). Bridge memories
        and profile-referenced / high-importance communities are exempt
        and kept as-is. One community is processed as one unit within a
        single run.

        Observability: one structured log and one metric increment per
        community decision (entity_id, community_id, size,
        activity_score, action). A broken entity is logged and skipped —
        one failure never aborts the sweep.

        Returns the number of forgotten memories.
        """
        now = datetime.now(UTC)
        target_entities = [entity_id] if entity_id else await self._list_all_entity_ids()

        total = 0
        for eid in target_entities:
            total += await self._forget_communities_for_entity(eid, now)

        if total:
            logger.info("forget.communities", count=total)
        return total

    async def _forget_communities_for_entity(
        self, entity_id: str, now: datetime
    ) -> int:
        try:
            partition = await CommunityDetector(graph=self.graph).detect(entity_id)
            if not partition:
                return 0

            nodes = sorted(partition)
            adjacency = await build_adjacency(self.graph, entity_id, nodes)
            features = await self._community_features(entity_id, nodes)
            scores = score_communities(partition, adjacency, features, now=now)
            verdicts = decide_communities(partition, adjacency, features, scores)
            forgotten = forgotten_memories(partition, verdicts)

            count = 0
            members_by_community: dict[str, list[str]] = {}
            for mid, community_id in partition.items():
                members_by_community.setdefault(community_id, []).append(mid)

            # One community is handled as one unit: decide, log, then
            # forget its cohort consecutively — a community is never
            # interleaved with another entity's work within the run.
            for community_id in sorted(members_by_community):
                verdict = verdicts[community_id]
                forget_communities_total.labels(action=verdict.action.value).inc()
                logger.info(
                    "forget.community_decision",
                    entity_id=entity_id,
                    community_id=community_id,
                    size=verdict.size,
                    activity_score=verdict.activity_score,
                    action=verdict.action.value,
                )
                for mid in sorted(members_by_community[community_id]):
                    if mid not in forgotten:
                        continue
                    try:
                        await self.graph.mark_expired(mid, reason="community_forgotten")
                        count += 1
                    except Exception:
                        # A single failing memory must not abort the rest
                        # of the entity's communities.
                        logger.exception(
                            "forget.communities.mark_expired_error",
                            entity_id=entity_id,
                            memory_id=mid,
                        )
            return count
        except Exception:
            # AGENTS.md: 每次提取必须优雅处理失败 — one broken entity
            # must never abort the sweep across the rest.
            logger.exception("forget.communities.entity_error", entity_id=entity_id)
            return 0

    async def _community_features(
        self, entity_id: str, nodes: list[str]
    ) -> dict[str, MemoryFeatures]:
        """Assemble per-memory scoring features: graph records plus the
        entity profile's static/dynamic references (#38 seam)."""
        features: dict[str, MemoryFeatures] = {}
        for mid in nodes:
            memory = await self.graph.get_memory(mid)
            if memory is None:
                continue
            features[mid] = MemoryFeatures(
                confidence=float(memory.get("confidence", 0.5)),
                created_at=memory.get("created_at"),
                last_accessed_at=memory.get("last_accessed_at"),
            )

        if self._profile_manager is None:
            self._profile_manager = ProfileManager(graph=self.graph)
        profile = await self._profile_manager.get(entity_id)
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

    # ---- Duplicate consolidation (B6, #44) — runs daily at 5 AM ----

    async def consolidate_duplicates(self, entity_id: str | None = None) -> int:
        """Converge near-duplicate active facts into single representatives
        (B6, ADR-0006; spec #41).

        Per entity: vector candidates → guardrail verdicts (T1 #42, the
        rule layer decides — no LLM), then every merge lands through the
        atomic ``mark_consolidated`` seam (T2 #43). Runs after the
        forgetting batch, so only memories that survived it (is_latest)
        are eligible. One entity's failure is logged and skipped — the
        sweep never aborts.

        A duplicate *group* (the connected component of consolidate
        verdicts) converges on a single representative: the deterministic
        total order (trust desc → created_at desc → id asc) picks the
        group representative, and each other member merges into it iff
        its own pair verdict with the representative is CONSOLIDATE — a
        vetoed member is kept as-is (误并率 = 0 硬门: a veto is never
        bypassed through a third member).

        Observability: one structured log and one metric increment per
        pair decision (``emerald_consolidate_duplicates_total``, action
        labels from ``DuplicateAction``), plus a log line per landed
        merge.

        Returns the number of consolidated memories.
        """
        now = datetime.now(UTC)
        target_entities = [entity_id] if entity_id else await self._list_all_entity_ids()

        detector = DuplicatesDetector(
            graph=self.graph,
            vector=self._vector_store,
            profile_manager=self._profile_manager,
            config=self._duplicate_config,
        )

        total = 0
        for eid in target_entities:
            total += await self._consolidate_entity(eid, now, detector)

        if total:
            logger.info("forget.consolidate", count=total)
        return total

    async def _consolidate_entity(
        self, entity_id: str, now: datetime, detector: DuplicatesDetector
    ) -> int:
        """Detect + decide one entity, report every decision, then land the
        merges. A broken entity is logged and skipped (AGENTS.md: 每次提取
        必须优雅处理失败 — one failure never aborts the sweep)."""
        try:
            verdicts = await detector.detect(entity_id, now=now)
            if not verdicts:
                return 0

            for verdict in verdicts:  # already deterministic (pair-ids order)
                consolidate_duplicates_total.labels(action=verdict.action.value).inc()
                merged_id = None
                if verdict.representative_id is not None:
                    a_id: str = verdict.candidate.memory_a["id"]
                    merged_id = (
                        verdict.candidate.memory_b["id"]
                        if verdict.representative_id == a_id
                        else a_id
                    )
                logger.info(
                    "forget.consolidate.decision",
                    entity_id=entity_id,
                    memory_a=verdict.candidate.memory_a["id"],
                    memory_b=verdict.candidate.memory_b["id"],
                    similarity=verdict.candidate.similarity,
                    action=verdict.action.value,
                    reason=verdict.reason,
                    representative_id=verdict.representative_id,
                    merged_id=merged_id,
                )
            return await self._land_merges(entity_id, verdicts)
        except Exception:
            logger.exception("forget.consolidate.entity_error", entity_id=entity_id)
            return 0

    async def _land_merges(
        self, entity_id: str, verdicts: list[DuplicateVerdict]
    ) -> int:
        """Reduce consolidate verdicts to merges: group the pairs into
        connected components, pick the component representative with the
        deterministic total order, and consolidate every member into it
        iff the member's own pair verdict with the representative
        consolidates. A vetoed or absent pair verdict leaves the member
        untouched — pairwise guardrails are never bypassed transitively.
        """
        by_pair = {v.candidate.ids: v for v in verdicts}
        consolidating = [v for v in verdicts if v.action is DuplicateAction.CONSOLIDATE]
        if not consolidating:
            return 0

        # Union-find over the consolidating pairs → duplicate groups.
        parent: dict[str, str] = {}

        def _find(mid: str) -> str:
            root = parent.setdefault(mid, mid)
            while parent[root] != root:
                root = parent[root]
            while parent[mid] != root:  # path compression
                parent[mid], mid = root, parent[mid]
            return root

        def _union(a: str, b: str) -> None:
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[rb] = ra

        for verdict in consolidating:
            first_id, second_id = verdict.candidate.ids
            _union(first_id, second_id)

        members: dict[str, set[str]] = {}
        trust: dict[str, float] = {}
        records: dict[str, dict[str, Any]] = {}
        for verdict in consolidating:
            mem_a, mem_b = verdict.candidate.memory_a, verdict.candidate.memory_b
            members.setdefault(_find(mem_a["id"]), set()).update(
                (mem_a["id"], mem_b["id"])
            )
            trust.setdefault(mem_a["id"], verdict.candidate.trust_a)
            trust.setdefault(mem_b["id"], verdict.candidate.trust_b)
            records.setdefault(mem_a["id"], mem_a)
            records.setdefault(mem_b["id"], mem_b)

        count = 0
        for root in sorted(members):
            component = sorted(members[root])
            representative = select_representative(
                [records[mid] for mid in component], trust
            )
            for mid in component:
                if mid == representative:
                    continue
                pair = (mid, representative) if mid < representative else (
                    representative,
                    mid,
                )
                pair_verdict = by_pair.get(pair)
                if (
                    pair_verdict is None
                    or pair_verdict.action is not DuplicateAction.CONSOLIDATE
                ):
                    continue  # vetoed or unverified — kept as-is
                try:
                    await self.graph.mark_consolidated(
                        mid, representative, reason="consolidated"
                    )
                    count += 1
                    logger.info(
                        "forget.consolidate.merged",
                        entity_id=entity_id,
                        merged=mid,
                        representative=representative,
                    )
                except Exception:
                    # A single failing memory must not abort the rest of
                    # the entity's merges.
                    logger.exception(
                        "forget.consolidate.mark_consolidated_error",
                        entity_id=entity_id,
                        memory_id=mid,
                    )
        return count

    async def _list_all_entity_ids(self) -> list[str]:
        """List all entity IDs that have at least one latest memory.

        Delegates to GraphStore.list_entity_ids() which queries Neo4j
        in production or scans the in-memory store for tests.
        """
        return await self.graph.list_entity_ids()
