"""Memory engine — the central entry point for content ingestion.

Routes incoming content through the pipeline: detect type → extract → chunk → embed → index.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from emerald.config import get_settings
from emerald.core.chunker import Chunk, ChunkerRegistry
from emerald.core.chunker import get_default_registry as get_default_chunker_registry
from emerald.core.embedder import EmbeddingProvider, get_embedding_provider
from emerald.core.exceptions import IndexingError
from emerald.core.extractor import ExtractedContent, ExtractorRegistry
from emerald.core.extractor import get_default_registry as get_default_extractor_registry
from emerald.core.fast_lane import FastLaneStore
from emerald.core.graph import GraphStore
from emerald.core.metrics import memory_add_latency_seconds, memory_add_total, timed
from emerald.core.profile import ProfileManager
from emerald.core.relationship import RelationshipEngine
from emerald.core.tracing import get_tracer
from emerald.core.vector import VectorStore

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# I5 refactor: override precedence helpers
# ---------------------------------------------------------------------------
# Per-field resolution: explicit add() arg > metadata dict > chunker default.
# Extracted so the per-chunk loop in _index() reads as a 3-line dispatch
# instead of 3 nested if-blocks.  None means "use the next lower priority".
def _resolve_override(
    explicit: Any,
    from_metadata: Any,
    from_chunker: Any,
) -> Any:
    """Pick the highest-priority non-None value among the three sources."""
    if explicit is not None:
        return explicit
    if from_metadata is not None:
        return from_metadata
    return from_chunker


def _resolve_override_valid_until(
    explicit: datetime | None,
    from_metadata: datetime | str | None,
    from_chunker: datetime | None,
) -> datetime | None:
    """Same precedence as _resolve_override, but parses ISO strings.

    ``valid_until`` may arrive as a datetime (from the SDK) or as an ISO
    8601 string (from the REST body via the metadata dict).
    """
    if explicit is not None:
        return explicit
    if from_metadata is not None:
        if isinstance(from_metadata, str):
            return datetime.fromisoformat(from_metadata.replace("Z", "+00:00"))
        return from_metadata
    return from_chunker


class AddResult:
    """Result of a memory add operation."""

    def __init__(
        self,
        memory_ids: list[str],
        pipeline_status: str = "done",
        extracted_count: int = 0,
        conflicts_pending: list[dict] | None = None,
    ) -> None:
        self.memory_ids = memory_ids
        self.pipeline_status = pipeline_status
        self.extracted_count = extracted_count
        self.conflicts_pending = conflicts_pending or []


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
        fast_lane_store: FastLaneStore | None = None,
        relationships: RelationshipEngine | None = None,
        profile_manager: ProfileManager | None = None,
        use_db: bool = False,
    ) -> None:
        self.extractors = extractor_registry or get_default_extractor_registry()
        self.chunkers = chunker_registry or get_default_chunker_registry()
        self.embedder = embedder or get_embedding_provider()
        self.graph = graph or GraphStore(use_db=use_db)
        self.vector = vector or VectorStore(use_db=use_db)
        self.fast_lane_store = fast_lane_store or FastLaneStore(use_db=use_db)
        self.relationships = relationships or RelationshipEngine(graph=self.graph)
        self.profile_manager = profile_manager or ProfileManager(graph=self.graph)

    async def add(
        self,
        content: str,
        *,
        entity_id: str,
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        require_confirmation_for_high_impact: bool = False,
        memory_type: str | None = None,
        confidence: float | None = None,
        valid_until: datetime | None = None,
    ) -> AddResult:
        """Add content to the memory graph (synchronous path).

        Returns AddResult with memory IDs.

        Optional per-memory overrides (P1.2a): when provided, ``memory_type``,
        ``confidence`` and ``valid_until`` take precedence over the chunker's
        defaults and any value tucked into ``metadata``.  This is the
        supported path for callers that know the semantic class of the
        memory (e.g. an onboarding form that just captured a preference)
        and want to skip the LLM classification step.
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
                        logger.info(
                            "memory.add.idempotent",
                            entity_id=entity_id,
                            key=idempotency_key,
                        )
                        return cached

                logger.info(
                    "memory.add.start",
                    entity_id=entity_id,
                    content_type=content_type,
                    content_length=len(content),
                )

                # 1. Extract
                extracted = await self._extract(content, content_type)

                # 1.5 Semantic dedup: skip if semantically identical to existing memory
                is_dup = await self._check_duplicate(extracted.text, entity_id)
                if is_dup:
                    logger.info("memory.add.duplicate_skipped", entity_id=entity_id,
                                content_preview=content[:50])
                    return AddResult(memory_ids=[], pipeline_status="duplicate",
                                     extracted_count=0)

                # 1.6 Fast lane: make a coarse raw chunk searchable immediately,
                #     before the heavier extraction/relationship pipeline finishes.
                fast_lane_ids: list[str] = []
                if get_settings().fast_lane_enabled:
                    fast_lane_ids = await self._fast_lane_index(
                        extracted.text, entity_id
                    )

                # 2. Chunk
                chunks = await self._chunk(extracted, content_type)

                # 3. Embed
                embeddings = await self._embed(chunks)

                # 4. Index — store in graph + vector
                memory_ids = await self._index(
                    chunks, embeddings, entity_id, content_type, metadata,
                    overrides={
                        "memory_type": memory_type,
                        "confidence": confidence,
                        "valid_until": valid_until,
                    },
                )

                # 4.5 Strengthen preferences: if similar preference already exists,
                #      boost its confidence instead of creating a near-duplicate.
                memory_ids = await self._strengthen_preferences(
                    chunks, memory_ids, entity_id, metadata
                )

                # 5. Infer relationships (automatic + optional high-impact confirmation)
                infer_result = await self.relationships.infer_with_conflicts(
                    memory_ids,
                    entity_id,
                    require_confirmation_for_high_impact=require_confirmation_for_high_impact,
                )

                # 5.5 Archive fast-lane chunks now that indexed memories exist.
                #     Archiving is best-effort; failures are logged but don't fail add().
                for fl_id in fast_lane_ids:
                    try:
                        await self.fast_lane_store.archive(fl_id)
                    except Exception as exc:
                        logger.warning(
                            "fast_lane.archive_failed",
                            fast_lane_id=fl_id,
                            entity_id=entity_id,
                            error=str(exc),
                        )

                # 6. Invalidate profile cache
                await self.profile_manager.invalidate(entity_id)

                result = AddResult(
                    memory_ids=memory_ids,
                    pipeline_status="done",
                    extracted_count=len(chunks),
                    conflicts_pending=infer_result.get("pending_conflicts", []),
                )

                # Cache result for idempotency
                if idempotency_key:
                    await self._cache_idempotency(entity_id, idempotency_key, result)

                from collections import Counter
                type_counts = Counter(chunk.memory_type for chunk in chunks)
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
                for idx, emb in zip(to_embed_indices, new_embeddings, strict=True):
                    pipe.setex(f"emb:{hashes[idx]}", 7 * 86400, json.dumps(emb))
                await pipe.execute()
            for idx, emb in zip(to_embed_indices, new_embeddings, strict=True):
                embeddings[idx] = emb

        return [e for e in embeddings if e is not None]

    async def _index(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        entity_id: str,
        content_type: str,
        metadata: dict[str, Any] | None,
        overrides: dict[str, Any] | None = None,
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

        for chunk, embedding in zip(chunks, embeddings, strict=True):
            # 1. Store in Neo4j graph — memory_id becomes the canonical ID
            # Apply override precedence (I5): explicit add() args >
            # metadata dict > chunker default.  Helper resolves one field
            # at a time so the per-field rules are obvious.
            overridden_type = _resolve_override(
                (overrides or {}).get("memory_type"),
                (metadata or {}).get("memory_type"),
                chunk.memory_type,
            )
            overridden_confidence = _resolve_override(
                (overrides or {}).get("confidence"),
                (metadata or {}).get("confidence"),
                chunk.confidence,
            )
            overridden_valid_until = _resolve_override_valid_until(
                (overrides or {}).get("valid_until"),
                (metadata or {}).get("valid_until"),
                chunk.valid_until,
            )
            memory_id = await self.graph.create_memory(
                content=chunk.text,
                entity_id=entity_id,
                memory_type=overridden_type,
                internal_type=chunk.internal_type,
                confidence=overridden_confidence,
                provenance=chunk.provenance,
                summary=chunk.summary or None,
                source_type="conversation" if content_type == "conversation" else "document",
                valid_until=overridden_valid_until,
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

    async def _strengthen_preferences(
        self,
        chunks: list[Chunk],
        memory_ids: list[str],
        entity_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        """Strengthen existing preference confidence when similar preferences repeat.

        If a new preference has high text overlap with an existing preference,
        boost the existing one's confidence by 0.05 (capped at 0.95) instead of
        creating a duplicate.  Lower-overlap preferences are kept as separate
        memories (complements, not duplicates).

        Only applies to chunks with memory_type='preference'.
        """
        threshold = 0.3  # bigram overlap threshold for "same preference"

        for chunk, mid in zip(chunks, memory_ids, strict=True):
            # Check memory_type — prefer metadata override, then chunk default
            mem_type = (metadata or {}).get("memory_type") or chunk.memory_type
            if mem_type != "preference":
                continue

            # Find existing preferences for this entity
            existing = await self.graph.list_latest_memories(
                entity_id, limit=50,
            )
            existing_prefs = [
                m for m in existing
                if m.get("memory_type") == "preference" and m["id"] != mid
            ]

            best_overlap = 0.0
            best_match = None

            new_bigrams = self._extract_bigrams(chunk.text)
            if not new_bigrams:
                continue

            for old in existing_prefs:
                overlap = self._bigram_overlap(chunk.text, old.get("content", ""))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_match = old

            if best_overlap >= threshold and best_match:
                # Boost existing preference confidence
                current_conf = best_match.get("confidence", 0.8)
                new_conf = min(current_conf + 0.05, 0.95)
                await self.graph.update_memory_confidence(best_match["id"], new_conf)

                # Mark the new (duplicate) memory as not latest
                await self.graph.update_is_latest(mid, False, replaced_by=best_match["id"])
                logger.info(
                    "preference.strengthened",
                    entity_id=entity_id,
                    existing_id=best_match["id"][:8],
                    confidence_before=current_conf,
                    confidence_after=new_conf,
                    overlap=round(best_overlap, 2),
                )

                # Remove duplicate from returned IDs
                memory_ids = [i for i in memory_ids if i != mid]

        return memory_ids

    @staticmethod
    def _extract_bigrams(text: str) -> set[str]:
        """Extract character bigrams for text overlap scoring."""
        import re
        normalized = re.sub(r"\s+", "", text)
        return {normalized[i:i+2] for i in range(len(normalized) - 1)}

    @staticmethod
    def _bigram_overlap(text_a: str, text_b: str) -> float:
        """Compute bigram overlap ratio: |A ∩ B| / |A|."""
        a = MemoryEngine._extract_bigrams(text_a)
        b = MemoryEngine._extract_bigrams(text_b)
        if not a:
            return 0.0
        return len(a & b) / len(a)

    async def _check_duplicate(self, text: str, entity_id: str) -> bool:
        """Check if text is semantically identical to an existing memory.

        Uses fast bigram filter first; only calls LLM for borderline cases.
        Returns True if text should be skipped as duplicate.
        """
        if not text.strip():
            return True

        # Fast filter: check bigram overlap with recent memories
        existing = await self.graph.list_latest_memories(entity_id, limit=30)

        exact_dup = None
        borderline = None

        for old in existing:
            old_text = old.get("content", "")
            # Exact match → definitely duplicate
            if text.strip() == old_text.strip():
                return True

            overlap = self._bigram_overlap(text, old_text)

            if overlap > 0.95:
                exact_dup = old
                break
            elif overlap > 0.6:
                borderline = old
                # Keep checking — maybe we find a closer match

        # High overlap → definitely duplicate
        if exact_dup:
            return True

        # Borderline → ask LLM
        if borderline:
            return await self._llm_check_duplicate(text, borderline["content"])

        return False

    async def _llm_check_duplicate(self, new_text: str, old_text: str) -> bool:
        """Use LLM to check if two texts convey the same fact."""
        try:
            from emerald.config import get_settings
            settings = get_settings()
            if not settings.deepseek_api_key:
                return False

            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(
                    f"{settings.fact_extraction_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.deepseek_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": (
                                "Determine if two texts express the same fact/information. "
                                "Answer only YES or NO."
                            )},
                            {"role": "user", "content": f"Text A: {old_text}\nText B: {new_text}"},
                        ],
                        "temperature": 0.0,
                        "max_tokens": 5,
                    },
                )
                response.raise_for_status()
                data = response.json()
                answer = data["choices"][0]["message"]["content"].strip().upper()
                return "YES" in answer
        except Exception:
            return False

    async def _fast_lane_index(
        self, text: str, entity_id: str
    ) -> list[str]:
        """Create coarse fast-lane chunks and store them for immediate search.

        Returns the list of fast-lane IDs. Failures are logged and skipped so
        the main pipeline can continue.
        """
        settings = get_settings()
        if not settings.fast_lane_enabled or not text.strip():
            return []

        chunks = self._fast_lane_split(text, settings.fast_lane_max_chars_per_chunk)
        if not chunks:
            return []

        try:
            embeddings = await self.embedder.embed(chunks)
        except Exception as exc:
            logger.warning(
                "fast_lane.embed_failed", entity_id=entity_id, error=str(exc)
            )
            return []

        model_name = getattr(self.embedder, "_model", "unknown")
        fast_lane_ids: list[str] = []
        for chunk_text, embedding in zip(chunks, embeddings, strict=False):
            try:
                fl_id = await self.fast_lane_store.store(
                    text=chunk_text,
                    embedding=embedding,
                    entity_id=entity_id,
                    model_name=model_name,
                )
                fast_lane_ids.append(fl_id)
            except Exception as exc:
                logger.warning(
                    "fast_lane.store_failed",
                    entity_id=entity_id,
                    error=str(exc),
                )

        if fast_lane_ids:
            logger.info(
                "fast_lane.indexed",
                entity_id=entity_id,
                chunk_count=len(fast_lane_ids),
            )
        return fast_lane_ids

    @staticmethod
    def _fast_lane_split(text: str, max_chars: int) -> list[str]:
        """Split text into coarse chunks for the fast lane.

        Splits on blank lines first, then hard-truncates any chunk that is
        still too long. This is intentionally simple: the goal is speed, not
        semantic perfection.
        """
        import re

        # Normalize line endings and split on blank lines
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            paragraphs = [text.strip()]

        chunks: list[str] = []
        for para in paragraphs:
            while len(para) > max_chars:
                # Try to break at the last sentence boundary within the limit
                cutoff = para.rfind("。", max_chars // 2, max_chars)
                if cutoff == -1:
                    cutoff = para.rfind(".", max_chars // 2, max_chars)
                if cutoff == -1:
                    cutoff = max_chars
                chunk = para[:cutoff].strip()
                if chunk:
                    chunks.append(chunk)
                para = para[cutoff:].strip()
            if para:
                chunks.append(para)
        return chunks

    async def process_async(
        self,
        content: str | bytes,
        *,
        entity_id: str,
        content_type: str,
        document_id: str | None = None,
    ) -> str:
        """Submit content for async pipeline processing (files, batch).

        Delegates to PipelineOrchestrator, which stores a fast-lane chunk
        before the full Celery chain and archives it once indexing completes.
        Returns pipeline_id for status tracking.
        """
        # Dedup check for async path too
        if isinstance(content, str):
            is_dup = await self._check_duplicate(content, entity_id)
            if is_dup:
                logger.info("memory.add.duplicate_skipped_async", entity_id=entity_id)
                return "duplicate"

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
