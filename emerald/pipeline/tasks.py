"""Pipeline Celery tasks — async task chain for processing."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import structlog
from celery import shared_task

from emerald.async_utils import run_async
from emerald.core.metrics import pipeline_jobs_total
from emerald.core.tracing import attach_traceparent, detach, get_traceparent, get_tracer
from emerald.pipeline.chunking.base import Chunk

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def _neo4j_driver_for_loop():
    """Ensure the Neo4j driver exists in the current event loop.

    Celery tasks run in a fresh event loop per invocation, and the driver
    created by a previous task belongs to a dead loop — so each task that
    touches the graph must create (and close) its own driver.
    """
    from emerald.db.neo4j import close_neo4j, init_neo4j

    await init_neo4j()
    try:
        yield
    finally:
        await close_neo4j()


async def _ensure_loop_redis():
    """Return a Redis client bound to the current task's event loop."""
    from emerald.db.redis import ensure_redis_for_loop

    return await ensure_redis_for_loop()


def _chunk_to_dict(c: Chunk) -> dict[str, Any]:
    """Serialize a chunk to the JSON-safe dict stored in Redis."""

    return {
        "id": c.id,
        "text": c.text,
        "index": c.index,
        "token_count": c.token_count,
        "memory_type": c.memory_type,
        "internal_type": c.internal_type,
        "confidence": c.confidence,
        "summary": c.summary,
        "valid_until": c.valid_until.isoformat() if c.valid_until else None,
    }


