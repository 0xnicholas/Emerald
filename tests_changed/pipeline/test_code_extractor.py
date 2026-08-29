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


@pytest.mark.asyncio
async def test_extract_auto_detect_go(extractor):
    """Auto-detect recognizes Go code."""
    code = "package main\n\nimport (\"fmt\")\n"
    result = await extractor.extract(code, language="auto")
    assert result.metadata["language"] == "go"


@pytest.mark.asyncio
async def test_extract_auto_detect_rust(extractor):
    """Auto-detect recognizes Rust code."""
    code = "fn main() {\n    println!(\"hello\");\n}\n"
    result = await extractor.extract(code, language="auto")
    assert result.metadata["language"] == "rust"


@pytest.mark.asyncio
async def test_extract_auto_detect_python_import(extractor):
    """Auto-detect recognizes Python import style."""
    code = "import os from pathlib\n"
    result = await extractor.extract(code, language="auto")
    assert result.metadata["language"] == "python"


@pytest.mark.asyncio
async def test_extract_auto_detect_javascript(extractor):
    """Auto-detect recognizes JavaScript const style."""
    code = "const x = 1;\nfunction hello() {}\n"
    result = await extractor.extract(code, language="auto")
    assert result.metadata["language"] == "javascript"


@pytest.mark.asyncio
async def test_extract_auto_detect_unknown(extractor):
    """Auto-detect falls back to unknown for unrecognized code."""
    code = "// some random text\nfoo bar baz\n"
    result = await extractor.extract(code, language="auto")
    assert result.metadata["language"] == "unknown"


@pytest.mark.asyncio
async def test_extract_normalizes_excessive_blank_lines(extractor):
    """More than 2 consecutive blank lines are collapsed to 2."""
    code = "line1\n\n\n\n\nline2\n"
    result = await extractor.extract(code, language="python")
    assert "\n\n\n\n" not in result.text
