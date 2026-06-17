"""Background reconciliation — repair orphaned graph nodes missing vector entries.

When the process crashes between Neo4j write and pgvector write, a memory
node exists in the graph with ``is_latest=True`` but has no corresponding
row in the embeddings table.  The :class:`ReconciliationEngine` periodically
scans for these orphans and either retries the vector write or marks them as
``indexing_failed``.
"""

from __future__ import annotations

import structlog

from emerald.core.embedder import EmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.metrics import pipeline_jobs_total
from emerald.core.vector import VectorStore

logger = structlog.get_logger(__name__)


class ReconciliationEngine:
    """Periodically scan for and repair orphaned graph nodes.

    An *orphan* is a Memory node with ``is_latest=True`` whose ``chunk_id``
    (memory ID) does not appear in the pgvector ``embeddings`` table.  The
    engine operates in a read-repair loop with configurable lookback window.
    """

    def __init__(
        self,
        *,
        graph: GraphStore,
        vector: VectorStore,
        embedder: EmbeddingProvider,
    ) -> None:
        self.graph = graph
        self.vector = vector
        self.embedder = embedder

    async def reconcile(
        self,
        *,
        lookback_minutes: int = 120,
        max_repairs: int = 200,
    ) -> dict:
        """Find and repair orphaned memories created in the last N minutes.

        For each orphan: re-embed the text and write to pgvector.  If
        embedding or the vector write fails, mark the graph node as
        ``is_latest=False`` with ``replaced_by="reconciliation_failed"``.

        Returns a summary dict with ``found``, ``repaired``, ``failed`` counts.
        """
        logger.info(
            "reconciliation.start",
            lookback_minutes=lookback_minutes,
            max_repairs=max_repairs,
        )

        # 1. Fetch recent memories from Neo4j
        recent = await self.graph.list_recent_memories(
            since_minutes=lookback_minutes,
            limit=max_repairs * 2,  # oversample — some may already be in pgvector
        )

        if not recent:
            logger.info("reconciliation.nothing_to_do")
            return {"found": 0, "repaired": 0, "failed": 0}

        # 2. Find orphans (memories without vector entries)
        orphans: list[dict] = []
        for mem in recent:
            memory_id = mem["id"]
            try:
                has_vector = await self.vector.exists(memory_id)
            except Exception:
                # Vector store might be temporarily unavailable — skip
                logger.warning(
                    "reconciliation.vector_check_failed",
                    memory_id=memory_id,
                    exc_info=True,
                )
                continue

            if not has_vector:
                orphans.append(mem)

        if not orphans:
            logger.info("reconciliation.no_orphans", total_checked=len(recent))
            return {"found": 0, "repaired": 0, "failed": 0}

        logger.info(
            "reconciliation.orphans_found",
            count=len(orphans),
            total_checked=len(recent),
        )

        # Limit batch size
        to_repair = orphans[:max_repairs]

        repaired = 0
        failed = 0

        for mem in to_repair:
            memory_id = mem["id"]
            content = mem.get("content", "")
            entity_id = mem.get("entity_id", "unknown")

            if not content.strip():
                # No text to embed — mark as failed
                await self._mark_failed(memory_id, reason="no_content")
                failed += 1
                continue

            # 3. Re-embed + write to vector store
            try:
                embeddings = await self.embedder.embed([content])
                if not embeddings:
                    raise ValueError("embedder returned empty result")

                model_name = getattr(self.embedder, "_model", "unknown")
                await self.vector.store(
                    chunk_id=memory_id,
                    text=content,
                    embedding=embeddings[0],
                    entity_id=entity_id,
                    model_name=model_name,
                )
                repaired += 1
                logger.info(
                    "reconciliation.repaired",
                    memory_id=memory_id,
                    entity_id=entity_id,
                )
            except Exception as exc:
                logger.error(
                    "reconciliation.repair_failed",
                    memory_id=memory_id,
                    entity_id=entity_id,
                    error=str(exc),
                )
                await self._mark_failed(memory_id, reason="reconciliation_failed")
                failed += 1

        # Update metrics
        if repaired:
            pipeline_jobs_total.labels(status="reconciled").inc(repaired)
        if failed:
            pipeline_jobs_total.labels(status="reconciliation_failed").inc(failed)

        logger.info(
            "reconciliation.complete",
            found=len(orphans),
            repaired=repaired,
            failed=failed,
        )

        return {"found": len(orphans), "repaired": repaired, "failed": failed}

    async def _mark_failed(self, memory_id: str, reason: str) -> None:
        """Mark a memory as not-latest because reconciliation could not repair it."""
        try:
            await self.graph.update_is_latest(
                memory_id, False, replaced_by=reason
            )
        except Exception as exc:
            logger.error(
                "reconciliation.mark_failed_error",
                memory_id=memory_id,
                reason=reason,
                error=str(exc),
            )
