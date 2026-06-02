"""Start Emerald API with Docker-backed persistent storage."""

from __future__ import annotations

import asyncio
import os
import sys

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from emerald.api.dependencies import api_key_auth, rate_limit, require_write_permission
from emerald.api.routes.v1 import memories, profiles, search, system
from emerald.config import Settings
from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.db.neo4j import init_neo4j, close_neo4j
from emerald.db.redis import init_redis, close_redis
from emerald.db.session import session_factory
from emerald.pipeline.chunking.conversation import ConversationChunker
from emerald.pipeline.chunking.markdown import MarkdownChunker
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor

# Override settings for Docker ports
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://emerald:emerald_dev@localhost:5433/emerald")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_PASSWORD", "emerald_dev")
os.environ.setdefault("REDIS_URL", "redis://:emerald_dev@localhost:6380/0")
os.environ.setdefault("EMERALD_ENV", "development")


async def init_db():
    """Initialize all database connections."""
    from sqlalchemy import text
    await init_neo4j()
    await init_redis()
    async with session_factory.session() as s:
        await s.execute(text("SELECT 1"))
    print("[init] Neo4j + Redis + PostgreSQL connected")


async def close_db():
    """Close all database connections."""
    await close_neo4j()
    await close_redis()
    await session_factory.close()
    print("[shutdown] All connections closed")


def create_persistent_app() -> FastAPI:
    """Create FastAPI app with persistent storage."""
    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    extractors.register("conversation", TextExtractor())
    extractors.register("markdown", TextExtractor())

    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    chunkers.register("conversation", ConversationChunker())
    chunkers.register("markdown", MarkdownChunker())

    engine = MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=MockEmbeddingProvider(dimension=128),
        graph=GraphStore(use_db=True),
        vector=VectorStore(use_db=True),
        use_db=True,
    )

    app = FastAPI(title="Emerald Persistent", version="0.2.0")

    @app.on_event("startup")
    async def startup():
        await init_db()

    @app.on_event("shutdown")
    async def shutdown():
        await close_db()

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        import uuid as _uuid
        request.state.request_id = str(_uuid.uuid4())[:8]
        response = await call_next(request)
        return response

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": f"{request.url.path}"}},
        )

    app.include_router(memories.router, prefix="/v1")
    app.include_router(search.router, prefix="/v1")
    app.include_router(profiles.router, prefix="/v1")
    app.include_router(system.router, prefix="/v1")

    app.state.engine = engine

    # Bypass auth for testing
    async def bypass_auth(request: Request):
        return "test_user"

    async def bypass_write(request: Request):
        return "authorized"

    async def bypass_rate(request: Request):
        return None

    app.dependency_overrides[api_key_auth] = bypass_auth
    app.dependency_overrides[require_write_permission] = bypass_write
    app.dependency_overrides[rate_limit] = bypass_rate

    return app


app = create_persistent_app()

if __name__ == "__main__":
    print("=" * 60)
    print("Emerald Persistent Server (Docker-backed)")
    print("URL:    http://localhost:8000")
    print("APIKey: any string (auth bypassed)")
    print("Data:   PostgreSQL:5433 + Neo4j:7687 + Redis:6380")
    print("Ctrl+C to stop")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
