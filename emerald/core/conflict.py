"""Conflict detection and resolution engine.

Emerald resolves most conflicts automatically (UPDATE relationship + is_latest).
For high-impact facts, this engine can flag a conflict for external confirmation
instead of auto-overwriting.  It is an optional path; the default remains fully
automatic.
"""

from __future__ import annotations

from enum import Enum
from uuid import uuid4

import structlog

from emerald.core.graph import GraphStore

logger = structlog.get_logger(__name__)


class ResolutionAction(str, Enum):
    KEEP_OLD = "keep_old"
    KEEP_NEW = "keep_new"
    KEEP_BOTH = "keep_both"
    MANUAL = "manual"


class ConflictEngine:
    """Scores conflict impact and supports optional interactive resolution."""

    # Types that describe identity-defining or high-stakes facts
    HIGH_IMPACT_INTERNAL_TYPES = frozenset({"decision", "commitment", "goal"})
    MEDIUM_IMPACT_INTERNAL_TYPES = frozenset({"preference", "relationship", "error"})

    def __init__(self, graph: GraphStore | None = None) -> None:
        self.graph = graph or GraphStore(use_db=False)

    @staticmethod
    def impact_score(new_memory: dict, old_memory: dict) -> float:
        """Score how consequential overwriting ``old_memory`` with ``new_memory`` is.

        Returns a value in [0, 1]. High-impact facts (decisions, commitments,
        goals) and high-confidence contradictions score higher.
        """
        score = 0.0

        # Base impact from internal fine type
        new_internal = new_memory.get("internal_type")
        old_internal = old_memory.get("internal_type")
        if new_internal in ConflictEngine.HIGH_IMPACT_INTERNAL_TYPES:
            score += 0.4
        elif new_internal in ConflictEngine.MEDIUM_IMPACT_INTERNAL_TYPES:
            score += 0.25
        if old_internal in ConflictEngine.HIGH_IMPACT_INTERNAL_TYPES:
            score += 0.3
        elif old_internal in ConflictEngine.MEDIUM_IMPACT_INTERNAL_TYPES:
            score += 0.15

        # Public memory type contribution
        high_impact_types = {"fact", "preference"}
        if new_memory.get("memory_type") in high_impact_types:
            score += 0.1
        if old_memory.get("memory_type") in high_impact_types:
            score += 0.1

        # Confidence of the new fact: high-confidence contradictions are riskier
        new_conf = float(new_memory.get("confidence", 0.8))
        score += min(new_conf * 0.2, 0.2)

        return min(score, 1.0)

    def requires_confirmation(
        self,
        new_memory: dict,
        old_memory: dict,
        *,
        threshold: float = 0.7,
        min_confidence: float = 0.9,
    ) -> bool:
        """Return True if this conflict should be confirmed before auto-resolving."""
        new_conf = float(new_memory.get("confidence", 0.8))
        return self.impact_score(new_memory, old_memory) >= threshold and new_conf >= min_confidence

    async def create_pending_conflict(
        self,
        new_memory_id: str,
        old_memory_id: str,
        *,
        reason: str = "high_impact_contradiction",
        impact_score: float | None = None,
    ) -> str:
        """Create a PENDING_CONFLICT relationship and return its conflict ID."""
        conflict_id = uuid4().hex
        await self.graph.create_relationship(
            from_id=new_memory_id,
            to_id=old_memory_id,
            rel_type="PENDING_CONFLICT",
            properties={
                "conflict_id": conflict_id,
                "reason": reason,
                "status": "pending",
                "impact_score": impact_score or 0.0,
            },
        )
        logger.info(
            "conflict.pending",
            conflict_id=conflict_id,
            new=new_memory_id,
            old=old_memory_id,
            impact_score=impact_score,
        )
        return conflict_id

    async def resolve(
        self,
        conflict_id: str,
        action: ResolutionAction,
    ) -> dict:
        """Resolve a pending conflict.

        Actions:
        - ``keep_old``: archive the new memory (is_latest=False).
        - ``keep_new``: apply the update (old memory is_latest=False, create UPDATES).
        - ``keep_both``: mark conflict resolved, keep both memories latest.
        - ``manual``: mark as manual, do not touch memories.
        """
        rel = await self.graph.get_relationship_by_property(
            rel_type="PENDING_CONFLICT", key="conflict_id", value=conflict_id
        )
        if not rel:
            raise ValueError(f"Conflict '{conflict_id}' not found")

        new_id = rel["from_id"]
        old_id = rel["to_id"]

        if action == ResolutionAction.KEEP_OLD:
            await self.graph.update_is_latest(new_id, False, replaced_by=old_id)
            await self.graph.update_relationship_property(
                rel_type="PENDING_CONFLICT",
                from_id=new_id,
                to_id=old_id,
                key="status",
                value="resolved_keep_old",
            )
            logger.info("conflict.resolved", conflict_id=conflict_id, action="keep_old")
            return {"conflict_id": conflict_id, "action": action.value, "status": "resolved"}

        if action == ResolutionAction.KEEP_NEW:
            await self.graph.create_update_relation(
                new_id, old_id, properties={"reason": "confirmed_resolution", "confidence": 0.95}
            )
            await self.graph.update_relationship_property(
                rel_type="PENDING_CONFLICT",
                from_id=new_id,
                to_id=old_id,
                key="status",
                value="resolved_keep_new",
            )
            logger.info("conflict.resolved", conflict_id=conflict_id, action="keep_new")
            return {"conflict_id": conflict_id, "action": action.value, "status": "resolved"}

        if action == ResolutionAction.KEEP_BOTH:
            await self.graph.update_relationship_property(
                rel_type="PENDING_CONFLICT",
                from_id=new_id,
                to_id=old_id,
                key="status",
                value="resolved_keep_both",
            )
            logger.info("conflict.resolved", conflict_id=conflict_id, action="keep_both")
            return {"conflict_id": conflict_id, "action": action.value, "status": "resolved"}

        if action == ResolutionAction.MANUAL:
            await self.graph.update_relationship_property(
                rel_type="PENDING_CONFLICT",
                from_id=new_id,
                to_id=old_id,
                key="status",
                value="manual",
            )
            logger.info("conflict.resolved", conflict_id=conflict_id, action="manual")
            return {"conflict_id": conflict_id, "action": action.value, "status": "manual"}

        raise ValueError(f"Unknown resolution action: {action}")
