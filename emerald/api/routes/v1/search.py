"""Search routes — POST /v1/search."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from emerald.api.dependencies import api_key_auth, rate_limit
from emerald.api.schemas import SearchRequest
from emerald.core.search import SearchMode, SearchOrchestrator

router = APIRouter(tags=["Search"])


def _get_engine(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Memory engine not configured")
    return engine


def _get_search_orchestrator(request: Request, engine=None) -> SearchOrchestrator:
    if engine is None:
        engine = _get_engine(request)
    return SearchOrchestrator(
        graph=engine.graph,
        vector=engine.vector,
        fast_lane_store=engine.fast_lane_store,
        embedder=engine.embedder,
    )


def _authorize_entity(request: Request, entity_id: str) -> None:
    """Ensure the request's API key is scoped to the target entity."""
    allowed = getattr(request.state, "entity_id", None)
    if allowed and allowed != entity_id:
        raise HTTPException(status_code=403, detail="Entity not authorized for this API key")


@router.post("/search", dependencies=[Depends(api_key_auth), Depends(rate_limit)])
async def search(body: SearchRequest, request: Request) -> dict:
    """Hybrid search across memory (graph) and RAG (vector)."""
    start = time.perf_counter()
    _authorize_entity(request, body.entity_id)
    engine = _get_engine(request)
    orchestrator = _get_search_orchestrator(request, engine)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    results = await orchestrator.search(
        q=body.q,
        entity_id=body.entity_id,
        search_mode=SearchMode(body.search_mode),
        top_k=body.top_k,
        rerank=body.rerank,
        rewrite_query=body.rewrite_query,
        filters=body.filters,
        min_confidence=body.min_confidence,
        dynamic_truncation=body.dynamic_truncation,
    )

    return {
        "data": {
            "results": [
                {
                    "id": r.id,
                    "content": r.content,
                    "summary": r.summary,
                    "score": r.score,
                    "source": r.source,
                    "memory_type": r.memory_type,
                    "is_latest": r.is_latest,
                    "document_id": r.document_id,
                    "document_title": r.document_title,
                }
                for r in results.results
            ],
            "search_mode": results.search_mode.value,
            "query_rewritten": results.query_rewritten,
        },
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.get("/search", dependencies=[Depends(api_key_auth), Depends(rate_limit)])
async def search_get(
    q: str = Query(...),
    entity_id: str = Query(...),
    search_mode: str = Query("hybrid"),
    top_k: int = Query(30, ge=1, le=100),
    rewrite_query: bool = Query(False),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    dynamic_truncation: bool = Query(True),
    request: Request = None,  # type: ignore
) -> dict:
    """GET variant of search."""
    start = time.perf_counter()
    _authorize_entity(request, entity_id)
    engine = _get_engine(request)
    orchestrator = _get_search_orchestrator(request, engine)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    results = await orchestrator.search(
        q=q,
        entity_id=entity_id,
        search_mode=SearchMode(search_mode),
        top_k=top_k,
        rewrite_query=rewrite_query,
        min_confidence=min_confidence,
        dynamic_truncation=dynamic_truncation,
    )

    return {
        "data": {
            "results": [
                {"id": r.id, "content": r.content, "score": r.score, "source": r.source}
                for r in results.results
            ],
            "search_mode": results.search_mode.value,
            "query_rewritten": results.query_rewritten,
        },
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }
