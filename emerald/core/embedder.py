"""Embedding engine — pluggable embedding providers.

Converts text chunks into vector embeddings for similarity search.
Supports OpenAI, BGE (local), text2vec (local), and custom providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

from emerald.config import EmbeddingProvider as EmbeddingProviderEnum
from emerald.config import get_settings

logger = structlog.get_logger(__name__)


class EmbeddingProvider(ABC):
    """Abstract interface for embedding providers."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""

    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding vector dimension."""


# ---- Built-in providers ----


class OpenAIProvider(EmbeddingProvider):
    """OpenAI text-embedding-3 provider."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self._api_key = api_key
        self._model = model
        self._dimensions_map = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # TODO: actual OpenAI API call
        raise NotImplementedError("OpenAI embedding not yet implemented")

    def dimension(self) -> int:
        return self._dimensions_map.get(self._model, 1536)


class LocalProvider(EmbeddingProvider):
    """Placeholder for local embedding (BGE, text2vec).

    In production, loads FlagEmbedding or similar locally.
    """

    def __init__(self, model_path: str, dimension: int = 1024) -> None:
        self._model_path = model_path
        self._dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # TODO: actual local model inference
        raise NotImplementedError("Local embedding not yet implemented")

    def dimension(self) -> int:
        return self._dimension


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic mock provider for testing without external API.

    Generates simple hash-based vectors of configurable dimension.
    """

    def __init__(self, dimension: int = 128) -> None:
        self._dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        embeddings = []
        for text in texts:
            h = hashlib.sha256(text.encode()).digest()
            vec = []
            for i in range(self._dimension):
                # Extract float from hash bytes (normalized to [-1, 1])
                byte_pair = h[(i * 2) % len(h)] * 256 + h[(i * 2 + 1) % len(h)]
                val = (byte_pair / 65535.0) * 2.0 - 1.0
                vec.append(val)
            embeddings.append(vec)
        return embeddings

    def dimension(self) -> int:
        return self._dimension


# ---- Factory ----


def get_embedding_provider() -> EmbeddingProvider:
    """Create an embedding provider from application settings."""
    settings = get_settings()

    if settings.embedding_provider == EmbeddingProviderEnum.openai:
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
    if settings.embedding_provider in (
        EmbeddingProviderEnum.bge,
        EmbeddingProviderEnum.text2vec,
        EmbeddingProviderEnum.local,
    ):
        return LocalProvider(
            model_path=settings.bge_model_path,
            dimension=1024,
        )

    raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
