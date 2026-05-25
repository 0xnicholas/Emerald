"""Neo4j async driver lifecycle."""

from __future__ import annotations

from neo4j import AsyncDriver, AsyncGraphDatabase

from emerald.config import get_settings

_driver: AsyncDriver | None = None


async def init_neo4j() -> None:
    """Initialize the Neo4j async driver. Called in FastAPI lifespan."""
    global _driver
    settings = get_settings()
    _driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    await _driver.verify_connectivity()


async def close_neo4j() -> None:
    """Close the Neo4j async driver."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


def get_neo4j_driver() -> AsyncDriver:
    """Return the initialized Neo4j driver.

    Raises RuntimeError if init_neo4j() has not been called.
    """
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialized. Call init_neo4j() first.")
    return _driver
