"""Vector store — pgvector operations for storing and searching embeddings."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

import structlog

logger = structlog.get_logger(__name__)


def _coerce_embedding(value: object) -> list[float]:
    """Normalize a stored embedding value to a list of floats.

    Backends differ: the in-memory store keeps Python lists; pgvector's
    ``Vector`` is a numpy array (``tolist``); and without a registered
    asyncpg codec a raw ``text()`` read returns the literal string
    ``'[0.1, 0.2, …]'``. Handle all three so the B6 candidate generator
    (#42) never corrupts a query vector.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        if not stripped.strip():
            return []
        return [float(part) for part in stripped.split(",")]
    if isinstance(value, (list, tuple)):
        parts: Iterable[Any] = value
    elif hasattr(value, "tolist"):
        parts = cast("Any", value).tolist()
    else:
        parts = cast("Iterable[Any]", value)
    return [float(part) for part in parts]


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
        self._memory_document_ids: dict[str, str | None] = {}

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
            self._memory_document_ids[chunk_id] = document_id

        logger.debug("vector.store", chunk_id=chunk_id, dims=len(embedding))

    async def store_document_chunks(
        self,
        document_id: str,
        texts: list[str],
        embeddings: list[list[float]],
        *,
        entity_id: str,
        model_name: str = "text-embedding-3-small",
    ) -> int:
        """Idempotently persist a document's RAG chunks.

        Replaces any previously stored chunks for ``document_id`` (pipeline
        retries and re-uploads must not duplicate or leave stale rows), then
        inserts one embedding per chunk with deterministic chunk ids
        ``{document_id}:rag:{i}``. Chunks carry ``document_id`` so RAG search
        (``require_document_id=True``) finds them while memory search
        (``memory_only=True``) never sees them. Returns the chunk count.
        """
        if len(texts) != len(embeddings):
            raise ValueError(
                f"texts/embeddings length mismatch: {len(texts)} != {len(embeddings)}"
            )
        chunk_ids = [f"{document_id}:rag:{i}" for i in range(len(texts))]
        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text
            async with self._session_factory.session() as session:
                await session.execute(
                    sql_text(
                        "DELETE FROM embeddings WHERE document_id = :document_id"
                    ),
                    {"document_id": document_id},
                )
                for chunk_id, chunk_text, embedding in zip(
                    chunk_ids, texts, embeddings, strict=True
                ):
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
                            "text": chunk_text,
                            "embedding": _pg_vector_literal(embedding),
                            "entity_id": entity_id,
                            "document_id": document_id,
                            "model_name": model_name,
                            "dimensions": len(embedding),
                        },
                    )
        else:
            for cid in list(self._memory_document_ids):
                if self._memory_document_ids[cid] == document_id:
                    self._memory_store.pop(cid, None)
                    self._memory_texts.pop(cid, None)
                    self._memory_entities.pop(cid, None)
                    self._memory_document_ids.pop(cid, None)
            for chunk_id, chunk_text, embedding in zip(
                chunk_ids, texts, embeddings, strict=True
            ):
                self._memory_store[chunk_id] = embedding
                self._memory_texts[chunk_id] = chunk_text
                self._memory_entities[chunk_id] = entity_id
                self._memory_document_ids[chunk_id] = document_id
        logger.info(
            "vector.document_chunks_stored",
            document_id=document_id,
            chunk_count=len(texts),
        )
        return len(texts)

    async def exists(self, chunk_id: str) -> bool:
        """Check whether an embedding row exists for the given chunk_id.

        Used by ReconciliationEngine to detect orphaned graph nodes
        (memory created in Neo4j but never persisted to pgvector).
        """
        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text
            async with self._session_factory.session() as session:
                result = await session.execute(
                    sql_text("SELECT 1 FROM embeddings WHERE chunk_id = :cid LIMIT 1"),
                    {"cid": chunk_id},
                )
                return result.fetchone() is not None
        return chunk_id in self._memory_store

    async def get_embeddings(self, chunk_ids: list[str]) -> dict[str, list[float]]:
        """Bulk-read stored embeddings by chunk id (B6 candidate generation, #42).

        Returns ``{chunk_id: embedding}``; ids with no stored embedding
        are absent. Memory embeddings (``document_id=None``) and RAG
        chunk embeddings alike. Used by the duplicate-candidate
        generator to query near-duplicates of each latest memory — the
        stored embedding is the canonical one, so candidate search never
        re-embeds.
        """
        ids = [cid for cid in chunk_ids if cid]
        if not ids:
            return {}
        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text

            async with self._session_factory.session() as session:
                result = await session.execute(
                    sql_text(
                        "SELECT chunk_id, embedding FROM embeddings WHERE chunk_id = ANY(:ids)"
                    ),
                    {"ids": ids},
                )
                embeddings: dict[str, list[float]] = {}
                for row in result.fetchall():
                    embeddings[row.chunk_id] = _coerce_embedding(row.embedding)
                return embeddings
        return {cid: self._memory_store[cid] for cid in ids if cid in self._memory_store}

    async def search(
        self,
        query_embedding: list[float],
        *,
        entity_id: str | None = None,
        top_k: int = 10,
        require_document_id: bool = False,
        memory_only: bool = False,
    ) -> list[tuple[str, str, float]]:
        """Search for similar embeddings.

        Returns list of (chunk_id, text, score) sorted by descending similarity.

        Args:
            require_document_id: If True, only return embeddings that belong to
                a document (RAG chunks). Memory embeddings have ``document_id=None``.
            memory_only: If True, only return memory embeddings
                (``document_id IS NULL``) — the inverse of
                ``require_document_id``. Used by the B6 duplicate-candidate
                generator (#42) so RAG chunks never consume the candidate
                top-k budget.

        Architecture note: There is no ``offset`` parameter.  Callers that need
        more candidates than ``top_k`` should request a larger ``top_k`` value.
        See spec §3.1 Decision 2 for the rationale.
        """
        if self._use_db and self._session_factory:
            from sqlalchemy import text as sql_text

            doc_filter = "AND document_id IS NOT NULL" if require_document_id else ""
            if memory_only:
                doc_filter = "AND document_id IS NULL"
            async with self._session_factory.session() as session:
                result = await session.execute(
                    sql_text(f"""
                        SELECT chunk_id, text, 1 - (embedding <=> :query_embedding) AS score
                        FROM embeddings
                        WHERE entity_id = :entity_id
                        {doc_filter}
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
            return self._memory_search(
                query_embedding, entity_id, top_k, require_document_id, memory_only
            )

    def _memory_search(
        self,
        query_embedding: list[float],
        entity_id: str | None,
        top_k: int,
        require_document_id: bool = False,
        memory_only: bool = False,
    ) -> list[tuple[str, str, float]]:
        """In-memory cosine similarity search."""
        results = []
        for chunk_id, emb in self._memory_store.items():
            if entity_id and self._memory_entities.get(chunk_id) != entity_id:
                continue
            if require_document_id and not self._memory_document_ids.get(chunk_id):
                continue
            if memory_only and self._memory_document_ids.get(chunk_id):
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
