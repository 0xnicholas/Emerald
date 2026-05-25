"""Search routes — POST /v1/search."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request

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
        embedder=engine.embedder,
    )


@router.post("/search")
async def search(body: SearchRequest, request: Request) -> dict:
    """Hybrid search across memory (graph) and RAG (vector)."""
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
        "meta": {"request_id": request_id},
    }


@router.get("/search")
async def search_get(
    q: str = Query(...),
    entity_id: str = Query(...),
    search_mode: str = Query("hybrid"),
    top_k: int = Query(10, ge=1, le=100),
    request: Request = None,  # type: ignore
) -> dict:
    """GET variant of search."""
    engine = _get_engine(request)
    orchestrator = _get_search_orchestrator(request, engine)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    results = await orchestrator.search(
        q=q,
        entity_id=entity_id,
        search_mode=SearchMode(search_mode),
        top_k=top_k,
    )

    return {
        "data": {
            "results": [
                {"id": r.id, "content": r.content, "score": r.score, "source": r.source}
                for r in results.results
            ],
            "search_mode": results.search_mode.value,
        },
        "meta": {"request_id": request_id},
    }
