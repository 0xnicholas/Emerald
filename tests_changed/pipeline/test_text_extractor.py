"""Tests for TextExtractor."""

import pytest

from emerald.core.exceptions import EmptyContentError
from emerald.pipeline.extraction.text import TextExtractor


@pytest.fixture
def extractor():
    return TextExtractor()


@pytest.mark.asyncio
async def test_extract_simple_text(extractor):
    """Normal text passes through unchanged."""
    result = await extractor.extract("Hello, world")
    assert result.text == "Hello, world"
    assert result.content_type == "text"


@pytest.mark.asyncio
async def test_extract_trims_whitespace(extractor):
    """Leading/trailing whitespace is stripped."""
    result = await extractor.extract("\n\n   hello   \n")
    assert result.text == "hello"


@pytest.mark.asyncio
async def test_extract_empty_string_raises(extractor):
    """Empty string after cleaning raises EmptyContentError."""
    with pytest.raises(EmptyContentError):
        await extractor.extract("")


@pytest.mark.asyncio
async def test_extract_whitespace_only_raises(extractor):
    """Whitespace-only content raises EmptyContentError."""
    with pytest.raises(EmptyContentError):
        await extractor.extract("   \n\t  \n  ")


@pytest.mark.asyncio
async def test_extract_chinese_text(extractor):
    """Chinese text is preserved as-is."""
    result = await extractor.extract("用户喜欢 TypeScript 和函数式编程")
    assert "TypeScript" in result.text
    assert "函数式编程" in result.text


@pytest.mark.asyncio
async def test_extract_mixed_language(extractor):
    """Mixed CJK + English + emoji preserved."""
    result = await extractor.extract("こんにちは world 🎉 你好")
    assert result.text == "こんにちは world 🎉 你好"


@pytest.mark.asyncio
async def test_supports_text(extractor):
    assert extractor.supports("text") is True


@pytest.mark.asyncio
async def test_does_not_support_other_types(extractor):
    assert extractor.supports("pdf") is False
    assert extractor.supports("image") is False
    assert extractor.supports("code") is False
