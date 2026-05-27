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


# ---- AST-aware tests (require tree-sitter) ----


def test_ast_chunk_python_function_boundary(chunker):
    """AST mode extracts exact function boundaries."""
    code = """import os
import sys

def hello():
    print("hello")

def world():
    print("world")
"""
    chunks = chunker.chunk(code, language="python")
    # Should have: imports preamble + hello + world
    names = [c.metadata.get("name", "") for c in chunks]
    assert "hello" in names
    assert "world" in names


def test_ast_chunk_preserves_function_body(chunker):
    """Each function chunk contains its full body."""
    code = """def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
"""
    chunks = chunker.chunk(code, language="python")
    func_chunks = [c for c in chunks if c.metadata.get("name") == "factorial"]
    assert len(func_chunks) == 1
    assert "factorial(n - 1)" in func_chunks[0].text


def test_ast_chunk_class_with_methods(chunker):
    """A class with methods is a single chunk."""
    code = """class Calculator:
    def add(self, a, b):
        return a + b

    def sub(self, a, b):
        return a - b
"""
    chunks = chunker.chunk(code, language="python")
    class_chunks = [c for c in chunks if c.metadata.get("name") == "Calculator"]
    assert len(class_chunks) == 1
    assert "def add" in class_chunks[0].text
    assert "def sub" in class_chunks[0].text


def test_ast_chunk_line_numbers(chunker):
    """AST chunks include line_start and line_end metadata."""
    code = """def one():
    pass

def two():
    pass
"""
    chunks = chunker.chunk(code, language="python")
    for c in chunks:
        if c.metadata.get("name") in ("one", "two"):
            assert "line_start" in c.metadata
            assert "line_end" in c.metadata
            assert c.metadata["line_end"] >= c.metadata["line_start"]


def test_ast_chunk_typescript_function(chunker):
    """TypeScript functions are extracted via AST."""
    code = """function greet(name: string): string {
    return `Hello, ${name}`;
}

const farewell = (name: string) => {
    return `Goodbye, ${name}`;
};
"""
    chunks = chunker.chunk(code, language="typescript")
    names = [c.metadata.get("name", "") for c in chunks]
    assert "greet" in names
    # Arrow function may be anonymous depending on AST


def test_ast_chunk_unknown_language_fallback(chunker):
    """Unknown language falls back to heuristic splitting."""
    code = """func hello() {
    print("hi")
}
"""
    chunks = chunker.chunk(code, language="rust")
    assert len(chunks) > 0
    assert all(c.content_type == "code" for c in chunks)
