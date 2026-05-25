"""PostgreSQL + pgvector integration tests — verify SessionFactory and VectorStore."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def docker_skipif():
    """Skip entire module if Docker is not available."""
    import shutil

    if shutil.which("docker") is None:
        pytest.skip("Docker not available", allow_module_level=True)


@pytest.fixture
async def pg_session_factory(docker_skipif):
    """Yield a SessionFactory connected to a real PostgreSQL + pgvector container."""
    from testcontainers.postgres import PostgresContainer

    from emerald.db.session import SessionFactory

    container = PostgresContainer(
        "pgvector/pgvector:pg16",
        username="test",
        password="test",
        dbname="test",
    )

    with container:
        url = container.get_connection_url().replace(
            "postgresql://", "postgresql+asyncpg://"
        )
        factory = SessionFactory(url)

        # Create embeddings table + pgvector extension
        from sqlalchemy import text

        async with factory.session() as s:
            await s.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await s.execute(text("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    chunk_id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    embedding VECTOR(3),
                    entity_id TEXT NOT NULL,
                    document_id TEXT,
                    model_name TEXT,
                    dimensions INT
                )
            """))

        yield factory

        await factory.close()


@pytest.mark.asyncio
async def test_session_factory_basic_query(pg_session_factory):
    """SessionFactory can execute a simple query against the container."""
    from sqlalchemy import text

    async with pg_session_factory.session() as s:
        result = await s.execute(text("SELECT 1 AS one"))
        row = result.fetchone()
        assert row.one == 1


@pytest.mark.asyncio
async def test_vector_store_with_real_pg(pg_session_factory):
    """VectorStore.store() and .search() work against real pgvector."""
    import emerald.db.session as session_mod
    from emerald.core.vector import VectorStore

    # Temporarily swap session factory
    original = session_mod.session_factory
    session_mod.session_factory = pg_session_factory

    try:
        store = VectorStore(use_db=True)

        emb = [1.0, 0.0, 0.0]
        await store.store("c1", "hello", emb, entity_id="e1")

        results = await store.search(emb, entity_id="e1", top_k=5)
        assert len(results) == 1
        assert results[0][0] == "c1"
        assert results[0][1] == "hello"
        # Cosine similarity of identical vectors = 1.0
        assert results[0][2] == pytest.approx(1.0, abs=1e-6)
    finally:
        session_mod.session_factory = original


@pytest.mark.asyncio
async def test_vector_store_entity_isolation_with_real_pg(pg_session_factory):
    """VectorStore search respects entity_id when using real pgvector."""
    import emerald.db.session as session_mod
    from emerald.core.vector import VectorStore

    original = session_mod.session_factory
    session_mod.session_factory = pg_session_factory

    try:
        store = VectorStore(use_db=True)

        await store.store("c1", "alice text", [1.0, 0.0, 0.0], entity_id="alice")
        await store.store("c2", "bob text", [1.0, 0.0, 0.0], entity_id="bob")

        alice_results = await store.search([1.0, 0.0, 0.0], entity_id="alice", top_k=5)
        assert len(alice_results) == 1
        assert alice_results[0][1] == "alice text"

        bob_results = await store.search([1.0, 0.0, 0.0], entity_id="bob", top_k=5)
        assert len(bob_results) == 1
        assert bob_results[0][1] == "bob text"
    finally:
        session_mod.session_factory = original
