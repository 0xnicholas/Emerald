"""Vector store — pgvector operations for storing and searching embeddings."""

from __future__ import annotations

import structlog

from emerald.core.exceptions import NotFoundError

logger = structlog.get_logger(__name__)


class VectorStore:
    """Manages embedding storage and similarity search via pgvector.

    In production this uses pgvector HNSW indexes. For testing/development
    without a database, an in-memory fallback is available.
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
        # In-memory fallback
        self._memory_store: dict[str, list[float]] = {}
        self._memory_texts: dict[str, str] = {}
        self._memory_entities: dict[str, str] = {}

    async def store(
        self,
        chunk_id: str,
        text: str,
        embedding: list[float],
        *,
        entity_id: str,
        document_id: str | None = None,
        model_name: str = "text-embedding-3-small",
    ) -> None:
        """Store an embedding for a chunk.

        In DB mode, writes to the embeddings table with pgvector.
        In test mode, stores in memory.
        """
        if self._use_db and self._session_factory:
            from sqlalchemy import text
            async with self._session_factory.session() as session:
                await session.execute(
                    text("""
                        INSERT INTO embeddings (chunk_id, text, embedding, entity_id, document_id, model_name, dimensions)
                        VALUES (:chunk_id, :text, :embedding, :entity_id, :document_id, :model_name, :dimensions)
                    """),
                    {
                        "chunk_id": chunk_id,
                        "text": text,
                        "embedding": embedding,
                        "entity_id": entity_id,
                        "document_id": document_id,
                        "model_name": model_name,
                        "dimensions": len(embedding),
                    },
                )
        else:
            self._memory_store[chunk_id] = embedding
            self._memory_texts[chunk_id] = text
            self._memory_entities[chunk_id] = entity_id

        logger.debug("vector.store", chunk_id=chunk_id, dims=len(embedding))

    async def search(
        self,
        query_embedding: list[float],
        *,
        entity_id: str | None = None,
        top_k: int = 10,
    ) -> list[tuple[str, str, float]]:
        """Search for similar embeddings.

        Returns list of (chunk_id, text, score) sorted by descending similarity.
        """
        if self._use_db and self._session_factory:
            from sqlalchemy import text
            async with self._session_factory.session() as session:
                result = await session.execute(
                    text("""
                        SELECT chunk_id, text, 1 - (embedding <=> :query_embedding) AS score
                        FROM embeddings
                        WHERE entity_id = :entity_id
                        ORDER BY embedding <=> :query_embedding
                        LIMIT :top_k
                    """),
                    {
                        "query_embedding": query_embedding,
                        "entity_id": entity_id,
                        "top_k": top_k,
                    },
                )
                rows = result.fetchall()
                return [(row.chunk_id, row.text, float(row.score)) for row in rows]
        else:
            return self._memory_search(query_embedding, entity_id, top_k)

    def _memory_search(
        self,
        query_embedding: list[float],
        entity_id: str | None,
        top_k: int,
    ) -> list[tuple[str, str, float]]:
        """In-memory cosine similarity search."""
        results = []
        for chunk_id, emb in self._memory_store.items():
            if entity_id and self._memory_entities.get(chunk_id) != entity_id:
                continue
            score = self._cosine_similarity(query_embedding, emb)
            results.append((chunk_id, self._memory_texts[chunk_id], score))

        results.sort(key=lambda x: x[2], reverse=True)
        return results[:top_k]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import math

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
