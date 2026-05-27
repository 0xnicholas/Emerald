"""Embedding engine — pluggable embedding providers.

Converts text chunks into vector embeddings for similarity search.
Supports OpenAI, BGE (local), text2vec (local), and custom providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import hashlib
import json

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from emerald.config import EmbeddingProvider as EmbeddingProviderEnum
from emerald.config import get_settings
from emerald.core.exceptions import (
    AuthenticationError,
    EmbeddingError,
    EmbeddingRetryableError,
)

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
    """OpenAI text-embedding-3 provider with batching and retry."""

    BATCH_SIZE = 2048
    MAX_RETRIES = 3

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self._api_key = api_key
        self._model = model
        self._dimensions_map = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }
        self._client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # Check Redis cache
        try:
            from emerald.db.redis import get_redis_client

            redis = get_redis_client()
        except RuntimeError:
            redis = None

        hashes = [
            hashlib.sha256((t + self._model).encode()).hexdigest() for t in texts
        ]
        cached: list[str | None] = []
        if redis:
            cached = await redis.mget([f"emb:{h}" for h in hashes])
        else:
            cached = [None] * len(texts)

        to_fetch: list[str] = []
        to_fetch_indices: list[int] = []
        results: list[list[float] | None] = [None] * len(texts)

        for i, c in enumerate(cached):
            if c is not None:
                results[i] = json.loads(c)
            else:
                to_fetch.append(texts[i])
                to_fetch_indices.append(i)

        if to_fetch:
            fetched: list[list[float]] = []
            fetched_idx_map: list[int] = []
            for i in range(0, len(to_fetch), self.BATCH_SIZE):
                batch = to_fetch[i : i + self.BATCH_SIZE]
                batch_indices = to_fetch_indices[i : i + self.BATCH_SIZE]
                batch_embeddings = await self._embed_batch_with_retry(batch)
                fetched.extend(batch_embeddings)
                fetched_idx_map.extend(batch_indices)

            if redis:
                pipe = redis.pipeline()
                for idx, vec in zip(fetched_idx_map, fetched):
                    h = hashes[idx]
                    pipe.setex(f"emb:{h}", 7 * 86400, json.dumps(vec))
                await pipe.execute()
            for idx, vec in zip(fetched_idx_map, fetched):
                results[idx] = vec

        return [r for r in results if r is not None]

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        response = await self._client.post(
            "/embeddings",
            json={"input": batch, "model": self._model},
        )

        if response.status_code in (429, 502, 503, 504):
            raise EmbeddingRetryableError(
                f"HTTP {response.status_code}: {response.text}"
            )
        if response.status_code == 401:
            raise AuthenticationError("Invalid OpenAI API key")
        if response.status_code == 400:
            raise ValueError(f"Bad request: {response.text}")

        response.raise_for_status()
        data = response.json()["data"]
        data.sort(key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    _embed_batch_with_retry = retry(
        retry=retry_if_exception_type(EmbeddingRetryableError),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )(_embed_batch)

    def dimension(self) -> int:
        return self._dimensions_map.get(self._model, 1536)

    async def close(self) -> None:
        await self._client.aclose()


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
        if settings.openai_api_key:
            return OpenAIProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_embedding_model,
            )
        logger.warning(
            "OpenAI API key missing; falling back to MockEmbeddingProvider"
        )
        return MockEmbeddingProvider(dimension=1536)

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
