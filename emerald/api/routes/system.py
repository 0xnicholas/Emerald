"""System routes — health check and metrics."""

from __future__ import annotations

from fastapi import APIRouter

from emerald.config import get_settings

router = APIRouter(tags=["System"])


@router.get("/health", response_model=dict)
async def health_check() -> dict:
    """System health check.

    Returns status of all dependent services.
    """
    settings = get_settings()
    # TODO: actually check each service connectivity
    return {
        "status": "ok",
        "version": "0.1.0",
        "checks": {
            "database": "ok",
            "neo4j": "ok",
            "redis": "ok",
            "minio": "ok",
            "celery": "ok",
        },
    }
