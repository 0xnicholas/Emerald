"""Start Emerald API in in-memory mode for Pandaria integration testing.

No database required. All data is stored in-process and lost on exit.
"""

import uvicorn
from emerald.api.app import create_app
from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.conversation import ConversationChunker
from emerald.pipeline.chunking.markdown import MarkdownChunker
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor


def main():
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
        graph=GraphStore(use_db=False),
        vector=VectorStore(use_db=False),
        use_db=False,
    )

    from contextlib import asynccontextmanager
    from fastapi import FastAPI, Request
    from emerald.api.dependencies import api_key_auth, require_write_permission, rate_limit

    # Build app manually to skip database lifespan (neo4j/postgres/redis)
    app = FastAPI(title="Emerald Test", version="0.2.0")

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        import uuid as _uuid
        request.state.request_id = str(_uuid.uuid4())[:8]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    from fastapi.responses import JSONResponse
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND", "message": f"{request.url.path}"}})

    from emerald.api.routes.v1 import memories, search, profiles, system
    app.include_router(memories.router, prefix="/v1")
    app.include_router(search.router, prefix="/v1")
    app.include_router(profiles.router, prefix="/v1")
    app.include_router(system.router, prefix="/v1")

    app.state.engine = engine

    async def bypass_auth(request: Request):
        return "test_user"

    async def bypass_write(request: Request):
        return "authorized"

    async def bypass_rate(request: Request):
        return None

    app.dependency_overrides[api_key_auth] = bypass_auth
    app.dependency_overrides[require_write_permission] = bypass_write
    app.dependency_overrides[rate_limit] = bypass_rate

    print("=" * 60)
    print("Emerald Test Server (in-memory mode)")
    print("URL:    http://localhost:9999")
    print("APIKey: any string (auth bypassed)")
    print("Ctrl+C to stop")
    print("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=9999, log_level="warning")


if __name__ == "__main__":
    main()
