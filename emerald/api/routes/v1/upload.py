"""Upload routes — POST /v1/upload + GET /v1/files."""

from __future__ import annotations

import asyncio
import io
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from emerald.api.dependencies import (
    api_key_auth,
    authorize_entity,
    rate_limit,
    require_write_permission,
)
from emerald.config import get_settings

router = APIRouter(tags=["Upload"])


# Local alias (N5 refactor: helper centralised in api.dependencies).
# This re-export is required so that tests can patch ``upload._authorize_entity``
# (see tests/api/test_upload_authorization.py).
_authorize_entity = authorize_entity


@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(api_key_auth),
        Depends(require_write_permission),
        Depends(rate_limit),
    ],
)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    entity_id: str = Form(...),
    content_type: str | None = Form(default=None),
    title: str | None = Form(default=None),
) -> dict:
    """Upload a file (PDF, image, audio, video, code, etc.) for async
    extraction, chunking, embedding, and indexing. Returns 202 Accepted
    with a pipeline_id to poll via ``GET /v1/pipelines/{id}``.

    File size limit: 50MB.
    """
    start = time.perf_counter()
    settings = get_settings()

    # 0. Entity authorization — must happen before any I/O so an attacker
    #    holding a valid write-permission key scoped to entity A cannot
    #    pollute entity B's document namespace.
    _authorize_entity(request, entity_id)

    # 1. Read and validate size
    contents = await file.read()
    max_size = 50 * 1024 * 1024
    if len(contents) > max_size:
        raise HTTPException(
            413, f"File too large: {len(contents)} bytes (max {max_size})"
        )

    # 2. Detect content type
    detected = content_type or _detect_mime(file.filename)

    # 3. Store in MinIO (offload sync call to thread pool to avoid blocking event loop)
    storage_key = f"{entity_id}/{uuid4().hex}/{file.filename or 'untitled'}"
    minio_client = _get_minio_client()
    await asyncio.to_thread(
        minio_client.put_object,
        settings.minio_bucket,
        storage_key,
        io.BytesIO(contents),
        len(contents),
        content_type=detected,
    )

    # 4. Resolve external entity_id → internal UUID, then create Document
    from sqlalchemy import select

    from emerald.db.session import session_factory
    from emerald.models.document import Document
    from emerald.models.entity import Entity

    async with session_factory.session() as session:
        result = await session.execute(
            select(Entity).where(Entity.external_id == entity_id)
        )
        entity = result.scalar_one_or_none()
        if not entity:
            raise HTTPException(404, f"Entity '{entity_id}' not found")

        doc = Document(
            entity_id=entity.id,
            title=title or file.filename or "untitled",
            content_type=detected,
            storage_key=storage_key,
            file_size_bytes=len(contents),
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)

    # 5. Submit async pipeline
    from emerald.pipeline.orchestrator import PipelineOrchestrator

    orchestrator = PipelineOrchestrator()
    pipeline_id = await orchestrator.process_async(
        content=contents,
        content_type=detected,
        entity_id=entity_id,
        document_id=str(doc.id),
    )

    return {
        "data": {
            "document_id": str(doc.id),
            "pipeline_id": pipeline_id,
            "pipeline_status": "queued",
            "file_size_bytes": len(contents),
            "content_type": detected,
            "title": title or file.filename or "untitled",
        },
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.get(
    "/files",
    response_model=dict,
    dependencies=[Depends(api_key_auth)],
)
async def list_files(
    request: Request,
    entity_id: str,
    status_filter: str = "done",
    page_token: str | None = Query(None, description="Cursor token for pagination"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> dict:
    """List uploaded files for an entity with cursor-based pagination."""
    start = time.perf_counter()

    from emerald.api.pagination import InvalidPaginationToken, PageToken

    try:
        token = PageToken.decode_or_raise(page_token, default_limit=page_size, max_limit=100)
    except InvalidPaginationToken as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    effective_limit = token.limit

    from sqlalchemy import select

    from emerald.db.session import session_factory
    from emerald.models.document import Document
    from emerald.models.entity import Entity

    async with session_factory.session() as session:
        # Resolve external entity_id → internal UUID
        entity_result = await session.execute(
            select(Entity).where(Entity.external_id == entity_id)
        )
        entity = entity_result.scalar_one_or_none()
        if not entity:
            return {
                "data": {"items": []},
                "meta": {"request_id": str(uuid4())[:8], "took_ms": 0},
                "pagination": {"next_page_token": None, "has_more": False},
            }

        # Build cursor-based query (fetch one extra to detect has_more)
        query = (
            select(Document)
            .where(
                Document.entity_id == entity.id,
                Document.status == status_filter,
            )
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(effective_limit + 1)
        )

        # Apply cursor if present (keyset pagination)
        if token.cursor:
            query = query.where(Document.id < token.cursor)

        docs_result = await session.execute(query)
        docs = docs_result.scalars().all()

        has_more = len(docs) > effective_limit
        if has_more:
            docs = docs[:effective_limit]

        next_token = None
        if has_more and docs:
            next_token = PageToken.encode(
                cursor=str(docs[-1].id), limit=effective_limit,
            )

        items = [
            {
                "id": str(doc.id),
                "title": doc.title,
                "content_type": doc.content_type,
                "status": doc.status,
                "file_size_bytes": doc.file_size_bytes,
                "chunk_count": doc.chunk_count,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
            for doc in docs
        ]

    return {
        "data": {
            "items": items,
            "page_size": effective_limit,
        },
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
        "pagination": {
            "next_page_token": next_token,
            "has_more": has_more,
        },
    }


def _detect_mime(filename: str | None) -> str:
    if not filename:
        return "application/octet-stream"
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    mapping = {
        "pdf": "application/pdf",
        "txt": "text/plain",
        "md": "text/markdown",
        "json": "application/json",
        "csv": "text/csv",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    return mapping.get(ext, "application/octet-stream")


def _get_minio_client():
    from minio import Minio

    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
