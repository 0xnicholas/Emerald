"""Hub factory — resolve the configured ConnectionHub implementation.

Swapping connection platforms = one registration here + a new
implementation of ``ConnectionHub`` + config. Nothing else in Emerald
references a concrete hub.
"""

from __future__ import annotations

import structlog

from emerald.config import get_settings
from emerald.sources.hub import ConnectionHub

logger = structlog.get_logger(__name__)

_HUBS: dict[str, type[ConnectionHub]] = {}


def register_hub(name: str, cls: type[ConnectionHub]) -> None:
    """Register a ConnectionHub implementation under a config name."""
    _HUBS[name] = cls


def get_hub(provider: str | None = None) -> ConnectionHub:
    """Return the configured ConnectionHub instance (cached per process)."""
    settings = get_settings()
    name = provider or settings.hub_provider
    if name not in _HUBS:
        raise ValueError(f"Unknown connection hub '{name}'. Registered: {list(_HUBS)}")
    return _HUBS[name].from_settings()


def _register_builtins() -> None:
    try:
        from emerald.sources.totem import TotemHubClient

        register_hub("totem", TotemHubClient)
    except ImportError:  # pragma: no cover - totem has no heavy deps
        logger.warning("totem hub unavailable")


_register_builtins()
