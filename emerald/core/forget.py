"""Forget engine — automatic memory lifecycle management.

Four strategies, triggered by Celery Beat scheduled tasks:

1. Time-based expiry: valid_until passed → is_latest=False, expired_at=now
2. Contradiction resolution: handled by RelationshipEngine (Phase 4)
3. Noise filtering: confidence < 0.3, no references, > 7 days old → archive
4. Episodic decay: episodic memories > 90 days → archive

AGENTS.md: "没有遗忘，每句随意的话都会变成永久记忆。图谱膨胀，噪音累积，检索质量下降。遗忘不是 bug——它是一项特性。"
"""

from __future__ import annotations

import structlog
from datetime import datetime, timedelta, timezone
from enum import Enum

from emerald.core.graph import GraphStore

logger = structlog.get_logger(__name__)


class ForgetStrategy(str, Enum):
    TIME_EXPIRY = "time_expiry"
    CONTRADICTION = "contradiction"
    NOISE_FILTER = "noise_filter"
    EPISODIC_DECAY = "episodic_decay"


class ForgetEngine:
    """Manages automatic forgetting of memories.

    Each strategy is a task that scans the graph and marks
    memories as is_latest=False with appropriate metadata.
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

        In production Neo4j:
          MATCH (m:Memory)
          WHERE m.valid_until IS NOT NULL
            AND m.valid_until < datetime()
            AND m.is_latest = true
          SET m.is_latest = false, m.expired_at = datetime()
        """
        now = datetime.now(timezone.utc)
        count = 0

        entities = [entity_id] if entity_id else list(self.graph._memories.keys())

        for eid in entities:
            for m in self.graph._memories.get(eid, []):
                if not m["is_latest"]:
                    continue
                valid_until = m.get("valid_until")
                if valid_until is not None and valid_until < now:
                    m["is_latest"] = False
                    m["expired_at"] = now
                    count += 1

        if count:
            logger.info("forget.expired", count=count)
        return count

    # ---- Noise filtering (runs daily at 3 AM) ----

    async def forget_noise(self, entity_id: str | None = None) -> int:
        """Archive low-confidence, old, unreferenced memories.

        Conditions:
        - confidence < NOISE_MAX_CONFIDENCE
        - created > NOISE_MIN_AGE_DAYS ago
        - is_latest=True (not already handled by another strategy)
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self.NOISE_MIN_AGE_DAYS)
        count = 0

        entities = [entity_id] if entity_id else list(self.graph._memories.keys())

        for eid in entities:
            for m in self.graph._memories.get(eid, []):
                if not m["is_latest"]:
                    continue

                confidence = m.get("confidence", 0.5)
                created_at = m.get("created_at", now)

                if confidence < self.NOISE_MAX_CONFIDENCE and created_at < cutoff:
                    m["is_latest"] = False
                    m["expired_at"] = now
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
        now = datetime.now(timezone.utc)
        archive_cutoff = now - timedelta(days=self.EPISODIC_ARCHIVE_DAYS)
        count = 0

        for eid in self.graph._memories:
            for m in self.graph._memories[eid]:
                if not m["is_latest"]:
                    continue

                memory_type = m.get("memory_type", "fact")
                if memory_type != "episodic":
                    continue

                created_at = m.get("created_at", now)
                if created_at < archive_cutoff:
                    m["is_latest"] = False
                    m["expired_at"] = now
                    count += 1

        if count:
            logger.info("forget.episodic_decay", count=count)
        return count
