"""Markdown chunker — heading-hierarchy-aware splitting."""

from __future__ import annotations

import re

from emerald.pipeline.chunking.base import BaseChunker, Chunk

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")


class MarkdownChunker(BaseChunker):
    """Splits Markdown by heading hierarchy (# ## ###).

    Code blocks become independent chunks.
    """

    target_size = 512
    overlap_size = 0
    _chars_per_token = 4

    def chunk(self, text: str, **kwargs) -> list[Chunk]:
        if not text.strip():
            return []

        chunks: list[Chunk] = []
        index = 0

        # Step 1: Split out code blocks
        segments = self._split_code_blocks(text)

        for seg_text, is_code in segments:
            if is_code:
                chunks.append(
                    Chunk(
                        text=seg_text,
                        index=index,
                        token_count=max(1, len(seg_text) // self._chars_per_token),
                        content_type="markdown",
                        metadata={"heading_path": [], "is_code_block": True},
                    )
                )
                index += 1
            else:
                # Step 2: Split non-code text by headings
                for heading_path, section_text in self._split_by_headings(seg_text):
                    chunks.append(
                        Chunk(
                            text=section_text,
                            index=index,
                            token_count=max(1, len(section_text) // self._chars_per_token),
                            content_type="markdown",
                            metadata={
                                "heading_path": heading_path,
                                "is_code_block": False,
                            },
                        )
                    )
                    index += 1

        return chunks

    def _split_code_blocks(self, text: str) -> list[tuple[str, bool]]:
        """Split text alternating non-code / code segments."""
        parts = _CODE_FENCE_RE.split(text)
        matches = _CODE_FENCE_RE.findall(text)

        segments = []
        # Interleave: part0 (non-code), match0 (code), part1 (non-code), match1 (code), ...
        for i, part in enumerate(parts):
            if part.strip():
                segments.append((part.strip(), False))
            if i < len(matches):
                segments.append((matches[i], True))
        return segments

    def _split_by_headings(self, text: str) -> list[tuple[list[str], str]]:
        """Split non-code text by heading hierarchy."""
        heading_matches = list(_HEADING_RE.finditer(text))

        if not heading_matches:
            if text.strip():
                return [([], text.strip())]
            return []

        sections = []
        stack: list[tuple[int, str]] = []

        for i, match in enumerate(heading_matches):
            level = len(match.group(1))
            title = match.group(2)
            start = match.start()
            end = heading_matches[i + 1].start() if i + 1 < len(heading_matches) else len(text)

            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            heading_path = [h[1] for h in stack]

            section_text = text[start:end].strip()
            if section_text:
                sections.append((heading_path, section_text))

        # Preamble before first heading
        if heading_matches and heading_matches[0].start() > 0:
            preamble = text[: heading_matches[0].start()].strip()
            if preamble:
                sections.insert(0, ([], preamble))

        return sections
