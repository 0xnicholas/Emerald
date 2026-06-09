"""Memory engine — the central entry point for content ingestion.

Routes incoming content through the pipeline: detect type → extract → chunk → embed → index.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog

from emerald.core.chunker import Chunk, ChunkerRegistry, get_default_registry as get_default_chunker_registry
from emerald.core.embedder import EmbeddingProvider, get_embedding_provider
from emerald.core.exceptions import IndexingError
from emerald.core.extractor import ExtractedContent, ExtractorRegistry, get_default_registry as get_default_extractor_registry
from emerald.core.graph import GraphStore
from emerald.core.metrics import memory_add_latency_seconds, memory_add_total, timed
from emerald.core.tracing import get_tracer
from emerald.core.profile import ProfileManager
from emerald.core.relationship import RelationshipEngine
from emerald.core.vector import VectorStore

logger = structlog.get_logger(__name__)


class AddResult:
    """Result of a memory add operation."""

    def __init__(
        self,
        memory_ids: list[str],
        pipeline_status: str = "done",
        extracted_count: int = 0,
    ) -> None:
        self.memory_ids = memory_ids
        self.pipeline_status = pipeline_status
        self.extracted_count = extracted_count


class MemoryEngine:
    """Central orchestrator for content ingestion.

    Runs the pipeline: extract → chunk → embed → index (graph + vector).
    Supports sync (text) and async (files) processing modes.
    """

    def __init__(
        self,
        *,
        extractor_registry: ExtractorRegistry | None = None,
        chunker_registry: ChunkerRegistry | None = None,
        embedder: EmbeddingProvider | None = None,
        graph: GraphStore | None = None,
        vector: VectorStore | None = None,
        relationships: RelationshipEngine | None = None,
        profile_manager: ProfileManager | None = None,
        use_db: bool = False,
    ) -> None:
        self.extractors = extractor_registry or get_default_extractor_registry()
        self.chunkers = chunker_registry or get_default_chunker_registry()
        self.embedder = embedder or get_embedding_provider()
        self.graph = graph or GraphStore(use_db=use_db)
        self.vector = vector or VectorStore(use_db=use_db)
        self.relationships = relationships or RelationshipEngine()
        self.profile_manager = profile_manager or ProfileManager()

    async def add(
        self,
        content: str,
        *,
        entity_id: str,
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> AddResult:
        """Add content to the memory graph (synchronous path).

        Returns AddResult with memory IDs.
        """
        tracer = get_tracer()
        with tracer.start_as_current_span("memory.add") as span:
            span.set_attribute("entity_id", entity_id)
            span.set_attribute("content_type", content_type)
            with timed(memory_add_latency_seconds):
                # Idempotency check
                if idempotency_key:
                    cached = await self._check_idempotency(entity_id, idempotency_key)
                    if cached:
                        logger.info("memory.add.idempotent", entity_id=entity_id, key=idempotency_key)
                        return cached

                logger.info(
                    "memory.add.start",
                    entity_id=entity_id,
                    content_type=content_type,
                    content_length=len(content),
                )

                # 1. Extract
                extracted = await self._extract(content, content_type)

                # 2. Chunk
                chunks = await self._chunk(extracted, content_type)

                # 3. Embed
                embeddings = await self._embed(chunks)

                # 4. Index — store in graph + vector
                memory_ids = await self._index(
                    chunks, embeddings, entity_id, content_type, metadata
                )

                # 5. Infer relationships
                await self.relationships.infer(memory_ids, entity_id)

                # 6. Invalidate profile cache
                await self.profile_manager.invalidate(entity_id)

                result = AddResult(
                    memory_ids=memory_ids,
                    pipeline_status="done",
                    extracted_count=len(chunks),
                )

                # Cache result for idempotency
                if idempotency_key:
                    await self._cache_idempotency(entity_id, idempotency_key, result)

                from collections import Counter
                type_counts = Counter(c.memory_type for c in chunks)
                for mt, count in type_counts.items():
                    memory_add_total.labels(memory_type=mt).inc(count)

                logger.info(
                    "memory.add.complete",
                    entity_id=entity_id,
                    memory_count=len(memory_ids),
                )

                return result

    async def _check_idempotency(
        self, entity_id: str, key: str
    ) -> AddResult | None:
        """Check Redis for a cached idempotent result."""
        try:
            from emerald.db.redis import get_redis_client

            redis = get_redis_client()
            cached = await redis.get(f"idempotency:{entity_id}:{key}")
            if cached:
                import json

                data = json.loads(cached)
                return AddResult(
                    memory_ids=data["memory_ids"],
                    pipeline_status=data["pipeline_status"],
                    extracted_count=data["extracted_count"],
                )
        except Exception:
            pass
        return None

    async def _cache_idempotency(
        self, entity_id: str, key: str, result: AddResult
    ) -> None:
        """Cache add result in Redis for 1 hour."""
        try:
            from emerald.db.redis import get_redis_client

            redis = get_redis_client()
            import json

            await redis.setex(
                f"idempotency:{entity_id}:{key}",
                3600,
                json.dumps({
                    "memory_ids": result.memory_ids,
                    "pipeline_status": result.pipeline_status,
                    "extracted_count": result.extracted_count,
                }),
            )
        except Exception:
            pass

    async def _extract(self, content: str, content_type: str) -> ExtractedContent:
        """Extract clean text from raw content."""
        return await self.extractors.extract(content, content_type)

    async def _chunk(self, extracted: ExtractedContent, content_type: str) -> list[Chunk]:
        """Split extracted text into semantic chunks."""
        return await self.chunkers.chunk(
            extracted.text,
            content_type,
            metadata=extracted.metadata,
        )

    async def _embed(self, chunks: list[Chunk]) -> list[list[float]]:
        """Generate embeddings for all chunks with Redis cache."""
        texts = [c.text for c in chunks]
        if not texts:
            return []

        try:
            from emerald.db.redis import get_redis_client

            redis = get_redis_client()
        except RuntimeError:
            redis = None

        import hashlib
        import json

        hashes = [hashlib.sha256(t.encode()).hexdigest() for t in texts]

        embeddings: list[list[float] | None] = [None] * len(texts)
        to_embed: list[str] = []
        to_embed_indices: list[int] = []

        if redis:
            cached = await redis.mget([f"emb:{h}" for h in hashes])
        else:
            cached = [None] * len(texts)

        for i, c in enumerate(cached):
            if c is not None:
                embeddings[i] = json.loads(c)
            else:
                to_embed.append(texts[i])
                to_embed_indices.append(i)

        if to_embed:
            new_embeddings = await self.embedder.embed(to_embed)
            if redis:
                pipe = redis.pipeline()
                for idx, emb in zip(to_embed_indices, new_embeddings):
                    pipe.setex(f"emb:{hashes[idx]}", 7 * 86400, json.dumps(emb))
                await pipe.execute()
            for idx, emb in zip(to_embed_indices, new_embeddings):
                embeddings[idx] = emb

        return [e for e in embeddings if e is not None]

    async def _index(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        entity_id: str,
        content_type: str,
        metadata: dict[str, Any] | None,
    ) -> list[str]:
        """Store chunks in Neo4j and pgvector, return memory IDs.

        Uses a per-chunk compensation pattern: if the vector store write fails
        after the graph node has been created, the graph node is marked as
        is_latest=False so it never surfaces in search results.  This keeps
        the two stores loosely consistent without a distributed transaction.
        """
        memory_ids = []
        failed_chunks: list[tuple[str, str]] = []  # (memory_id, reason)
        model_name = getattr(self.embedder, "_model", "unknown")

        for chunk, embedding in zip(chunks, embeddings):
            # 1. Store in Neo4j graph — memory_id becomes the canonical ID
            memory_id = await self.graph.create_memory(
                content=chunk.text,
                entity_id=entity_id,
                memory_type=chunk.memory_type,
                confidence=chunk.confidence,
                summary=chunk.summary or None,
                source_type="conversation" if content_type == "conversation" else "document",
                metadata=metadata,
            )
            chunk.id = memory_id

            # 2. Store embedding in vector store
            try:
                await self.vector.store(
                    chunk_id=memory_id,
                    text=chunk.text,
                    embedding=embedding,
                    entity_id=entity_id,
                    model_name=model_name,
                )
                memory_ids.append(memory_id)
            except Exception as exc:
                # Compensation: mark graph node as failed so it doesn't leak into search
                logger.warning(
                    "index.vector_store_failed",
                    memory_id=memory_id,
                    entity_id=entity_id,
                    error=str(exc),
                )
                try:
                    await self.graph.update_is_latest(
                        memory_id, False, replaced_by="indexing_failed"
                    )
                except Exception as comp_exc:
                    logger.error(
                        "index.compensation_failed",
                        memory_id=memory_id,
                        error=str(comp_exc),
                    )
                failed_chunks.append((memory_id, str(exc)))

        if failed_chunks:
            logger.error(
                "index.partial_failure",
                entity_id=entity_id,
                success=len(memory_ids),
                failed=len(failed_chunks),
            )
            if not memory_ids:
                raise IndexingError(
                    f"All {len(failed_chunks)} chunk indexings failed. "
                    f"First error: {failed_chunks[0][1]}"
                )

        return memory_ids

    async def process_async(
        self,
        content: str | bytes,
        *,
        entity_id: str,
        content_type: str,
        document_id: str | None = None,
    ) -> str:
        """Submit content for async pipeline processing (files, batch).

        Delegates to PipelineOrchestrator for full Celery chain execution.
        Returns pipeline_id for status tracking.
        """
        from emerald.pipeline.orchestrator import PipelineOrchestrator

        orchestrator = PipelineOrchestrator(
            extractor_registry=self.extractors,
            chunker_registry=self.chunkers,
        )
        return await orchestrator.process_async(
            content=content,
            content_type=content_type,
            entity_id=entity_id,
            document_id=document_id,
        )
