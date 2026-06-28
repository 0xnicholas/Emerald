"""Fast lane store — immediately-searchable raw chunks.

When content is ingested, a coarse fast-lane chunk is embedded and stored here
before (or in parallel with) the full extraction/chunking/relationship pipeline.
Search merges fast-lane hits alongside fully-indexed memories. Once the full
pipeline finishes, the corresponding fast-lane chunks are archived.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from emerald.config import get_settings
from emerald.core.constants import MemoryStage

logger = structlog.get_logger(__name__)


class FastLaneHit:
    """Single fast-lane search result."""

    def __init__(
        self,
        fast_lane_id: str,
        entity_id: str,
        text: str,
        score: float,
        created_at: datetime,
    ) -> None:
        self.fast_lane_id = fast_lane_id
        self.entity_id = entity_id
        self.text = text
        self.score = score
        self.created_at = created_at


class FastLaneStore:
    """Stores and searches coarse fast-lane chunks.

    Uses PostgreSQL in production (table ``fast_lane_chunks``) and an in-memory
    fallback for tests / local development.
    """

    def __init__(self, use_db: bool = True) -> None:
        self._use_db = use_db
        self._session_factory = None
        if use_db:
            try:
                from emerald.db.session import session_factory

                self._session_factory = session_factory
            except Exception:
                self._use_db = False

        # In-memory fallback: fast_lane_id -> dict
        self._memory_store: dict[str, dict[str, Any]] = {}

    async def store(
        self,
        text: str,
        embedding: list[float],
        *,
        entity_id: str,
        model_name: str = "unknown",
    ) -> str:
        """Store a new fast-lane chunk and return its ID."""
        fast_lane_id = uuid.uuid4().hex
        now = datetime.now(UTC)

        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text

            async with self._session_factory.session() as session:
                await session.execute(
                    sql_text(
                        """
                        INSERT INTO fast_lane_chunks (
                            id, entity_id, text, embedding, stage,
                            model_name, dimensions, created_at
                        )
                        VALUES (
                            :id, :entity_id, :text, :embedding, :stage,
                            :model_name, :dimensions, :created_at
                        )
                        """
                    ),
                    {
                        "id": fast_lane_id,
                        "entity_id": entity_id,
                        "text": text,
                        "embedding": embedding,
                        "stage": MemoryStage.FAST_LANE.value,
                        "model_name": model_name,
                        "dimensions": len(embedding),
                        "created_at": now,
                    },
                )
        else:
            self._memory_store[fast_lane_id] = {
                "id": fast_lane_id,
                "entity_id": entity_id,
                "text": text,
                "embedding": embedding,
                "stage": MemoryStage.FAST_LANE.value,
                "model_name": model_name,
                "dimensions": len(embedding),
                "created_at": now,
                "archived_at": None,
            }

        logger.debug(
            "fast_lane.stored",
            fast_lane_id=fast_lane_id,
            entity_id=entity_id,
            dims=len(embedding),
        )
        return fast_lane_id

    async def archive(self, fast_lane_id: str) -> bool:
        """Mark a fast-lane chunk as archived (no longer searchable)."""
        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text

            async with self._session_factory.session() as session:
                result = await session.execute(
                    sql_text(
                        """
                        UPDATE fast_lane_chunks
                        SET stage = :stage, archived_at = :archived_at
                        WHERE id = :id AND stage = :old_stage
                        """
                    ),
                    {
                        "id": fast_lane_id,
                        "stage": MemoryStage.ARCHIVED.value,
                        "old_stage": MemoryStage.FAST_LANE.value,
                        "archived_at": datetime.now(UTC),
                    },
                )
                return result.rowcount > 0

        memory = self._memory_store.get(fast_lane_id)
        if memory and memory.get("stage") == MemoryStage.FAST_LANE.value:
            memory["stage"] = MemoryStage.ARCHIVED.value
            memory["archived_at"] = datetime.now(UTC)
            return True
        return False

    async def search(
        self,
        query_embedding: list[float],
        *,
        entity_id: str,
        top_k: int = 10,
        max_age_hours: float | None = None,
    ) -> list[FastLaneHit]:
        """Search active fast-lane chunks by cosine similarity."""
        settings = get_settings()
        max_age = timedelta(
            hours=max_age_hours if max_age_hours is not None else settings.fast_lane_max_age_hours
        )
        cutoff = datetime.now(UTC) - max_age

        candidates: list[dict[str, Any]] = []

        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text

            async with self._session_factory.session() as session:
                result = await session.execute(
                    sql_text(
                        """
                        SELECT id, entity_id, text, embedding, created_at
                        FROM fast_lane_chunks
                        WHERE entity_id = :entity_id
                          AND stage = :stage
                          AND created_at > :cutoff
                        """
                    ),
                    {
                        "entity_id": entity_id,
                        "stage": MemoryStage.FAST_LANE.value,
                        "cutoff": cutoff,
                    },
                )
                for row in result.fetchall():
                    candidates.append(
                        {
                            "id": row.id,
                            "entity_id": row.entity_id,
                            "text": row.text,
                            "embedding": row.embedding,
                            "created_at": row.created_at,
                        }
                    )
        else:
            for memory in self._memory_store.values():
                if memory.get("entity_id") != entity_id:
                    continue
                if memory.get("stage") != MemoryStage.FAST_LANE.value:
                    continue
                created_at = memory["created_at"]
                if created_at < cutoff:
                    continue
                candidates.append(memory)

        scored: list[tuple[float, dict[str, Any]]] = []
        for memory in candidates:
            score = self._cosine_similarity(query_embedding, memory["embedding"])
            scored.append((score, memory))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            FastLaneHit(
                fast_lane_id=memory["id"],
                entity_id=memory["entity_id"],
                text=memory["text"],
                score=score,
                created_at=memory["created_at"],
            )
            for score, memory in scored[:top_k]
        ]

    async def cleanup(self, max_age_hours: float | None = None) -> int:
        """Archive fast-lane chunks older than the configured age."""
        settings = get_settings()
        max_age = timedelta(
            hours=max_age_hours if max_age_hours is not None else settings.fast_lane_max_age_hours
        )
        cutoff = datetime.now(UTC) - max_age
        count = 0

        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text

            async with self._session_factory.session() as session:
                result = await session.execute(
                    sql_text(
                        """
                        UPDATE fast_lane_chunks
                        SET stage = :stage, archived_at = :archived_at
                        WHERE stage = :old_stage AND created_at <= :cutoff
                        """
                    ),
                    {
                        "stage": MemoryStage.ARCHIVED.value,
                        "old_stage": MemoryStage.FAST_LANE.value,
                        "archived_at": datetime.now(UTC),
                        "cutoff": cutoff,
                    },
                )
                count = result.rowcount
        else:
            for memory in list(self._memory_store.values()):
                if (
                    memory.get("stage") == MemoryStage.FAST_LANE.value
                    and memory["created_at"] <= cutoff
                ):
                    memory["stage"] = MemoryStage.ARCHIVED.value
                    memory["archived_at"] = datetime.now(UTC)
                    count += 1

        if count:
            logger.info("fast_lane.cleanup", archived_count=count)
        return count

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
