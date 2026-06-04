"""Forbidden exposure tests — verify SDK and API don't leak internals.

AGENTS.md: "SDK 不得暴露内部图谱操作。公共 API 仅限 add/search/profile/upload。"
AGENTS.md: "禁止 API 泄漏。SDK 不得暴露内部图谱操作。"
"""

import inspect

from emerald.api.app import create_app
from emerald.sdk import EmeraldClient

# ---- SDK: no internal exposure ----

INTERNAL_METHODS = [
    "create_memory",
    "update_is_latest",
    "classify_relation",
    "create_update_relation",
    "create_extends_relation",
    "create_derives_relation",
    "infer",
    "list_latest_memories",
    "get_memory_raw",
    "store_embedding",
]


def test_sdk_has_no_graph_store_methods():
    """SDK client does not expose GraphStore methods."""
    public = {name for name, _ in inspect.getmembers(EmeraldClient, predicate=inspect.isfunction)
              if not name.startswith("_")}
    for method in INTERNAL_METHODS:
        assert method not in public, f"SDK must not expose '{method}'"


def test_sdk_only_exposes_allowed_methods():
    """SDK exposes only the 4 core + utility methods."""
    allowed = {"add", "search", "profile", "upload", "health", "pipeline_status", "get_memory", "close"}
    public = {name for name, _ in inspect.getmembers(EmeraldClient, predicate=inspect.isfunction)
              if not name.startswith("_")}
    unexpected = public - allowed
    assert not unexpected, f"SDK exposes unexpected methods: {unexpected}"


# ---- API: no internal graph endpoints ----

FORBIDDEN_PATHS = [
    "/v1/graph",
    "/v1/relationships",
    "/v1/internal",
    "/v1/admin",
    "/v1/neo4j",
    "/v1/vector",
]


def test_api_has_no_internal_routes():
    """API does not expose internal graph/vector routes."""
    app = create_app()
    routes = {route.path for route in app.routes}

    for forbidden in FORBIDDEN_PATHS:
        assert forbidden not in routes, f"API must not expose '{forbidden}'"
        # Also check prefix match
        for route in routes:
            assert not route.startswith(forbidden), (
                f"API must not expose route starting with '{forbidden}': {route}"
            )


def test_api_routes_under_version_prefix():
    """All API routes are under /v1/ or /v2/ (or are system routes: openapi, docs).

    Verifies no internal paths like /admin, /neo4j, /graph leak into the API.
    """
    app = create_app()
    for route in app.routes:
        path = route.path
        # Allow root, openapi, docs, and versioned API paths
        if path in ("/", "/openapi.json"):
            continue
        if path.startswith("/docs") or path.startswith("/redoc"):
            continue
        if path.startswith("/v1/") or path.startswith("/v2/"):
            continue
        raise AssertionError(f"Unexpected route outside /v1/ and /v2/: {path}")
