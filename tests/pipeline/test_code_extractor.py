"""Tests for CodeExtractor."""

import pytest

from emerald.pipeline.extraction.code import CodeExtractor


@pytest.fixture
def extractor():
    return CodeExtractor()


@pytest.mark.asyncio
async def test_supports_code(extractor):
    assert extractor.supports("code") is True
    assert extractor.supports("text") is False


@pytest.mark.asyncio
async def test_extract_python(extractor):
    """Python code is extracted with structure preserved."""
    code = "def hello():\n    print('hi')\n"
    result = await extractor.extract(code, language="python")
    assert "hello" in result.text
    assert result.content_type == "code"


@pytest.mark.asyncio
async def test_extract_with_auto_language(extractor):
    """Auto-detect falls back to pass-through."""
    code = "function hello() {\n  return 'hi'\n}"
    result = await extractor.extract(code, language="auto")
    assert len(result.text) > 0


@pytest.mark.asyncio
async def test_extract_empty(extractor):
    """Empty code returns empty."""
    result = await extractor.extract("   ", language="python")
    assert result.text == ""
