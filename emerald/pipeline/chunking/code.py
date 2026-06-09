"""Code chunker — structural code splitting via tree-sitter AST.

Uses tree-sitter AST when available; falls back to blank-line-based splitting
for environments without tree-sitter or the required language grammar installed.
"""

from __future__ import annotations

import re
from typing import Callable

from emerald.pipeline.chunking.base import BaseChunker, Chunk

# Regex to identify function/class definitions (fallback heuristic)
_FUNC_RE = re.compile(r"^\s*(def |class |async def |function |func |fn )", re.MULTILINE)

# Mapping: file extension / language hint → tree-sitter language module name
_LANGUAGE_MODULES: dict[str, str] = {
    "python": "tree_sitter_python",
    "py": "tree_sitter_python",
    "typescript": "tree_sitter_typescript",
    "ts": "tree_sitter_typescript",
    "javascript": "tree_sitter_typescript",
    "js": "tree_sitter_typescript",
    "tsx": "tree_sitter_typescript",
    "jsx": "tree_sitter_typescript",
}

# AST node types that represent logical units
_CHUNK_NODE_TYPES: set[str] = {
    "function_definition",
    "class_definition",
    "function_declaration",
    "class_declaration",
    "method_definition",
    "arrow_function",
}


def _get_language(language: str) -> object | None:
    """Attempt to load a tree-sitter Language for the given identifier.

    Returns None if the language module is not installed.
    """
    module_name = _LANGUAGE_MODULES.get(language.lower())
    if not module_name:
        return None

    try:
        import importlib

        mod = importlib.import_module(module_name)
        from tree_sitter import Language

        return Language(mod.language())
    except (ImportError, AttributeError):
        return None


class CodeChunker(BaseChunker):
    """Splits code by logical units (functions, classes, methods).

    When tree-sitter is available: AST-aware splitting.
    Fallback: blank-line heuristic splitting with function detection.
    """

    target_size = 0  # Structure-driven, not size-driven
    overlap_size = 0

    async def chunk(self, text: str, **kwargs) -> list[Chunk]:
        language = kwargs.get("language", "auto")

        if not text.strip():
            return []

        # Try tree-sitter first when language is known
        if language != "auto":
            try:
                return self._chunk_ast(text, language)
            except Exception:
                pass

        # Fallback: blank-line-based splitting
        return self._chunk_fallback(text)

    def _chunk_ast(self, text: str, language: str) -> list[Chunk]:
        """AST-aware chunking via tree-sitter."""
        from tree_sitter import Parser

        lang = _get_language(language)
        if lang is None:
            return self._chunk_fallback(text)

        parser = Parser(lang)
        tree = parser.parse(text.encode("utf-8"))
        root = tree.root_node

        chunks: list[Chunk] = []
        # Collect top-level logical units + module-level preamble
        preamble_lines: list[str] = []
        last_end_line = 0

        for child in root.children:
            if child.type in _CHUNK_NODE_TYPES:
                # Flush any preamble before this unit
                if child.start_point.row > last_end_line:
                    preamble = self._extract_lines(text, last_end_line, child.start_point.row)
                    if preamble.strip():
                        chunks.append(
                            self._make_chunk(
                                preamble,
                                len(chunks),
                                name="module",
                                line_start=last_end_line + 1,
                                line_end=child.start_point.row,
                            )
                        )

                unit_text = self._extract_lines(
                    text, child.start_point.row, child.end_point.row + 1
                )
                name = self._extract_node_name(child)
                chunks.append(
                    self._make_chunk(
                        unit_text,
                        len(chunks),
                        name=name,
                        line_start=child.start_point.row + 1,
                        line_end=child.end_point.row,
                    )
                )
                last_end_line = child.end_point.row

        # Trailing module-level code
        total_lines = text.count("\n") + 1
        if last_end_line < total_lines:
            trailing = self._extract_lines(text, last_end_line, total_lines)
            if trailing.strip():
                chunks.append(
                    self._make_chunk(
                        trailing,
                        len(chunks),
                        name="module",
                        line_start=last_end_line + 1,
                        line_end=total_lines,
                    )
                )

        return chunks if chunks else self._chunk_fallback(text)

    @staticmethod
    def _extract_lines(text: str, start_row: int, end_row: int) -> str:
        """Extract lines [start_row, end_row) from text (0-indexed rows)."""
        lines = text.split("\n")
        return "\n".join(lines[start_row:end_row])

    @staticmethod
    def _extract_node_name(node: object) -> str:
        """Extract the identifier name from a function/class AST node."""
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
        return "anonymous"

    @staticmethod
    def _make_chunk(
        text: str,
        index: int,
        name: str,
        line_start: int = 0,
        line_end: int = 0,
    ) -> Chunk:
        stripped = text.rstrip()
        return Chunk(
            text=stripped,
            index=index,
            token_count=max(1, len(stripped) // 4),
            content_type="code",
            metadata={
                "name": name,
                "function_name": name,
                "line_count": line_end - line_start + 1 if line_end >= line_start else 1,
                "line_start": line_start,
                "line_end": line_end,
            },
        )

    def _chunk_fallback(self, text: str) -> list[Chunk]:
        """Fallback: split by blank lines, keeping related code together."""
        # Split on double newlines (blank line separators)
        blocks = re.split(r"\n\s*\n", text)
        chunks = []

        for i, block in enumerate(blocks):
            stripped = block.strip()
            if not stripped:
                continue

            # Detect function/class name from first line
            name = "module"
            match = _FUNC_RE.search(stripped)
            if match:
                name_line = stripped.split("\n")[0].strip()
                # Extract name after def/class/function
                name = name_line.split("(")[0].split()[-1].rstrip(":")
                if not name:
                    name = name_line[:40]

            lines = stripped.split("\n")
            line_count = len(lines)

            chunks.append(
                Chunk(
                    text=stripped,
                    index=i,
                    token_count=max(1, len(stripped) // 4),
                    content_type="code",
                    metadata={
                        "name": name,
                        "function_name": name,
                        "line_count": line_count,
                    },
                )
            )

        return chunks
