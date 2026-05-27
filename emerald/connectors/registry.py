"""Connector registry — maps provider names to connector classes."""

from __future__ import annotations

from functools import lru_cache

from emerald.connectors.base import BaseConnector


class ConnectorRegistry:
    """Registry of connector classes, keyed by provider name."""

    def __init__(self) -> None:
        self._connectors: dict[str, type[BaseConnector]] = {}

    def register(self, provider: str, connector_cls: type[BaseConnector]) -> None:
        self._connectors[provider] = connector_cls

    def get(self, provider: str) -> type[BaseConnector]:
        if provider not in self._connectors:
            raise UnsupportedConnectorError(
                f"No connector for provider='{provider}'. "
                f"Available: {list(self._connectors)}"
            )
        return self._connectors[provider]

    def list_providers(self) -> list[str]:
        return list(self._connectors)


class UnsupportedConnectorError(Exception):
    """Raised when no connector is registered for a provider."""


@lru_cache
def get_connector_registry() -> ConnectorRegistry:
    """Get the global connector registry singleton."""
    registry = ConnectorRegistry()
    # Eager-import to trigger registration side-effects.
    from emerald.connectors.github import GitHubConnector
    registry.register("github", GitHubConnector)
    return registry
