"""System routes — health check and metrics."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from emerald.api.dependencies import api_key_auth
from emerald.config import get_settings

router = APIRouter(tags=["System"])


async def _probe_postgres() -> None:
    from emerald.db.session import session_factory
    from sqlalchemy import text

    async with session_factory.session() as session:
        await session.execute(text("SELECT 1"))


async def _probe_neo4j() -> None:
    from emerald.db.neo4j import get_neo4j_driver

    driver = get_neo4j_driver()
    await driver.verify_connectivity()


async def _probe_redis() -> None:
    from emerald.db.redis import get_redis_client

    redis = get_redis_client()
    await redis.ping()


async def _probe_minio() -> None:
    from minio import Minio

    settings = get_settings()
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    client.list_buckets()


@router.get("/health", response_model=dict)
async def health_check() -> dict:
    start = time.perf_counter()
    checks = {}
    overall = "ok"

    for name, probe in [
        ("database", _probe_postgres),
        ("neo4j", _probe_neo4j),
        ("redis", _probe_redis),
        ("minio", _probe_minio),
    ]:
        try:
            await probe()
            checks[name] = "ok"
        except Exception as e:
            checks[name] = f"error: {e}"
            overall = "degraded"

    return {
        "status": overall,
        "version": "0.3.0",
        "checks": checks,
        "meta": {
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.get("/graph/viewport", response_model=dict, dependencies=[Depends(api_key_auth)])
async def graph_viewport(
    entity_id: str,
    limit: int = 100,
    request: Request = None,
) -> dict:
    """Return graph data (nodes + edges) for visualization.

    Suitable for D3.js / vis-network force-directed graph rendering.
    Requires API key authentication.
    """
    engine = getattr(request.app.state, "engine", None) if request else None

    graph = engine.graph if engine else None
    if not graph:
        return {"data": {"nodes": [], "edges": []}}

    memories = await graph.list_latest_memories(entity_id, limit=limit)
    nodes = []
    edges = []
    seen_ids = set()

    for m in memories:
        mid = m["id"]
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        nodes.append({
            "id": mid,
            "label": m.get("summary", "") or m["content"][:60],
            "type": m.get("memory_type", "fact"),
            "confidence": m.get("confidence", 0),
            "is_latest": m.get("is_latest", True),
        })

        for rel in m.get("relationships", []):
            target_id = rel.get("from_id") or rel.get("to_id", "")
            edges.append({
                "source": mid,
                "target": target_id,
                "type": rel.get("type", "EXTENDS"),
                "aspect": rel.get("aspect", ""),
            })

    return {
        "data": {
            "nodes": nodes,
            "edges": edges,
        },
        "meta": {
            "entity_id": entity_id,
            "node_count": len(nodes),
        },
    }
