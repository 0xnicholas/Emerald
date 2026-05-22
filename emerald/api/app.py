"""FastAPI application with middleware and engine injection."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from emerald.config import get_settings
from emerald.core.engine import MemoryEngine
from emerald.core.exceptions import EmeraldError


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    from emerald.core.logging import configure_logging
    configure_logging(level=settings.emerald_log_level)
    yield


def create_app(engine: MemoryEngine | None = None) -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Emerald",
        version="0.1.0",
        description="Memory and context infrastructure for AI agents",
        docs_url="/docs" if settings.emerald_env == "development" else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store engine in app state so routes can access it
    if engine is not None:
        app.state.engine = engine

    # ---- Middleware: request ID + response wrapping ----

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # ---- Exception handlers ----

    @app.exception_handler(EmeraldError)
    async def emerald_error_handler(request: Request, exc: EmeraldError):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": type(exc).__name__.upper(),
                    "message": str(exc),
                },
                "meta": {"request_id": getattr(request.state, "request_id", "")},
            },
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Route not found: {request.url.path}",
                },
                "meta": {"request_id": getattr(request.state, "request_id", "")},
            },
        )

    # Register routes
    from emerald.api.routes import (
        memories,
        search,
        profiles,
        upload,
        connectors,
        system,
    )

    app.include_router(memories.router, prefix="/v1")
    app.include_router(search.router, prefix="/v1")
    app.include_router(profiles.router, prefix="/v1")
    app.include_router(upload.router, prefix="/v1")
    app.include_router(connectors.router, prefix="/v1")
    app.include_router(system.router, prefix="/v1")

    return app


# Default app (no engine, routes return stubs)
app = create_app()