def _deserialize_valid_until(raw: Any) -> datetime | None:
    """Parse an ISO-8601 ``valid_until`` value, returning ``None`` on invalid input."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("pipeline.index.invalid_valid_until", value=raw)
        return None


async def _update_status(pipeline_id: str, status: str) -> None:
    from sqlalchemy import text

    from emerald.db.session import session_factory

    async with session_factory.session() as session:
        await session.execute(
            text("UPDATE pipeline_jobs SET status = :status, updated_at = NOW() WHERE id = :id"),
            {"status": status, "id": pipeline_id},
        )


async def _update_fact_extraction_status(
    pipeline_id: str, status: str, memory_count: int | None = None
) -> None:
    """Record the outcome of the chunking/fact-extraction stage.

    P1.2b: surfaces this in ``GET /v1/pipelines/{id}`` so clients can
    distinguish "extractor ran but found nothing" from "pipeline still
    running" from "extractor crashed".
    """
    from sqlalchemy import text

    from emerald.db.session import session_factory

    set_clauses = "fact_extraction_status = :status, updated_at = NOW()"
    params: dict[str, object] = {"status": status, "id": pipeline_id}
    if memory_count is not None:
        set_clauses += ", memory_count = :memory_count"
        params["memory_count"] = memory_count
    async with session_factory.session() as session:
        await session.execute(
            text(
                f"UPDATE pipeline_jobs SET {set_clauses} WHERE id = :id"
            ),
            params,
        )


async def _update_error(pipeline_id: str, stage: str, error: str) -> None:
    pipeline_jobs_total.labels(status="failed").inc()
    from sqlalchemy import text

    from emerald.db.session import session_factory

    async with session_factory.session() as session:
        await session.execute(
            text("""
                UPDATE pipeline_jobs
                SET status = 'failed', error_message = :error, updated_at = NOW()
                WHERE id = :id
            """),
            {"error": f"{stage}: {error}", "id": pipeline_id},
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def extract_task(self, pipeline_id: str, content: str | bytes, content_type: str) -> dict:
    try:
        return run_async(_run_extract)(pipeline_id, content, content_type)
    except Exception as exc:
        run_async(_update_error)(pipeline_id, "extracting", str(exc))
        raise self.retry(exc=exc) from exc


async def _run_extract(pipeline_id, content, content_type):
    await _update_status(pipeline_id, "extracting")
    from emerald.pipeline.extraction import get_default_registry

    registry = get_default_registry()
    extractor = registry.get(content_type)
    result = await extractor.extract(content)

    redis = await _ensure_loop_redis()
    await redis.setex(f"pipeline:{pipeline_id}:text", 86400, result.text)

    traceparent = get_traceparent()
    return {"pipeline_id": pipeline_id, "content_type": content_type, "__traceparent": traceparent}


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def chunk_task(self, prev_result: dict) -> dict:
    try:
        return run_async(_run_chunk)(prev_result)
    except Exception as exc:
        run_async(_update_error)(prev_result["pipeline_id"], "chunking", str(exc))
        raise self.retry(exc=exc) from exc


async def _run_chunk(prev_result: dict) -> dict:
    pipeline_id = prev_result["pipeline_id"]
    await _update_status(pipeline_id, "chunking")
    redis = await _ensure_loop_redis()
    text = await redis.get(f"pipeline:{pipeline_id}:text")

    from emerald.pipeline.chunking import get_default_registry

    registry = get_default_registry()
    chunker = registry.get(prev_result.get("content_type", "text"))
    chunks = await chunker.chunk(text or "")

    data = [_chunk_to_dict(c) for c in chunks]
    await redis.setex(f"pipeline:{pipeline_id}:chunks", 86400, json.dumps(data))
    prev_result["chunk_count"] = len(chunks)
    # P1.2b: fact_extraction_status is set exclusively by the index_task's
    # finally block (it has authoritative knowledge of how many memories
    # were actually created). Writing it here would be dead code — the
    # downstream update would overwrite this value unconditionally.
    return prev_result


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def embed_task(self, prev_result: dict) -> dict:
    try:
        return run_async(_run_embed)(prev_result)
    except Exception as exc:
        run_async(_update_error)(prev_result["pipeline_id"], "embedding", str(exc))
        raise self.retry(exc=exc) from exc


async def _run_embed(prev_result: dict) -> dict:
    pipeline_id = prev_result["pipeline_id"]
    await _update_status(pipeline_id, "embedding")
    redis = await _ensure_loop_redis()
    chunks_raw = await redis.get(f"pipeline:{pipeline_id}:chunks")
    chunks_data = json.loads(chunks_raw or "[]")
    texts = [c["text"] for c in chunks_data]

    from emerald.core.embedder import get_embedding_provider

    provider = get_embedding_provider()
    embeddings = await provider.embed(texts)

    await redis.setex(f"pipeline:{pipeline_id}:embeddings", 86400, json.dumps(embeddings))
    prev_result["__traceparent"] = get_traceparent()
    return prev_result


@shared_task(bind=True)
def index_task(self, prev_result: dict, entity_id: str) -> dict:
    traceparent = prev_result.get("__traceparent")
    token = attach_traceparent(traceparent)
    try:
        tracer = get_tracer()
        with tracer.start_as_current_span("pipeline.index") as span:
            span.set_attribute("entity_id", entity_id)
            span.set_attribute("pipeline_id", prev_result.get("pipeline_id", ""))
            return run_async(_run_index)(self, prev_result, entity_id)
    finally:
        detach(token)


async def _run_index(task_self, prev_result: dict, entity_id: str) -> dict:
    """Stage 4: Write to Neo4j + pgvector, infer relationships."""
    pipeline_id = prev_result["pipeline_id"]
    memory_ids: list[str] = []
    try:
        async with _neo4j_driver_for_loop():
            await _update_status(pipeline_id, "indexing")
            redis = await _ensure_loop_redis()
            chunks_raw = await redis.get(f"pipeline:{pipeline_id}:chunks")
            embeddings_raw = await redis.get(f"pipeline:{pipeline_id}:embeddings")
            chunks_data = json.loads(chunks_raw or "[]")
            embeddings = json.loads(embeddings_raw or "[]")

            from emerald.core.graph import GraphStore
            from emerald.core.vector import VectorStore

            graph = GraphStore(use_db=True)
            vector = VectorStore(use_db=True)
            for chunk_data, embedding in zip(chunks_data, embeddings, strict=False):
                valid_until = _deserialize_valid_until(chunk_data.get("valid_until"))
                mid = await graph.create_memory(
                    content=chunk_data["text"],
                    entity_id=entity_id,
                    memory_type=chunk_data.get("memory_type", "fact"),
                    internal_type=chunk_data.get("internal_type"),
                    confidence=chunk_data.get("confidence", 0.8),
                    summary=chunk_data.get("summary") or None,
                    source_type="document",
                    valid_until=valid_until,
                )
                memory_ids.append(mid)
                await vector.store(
                    chunk_id=mid,
                    text=chunk_data["text"],
                    embedding=embedding,
                    entity_id=entity_id,
                )

        return {"pipeline_id": pipeline_id, "memory_ids": memory_ids}
    except Exception as exc:
        await _update_error(pipeline_id, "indexing", str(exc))
        raise
    finally:
        # P1.2b: record the number of memories actually created so clients
        # can show "extracted 5 facts" etc. via GET /v1/pipelines/{id}.
        try:
            await _update_fact_extraction_status(
                pipeline_id, "success", memory_count=len(memory_ids)
            )
        except Exception:  # never let status update mask the real error
            pass


@shared_task
def postprocess_task(prev_result: dict, entity_id: str) -> None:
    traceparent = prev_result.get("__traceparent")
    token = attach_traceparent(traceparent)
    try:
        tracer = get_tracer()
        with tracer.start_as_current_span("pipeline.postprocess") as span:
            span.set_attribute("entity_id", entity_id)
            span.set_attribute("pipeline_id", prev_result.get("pipeline_id", ""))
            return run_async(_run_postprocess)(prev_result, entity_id)
    finally:
        detach(token)


async def _run_postprocess(prev_result: dict, entity_id: str) -> None:
    pipeline_id = prev_result["pipeline_id"]
    memory_ids = prev_result.get("memory_ids", [])

    async with _neo4j_driver_for_loop():
        from emerald.core.graph import GraphStore
        from emerald.core.relationship import RelationshipEngine

        rel_engine = RelationshipEngine(graph=GraphStore(use_db=True))
        await rel_engine.infer(memory_ids, entity_id)

        from emerald.core.profile import ProfileManager

        profile_mgr = ProfileManager(graph=GraphStore(use_db=True))
        await profile_mgr.refresh(entity_id, memory_ids)

        redis = await _ensure_loop_redis()

        # Archive the fast-lane chunk that was created when the pipeline was queued.
        try:
            fast_lane_id = await redis.get(f"pipeline:{pipeline_id}:fast_lane_id")
            if fast_lane_id:
                from emerald.core.fast_lane import FastLaneStore

                await FastLaneStore(use_db=True).archive(str(fast_lane_id))
        except Exception:
            logger.warning("pipeline.postprocess.fast_lane_archive_failed", pipeline_id=pipeline_id)

        for key in ["text", "chunks", "embeddings", "fast_lane_id"]:
            await redis.delete(f"pipeline:{pipeline_id}:{key}")

        await _update_status(pipeline_id, "done")
        pipeline_jobs_total.labels(status="done").inc()


# ---- Scheduled tasks (Celery Beat) ----


@shared_task
def cleanup_fast_lane_task() -> dict:
    """Celery Beat: hourly - archive stale fast-lane chunks."""
    return run_async(_run_cleanup_fast_lane)()


async def _run_cleanup_fast_lane() -> dict:
    from emerald.core.fast_lane import FastLaneStore

    async def _work():
        store = FastLaneStore(use_db=True)
        count = await store.cleanup()
        logger.info("pipeline.task.cleanup_fast_lane", count=count)
        return {"strategy": "fast_lane_cleanup", "count": count}
    result = await _locked_run(_work(), "task_cleanup_fast_lane")
    return (
        result
        if result is not None
        else {"strategy": "fast_lane_cleanup", "count": 0, "skipped": True}
    )


async def _locked_run(coro, lock_name: str, ttl: int = 600) -> dict | None:
    """Execute *coro* under a distributed lock; skip if lock is held by another instance."""
    from emerald.core.lock import DistributedLock

    lock = DistributedLock(lock_name, ttl_seconds=ttl)
    if not await lock.acquire():
        logger.info("beat.skipped", task=lock_name, reason="lock_contention")
        return None
    try:
        return await coro
    finally:
        await lock.release()


@shared_task
def forget_expired_task() -> dict:
    """Celery Beat: hourly - expire past valid_until memories."""
    return run_async(_run_forget_expired)()


async def _run_forget_expired() -> dict:
    from emerald.core.forget import ForgetEngine
    from emerald.core.graph import GraphStore

    async def _work():
        async with _neo4j_driver_for_loop():
            engine = ForgetEngine(graph=GraphStore(use_db=True))
            count = await engine.forget_expired()
            logger.info("pipeline.task.forget_expired", count=count)
            return {"strategy": "time_expiry", "count": count}

    result = await _locked_run(_work(), "task_forget_expired")
    return (
        result if result is not None else {"strategy": "time_expiry", "count": 0, "skipped": True}
    )


@shared_task
def forget_noise_task() -> dict:
    """Celery Beat: daily 3 AM - archive noise memories."""
    return run_async(_run_forget_noise)()


async def _run_forget_noise() -> dict:
    from emerald.core.forget import ForgetEngine
    from emerald.core.graph import GraphStore

    async def _work():
        async with _neo4j_driver_for_loop():
            engine = ForgetEngine(graph=GraphStore(use_db=True))
            count = await engine.forget_noise()
            logger.info("pipeline.task.forget_noise", count=count)
            return {"strategy": "noise_filter", "count": count}

    result = await _locked_run(_work(), "task_forget_noise", ttl=1800)
    return (
        result if result is not None else {"strategy": "noise_filter", "count": 0, "skipped": True}
    )


@shared_task
def decay_episodic_task() -> dict:
    """Celery Beat: daily 4 AM - decay old episodic memories."""
    return run_async(_run_decay_episodic)()


async def _run_decay_episodic() -> dict:
    from emerald.core.forget import ForgetEngine
    from emerald.core.graph import GraphStore

    async def _work():
        async with _neo4j_driver_for_loop():
            engine = ForgetEngine(graph=GraphStore(use_db=True))
            count = await engine.decay_episodic()
            logger.info("pipeline.task.decay_episodic", count=count)
            return {"strategy": "episodic_decay", "count": count}

    result = await _locked_run(_work(), "task_decay_episodic", ttl=1800)
    return (
        result
        if result is not None
        else {"strategy": "episodic_decay", "count": 0, "skipped": True}
    )


@shared_task
def reconcile_index_task() -> dict:
    """Celery Beat: every 30 min - repair orphaned graph nodes.

    Scans for Memory nodes created recently that have no corresponding
    pgvector embedding row and either re-writes the vector or marks the
    node as ``indexing_failed``.
    """
    return run_async(_run_reconcile)()


async def _run_reconcile() -> dict:
    from emerald.core.embedder import get_embedding_provider
    from emerald.core.graph import GraphStore
    from emerald.core.reconciliation import ReconciliationEngine
    from emerald.core.vector import VectorStore

    async def _work():
        async with _neo4j_driver_for_loop():
            engine = ReconciliationEngine(
                graph=GraphStore(use_db=True),
                vector=VectorStore(use_db=True),
                embedder=get_embedding_provider(),
            )
            result = await engine.reconcile(lookback_minutes=120, max_repairs=200)
            logger.info(
                "pipeline.task.reconcile",
                found=result["found"],
                repaired=result["repaired"],
                failed=result["failed"],
            )
            return result

    result = await _locked_run(_work(), "task_reconcile_index", ttl=600)
    return (
        result if result is not None else {"found": 0, "repaired": 0, "failed": 0, "skipped": True}
    )
