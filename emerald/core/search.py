"""Search orchestrator — hybrid search across memory (Neo4j) and RAG (pgvector).

Single query returns both memory results (personalised, stateful) and
RAG results (document chunks, stateless). Results are merged, deduplicated,
and sorted by relevance score.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import structlog

from emerald.core.embedder import EmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore

logger = structlog.get_logger(__name__)


class SearchMode(str, Enum):
    HYBRID = "hybrid"
    MEMORY = "memory"
    RAG = "rag"


@dataclass
class SearchResult:
    id: str
    content: str
    summary: str = ""
    score: float = 0.0
    source: str = "memory"
    memory_type: str = ""
    is_latest: bool = True
    document_id: str | None = None
    document_title: str | None = None


@dataclass
class SearchResponse:
    results: list[SearchResult]
    search_mode: SearchMode
    query_rewritten: str | None = None


class SearchOrchestrator:
    """Orchestrates hybrid search across memory (graph) and RAG (vector)."""

    def __init__(
        self,
        graph: GraphStore | None = None,
        vector: VectorStore | None = None,
        embedder: EmbeddingProvider | None = None,
        rag_min_score: float = 0.0,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self.vector = vector or VectorStore(use_db=False)
        self.embedder = embedder
        self.rag_min_score = rag_min_score

    async def search(
        self,
        q: str,
        *,
        entity_id: str,
        search_mode: SearchMode = SearchMode.HYBRID,
        top_k: int = 10,
        rerank: bool = False,
        rewrite_query: bool = False,
        filters: dict | None = None,
    ) -> SearchResponse:
        """Execute a hybrid search query."""
        logger.info(
            "search.start",
            entity_id=entity_id,
            search_mode=search_mode,
            q=q[:100],
        )

        results: list[SearchResult] = []

        # Memory search
        if search_mode in (SearchMode.HYBRID, SearchMode.MEMORY):
            memory_results = await self._search_memory(q, entity_id, top_k, filters)
            results.extend(memory_results)

        # RAG search
        if search_mode in (SearchMode.HYBRID, SearchMode.RAG):
            rag_results = await self._search_rag(q, entity_id, top_k, filters)
            results.extend(rag_results)

        # Merge, deduplicate, sort
        results = self._merge_results(results, top_k)

        logger.info("search.complete", result_count=len(results), mode=search_mode)

        return SearchResponse(results=results, search_mode=search_mode)

    # ---- Memory search (graph) ----

    async def _search_memory(
        self,
        q: str,
        entity_id: str,
        top_k: int,
        filters: dict | None,
    ) -> list[SearchResult]:
        """Search the memory graph for keyword matches."""
        memories = await self.graph.list_latest_memories(
            entity_id, limit=100,
        )

        # Apply filters
        if filters:
            mtype = filters.get("memory_type")
            min_conf = filters.get("min_confidence")
            if mtype:
                memories = [m for m in memories if m.get("memory_type") == mtype]
            if min_conf is not None:
                memories = [m for m in memories if m.get("confidence", 0) >= min_conf]

        # Score: keyword overlap + confidence
        results = []
        query_terms = self._tokenize(q)

        for m in memories:
            content = m.get("content", "")
            score = self._keyword_score(content, query_terms)
            if score > 0:
                results.append(
                    SearchResult(
                        id=m["id"],
                        content=content,
                        summary=m.get("summary", "")[:200],
                        score=score * m.get("confidence", 0.5),
                        source="memory",
                        memory_type=m.get("memory_type", "fact"),
                        is_latest=m.get("is_latest", True),
                    )
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    # ---- RAG search (vector) ----

    async def _search_rag(
        self,
        q: str,
        entity_id: str,
        top_k: int,
        filters: dict | None,
    ) -> list[SearchResult]:
        """Search vector store for similar embeddings."""
        if not self.embedder:
            return []

        try:
            query_embedding = (await self.embedder.embed([q]))[0]
        except Exception:
            logger.warning("search.rag.embed_failed", q=q[:50])
            return []

        hits = await self.vector.search(
            query_embedding, entity_id=entity_id, top_k=top_k,
        )

        # Filter out low-quality matches
        hits = [
            (cid, txt, score)
            for cid, txt, score in hits
            if score >= self.rag_min_score
        ]

        results = []
        for chunk_id, text, score in hits:
            results.append(
                SearchResult(
                    id=chunk_id,
                    content=text,
                    score=score,
                    source="rag",
                )
            )

        return results

    # ---- Merge helpers ----

    def _merge_results(
        self, results: list[SearchResult], top_k: int
    ) -> list[SearchResult]:
        """Deduplicate by content and sort by score descending."""
        seen_contents: set[str] = set()
        merged = []

        # Sort by score desc
        results.sort(key=lambda r: r.score, reverse=True)

        for r in results:
            # Normalize for dedup
            key = r.content.strip().lower()
            if key not in seen_contents:
                seen_contents.add(key)
                merged.append(r)
                if len(merged) >= top_k:
                    break

        return merged

    # ---- Scoring ----

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Split query into searchable tokens (supports CJK + alphabetic)."""
        import re
        # Extract CJK characters individually + alphabetic words
        tokens = []
        # Alphabetic words
        tokens.extend(re.findall(r"[a-zA-Z0-9]+", text.lower()))
        # Individual CJK characters
        cjk = re.findall(r"[\u4e00-\u9fff]", text)
        tokens.extend(cjk)
        return tokens

    @staticmethod
    def _keyword_score(content: str, query_terms: list[str]) -> float:
        """Score content by keyword overlap with query.

        Returns a score in [0, 1].
        """
        if not query_terms:
            return 0.0

        content_lower = content.lower()
        matches = sum(1 for term in query_terms if term in content_lower)
        return matches / len(query_terms)
