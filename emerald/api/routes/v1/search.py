"""Search routes — POST /v1/search."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from emerald.api.dependencies import (
    api_key_auth,
    authorize_entity,
    rate_limit,
)
from emerald.api.pagination import InvalidPaginationToken, PageToken
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


# Local alias (N5 refactor: helper centralised in api.dependencies).
_authorize_entity = authorize_entity


@router.post("/search", dependencies=[Depends(api_key_auth), Depends(rate_limit)])
async def search(
    body: SearchRequest,
    request: Request,
    page_token: str | None = Query(None, description="Page token for pagination"),
) -> dict:
    """Hybrid search across memory (graph) and RAG (vector)."""
    start = time.perf_counter()
    _authorize_entity(request, body.entity_id)
    engine = _get_engine(request)
    orchestrator = _get_search_orchestrator(request, engine)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    try:
        token = PageToken.decode_or_raise(page_token, default_limit=body.top_k or 30, max_limit=100)
    except InvalidPaginationToken as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    effective_top_k = token.limit

    results = await orchestrator.search(
        q=body.q,
        entity_id=body.entity_id,
        search_mode=SearchMode(body.search_mode),
        top_k=effective_top_k + 1,  # fetch one extra to detect has_more
        rerank=body.rerank,
        rewrite_query=body.rewrite_query,
        filters=body.filters,
        min_confidence=body.min_confidence,
        dynamic_truncation=body.dynamic_truncation,
        about=body.about,
        depth=body.depth,
    )

    result_items = results.results
    pagination = PageToken.pagination_meta(result_items, token)
    if pagination["has_more"]:
        result_items = result_items[:effective_top_k]

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
                    "container_tag": r.container_tag,
                    "tags": r.tags,
                    "is_latest": r.is_latest,
                    "document_id": r.document_id,
                    "document_title": r.document_title,
                    "depth": r.depth,
                    "path": [{"kind": s.kind, "id": s.id} for s in r.path],
                }
                for r in result_items
            ],
            "search_mode": results.search_mode.value,
            "query_rewritten": results.query_rewritten,
        },
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
        "pagination": pagination,
    }


@router.get("/search", dependencies=[Depends(api_key_auth), Depends(rate_limit)])
async def search_get(
    q: str = Query(""),
    entity_id: str = Query(...),
    search_mode: str = Query("hybrid"),
    top_k: int = Query(30, ge=1, le=100),
    rewrite_query: bool = Query(False),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    dynamic_truncation: bool = Query(True),
    about: str | None = Query(
        None,
        description="Entity-centric retrieval (B4): a mention canonical form "
        "or mention id — returns the entity's memories mentioning it "
        "across all surface forms. Skips RAG and fast-lane paths.",
    ),
    depth: int = Query(
        0,
        ge=0,
        le=4,  # must match MAX_DEPTH (emerald/core/multihop.py)
        description="Graph traversal hops (B4): >=1 walks shared-subject "
        "mention bridges and relationship edges (UPDATES / EXTENDS / "
        "DERIVES_FROM, both directions). 0 = status quo. Historical nodes "
        "surface only along UPDATES chains and are marked is_latest=false.",
    ),
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
        about=about,
        depth=depth,
    )

    return {
        "data": {
            "results": [
                {
                    "id": r.id,
                    "content": r.content,
                    "score": r.score,
                    "source": r.source,
                    "container_tag": r.container_tag,
                    "is_latest": r.is_latest,
                    "depth": r.depth,
                    "path": [{"kind": s.kind, "id": s.id} for s in r.path],
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
