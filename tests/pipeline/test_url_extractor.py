"""Tests for URLExtractor."""

import pytest

from emerald.pipeline.extraction.url import URLExtractor


@pytest.fixture
def extractor():
    return URLExtractor()


@pytest.mark.asyncio
async def test_supports_url(extractor):
    assert extractor.supports("url") is True
    assert extractor.supports("text") is False


@pytest.mark.asyncio
async def test_validate_valid_url(extractor):
    """Valid HTTP URL passes validation."""
    # Validation doesn't fetch, just checks format
    assert extractor._is_valid_url("https://example.com/page") is True
    assert extractor._is_valid_url("http://example.com") is True


@pytest.mark.asyncio
async def test_validate_invalid_url(extractor):
    """Invalid URL format raises ExtractionError."""
    assert extractor._is_valid_url("not-a-url") is False
    assert extractor._is_valid_url("") is False
    assert extractor._is_valid_url("ftp://example.com") is False  # Only http/https
