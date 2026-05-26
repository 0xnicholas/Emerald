"""Pipeline orchestrator — synchronous and asynchronous pipeline entry points.

The orchestrator chains together the four pipeline stages (extract → chunk →
embed → index) and provides both sync (lightweight content) and async
(Celery-driven, for files/batch) processing modes.
"""

from __future__ import annotations

from uuid import uuid4

import structlog

from emerald.pipeline.chunking.registry import ChunkerRegistry
from emerald.pipeline.extraction.registry import ExtractorRegistry

logger = structlog.get_logger(__name__)


class PipelineOrchestrator:
    """Orchestrates the content processing pipeline.

    Sync mode returns results directly. Async mode submits a Celery chain
    and returns a pipeline_id for status tracking.
    """

    def __init__(
        self,
        extractor_registry: ExtractorRegistry | None = None,
        chunker_registry: ChunkerRegistry | None = None,
        *,
        use_db: bool = True,
    ) -> None:
        # Lazy import to avoid circular dependency:
        # pipeline.orchestrator -> core.engine -> core.chunker -> pipeline.chunking.base
        from emerald.core.engine import MemoryEngine

        self._engine = MemoryEngine(
            extractor_registry=extractor_registry,
            chunker_registry=chunker_registry,
            use_db=use_db,
        )

    async def process_sync(
        self,
        content: str,
        *,
        content_type: str,
        entity_id: str,
        metadata: dict | None = None,
    ) -> list[str]:
        """Process lightweight content synchronously.

        When *use_db* is ``True`` (the default), memory nodes are written to
        Neo4j and embeddings to pgvector.  When ``False``, the pipeline runs
        in-memory and only returns memory IDs.

        Returns the list of created memory IDs.
        """
        result = await self._engine.add(
            content,
            entity_id=entity_id,
            content_type=content_type,
            metadata=metadata,
        )
        return result.memory_ids

    async def process_async(
        self,
        content: str | bytes,
        *,
        content_type: str,
        entity_id: str,
        document_id: str | None = None,
    ) -> str:
        """Submit content for async pipeline processing.

        Suitable for files, URLs, and batch content.
        Returns the pipeline_id for status polling.
        """
        from hashlib import sha256

        pipeline_id = uuid4().hex
        content_hash = sha256(
            content.encode() if isinstance(content, str) else content
        ).hexdigest()

        # TODO: Write PipelineJob record to PostgreSQL
        # TODO: Submit Celery chain:
        #   chain(extract_task, chunk_task, embed_task, index_task, postprocess_task)
        logger.info(
            "pipeline.async.submitted",
            pipeline_id=pipeline_id,
            entity_id=entity_id,
            content_type=content_type,
        )

        return pipeline_id
