"""Tests for CodeChunker."""

import pytest

from emerald.pipeline.chunking.code import CodeChunker


@pytest.fixture
def chunker():
    return CodeChunker()


def test_chunk_python_function(chunker):
    """Python functions become individual chunks."""
    code = """import os

def hello():
    '''Say hello.'''
    print("hello")

def goodbye():
    print("goodbye")
"""
    chunks = chunker.chunk(code, language="python")
    assert len(chunks) >= 2  # At least imports + functions


def test_chunk_metadata_has_function_name(chunker):
    """Chunk metadata includes function/class names."""
    code = """def add(a, b):
    return a + b
"""
    chunks = chunker.chunk(code, language="python")
    for c in chunks:
        if "def add" in c.text:
            assert "function_name" in c.metadata or "name" in c.metadata


def test_chunk_python_class(chunker):
    """Python classes get their own chunks."""
    code = """class Calculator:
    '''Simple calculator.'''

    def add(self, a, b):
        return a + b

    def sub(self, a, b):
        return a - b
"""
    chunks = chunker.chunk(code, language="python")
    assert len(chunks) >= 1


def test_chunk_content_type_code(chunker):
    """Chunks carry content_type='code'."""
    chunks = chunker.chunk("def foo(): pass", language="python")
    for c in chunks:
        assert c.content_type == "code"


def test_chunk_auto_detect_language(chunker):
    """Language=auto falls back to naive line-based splitting."""
    code = "function hello() {\n  return 'hi'\n}\n\nfunction bye() {\n  return 'bye'\n}"
    chunks = chunker.chunk(code, language="auto")
    assert len(chunks) > 0


def test_chunk_empty(chunker):
    assert chunker.chunk("", language="python") == []
