"""FastAPI application with middleware and engine injection."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from emerald.config import get_settings
from emerald.core.engine import MemoryEngine
from emerald.core.exceptions import EmeraldError


def _init_engine() -> MemoryEngine:
    """Build a MemoryEngine with all built-in extractors and chunkers registered.

    Extractors/chunkers that require optional dependencies (e.g. PyMuPDF,
    tree-sitter, Pillow) are imported inside try/except so the app can start
    even when ``pip install -e '.[extraction]'`` has not been run.
    """
    import logging

    from emerald.pipeline.chunking.conversation import ConversationChunker
    from emerald.pipeline.chunking.markdown import MarkdownChunker
    from emerald.pipeline.chunking.registry import ChunkerRegistry
    from emerald.pipeline.extraction.registry import ExtractorRegistry
    from emerald.pipeline.extraction.text import TextExtractor

    logger = logging.getLogger(__name__)

    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    extractors.register("conversation", TextExtractor())
    extractors.register("markdown", TextExtractor())

    # --- Optional: URL extractor (trafilatura) ---
    try:
        from emerald.pipeline.extraction.url import URLExtractor
        extractors.register("url", URLExtractor())
    except ImportError as e:
        logger.warning("URLExtractor not available: %s", e)

    # --- Optional: PDF extractor (PyMuPDF) ---
    try:
        from emerald.pipeline.extraction.pdf import PDFExtractor
        extractors.register("pdf", PDFExtractor())
    except ImportError as e:
        logger.warning("PDFExtractor not available: %s", e)

    # --- Optional: Image extractor (Pillow + pytesseract) ---
    try:
        from emerald.pipeline.extraction.image import ImageExtractor
        extractors.register("image", ImageExtractor())
    except ImportError as e:
        logger.warning("ImageExtractor not available: %s", e)

    # --- Optional: Audio extractor (faster-whisper) ---
    try:
        from emerald.pipeline.extraction.audio import AudioExtractor
        extractors.register("audio", AudioExtractor())
    except ImportError as e:
        logger.warning("AudioExtractor not available: %s", e)

    # --- Optional: Video extractor (ffmpeg + faster-whisper) ---
    try:
        from emerald.pipeline.extraction.video import VideoExtractor
        extractors.register("video", VideoExtractor())
    except ImportError as e:
        logger.warning("VideoExtractor not available: %s", e)

    # --- Optional: Code extractor (tree-sitter) ---
    try:
        from emerald.pipeline.extraction.code import CodeExtractor
        extractors.register("code", CodeExtractor())
    except ImportError as e:
        logger.warning("CodeExtractor not available: %s", e)

    from emerald.pipeline.chunking.fact_extractor import get_fact_extractor
    from emerald.pipeline.chunking.text import SemanticTextChunker

    fact_extractor = get_fact_extractor()

    chunkers = ChunkerRegistry()
    chunkers.register("text", SemanticTextChunker(fact_extractor=fact_extractor))
    chunkers.register("conversation", ConversationChunker(fact_extractor=fact_extractor))
    chunkers.register("markdown", MarkdownChunker())

    # --- Optional: PDF chunker (PyMuPDF) ---
    try:
        from emerald.pipeline.chunking.pdf import PDFChunker
        chunkers.register("pdf", PDFChunker())
    except ImportError as e:
        logger.warning("PDFChunker not available: %s", e)

    # --- Optional: Code chunker (tree-sitter) ---
    try:
        from emerald.pipeline.chunking.code import CodeChunker
        chunkers.register("code", CodeChunker())
    except ImportError as e:
        logger.warning("CodeChunker not available: %s", e)

    return MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    from emerald.core.logging import configure_logging
    configure_logging(level=settings.emerald_log_level)

    from sqlalchemy import text

    from emerald.db.neo4j import init_neo4j
    from emerald.db.redis import init_redis
    from emerald.db.session import session_factory

    from emerald.core.tracing import init_tracing
    from emerald.core.tracing_instrumentation import instrument_all

    init_tracing()
    instrument_all()
    await init_neo4j()
    await init_redis()
    async with session_factory.session() as s:
        await s.execute(text("SELECT 1"))

    yield

    from emerald.core.tracing import shutdown_tracing
    from emerald.db.neo4j import close_neo4j
    from emerald.db.redis import close_redis
    shutdown_tracing()
    await close_neo4j()
    await close_redis()
    await session_factory.close()

    # Close embedding provider httpx client to avoid connection leaks
    engine = getattr(app.state, "engine", None)
    if engine:
        from emerald.core.embedder import OpenAIProvider
        embedder = getattr(engine, "embedder", None)
        if isinstance(embedder, OpenAIProvider):
            await embedder.close()


def create_app(engine: MemoryEngine | None = None) -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Emerald",
        version="0.3.0",
        description="Memory and context infrastructure for AI agents",
        docs_url="/docs" if settings.emerald_env == "development" else None,
        lifespan=lifespan,
    )

    # CORS — production should restrict origins via CORS_ALLOWED_ORIGINS env var
    _cors_origins = settings.cors_allowed_origins.strip()
    if _cors_origins and _cors_origins != "*":
        cors_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
    elif _cors_origins == "*":
        cors_origins = ["*"]
        if settings.emerald_env != "development":
            logging.getLogger(__name__).warning(
                "cors_wildcard_in_production: "
                "CORS_ALLOWED_ORIGINS is set to '*'. "
                "Restrict to specific origins in production."
            )
    else:
        # Empty string — no CORS headers (most restrictive, breaks browser access)
        cors_origins = []

    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True if "*" not in cors_origins else False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Store engine in app state so routes can access it
    if engine is not None:
        app.state.engine = engine
    else:
        # Auto-initialize engine with built-in extractors/chunkers
        app.state.engine = _init_engine()

    # ---- Prometheus metrics ----
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app, endpoint="/v1/metrics", include_in_schema=False)

    # ---- OpenTelemetry middleware ----
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:
        # OTel is optional — graceful degradation if dependencies are missing
        logging.getLogger(__name__).warning("otel_instrumentation_failed: %s", exc)

    # ---- Middleware: request ID + response wrapping ----

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        # Inject rate limit headers (A3.4)
        if hasattr(request.state, "rate_limit_limit"):
            response.headers["X-RateLimit-Limit"] = str(request.state.rate_limit_limit)
            response.headers["X-RateLimit-Remaining"] = str(request.state.rate_limit_remaining)
            response.headers["X-RateLimit-Reset"] = str(request.state.rate_limit_reset)

        return response

    # ---- Exception handlers (v2 standardized error format) ----

    def _error_response(
        request: Request,
        error_code: str,
        message: str,
        status_code: int,
        details: list | None = None,
    ) -> JSONResponse:
        """Build a standardized error response."""
        body: dict[str, object] = {
            "error_code": error_code,
            "message": message,
            "details": details or [],
            "request_id": getattr(request.state, "request_id", ""),
        }
        return JSONResponse(status_code=status_code, content=body)

    @app.exception_handler(EmeraldError)
    async def emerald_error_handler(request: Request, exc: EmeraldError):
        from emerald.api.error_codes import get_error_code

        code = type(exc).__name__.upper()
        mapped = get_error_code(code)
        return _error_response(request, mapped.code, str(exc), mapped.http_status)

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return _error_response(
            request,
            "ROUTE_NOT_FOUND",
            f"Route not found: {request.url.path}",
            404,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # Map common HTTP statuses to error codes. Unmapped statuses
        # fall back to INTERNAL_ERROR to avoid generating non-existent
        # codes like "HTTP_418" in error responses.
        status_map: dict[int, str] = {
            400: "VALIDATION_ERROR",
            401: "AUTH_INVALID_KEY",
            403: "AUTH_INSUFFICIENT_PERMISSIONS",
            404: "MEMORY_NOT_FOUND",
            409: "DUPLICATE_RESOURCE",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
            503: "SERVICE_UNAVAILABLE",
        }
        code = status_map.get(exc.status_code, "INTERNAL_ERROR")
        return _error_response(
            request,
            code,
            exc.detail if isinstance(exc.detail, str) else str(exc.detail),
            exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logging.getLogger(__name__).exception("Unhandled exception: %s", exc)
        return _error_response(
            request,
            "INTERNAL_ERROR",
            "An unexpected internal error occurred",
            500,
        )

    # Register V1 routes
    from emerald.api.routes.v1 import (
        conflicts as v1_conflicts,
        connectors as v1_connectors,
        extract as v1_extract,
        keys as v1_keys,
        memories as v1_memories,
        pipelines as v1_pipelines,
        profiles as v1_profiles,
        search as v1_search,
        sessions as v1_sessions,
        sources as v1_sources,
        spaces as v1_spaces,
        system as v1_system,
        upload as v1_upload,
    )

    app.include_router(v1_memories.router, prefix="/v1")
    app.include_router(v1_search.router, prefix="/v1")
    app.include_router(v1_profiles.router, prefix="/v1")
    app.include_router(v1_upload.router, prefix="/v1")
    app.include_router(v1_pipelines.router, prefix="/v1")
    app.include_router(v1_conflicts.router, prefix="/v1")
    app.include_router(v1_extract.router, prefix="/v1")
    app.include_router(v1_sessions.router, prefix="/v1")
    app.include_router(v1_connectors.router, prefix="/v1")
    app.include_router(v1_sources.router, prefix="/v1")
    app.include_router(v1_spaces.router, prefix="/v1")
    app.include_router(v1_system.router, prefix="/v1")
    app.include_router(v1_keys.router, prefix="/v1")

    return app


# Default app (no engine, routes return stubs)
app = create_app()
