"""Tests for provider_model_name (embedder → engine seam).

Regression (2026-08-15 :80 smoke): engine read ``embedder._model`` directly.
OpenAIProvider keeps the model *name string* there, but FastembedProvider's
``_model`` holds the loaded TextEmbedding *object* — engine serialized the
object into ``embeddings.model_name`` / ``fast_lane_chunks.model_name`` and
asyncpg rejected the bind parameter (DataError), failing every vector write
under fastembed. The helper only ever returns a str.
"""

from __future__ import annotations

from emerald.core.embedder import (
    OpenAIProvider,
    provider_model_name,
)


class _ObjectModelProvider:
    """Stands in for FastembedProvider (fastembed not installed in dev env)."""

    _model_name = "BAAI/bge-small-zh-v1.5"
    _model = object()  # loaded model object — must never leak


class _StringModelProvider:
    _model = "text-embedding-3-small"


class _BareProvider:
    """No model attrs at all (e.g. Mock)."""


def test_object_valued_model_attr_never_leaks():
    assert provider_model_name(_ObjectModelProvider()) == "BAAI/bge-small-zh-v1.5"


def test_string_model_attr_returned():
    assert provider_model_name(_StringModelProvider()) == "text-embedding-3-small"


def test_bare_provider_falls_back_to_unknown():
    assert provider_model_name(_BareProvider()) == "unknown"


def test_openai_provider_real():
    provider = OpenAIProvider(api_key="sk-test", model="text-embedding-3-small")
    assert provider_model_name(provider) == "text-embedding-3-small"


def test_empty_string_is_skipped():
    class _Empty:
        model_name = ""
        _model_name = "fallback-name"

    assert provider_model_name(_Empty()) == "fallback-name"
