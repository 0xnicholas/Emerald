"""Neo4j driver singleton."""

from __future__ import annotations

from neo4j import AsyncGraphDatabase, AsyncDriver

from emerald.config import get_settings


class Neo4jDriver:
    """Async Neo4j driver wrapper."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri, auth=(user, password)
        )

    @property
    def driver(self) -> AsyncDriver:
        return self._driver

    async def verify(self) -> None:
        await self._driver.verify_connectivity()

    async def close(self) -> None:
        await self._driver.close()


settings = get_settings()
neo4j_driver = Neo4jDriver(
    uri=settings.neo4j_uri,
    user=settings.neo4j_user,
    password=settings.neo4j_password,
)


def get_neo4j() -> Neo4jDriver:
    """FastAPI dependency for Neo4j driver."""
    return neo4j_driver
