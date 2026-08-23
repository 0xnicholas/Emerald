"""Generate the public OpenAPI 3.0 spec from the running FastAPI app.

Single source of truth: the FastAPI app itself. Running this script
re-generates ``docs/api/openapi.yaml`` so the published spec never
drifts from the actual code (P0.2 / P3 fix).

Usage:
    .venv/bin/python scripts/generate_openapi.py
    .venv/bin/python scripts/generate_openapi.py --check  # CI: exit 1 if drift
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Allow running from repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from emerald.api.app import create_app  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "docs" / "api" / "openapi.yaml"

# Server / contact / tag metadata that FastAPI's auto-spec doesn't
# produce. We layer it on top of the auto-generated schema so the
# published file remains human-curated where it matters.
EXTRA_INFO = {
    "contact": {"name": "Emerald", "url": "https://emerald.ai"},
    "license": {"name": "MIT"},
    "servers": [
        {"url": "http://localhost:8000/v1", "description": "Local development"},
        {"url": "https://api.emerald.ai/v1", "description": "Production"},
    ],
    "tags": [
        {"name": "Memories", "description": "Ingest, retrieve and manage memories (incl. batch add and validation)"},
        {"name": "Search", "description": "Hybrid search across memory and RAG, with multi-hop reasoning and entity-centric retrieval"},
        {"name": "Profiles", "description": "Entity profiles (static + dynamic facts), profile config and MEMORY.md export"},
        {"name": "Upload", "description": "File upload and processing pipeline"},
        {"name": "Pipelines", "description": "Ingestion pipeline status"},
        {"name": "Spaces", "description": "User-explicit organization views (ADR-0002)"},
        {"name": "Sources", "description": "External data source bindings via the connection hub (ADR-0004)"},
        {"name": "Conflicts", "description": "Contradiction review and resolution (admin extension)"},
        {"name": "Extract", "description": "URL content extraction"},
        {"name": "Sessions", "description": "Session tokens (admin extension)"},
        {"name": "Keys", "description": "API key management"},
        {"name": "System", "description": "Health check and memory graph visualization"},
    ],
    "x-content-types": {
        "supported": [
            "text", "conversation", "url", "pdf", "image",
            "audio", "video", "code", "markdown",
        ],
    },
}

SECURITY_SCHEMES = {
    "ApiKeyAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "em_<32-hex>",
        "description": (
            "All endpoints require a Bearer API key in the `Authorization` "
            "header. Keys are prefixed with `em_` and scoped to a single "
            "entity. The server stores only the SHA-256 hash."
        ),
    }
}


def build_spec() -> dict:
    """Return the merged OpenAPI 3.0 spec as a dict."""
    app = create_app()
    schema = app.openapi()

    # Layer extra metadata.
    schema["info"].update({k: v for k, v in EXTRA_INFO.items() if k in {"contact", "license"}})
    schema["servers"] = EXTRA_INFO["servers"]
    schema["tags"] = EXTRA_INFO["tags"]
    schema.setdefault("x-emerald-meta", {})["content_types"] = EXTRA_INFO["x-content-types"]

    # Add security definition.
    schema.setdefault("components", {}).setdefault("securitySchemes", {}).update(
        SECURITY_SCHEMES
    )
    # Apply global security requirement (every endpoint requires a key,
    # except those that explicitly override with `security: []`).
    schema.setdefault("security", [{"ApiKeyAuth": []}])

    # The /metrics endpoint is intentionally hidden from the schema by
    # Prometheus's `include_in_schema=False`. If a future FastAPI version
    # leaks it, strip it here so the public spec stays clean.
    schema["paths"].pop("/v1/metrics", None)

    return schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if generated spec differs from on-disk file (CI mode).",
    )
    args = parser.parse_args()

    spec = build_spec()

    # Custom YAML representer to preserve key order and avoid aliases.
    yaml_text = yaml.safe_dump(
        spec,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )

    if args.check:
        existing = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
        if existing.strip() == yaml_text.strip():
            print(f"OK: {OUTPUT_PATH} is up to date.")
            return 0
        print(f"DRIFT: {OUTPUT_PATH} differs from generated spec.")
        print("Run: python scripts/generate_openapi.py")
        return 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(yaml_text)
    path_count = len(spec.get("paths", {}))
    op_count = sum(
        1
        for ops in spec.get("paths", {}).values()
        for m in ops
        if m in {"get", "post", "put", "delete", "patch"}
    )
    print(
        f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} "
        f"({path_count} paths, {op_count} operations)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
