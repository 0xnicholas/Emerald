"""Vector store — pgvector operations for storing and searching embeddings."""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def _pg_vector_literal(embedding: list[float]) -> str:
    """Convert a Python list of floats into pgvector text literal.

    asyncpg does not know how to serialise the VECTOR type natively;
    passing the vector as a string literal '[a,b,c]' works with
    pgvector's implicit cast.
    """
    try:
        from pgvector.utils import Vector as PgVector

        return str(PgVector(embedding).to_text())
    except ImportError:
        # Fallback if pgvector python package is not installed
        return "[" + ",".join(str(v) for v in embedding) + "]"


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

        Architecture note: ``document_id`` distinguishes RAG chunks (always
        present) from memory embeddings (``None``).  We intentionally do NOT
        store a separate ``source_type`` column; see spec §3.1 Decision 1.
        """
        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text
            async with self._session_factory.session() as session:
                await session.execute(
                    sql_text(
                        """
                        INSERT INTO embeddings (
                            chunk_id, text, embedding, entity_id,
                            document_id, model_name, dimensions
                        )
                        VALUES (
                            :chunk_id, :text, :embedding, :entity_id,
                            :document_id, :model_name, :dimensions
                        )
                        """
                    ),
                    {
                        "chunk_id": chunk_id,
                        "text": text,
                        "embedding": _pg_vector_literal(embedding),
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

        Architecture note: There is no ``offset`` parameter.  Callers that need
        more candidates than ``top_k`` should request a larger ``top_k`` value.
        See spec §3.1 Decision 2 for the rationale.
        """
        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text
            async with self._session_factory.session() as session:
                result = await session.execute(
                    sql_text("""
                        SELECT chunk_id, text, 1 - (embedding <=> :query_embedding) AS score
                        FROM embeddings
                        WHERE entity_id = :entity_id
                        ORDER BY embedding <=> :query_embedding
                        LIMIT :top_k
                    """),
                    {
                        "query_embedding": _pg_vector_literal(query_embedding),
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

    async def keyword_search(
        self,
        query: str,
        *,
        entity_id: str,
        top_k: int = 10,
    ) -> list[tuple[str, str, float]]:
        """Database-level keyword search using PostgreSQL FTS + pg_trgm.

        Returns list of (chunk_id, text, score) sorted by descending relevance.
        Falls back to in-memory brute-force search when DB is unavailable.
        """
        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text
            async with self._session_factory.session() as session:
                result = await session.execute(
                    sql_text("""
                        SELECT chunk_id, text,
                            COALESCE(ts_rank_cd(text_tsv, plainto_tsquery('simple', :q)), 0) * 0.6 +
                            COALESCE(similarity(text, :q), 0) * 0.4 AS score
                        FROM embeddings
                        WHERE entity_id = :entity_id
                          AND (
                              text_tsv @@ plainto_tsquery('simple', :q)
                              OR text % :q
                          )
                        ORDER BY score DESC
                        LIMIT :top_k
                    """),
                    {"q": query, "entity_id": entity_id, "top_k": top_k},
                )
                rows = result.fetchall()
                return [(row.chunk_id, row.text, float(row.score)) for row in rows]
        else:
            return self._memory_keyword_search(query, entity_id, top_k)

    def _memory_keyword_search(
        self,
        query: str,
        entity_id: str,
        top_k: int,
    ) -> list[tuple[str, str, float]]:
        """In-memory keyword overlap search (fallback)."""
        import re

        query_terms = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", query.lower())
        if not query_terms:
            return []

        results = []
        for chunk_id, text in self._memory_texts.items():
            if self._memory_entities.get(chunk_id) != entity_id:
                continue
            text_lower = text.lower()
            matches = sum(1 for term in query_terms if term in text_lower)
            if matches:
                score = matches / len(query_terms)
                results.append((chunk_id, text, score))

        results.sort(key=lambda x: x[2], reverse=True)
        return results[:top_k]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import math

        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
