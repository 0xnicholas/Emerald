"""Unit tests for ExtractorRegistry."""

import pytest

from emerald.pipeline.extraction.registry import ExtractorRegistry, UnsupportedContentType
from emerald.pipeline.extraction.text import TextExtractor


@pytest.fixture
def registry():
    return ExtractorRegistry()


def test_register_and_get(registry):
    """After registering, get() returns the extractor."""
    extractor = TextExtractor()
    registry.register("text", extractor)
    assert registry.get("text") is extractor


def test_register_overwrites(registry):
    """Registering the same content_type overwrites."""
    e1 = TextExtractor()
    e2 = TextExtractor()
    registry.register("text", e1)
    registry.register("text", e2)
    assert registry.get("text") is e2


def test_get_unsupported_raises(registry):
    """Getting an unregistered type raises UnsupportedContentType."""
    with pytest.raises(UnsupportedContentType):
        registry.get("unknown_type")


@pytest.mark.asyncio
async def test_extract_delegates(registry):
    """extract() calls the registered extractor."""
    registry.register("text", TextExtractor())
    result = await registry.extract("hello", "text")
    assert result.text == "hello"
    assert result.content_type == "text"


@pytest.mark.asyncio
async def test_extract_unsupported_raises(registry):
    """extract() with unregistered type raises."""
    with pytest.raises(UnsupportedContentType):
        await registry.extract("content", "video")


def test_get_error_message_lists_available(registry):
    """Error message lists registered types."""
    registry.register("text", TextExtractor())
    with pytest.raises(UnsupportedContentType) as exc:
        registry.get("pdf")
    assert "text" in str(exc.value)


# ---- MIME normalization (spec issue #1: uploads carry MIME strings) ----

def test_get_normalizes_mime_application_prefix(registry):
    """application/json resolves to the registered json extractor."""
    extractor = TextExtractor()
    registry.register("json", extractor)
    assert registry.get("application/json") is extractor


def test_get_normalizes_mime_text_prefix(registry):
    """text/csv resolves to the registered csv extractor."""
    extractor = TextExtractor()
    registry.register("csv", extractor)
    assert registry.get("text/csv") is extractor


def test_get_normalizes_mime_to_short_type(registry):
    """application/pdf resolves to the registered pdf extractor."""
    from emerald.pipeline.extraction.pdf import PDFExtractor

    extractor = PDFExtractor()
    registry.register("pdf", extractor)
    assert registry.get("application/pdf") is extractor


def test_get_unknown_mime_still_raises(registry):
    """An unknown MIME type still raises UnsupportedContentType."""
    registry.register("text", TextExtractor())
    with pytest.raises(UnsupportedContentType):
        registry.get("application/xml")
