"""Code chunker — structural code splitting.

Uses tree-sitter AST when available; falls back to blank-line-based splitting
for environments without tree-sitter installed.
"""

from __future__ import annotations

import re

from emerald.pipeline.chunking.base import BaseChunker, Chunk

# Regex to identify function/class definitions
_FUNC_RE = re.compile(r"^\s*(def |class |async def |function |func |fn )", re.MULTILINE)


class CodeChunker(BaseChunker):
    """Splits code by logical units (functions, classes, methods).

    When tree-sitter is available: AST-aware splitting.
    Fallback: blank-line heuristic splitting with function detection.
    """

    target_size = 0  # Structure-driven, not size-driven
    overlap_size = 0

    def chunk(self, text: str, **kwargs) -> list[Chunk]:
        language = kwargs.get("language", "auto")

        if not text.strip():
            return []

        # Try tree-sitter first
        if language != "auto":
            try:
                return self._chunk_ast(text, language)
            except Exception:
                pass

        # Fallback: blank-line-based splitting
        return self._chunk_fallback(text)

    def _chunk_ast(self, text: str, language: str) -> list[Chunk]:
        """AST-aware chunking via tree-sitter (attempted, falls back on error)."""
        import importlib

        try:
            importlib.import_module("tree_sitter")
        except ImportError:
            return self._chunk_fallback(text)

        # TODO: tree-sitter AST parsing + logical unit extraction
        return self._chunk_fallback(text)

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
