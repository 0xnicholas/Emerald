"""Upload routes — POST /v1/upload + GET /v1/files."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from emerald.api.dependencies import api_key_auth, require_write_permission

router = APIRouter(tags=["Upload"])


@router.post(
    "/upload",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(api_key_auth), Depends(require_write_permission)],
)
async def upload_file(
    file: UploadFile = File(...),
    entity_id: str = Form(...),
    content_type: str | None = Form(default=None),
    title: str | None = Form(default=None),
    metadata: str | None = Form(default=None),
) -> dict:
    """Upload a file for processing.

    Files up to 50MB. Returns HTTP 202 with pipeline_id for async processing.
    """
    # TODO:
    # 1. Validate file size (50MB limit)
    # 2. Detect content_type if not provided
    # 3. Upload to MinIO
    # 4. Create Document record in PostgreSQL
    # 5. Submit async pipeline task
    return {
        "data": {
            "document_id": "",
            "pipeline_id": "",
            "pipeline_status": "queued",
            "file_size_bytes": 0,
            "content_type": content_type or "auto",
            "title": title or file.filename or "untitled",
        },
    }


@router.get(
    "/files",
    response_model=dict,
    dependencies=[Depends(api_key_auth)],
)
async def list_files(
    entity_id: str,
    status_filter: str = "done",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """List uploaded files for an entity."""
    return {
        "data": {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
        },
    }


@router.get(
    "/pipelines/{pipeline_id}",
    response_model=dict,
    dependencies=[Depends(api_key_auth)],
)
async def get_pipeline_status(pipeline_id: str) -> dict:
    """Check pipeline processing status."""
    # TODO: query pipeline_jobs table
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Pipeline {pipeline_id} not found",
    )
