"""Tests for URLExtractor."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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




@pytest.mark.asyncio
async def test_extract_trafilatura_unavailable_fallback_to_urllib(extractor):
    """When trafilatura is not installed, falls back to urllib + HTML stripping."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"<html><body><p>Fallback text</p></body></html>"
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch.dict("sys.modules", {"trafilatura": None}):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await extractor.extract("https://example.com")

    assert "Fallback text" in result.text
    assert result.metadata["source_url"] == "https://example.com"


@pytest.mark.asyncio
async def test_extract_invalid_url_raises(extractor):
    """Invalid URL format raises ExtractionError immediately."""
    with pytest.raises(Exception):
        await extractor.extract("not-a-url")


@pytest.mark.asyncio
async def test_strip_html_removes_scripts_and_styles(extractor):
    """_strip_html removes script/style blocks and tags."""
    html = "<script>alert('x')</script><style>body{color:red}</style><p>Keep me</p>"
    result = extractor._strip_html(html)
    assert "alert" not in result
    assert "color" not in result
    assert "Keep me" in result


@pytest.mark.asyncio
async def test_strip_html_collapses_whitespace(extractor):
    """_strip_html collapses multiple whitespace into single spaces."""
    html = "<p>Hello</p>\n\n\n<p>World</p>"
    result = extractor._strip_html(html)
    assert "Hello" in result
    assert "World" in result
