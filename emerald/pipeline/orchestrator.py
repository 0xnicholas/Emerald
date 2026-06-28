"""Pipeline orchestrator — synchronous and asynchronous pipeline entry points.

The orchestrator chains together the four pipeline stages (extract → chunk →
embed → index) and provides both sync (lightweight content) and async
(Celery-driven, for files/batch) processing modes.
"""

from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import structlog
from celery import chain

from emerald.config import get_settings
from emerald.db.session import session_factory
from emerald.models.pipeline_job import PipelineJob
from emerald.pipeline.chunking.registry import ChunkerRegistry
from emerald.pipeline.extraction.registry import ExtractorRegistry
from emerald.pipeline.tasks import (
    chunk_task,
    embed_task,
    extract_task,
    index_task,
    postprocess_task,
)
from emerald.utils import _is_uuid

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
        from emerald.pipeline.extraction import get_default_registry as get_default_extractors
        from emerald.pipeline.chunking import get_default_registry as get_default_chunkers

        self.extractors = extractor_registry or get_default_extractors()
        self.chunkers = chunker_registry or get_default_chunkers()
        self._engine = MemoryEngine(
            extractor_registry=self.extractors,
            chunker_registry=self.chunkers,
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
            content=content,
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
        import uuid

        pipeline_id = uuid4().hex
        content_hash = sha256(
            content.encode() if isinstance(content, str) else content
        ).hexdigest()

        async with session_factory.session() as session:
            from sqlalchemy import select
            from emerald.models.entity import Entity

            result = await session.execute(
                select(Entity).where(Entity.external_id == entity_id)
            )
            entity = result.scalar_one_or_none()
            if not entity:
                raise ValueError(f"Entity '{entity_id}' not found")

            session.add(
                PipelineJob(
                    id=uuid.UUID(pipeline_id),
                    entity_id=entity.id,
                    document_id=uuid.UUID(document_id)
                    if document_id and _is_uuid(document_id)
                    else None,
                    content_hash=content_hash,
                    content_type=content_type,
                    status="queued",
                )
            )
            await session.commit()

        # Fast lane: for textual content, store a coarse searchable chunk
        # immediately so the upload is retrievable before the pipeline finishes.
        fast_lane_id: str | None = None
        if get_settings().fast_lane_enabled and isinstance(content, str):
            fast_lane_ids = await self._engine._fast_lane_index(content, entity_id)
            fast_lane_id = fast_lane_ids[0] if fast_lane_ids else None
            if fast_lane_id:
                try:
                    from emerald.db.redis import get_redis_client

                    redis = get_redis_client()
                    await redis.setex(
                        f"pipeline:{pipeline_id}:fast_lane_id",
                        2 * 86400,
                        fast_lane_id,
                    )
                except Exception:
                    pass

        chain(
            extract_task.s(pipeline_id, content, content_type),
            chunk_task.s(),
            embed_task.s(),
            index_task.s(entity_id),
            postprocess_task.s(entity_id),
        ).apply_async()

        logger.info(
            "pipeline.async.submitted",
            pipeline_id=pipeline_id,
            entity_id=entity_id,
            content_type=content_type,
            fast_lane_id=fast_lane_id,
        )
        return pipeline_id
