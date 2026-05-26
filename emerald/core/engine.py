"""Memory engine — the central entry point for content ingestion.

Routes incoming content through the pipeline: detect type → extract → chunk → embed → index.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog

from emerald.core.chunker import Chunk, ChunkerRegistry
from emerald.core.embedder import EmbeddingProvider, get_embedding_provider
from emerald.core.extractor import ExtractedContent, ExtractorRegistry
from emerald.core.graph import GraphStore
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
        self.extractors = extractor_registry or ExtractorRegistry()
        self.chunkers = chunker_registry or ChunkerRegistry()
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
    ) -> AddResult:
        """Add content to the memory graph (synchronous path).

        Returns AddResult with memory IDs.
        """
        logger.info(
            "memory.add.start",
            entity_id=entity_id,
            content_type=content_type,
            content_length=len(content),
        )

        # 1. Extract
        extracted = await self._extract(content, content_type)

        # 2. Chunk
        chunks = self._chunk(extracted, content_type)

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

        logger.info(
            "memory.add.complete",
            entity_id=entity_id,
            memory_count=len(memory_ids),
        )

        return AddResult(
            memory_ids=memory_ids,
            pipeline_status="done",
            extracted_count=len(chunks),
        )

    async def _extract(self, content: str, content_type: str) -> ExtractedContent:
        """Extract clean text from raw content."""
        return await self.extractors.extract(content, content_type)

    def _chunk(self, extracted: ExtractedContent, content_type: str) -> list[Chunk]:
        """Split extracted text into semantic chunks."""
        return self.chunkers.chunk(
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
        """Store chunks in Neo4j and pgvector, return memory IDs."""
        memory_ids = []

        for chunk, embedding in zip(chunks, embeddings):
            # Store in Neo4j graph — memory_id becomes the canonical ID
            memory_id = await self.graph.create_memory(
                content=chunk.text,
                entity_id=entity_id,
                memory_type="fact",
                confidence=0.8,
                source_type="conversation" if content_type == "conversation" else "document",
            )
            # Unify IDs: vector-store row uses the same ID as the graph node.
            # This lets SearchOrchestrator resolve vector hits directly via
            # GraphStore.get_memory() without a translation table.
            chunk.id = memory_id
            memory_ids.append(memory_id)

            # Store embedding in vector store
            await self.vector.store(
                chunk_id=memory_id,
                text=chunk.text,
                embedding=embedding,
                entity_id=entity_id,
                model_name="mock-128" if not self.embedder else "text-embedding-3-small",
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

        Returns pipeline_id for status tracking.
        """
        from hashlib import sha256

        pipeline_id = uuid4().hex
        content_hash = sha256(
            content.encode() if isinstance(content, str) else content
        ).hexdigest()

        logger.info(
            "memory.add.async",
            pipeline_id=pipeline_id,
            entity_id=entity_id,
            content_type=content_type,
        )

        return pipeline_id
