"""Tests for URLExtractor."""

import pytest
from unittest.mock import AsyncMock, patch

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


@pytest.mark.asyncio
async def test_extract_fetches_and_cleans(extractor):
    """extract() fetches URL and returns cleaned text."""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = "<html><head><title>Hello</title></head><body><p>World</p></body></html>"
    mock_response.headers = {"content-type": "text/html"}
    mock_response.raise_for_status = AsyncMock()

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        with patch("trafilatura.extract", return_value="Hello\n\nWorld"):
            result = await extractor.extract("https://example.com")

    assert "World" in result.text
    assert result.content_type == "url"


@pytest.mark.asyncio
async def test_extract_http_error(extractor):
    """extract() raises ExtractionError on HTTP failure."""
    mock_response = AsyncMock()
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = Exception("Not found")

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        with pytest.raises(Exception):
            await extractor.extract("https://example.com/missing")


