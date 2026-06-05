"""Integration tests for OpenAI embedder. Skipped if no API key."""

import os
import pytest

from emerald.core.embedder import OpenAIProvider


@pytest.fixture
async def real_provider():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or api_key in ("sk-...", "sk-your-key", "sk-test-placeholder", ""):
        pytest.skip("OPENAI_API_KEY not set or is a placeholder")
    # Also skip if key is too short to be a real OpenAI key
    if len(api_key) < 20:
        pytest.skip("OPENAI_API_KEY looks like a placeholder")
    return OpenAIProvider(api_key=api_key)


@pytest.mark.asyncio
async def test_real_openai_embeds_semantically(real_provider):
    """'cat' and 'feline' should have high cosine similarity."""
    import math

    vecs = await real_provider.embed(["cat", "feline", "car"])

    def cos(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb)

    assert cos(vecs[0], vecs[1]) > cos(vecs[0], vecs[2])
