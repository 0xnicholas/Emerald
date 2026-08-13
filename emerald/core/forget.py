"""Forget engine — automatic memory lifecycle management.

Four strategies, triggered by Celery Beat scheduled tasks:

1. Time-based expiry: valid_until passed → is_latest=False, expired_at=now
2. Contradiction resolution: handled by RelationshipEngine (Phase 4)
3. Noise filtering: confidence < 0.3, no references, > 7 days old → archive
4. Episodic decay: episodic memories > 90 days → archive

Forgetting integration (B3 NER, #27): every strategy funnels through
GraphStore.mark_expired, which also removes the memory's MENTIONS edges
and prunes Mention nodes left with zero MENTIONS edges — the graph never
accumulates dead mention nodes. The UPDATES replacement path is separate
(update_is_latest) and keeps the replaced memory's historical edges (#26).

AGENTS.md: "没有遗忘，每句随意的话都会变成永久记忆。图谱膨胀，噪音累积，检索质量下降。遗忘不是 bug——它是一项特性。"
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum

import structlog

from emerald.core.graph import GraphStore

logger = structlog.get_logger(__name__)


class ForgetStrategy(str, Enum):
    TIME_EXPIRY = "time_expiry"
    CONTRADICTION = "contradiction"
    NOISE_FILTER = "noise_filter"
    EPISODIC_DECAY = "episodic_decay"


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

    def __init__(self, graph: GraphStore | None = None) -> None:
        self.graph = graph or GraphStore(use_db=False)

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

    async def _list_all_entity_ids(self) -> list[str]:
        """List all entity IDs that have at least one latest memory.

        Delegates to GraphStore.list_entity_ids() which queries Neo4j
        in production or scans the in-memory store for tests.
        """
        return await self.graph.list_entity_ids()
