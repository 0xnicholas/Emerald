"""Search orchestrator — hybrid search across memory (Neo4j) and RAG (pgvector).

Single query returns both memory results (personalised, stateful) and
RAG results (document chunks, stateless). Results are merged, deduplicated,
and sorted by relevance score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from enum import Enum
from typing import Any

import structlog

from emerald.config import get_settings
from emerald.core.embedder import EmbeddingProvider
from emerald.core.fast_lane import FastLaneStore
from emerald.core.graph import GraphStore
from emerald.core.metrics import search_latency_seconds, timed
from emerald.core.multihop import MAX_DEPTH, MultihopEngine
from emerald.core.tracing import get_tracer
from emerald.core.trust import compute_trust_score
from emerald.core.vector import VectorStore

logger = structlog.get_logger(__name__)


class SearchMode(str, Enum):
    HYBRID = "hybrid"
    MEMORY = "memory"
    RAG = "rag"


@dataclass
class PathStep:
    """One node/edge in a multihop result's provenance path (B4, #33).

    ``kind`` is "memory" for a memory node, "mention" for a shared
    Mention node, or a relationship type (UPDATES / EXTENDS /
    DERIVES_FROM) for an edge; ``id`` is the node id or, for an edge
    step, the id of the memory at the edge's far end. Paths contain only
    in-entity nodes (spec #29: 路径仅含实体内节点).
    """

    kind: str
    id: str


@dataclass
class SearchResult:
    id: str
    content: str
    summary: str = ""
    score: float = 0.0
    source: str = "memory"
    memory_type: str = ""
    container_tag: str | None = None
    tags: list[str] = field(default_factory=list)
    is_latest: bool = True
    document_id: str | None = None
    document_title: str | None = None
    # Multihop provenance (B4, #33): seeds are depth 0 with an empty
    # path; graph-reached results carry their hop depth and the full
    # walk from the seed.
    depth: int = 0
    path: list[PathStep] = field(default_factory=list)


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
        fast_lane_store: FastLaneStore | None = None,
        embedder: EmbeddingProvider | None = None,
        rag_min_score: float = 0.0,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self.vector = vector or VectorStore(use_db=False)
        self.fast_lane_store = fast_lane_store or FastLaneStore(use_db=False)
        self.embedder = embedder
        self.rag_min_score = rag_min_score

    async def search(
        self,
        q: str = "",
        *,
        entity_id: str,
        search_mode: SearchMode = SearchMode.HYBRID,
        top_k: int | None = None,
        rerank: bool = False,
        rewrite_query: bool = False,
        filters: dict | None = None,
        min_confidence: float | None = None,
        dynamic_truncation: bool = True,
        about: str | None = None,
        depth: int = 0,
    ) -> SearchResponse:
        """Execute a hybrid search query.

        ``about`` (B4, #30): entity-centric retrieval — instead of seeding
        with vector similarity, return the entity's latest memories that
        mention the given canonical form (or mention id), across all
        surface forms. It is a memory-graph operation: RAG and fast-lane
        paths are skipped regardless of ``search_mode``, ``q`` may be
        empty, dynamic truncation is disabled (the full mentioning set is
        returned), and the result set is exactly the mentioning memories
        (no relationship expansion in this ticket; traversal lands in
        #31/#32).

        ``depth`` (B4, #31/#32): graph-traversal hops over shared-subject
        bridges and relationship edges applied to the memory seed set.
        0 (default) is the status quo; >=1 walks
        Memory-MENTIONS->Mention<-MENTIONS-Memory and
        UPDATES/EXTENDS/DERIVES_FROM (both directions) within the
        entity. Historical nodes surface only along UPDATES chains and
        are marked is_latest=false. Clamped to [0, 4] (spec #29).
        """
        depth = max(0, min(depth, MAX_DEPTH))
        settings = get_settings()
        resolved_top_k = min(
            top_k if top_k is not None else settings.search_default_top_k,
            settings.search_max_top_k,
        )

        tracer = get_tracer()
        with tracer.start_as_current_span("search") as span:
            span.set_attribute("entity_id", entity_id)
            span.set_attribute("search_mode", search_mode.value)
            span.set_attribute("top_k", resolved_top_k)
            span.set_attribute(
                "min_confidence", min_confidence if min_confidence is not None else -1.0
            )
            span.set_attribute("dynamic_truncation", dynamic_truncation)
            rewritten_q = await self._rewrite_query(q) if rewrite_query else q

        logger.info(
            "search.start",
            entity_id=entity_id,
            search_mode=search_mode,
            top_k=resolved_top_k,
            min_confidence=min_confidence,
            dynamic_truncation=dynamic_truncation,
            q=q[:100],
            rewritten=rewritten_q[:100] if rewrite_query else None,
        )

        with timed(search_latency_seconds, search_mode=search_mode.value):
            results: list[SearchResult] = []

            # Memory search
            memory_results: list[SearchResult] = []
            if about is not None:
                # Entity-centric retrieval (B4, #30): the mention seed set
                # replaces vector/keyword seeding. RAG and fast-lane are
                # skipped — about is a memory-graph operation.
                memory_results = await self._search_memories_about(
                    about, entity_id, resolved_top_k, filters, min_confidence
                )
            elif search_mode in (SearchMode.HYBRID, SearchMode.MEMORY):
                memory_results = await self._search_memory(
                    rewritten_q, entity_id, resolved_top_k, filters, min_confidence
                )

                # Expand via graph relationships (EXTENDS, DERIVES_FROM)
                memory_results = await self._expand_relationships(
                    memory_results, entity_id, resolved_top_k
                )

            # Shared-subject bridging (B4, #31): explicit depth opt-in
            # walks the mention graph from the memory seed set.
            if depth > 0 and memory_results:
                memory_results = await self._expand_multihop(
                    memory_results, entity_id, depth
                )

            results.extend(memory_results)

            # RAG search
            if about is None and search_mode in (SearchMode.HYBRID, SearchMode.RAG):
                rag_results = await self._search_rag(
                    rewritten_q, entity_id, resolved_top_k, filters
                )
                results.extend(rag_results)

            # Fast-lane search: raw, coarse chunks that are searchable before the
            # full pipeline has finished. Included in memory/hybrid modes.
            if about is None and search_mode in (SearchMode.HYBRID, SearchMode.MEMORY):
                fast_lane_results = await self._search_fast_lane(
                    rewritten_q, entity_id, resolved_top_k
                )
                results.extend(fast_lane_results)

            # Dynamic truncation is designed for dense semantic scores. Keyword
            # fallback scores are sparse (often 0 vs 1), so large gaps are normal
            # and should not truncate useful partial matches. The about path
            # scores by trust and must return the full mentioning set (#30).
            apply_dynamic_truncation = (
                dynamic_truncation and self.embedder is not None and about is None
            )

            # Merge, deduplicate, sort, and optionally truncate on score gap
            results = self._merge_results(
                results,
                resolved_top_k,
                dynamic_truncation=apply_dynamic_truncation,
            )

            # Optional rerank: boost results with direct keyword matches
            if rerank:
                results = await self._rerank_results(results, rewritten_q)

            logger.info(
                "search.complete",
                result_count=len(results),
                mode=search_mode,
                reranked=rerank,
            )

            return SearchResponse(
                results=results,
                search_mode=search_mode,
                query_rewritten=rewritten_q if rewrite_query else None,
            )

    # ---- Memory search (graph) ----

    async def _search_memory(
        self,
        q: str,
        entity_id: str,
        top_k: int,
        filters: dict | None,
        min_confidence: float | None = None,
    ) -> list[SearchResult]:
        if not self.embedder:
            # Fallback to keyword search when embedder is unavailable
            return await self._search_memory_keyword(
                q, entity_id, top_k, filters, min_confidence
            )

        query_embedding = (await self.embedder.embed([q]))[0]
        candidate_limit = min(top_k * 5, 200)
        candidates = await self.vector.search(
            query_embedding, entity_id=entity_id, top_k=candidate_limit
        )

        results = []
        now = datetime.now(timezone.utc)

        for chunk_id, text, vec_score in candidates:
            memory = await self.graph.get_memory(chunk_id)
            if not memory:
                continue
            if not memory.get("is_latest", True):
                continue
            valid_until = memory.get("valid_until")
            if valid_until is not None:
                # Neo4j returns neo4j.time.DateTime; convert to Python datetime
                if hasattr(valid_until, "to_native"):
                    valid_until = valid_until.to_native()
                if valid_until < now:
                    continue
            if filters and not self._passes_filters(memory, filters):
                continue
            if min_confidence is not None and memory.get("confidence", 0.0) < min_confidence:
                continue

            trust = compute_trust_score(memory)
            score = vec_score * trust
            results.append(self._memory_to_result(memory, score))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    @staticmethod
    def _memory_to_result(
        memory: dict[str, Any],
        score: float,
        source: str = "memory",
        *,
        depth: int = 0,
        path: list[PathStep] | None = None,
    ) -> SearchResult:
        """Build a memory SearchResult from a graph memory dict.

        Shared by every graph-seeded memory path (vector, about, graph
        expansion) so the result shape cannot drift between them.
        ``depth``/``path`` carry multihop provenance (B4, #33): seeds
        are depth 0 with an empty path.
        """
        return SearchResult(
            id=memory["id"],
            content=memory["content"],
            summary=memory.get("summary", "")[:200],
            score=score,
            source=source,
            memory_type=memory.get("memory_type", "fact"),
            container_tag=memory.get("container_tag"),
            tags=memory.get("tags") or [],
            is_latest=memory.get("is_latest", True),
            depth=depth,
            path=list(path) if path else [],
        )

    async def _search_memories_about(
        self,
        about: str,
        entity_id: str,
        top_k: int,
        filters: dict[str, Any] | None,
        min_confidence: float | None = None,
    ) -> list[SearchResult]:
        """Entity-centric retrieval (B4, #30): memories mentioning ``about``.

        The seed set is the entity's latest memories whose mention node
        matches ``about`` (canonical form or id, any surface form). No
        vector search, no RAG — ranking is by trust score (recency as
        tie-breaker via graph order), so the result set is deterministic
        and exactly the mentioning memories.
        """
        memories = await self.graph.get_memories_mentioning(
            entity_id, about, limit=max(top_k * 5, 100),
        )
        now = datetime.now(UTC)

        results = []
        for memory in memories:
            valid_until = memory.get("valid_until")
            if valid_until is not None:
                # Neo4j returns neo4j.time.DateTime; convert to Python datetime
                if hasattr(valid_until, "to_native"):
                    valid_until = valid_until.to_native()
                if valid_until < now:
                    continue
            if filters and not self._passes_filters(memory, filters):
                continue
            if min_confidence is not None and memory.get("confidence", 0.0) < min_confidence:
                continue

            results.append(
                self._memory_to_result(memory, compute_trust_score(memory))
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    async def _expand_multihop(
        self,
        results: list[SearchResult],
        entity_id: str,
        depth: int,
    ) -> list[SearchResult]:
        """Walk the graph from the seed set (B4, #31/#32/#33).

        Each reached memory is added once at its shallowest depth, scored
        by trust discounted per hop so seeds rank first. Every reached
        result carries ``depth`` (its hop count) and ``path`` (the full
        walk from the seed: memory nodes, shared Mention nodes and
        relationship edges) — provenance an agent can explain. Historical
        nodes (is_latest=false, reached along an UPDATES edge) are
        surfaced with is_latest=false (spec #29 story 7).
        """
        engine = MultihopEngine(graph=self.graph)
        hops = await engine.expand(
            [r.id for r in results], entity_id, depth,
        )
        if not hops:
            return results

        seen_ids = {r.id for r in results}
        expanded: list[SearchResult] = list(results)
        for bridged_id, hop in hops.items():
            if bridged_id in seen_ids:
                continue
            memory = await self.graph.get_memory(bridged_id)
            if not memory:
                continue
            is_latest = memory.get("is_latest", True)
            if not is_latest and not hop.historical:
                # Never reach into history proactively — only UPDATES
                # chains surface it (engine contract, #32).
                continue
            seen_ids.add(bridged_id)
            expanded.append(
                self._memory_to_result(
                    memory,
                    compute_trust_score(memory) * (0.85**hop.depth),
                    source="memory_expanded",
                    depth=hop.depth,
                    path=[
                        PathStep(kind=kind, id=step_id)
                        for kind, step_id in hop.path
                    ],
                )
            )
        return expanded

    async def _search_memory_keyword(
        self,
        q: str,
        entity_id: str,
        top_k: int,
        filters: dict | None,
        min_confidence: float | None = None,
    ) -> list[SearchResult]:
        """Fallback keyword-based memory search.

        Tries database-level keyword search (PostgreSQL FTS + pg_trgm) first;
        falls back to in-memory brute-force if DB is unavailable.
        """
        # Attempt DB-level keyword search via vector store
        try:
            candidates = await self.vector.keyword_search(
                q, entity_id=entity_id, top_k=top_k
            )
            if candidates:
                results = []
                for chunk_id, text, score in candidates:
                    memory = await self.graph.get_memory(chunk_id)
                    if not memory:
                        continue
                    if not memory.get("is_latest", True):
                        continue
                    if filters and not self._passes_filters(memory, filters):
                        continue
                    if min_confidence is not None and memory.get(
                        "confidence", 0.0
                    ) < min_confidence:
                        continue
                    trust = compute_trust_score(memory)
                    results.append(
                        SearchResult(
                            id=chunk_id,
                            content=text,
                            summary=memory.get("summary", "")[:200],
                            score=score * trust,
                            source="memory",
                            memory_type=memory.get("memory_type", "fact"),
                            container_tag=memory.get("container_tag"),
                            tags=memory.get("tags") or [],
                            is_latest=memory.get("is_latest", True),
                        )
                    )
                results.sort(key=lambda r: r.score, reverse=True)
                return results[:top_k]
        except Exception:
            # DB keyword search failed — fall through to in-memory
            pass

        # In-memory brute-force fallback
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
        if min_confidence is not None:
            memories = [m for m in memories if m.get("confidence", 0) >= min_confidence]

        # Score: keyword overlap + confidence
        results = []
        query_terms = self._tokenize(q)

        for m in memories:
            content = m.get("content", "")
            score = self._keyword_score(content, query_terms)
            if score > 0:
                trust = compute_trust_score(m)
                results.append(
                    SearchResult(
                        id=m["id"],
                        content=content,
                        summary=m.get("summary", "")[:200],
                        score=score * trust,
                        source="memory",
                        memory_type=m.get("memory_type", "fact"),
                        container_tag=m.get("container_tag"),
                        tags=m.get("tags") or [],
                        is_latest=m.get("is_latest", True),
                    )
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _passes_filters(self, memory: dict, filters: dict) -> bool:
        """Check if a memory passes the given filters.

        Supports:
        - Flat filters: {"memory_type": "fact", "min_confidence": 0.5}
        - $and: {"$and": [{"memory_type": "fact"}, {"confidence": {"$gte": 0.5}}]}
        - $or:  {"$or": [{"memory_type": "preference"}, {"memory_type": "episodic"}]}
        - Numeric operators: $gte, $gt, $lte, $lt, $eq, $ne
        """
        if not filters:
            return True

        # $and: all sub-filters must pass
        if "$and" in filters:
            return all(self._passes_filters(memory, f) for f in filters["$and"])

        # $or: at least one sub-filter must pass
        if "$or" in filters:
            return any(self._passes_filters(memory, f) for f in filters["$or"])

        # Flat filter: check each key-value pair
        for key, value in filters.items():
            if key in ("$and", "$or"):
                continue

            mem_val = memory.get(key)

            # Numeric operators: {"confidence": {"$gte": 0.5}}
            if isinstance(value, dict) and any(k.startswith("$") for k in value):
                if not self._eval_numeric(mem_val, value):
                    return False
            # Shorthand: {"memory_type": "fact"}
            elif mem_val != value:
                return False

        return True

    @staticmethod
    def _eval_numeric(mem_value: float | int | None, ops: dict) -> bool:
        """Evaluate numeric operators like $gte, $gt, $lte, $lt, $eq, $ne."""
        if mem_value is None:
            return False
        for op, target in ops.items():
            if op == "$gte" and not (mem_value >= target):
                return False
            if op == "$gt" and not (mem_value > target):
                return False
            if op == "$lte" and not (mem_value <= target):
                return False
            if op == "$lt" and not (mem_value < target):
                return False
            if op == "$eq" and not (mem_value == target):
                return False
            if op == "$ne" and not (mem_value != target):
                return False
        return True

    # ---- Relationship expansion ----

    async def _expand_relationships(
        self,
        results: list[SearchResult],
        entity_id: str,
        top_k: int,
        expansion_factor: float = 0.85,
    ) -> list[SearchResult]:
        """Expand search results by traversing graph relationships.

        For each result, navigates EXTENDS and DERIVES_FROM relationships
        (both directions, depth=1) and adds related memories as expansion
        candidates with slightly discounted scores (default 0.85×). Each
        expanded result carries ``depth=1`` and an honest one-edge path
        (B4, #33) so it is never mistaken for a seed. The expansion is
        entity-scoped: neighbors in another entity's pool are skipped.

        This turns a flat vector search into a graph-aware retrieval:
        - EXTENDS: includes complementary facts that enrich context
        - DERIVES_FROM: includes source facts showing the reasoning chain
        - UPDATES: already handled by is_latest filtering (superseded excluded)
        """
        if not results:
            return results

        result_ids = [r.id for r in results]
        neighbors = await self.graph.get_relationship_neighbors(
            result_ids, rel_types=["EXTENDS", "DERIVES_FROM"],
        )

        if not neighbors:
            return results

        expanded: list[SearchResult] = list(results)
        seen_ids = {r.id for r in results}
        added = 0

        for src_id, adjacent in neighbors.items():
            # Find the original score for this source result
            src_score = 0.5
            for r in results:
                if r.id == src_id:
                    src_score = r.score
                    break

            for neighbor in adjacent:
                rid = neighbor["id"]
                if rid in seen_ids:
                    continue
                # Entity isolation at the seam; history is never reached
                # proactively (spec #29 story 7).
                if neighbor.get("entity_id") != entity_id:
                    continue
                if not neighbor.get("is_latest", True):
                    continue
                memory = await self.graph.get_memory(rid)
                if not memory:
                    continue

                trust = compute_trust_score(memory)
                seen_ids.add(rid)
                expanded.append(
                    self._memory_to_result(
                        memory,
                        src_score * expansion_factor * trust,
                        source="memory_expanded",
                        depth=1,
                        path=[
                            PathStep(kind="memory", id=src_id),
                            PathStep(kind=neighbor["rel_type"], id=rid),
                        ],
                    )
                )
                added += 1

        if added:
            logger.info(
                "search.expanded_relationships",
                entity_id=entity_id,
                original=len(results),
                added=added,
            )

        # Re-sort and trim to avoid result bloat (allow up to 2× expansion)
        expanded.sort(key=lambda r: r.score, reverse=True)
        return expanded[: max(top_k, top_k * 2)]

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
            query_embedding, entity_id=entity_id, top_k=top_k, require_document_id=True
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

    async def _search_fast_lane(
        self,
        q: str,
        entity_id: str,
        top_k: int,
    ) -> list[SearchResult]:
        """Search raw fast-lane chunks that are not yet fully indexed."""
        if not self.embedder:
            return []

        try:
            query_embedding = (await self.embedder.embed([q]))[0]
        except Exception:
            logger.warning("search.fast_lane.embed_failed", q=q[:50])
            return []

        settings = get_settings()
        if not settings.fast_lane_enabled:
            return []

        hits = await self.fast_lane_store.search(
            query_embedding, entity_id=entity_id, top_k=top_k
        )
        discount = settings.fast_lane_score_discount

        results = []
        for hit in hits:
            results.append(
                SearchResult(
                    id=hit.fast_lane_id,
                    content=hit.text,
                    score=hit.score * discount,
                    source="fast_lane",
                    memory_type="raw",
                    is_latest=True,
                )
            )

        return results

    # ---- Merge helpers ----

    def _merge_results(
        self,
        results: list[SearchResult],
        top_k: int,
        *,
        dynamic_truncation: bool = True,
    ) -> list[SearchResult]:
        """Deduplicate, sort by score descending, and optionally truncate.

        Dedup semantics (B4 #30): the same result id is deduplicated
        everywhere (one memory hit from several paths); identical content
        is additionally deduplicated across *different* sources (a fast-
        lane chunk mirroring an indexed memory, a RAG chunk mirroring a
        memory). Distinct memories of the same source stay distinct —
        "在 Google 工作" and "在 GOOGLE 工作" are two facts, not one.

        Truncation happens on a score gap when enabled.
        """
        settings = get_settings()
        seen_ids: set[str] = set()
        seen_contents: dict[str, str] = {}  # content key → source
        merged: list[SearchResult] = []

        # Sort by score desc; depth asc breaks ties. Ranking is
        # score-dominant: multihop results are discounted by 0.85^hop
        # depth (so a same-trust seed always outranks them), and on an
        # exact score tie a shallower (seed) result wins — graph-reached
        # results never rank above a same-scoring seed (B4, #33: 种子
        # 向量命中在前).
        results.sort(key=lambda r: (-r.score, r.depth))

        # Avoid over-truncating tiny result sets (common with mock/deterministic
        # embedders in tests). Require a small floor of results before a score-gap
        # cut can fire; this preserves recall for small candidate pools while still
        # dropping low-quality tails in production-scale result sets.
        min_before_truncate = min(top_k, 3 if top_k <= 5 else 2)

        prev_score: float | None = None
        for r in results:
            # Normalize for dedup
            content_key = r.content.strip().lower()
            if r.id in seen_ids:
                continue
            if content_key in seen_contents and seen_contents[content_key] != r.source:
                continue
            # Dynamic truncation: stop when the score drop from the previous
            # result exceeds the configured gap threshold. This avoids
            # including low-relevance tail results when there is a clear
            # separation, while still respecting top_k as a hard cap.
            # Historical nodes (is_latest=false, surfaced along an UPDATES
            # chain — B4 #32) score 0 by design (superseded → trust 0) and
            # must not be dropped by the gap cut: once walked, history is
            # surfaced and marked (spec #29 story 7).
            if (
                dynamic_truncation
                and len(merged) >= min_before_truncate
                and prev_score is not None
                and settings.search_dynamic_truncation_enabled
                and (prev_score - r.score) > settings.search_score_gap_threshold
                and r.is_latest
            ):
                break

            seen_ids.add(r.id)
            seen_contents[content_key] = r.source
            merged.append(r)
            prev_score = r.score
            if len(merged) >= top_k:
                break

        return merged

    # ---- Rerank ----

    # Module-level cross-encoder cache (lazy loaded, shared across all instances)
    _cross_encoder_cache: object | None = None
    _cross_encoder_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    @classmethod
    def _get_cross_encoder(cls) -> object | None:
        """Return the module-level cached cross-encoder, loading it once.

        Returns None if sentence-transformers is not installed.
        Model is loaded on first call and reused thereafter.
        """
        if cls._cross_encoder_cache is not None:
            return cls._cross_encoder_cache
        try:
            from sentence_transformers import CrossEncoder
            cls._cross_encoder_cache = CrossEncoder(cls._cross_encoder_model_name)
            logger.info("rerank.cross_encoder_loaded", model=cls._cross_encoder_model_name)
            return cls._cross_encoder_cache
        except ImportError:
            logger.info("rerank.cross_encoder_unavailable", reason="sentence_transformers not installed")
            return None
        except Exception:
            logger.warning("rerank.cross_encoder_load_failed", exc_info=True)
            return None

    async def _rerank_results(
        self, results: list[SearchResult], q: str
    ) -> list[SearchResult]:
        """Rerank results using 3-tier fallback:

        1. Cross-encoder (sentence-transformers) — highest quality
        2. Embedding cosine similarity (if embedder available) — medium quality
        3. Keyword boost — always available, lowest quality
        """
        if not results:
            return results

        # Tier 1: Cross-encoder (cached, lazy-loaded)
        ce = self._get_cross_encoder()
        if ce is not None:
            try:
                return await self._cross_encoder_rerank(results, q, ce)
            except Exception:
                logger.warning("rerank.cross_encoder_failed", exc_info=True)
                # Fall through to Tier 2

        # Tier 2: Embedding-based cosine rerank (if embedder available)
        if self.embedder is not None:
            try:
                return await self._embedding_rerank(results, q)
            except Exception:
                logger.warning("rerank.embedding_failed", exc_info=True)
                # Fall through to Tier 3

        # Tier 3: Keyword boost (always available)
        return self._keyword_boost_rerank(results, q)

    async def _cross_encoder_rerank(
        self, results: list[SearchResult], q: str, ce: object
    ) -> list[SearchResult]:
        """Use a cross-encoder to score query-document pairs.

        Uses the pre-loaded module-level cached model.
        Default model: cross-encoder/ms-marco-MiniLM-L-6-v2
        """
        import asyncio

        pairs = [(q, r.content) for r in results]
        scores = await asyncio.to_thread(ce.predict, pairs)

        for r, score in zip(results, scores):
            r.score = float(score)

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    async def _embedding_rerank(
        self, results: list[SearchResult], q: str
    ) -> list[SearchResult]:
        """Rerank using cosine similarity between query embedding and result content.

        Falls back to keyword boost if embedder is unavailable or fails.
        """
        if not self.embedder:
            return self._keyword_boost_rerank(results, q)

        import asyncio
        import math

        def _cosine_similarity(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)

        # Embed query + all result contents in one batch
        texts = [q] + [r.content for r in results]
        try:
            embeddings = await self.embedder.embed(texts)
        except Exception:
            return self._keyword_boost_rerank(results, q)

        query_emb = embeddings[0]
        for i, r in enumerate(results):
            sim = _cosine_similarity(query_emb, embeddings[i + 1])
            # Blend: 70% cosine similarity, 30% original score
            r.score = 0.7 * sim + 0.3 * r.score

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _keyword_boost_rerank(
        self, results: list[SearchResult], q: str
    ) -> list[SearchResult]:
        """Fallback reranker — boost results with direct keyword overlap."""
        query_terms = set(self._tokenize(q))
        if not query_terms:
            return results

        def _boost(r: SearchResult) -> float:
            content_terms = set(self._tokenize(r.content))
            overlap = len(query_terms & content_terms) / len(query_terms)
            # Boost up to 15% for perfect keyword overlap
            return r.score * (1.0 + 0.15 * overlap)

        results.sort(key=_boost, reverse=True)
        return results

    # ---- Query rewriting ----

    async def _rewrite_query(self, q: str) -> str:
        """Rewrite query to improve recall.

        Uses DeepSeek or OpenAI for semantic expansion when available.
        Falls back to pattern-based expansions.
        """
        q = q.strip()
        if not q:
            return q

        settings = get_settings()

        # Try DeepSeek first, then OpenAI
        if settings.deepseek_api_key or settings.openai_api_key:
            try:
                return await self._llm_rewrite(q)
            except Exception:
                logger.warning("search.rewrite.llm_failed", query=q[:50])
                # Fall through to pattern-based

        # Pattern-based expansions for common interrogatives
        if q.startswith("如何"):
            return f"{q} 方法 步骤"
        if q.startswith("什么是") or q.startswith("啥是"):
            return f"{q} 定义 说明"
        # Short queries: append generic expansion terms to improve recall
        if len(q) <= 10:
            return f"{q} 相关信息"
        return q

    async def _llm_rewrite(self, q: str) -> str:
        """Use DeepSeek or OpenAI API to semantically expand the query."""
        import httpx
        from emerald.config import get_settings

        settings = get_settings()

        # Prefer DeepSeek, fall back to OpenAI
        if settings.deepseek_api_key:
            api_key = settings.deepseek_api_key
            base_url = settings.fact_extraction_base_url.rstrip("/")
            model = "deepseek-chat"
        elif settings.openai_api_key:
            api_key = settings.openai_api_key
            base_url = "https://api.openai.com/v1"
            model = "gpt-3.5-turbo"
        else:
            return q

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a query expansion assistant for a semantic search system. "
                                "Given a user query, expand it with synonyms and related terms "
                                "to improve recall. Return ONLY the expanded query text, no explanation."
                            ),
                        },
                        {"role": "user", "content": f"Expand this search query: {q}"},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 100,
                },
            )
            response.raise_for_status()
            data = response.json()
            expanded = data["choices"][0]["message"]["content"].strip()
            # Safety: if expansion is too long, truncate
            if len(expanded) > 200:
                expanded = expanded[:200]
            logger.info("search.rewrite.llm", original=q[:50], expanded=expanded[:50])
            return expanded if expanded else q

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
