"""Pipeline Celery tasks — async task chain for processing."""

from __future__ import annotations

import json
import structlog
from celery import shared_task

from emerald.async_utils import run_async

logger = structlog.get_logger(__name__)


async def _update_status(pipeline_id: str, status: str) -> None:
    from emerald.db.session import session_factory
    from sqlalchemy import text

    async with session_factory.session() as session:
        await session.execute(
            text(
                "UPDATE pipeline_jobs SET status = :status, updated_at = NOW() WHERE id = :id"
            ),
            {"status": status, "id": pipeline_id},
        )


async def _update_error(pipeline_id: str, stage: str, error: str) -> None:
    from emerald.db.session import session_factory
    from sqlalchemy import text

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
        return run_async(_run_extract)(self, pipeline_id, content, content_type)
    except Exception as exc:
        run_async(_update_error)(pipeline_id, "extracting", str(exc))
        raise self.retry(exc=exc)


async def _run_extract(pipeline_id, content, content_type):
    await _update_status(pipeline_id, "extracting")
    from emerald.pipeline.extraction.registry import ExtractorRegistry

    extractor = ExtractorRegistry().get(content_type)
    result = await extractor.extract(content)

    from emerald.db.redis import get_redis_client

    redis = get_redis_client()
    await redis.setex(f"pipeline:{pipeline_id}:text", 86400, result.text)

    return {"pipeline_id": pipeline_id, "content_type": content_type}


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def chunk_task(self, prev_result: dict) -> dict:
    try:
        return run_async(_run_chunk)(self, prev_result)
    except Exception as exc:
        run_async(_update_error)(prev_result["pipeline_id"], "chunking", str(exc))
        raise self.retry(exc=exc)


async def _run_chunk(prev_result: dict) -> dict:
    pipeline_id = prev_result["pipeline_id"]
    await _update_status(pipeline_id, "chunking")
    from emerald.db.redis import get_redis_client

    redis = get_redis_client()
    text = await redis.get(f"pipeline:{pipeline_id}:text")

    from emerald.pipeline.chunking.registry import ChunkerRegistry

    chunker = ChunkerRegistry().get(prev_result.get("content_type", "text"))
    chunks = chunker.chunk(text or "")

    data = [
        {"id": c.id, "text": c.text, "index": c.index, "token_count": c.token_count}
        for c in chunks
    ]
    await redis.setex(f"pipeline:{pipeline_id}:chunks", 86400, json.dumps(data))
    return {"pipeline_id": pipeline_id, "chunk_count": len(chunks)}


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def embed_task(self, prev_result: dict) -> dict:
    try:
        return run_async(_run_embed)(self, prev_result)
    except Exception as exc:
        run_async(_update_error)(prev_result["pipeline_id"], "embedding", str(exc))
        raise self.retry(exc=exc)


async def _run_embed(prev_result: dict) -> dict:
    pipeline_id = prev_result["pipeline_id"]
    await _update_status(pipeline_id, "embedding")
    from emerald.db.redis import get_redis_client

    redis = get_redis_client()
    chunks_raw = await redis.get(f"pipeline:{pipeline_id}:chunks")
    chunks_data = json.loads(chunks_raw or "[]")
    texts = [c["text"] for c in chunks_data]

    from emerald.core.embedder import get_embedding_provider

    provider = get_embedding_provider()
    embeddings = await provider.embed(texts)

    await redis.setex(
        f"pipeline:{pipeline_id}:embeddings", 86400, json.dumps(embeddings)
    )
    return {"pipeline_id": pipeline_id}


@shared_task(bind=True)
def index_task(self, prev_result: dict, entity_id: str) -> dict:
    return run_async(_run_index)(self, prev_result, entity_id)


async def _run_index(task_self, prev_result: dict, entity_id: str) -> dict:
    """Stage 4: Write to Neo4j + pgvector, infer relationships."""
    pipeline_id = prev_result["pipeline_id"]
    from emerald.db.neo4j import close_neo4j, init_neo4j

    await init_neo4j()
    try:
        await _update_status(pipeline_id, "indexing")
        from emerald.db.redis import get_redis_client

        redis = get_redis_client()
        chunks_raw = await redis.get(f"pipeline:{pipeline_id}:chunks")
        embeddings_raw = await redis.get(f"pipeline:{pipeline_id}:embeddings")
        chunks_data = json.loads(chunks_raw or "[]")
        embeddings = json.loads(embeddings_raw or "[]")

        from emerald.core.graph import GraphStore
        from emerald.core.vector import VectorStore

        graph = GraphStore(use_db=True)
        vector = VectorStore(use_db=True)

        memory_ids = []
        for chunk_data, embedding in zip(chunks_data, embeddings):
            mid = await graph.create_memory(
                content=chunk_data["text"],
                entity_id=entity_id,
                memory_type="fact",
                confidence=0.8,
                source_type="document",
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
        await close_neo4j()


@shared_task
def postprocess_task(prev_result: dict, entity_id: str) -> None:
    return run_async(_run_postprocess)(prev_result, entity_id)


async def _run_postprocess(prev_result: dict, entity_id: str) -> None:
    pipeline_id = prev_result["pipeline_id"]
    memory_ids = prev_result.get("memory_ids", [])

    from emerald.core.graph import GraphStore
    from emerald.core.relationship import RelationshipEngine

    rel_engine = RelationshipEngine(graph=GraphStore(use_db=True))
    await rel_engine.infer(memory_ids, entity_id)

    from emerald.core.profile import ProfileManager

    profile_mgr = ProfileManager(graph=GraphStore(use_db=True))
    await profile_mgr.invalidate(entity_id)

    from emerald.db.redis import get_redis_client

    redis = get_redis_client()
    for key in ["text", "chunks", "embeddings"]:
        await redis.delete(f"pipeline:{pipeline_id}:{key}")

    await _update_status(pipeline_id, "done")


# ---- Scheduled tasks (kept async for Celery Beat compatibility) ----


async def forget_expired() -> None:
    """Celery Beat: hourly - expire past valid_until memories."""
    logger.info("pipeline.task.forget_expired")


async def forget_noise() -> None:
    """Celery Beat: daily 3 AM - archive noise memories."""
    logger.info("pipeline.task.forget_noise")


async def decay_episodic() -> None:
    """Celery Beat: daily 4 AM - decay old episodic memories."""
    logger.info("pipeline.task.decay_episodic")
