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
    from emerald.pipeline.chunking.text import TextChunker
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

    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    chunkers.register("conversation", ConversationChunker())
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

    await init_neo4j()
    await init_redis()
    async with session_factory.session() as s:
        await s.execute(text("SELECT 1"))

    yield

    from emerald.db.neo4j import close_neo4j
    from emerald.db.redis import close_redis
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
        version="0.2.0",
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
    else:
        # Auto-initialize engine with built-in extractors/chunkers
        app.state.engine = _init_engine()

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
        connectors,
        memories,
        pipelines,
        profiles,
        search,
        system,
        upload,
    )

    app.include_router(memories.router, prefix="/v1")
    app.include_router(search.router, prefix="/v1")
    app.include_router(profiles.router, prefix="/v1")
    app.include_router(upload.router, prefix="/v1")
    app.include_router(pipelines.router, prefix="/v1")
    app.include_router(connectors.router, prefix="/v1")
    app.include_router(system.router, prefix="/v1")

    return app


# Default app (no engine, routes return stubs)
app = create_app()
