"""CLI-level tests for benchmark embedding-model selection (issue #18, T2).

Covers acceptance criteria 1–2 without network:
- explicit ``--embedding-model`` maps to the right provider + dimension
  (3-large → 3072)
- no ``--embedding-model`` keeps the current behavior (provider factory)

Only ``_make_engine`` / provider selection is exercised; the paid, non-
deterministic real API runs stay manual (per spec).
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ is not a package; add it to the import path like the CI jobs do.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_benchmarks as rb  # noqa: E402


def _fake_openai_settings(monkeypatch):
    """Point the script at Settings with an API key (no .env needed)."""
    from emerald.config import Settings

    monkeypatch.setattr(
        "emerald.config.get_settings", lambda: Settings(openai_api_key="sk-test")
    )


def test_make_engine_explicit_large_model_dimension_3072(monkeypatch):
    """text-embedding-3-large → provider dimension 3072 (no code change)."""
    _fake_openai_settings(monkeypatch)
    config = rb.BenchConfig(
        use_real_embeddings=True, embedding_model="text-embedding-3-large"
    )
    engine = rb._make_engine(config)
    assert engine.embedder.dimension() == 3072


def test_make_engine_explicit_small_model_dimension_1536(monkeypatch):
    """text-embedding-3-small → provider dimension 1536."""
    _fake_openai_settings(monkeypatch)
    config = rb.BenchConfig(
        use_real_embeddings=True, embedding_model="text-embedding-3-small"
    )
    engine = rb._make_engine(config)
    assert engine.embedder.dimension() == 1536


def test_make_engine_explicit_bge_m3_dimension_1024(monkeypatch):
    """bge-m3 (SiliconFlow gateway) → provider dimension 1024.

    Gateway model support added 2026-08-11 for deployments that cannot
    reach api.openai.com; the explicit-model path must honor
    ``settings.openai_base_url``.
    """
    _fake_openai_settings(monkeypatch)
    config = rb.BenchConfig(
        use_real_embeddings=True, embedding_model="bge-m3"
    )
    engine = rb._make_engine(config)
    assert engine.embedder.dimension() == 1024
    assert str(engine.embedder._client.base_url).rstrip("/") == "https://api.openai.com/v1"


def test_make_engine_explicit_model_uses_openai_base_url_setting(monkeypatch):
    """Explicit-model path respects settings.openai_base_url (gateway)."""
    from emerald.config import Settings

    monkeypatch.setattr(
        "emerald.config.get_settings",
        lambda: Settings(
            openai_api_key="sk-test",
            openai_base_url="https://api.siliconflow.cn/v1",
        ),
    )
    config = rb.BenchConfig(
        use_real_embeddings=True, embedding_model="bge-m3"
    )
    engine = rb._make_engine(config)
    assert str(engine.embedder._client.base_url).rstrip("/") == "https://api.siliconflow.cn/v1"


def test_make_engine_default_uses_provider_factory(monkeypatch):
    """No --embedding-model → get_embedding_provider() (current behavior)."""
    called = {"factory": False}

    def fake_factory():
        called["factory"] = True
        return rb.MockEmbeddingProvider(dimension=1536)

    monkeypatch.setattr(rb, "get_embedding_provider", fake_factory)
    config = rb.BenchConfig(use_real_embeddings=True)
    engine = rb._make_engine(config)
    assert called["factory"]
    assert engine.embedder.dimension() == 1536


def test_make_engine_mock_mode_uses_mock_embedder():
    """Mock mode is untouched by embedding-model selection."""
    config = rb.BenchConfig(
        use_real_embeddings=False, embedding_model="text-embedding-3-large"
    )
    engine = rb._make_engine(config)
    assert isinstance(engine.embedder, rb.MockEmbeddingProvider)
