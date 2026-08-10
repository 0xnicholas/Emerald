"""Embedding engine — pluggable embedding providers.

Converts text chunks into vector embeddings for similarity search.
Supports OpenAI, BGE (local), text2vec (local), and custom providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import hashlib
import json

import httpx
import redis.exceptions as redis_exceptions
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

        # Check Redis cache (loop-aware: worker tasks run per-task loops)
        try:
            from emerald.db.redis import ensure_redis_for_loop

            redis = await ensure_redis_for_loop()
        except (RuntimeError, OSError, redis_exceptions.ConnectionError):
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


class SentenceTransformersProvider(EmbeddingProvider):
    """Local embedding via sentence-transformers (all-MiniLM-L6-v2 by default).

    Falls back gracefully if sentence-transformers is not installed.
    """

    DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
    DEFAULT_DIMENSION = 384

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None
        self._dimension = self.DEFAULT_DIMENSION
        # Pre-check that sentence-transformers is installed so callers can
        # catch ImportError early and fall back to MockEmbeddingProvider.
        try:
            import sentence_transformers  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for local embeddings. "
                "Install it with: pip install sentence-transformers>=2.0"
            ) from exc

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self._model_name)
                self._dimension = self._model.get_sentence_embedding_dimension()
            except ImportError as exc:
                raise ImportError(
                    "sentence-transformers is required for local embeddings. "
                    "Install it with: pip install sentence-transformers>=2.0"
                ) from exc
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        # sentence-transformers encode() is CPU-bound; offload to thread pool
        import asyncio

        embeddings = await asyncio.to_thread(model.encode, texts, convert_to_numpy=True)
        return embeddings.tolist()

    def dimension(self) -> int:
        if self._model is not None:
            return self._dimension
        # Lazy-load to determine dimension
        return self._load_model().get_sentence_embedding_dimension()


class FastembedProvider(EmbeddingProvider):
    """Local embedding via fastembed (ONNX runtime, no PyTorch).

    Uses BGE-small-en-v1.5 by default (67 MB, 384 dims).  Falls back
    gracefully if ``fastembed`` is not installed.
    """

    DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
    DEFAULT_DIMENSION = 384

    def __init__(
        self,
        model_name: str | None = None,
        max_length: int = 512,
    ) -> None:
        self._model_name = model_name or self.DEFAULT_MODEL
        self._max_length = max_length
        self._model = None
        self._dimension = self.DEFAULT_DIMENSION
        # Pre-check that fastembed is installed so callers can catch
        # ImportError early and fall back to MockEmbeddingProvider.
        try:
            import fastembed  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "fastembed is required for local embeddings. "
                "Install it with: pip install fastembed"
            ) from exc

    def _load_model(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(
                    model_name=self._model_name,
                    max_length=self._max_length,
                )
                # Determine dimension from the loaded model's config
                desc = self._model._get_model_description(self._model_name)
                if desc is not None and hasattr(desc, "dim"):
                    self._dimension = desc.dim
            except ImportError as exc:
                raise ImportError(
                    "fastembed is required for local embeddings. "
                    "Install it with: pip install fastembed"
                ) from exc
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        import asyncio

        # fastembed.embed() returns a generator of numpy arrays
        def _embed_sync():
            return list(model.embed(texts))

        embeddings = await asyncio.to_thread(_embed_sync)
        return [e.tolist() for e in embeddings]

    def dimension(self) -> int:
        if self._model is not None:
            return self._dimension
        # Lazy-load to get accurate dimension
        self._load_model()
        return self._dimension


class LocalProvider(EmbeddingProvider):
    """Deprecated alias — use FastembedProvider or SentenceTransformersProvider directly."""

    def __init__(self, model_path: str, dimension: int = 1024) -> None:
        self._model_path = model_path
        self._dimension = dimension
        self._provider: FastembedProvider | None = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._provider is None:
            self._provider = FastembedProvider(model_name=self._model_path)
        return await self._provider.embed(texts)

    def dimension(self) -> int:
        if self._provider is not None:
            return self._provider.dimension()
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
            "OpenAI API key missing; attempting local embedding fallback"
        )
        try:
            return FastembedProvider()
        except ImportError:
            logger.warning(
                "fastembed not installed; falling back to MockEmbeddingProvider "
                "(deterministic but NOT semantic). Install with: pip install fastembed"
            )
            # Must match the embeddings.embedding column (Vector(1536)); a
            # mismatched dimension makes every async ingest fail at index.
            return MockEmbeddingProvider(dimension=1536)

    if settings.embedding_provider in (
        EmbeddingProviderEnum.bge,
        EmbeddingProviderEnum.text2vec,
        EmbeddingProviderEnum.local,
    ):
        try:
            return FastembedProvider(model_name=settings.bge_model_path)
        except ImportError:
            logger.warning(
                "fastembed not installed; falling back to MockEmbeddingProvider"
            )
            return MockEmbeddingProvider(dimension=1536)

    raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
