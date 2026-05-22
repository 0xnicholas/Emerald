"""Text chunker — paragraph + sentence boundary splitting with overlap."""

from __future__ import annotations

import re

from emerald.pipeline.chunking.base import BaseChunker, Chunk

# Sentence boundary regex (handles . ! ? in multiple languages)
_SENTENCE_RE = re.compile(r"(?<=[.!?。！？\n])\s+")


class TextChunker(BaseChunker):
    """Splits text by paragraph and sentence boundaries with sliding window overlap.

    Target: ~512 tokens per chunk
    Overlap: ~64 tokens between adjacent chunks
    """

    target_size = 512
    overlap_size = 64
    # Rough heuristic: ~4 chars per token for mixed-language text
    _chars_per_token = 4

    def chunk(self, text: str, **kwargs) -> list[Chunk]:
        if not text.strip():
            return []

        target_chars = self.target_size * self._chars_per_token
        overlap_chars = self.overlap_size * self._chars_per_token
        min_chunk_chars = 100 * self._chars_per_token

        # Step 1: Split by paragraph boundaries
        paragraphs = self._split_paragraphs(text)

        # Step 2: Split long paragraphs by sentence boundaries
        raw_chunks = []
        current_offset = 0
        for para_text, para_start in paragraphs:
            if len(para_text) > target_chars:
                raw_chunks.extend(
                    self._split_sentences(para_text, para_start, target_chars)
                )
            else:
                raw_chunks.append((para_text, para_start))

        # Step 3: Merge undersized adjacent chunks
        merged = self._merge_short_chunks(raw_chunks, min_chunk_chars, target_chars)

        # Step 4: Add overlap from previous chunk
        final_chunks = self._add_overlap(merged, overlap_chars)

        # Step 5: Build Chunk objects with metadata
        return self._build_chunks(final_chunks, text)

    # ---- internal helpers ----

    def _split_paragraphs(self, text: str) -> list[tuple[str, int]]:
        """Split text by paragraph breaks, preserving offsets."""
        paragraphs = []
        pos = 0
        for part in text.split("\n\n"):
            # Find the actual start of this paragraph (skip leading whitespace within the split)
            stripped = part.strip()
            if not stripped:
                pos += len(part) + 2  # +2 for the \n\n separator
                continue
            # Find where the stripped content starts within the current segment
            local_start = part.index(stripped)
            actual_start = pos + local_start
            paragraphs.append((stripped, actual_start))
            pos += len(part) + 2  # advance past this paragraph + separator
        return paragraphs

    def _split_sentences(
        self, text: str, base_offset: int, max_chars: int
    ) -> list[tuple[str, int]]:
        """Split long text into chunks at sentence boundaries."""
        sentences = _SENTENCE_RE.split(text)
        chunks = []
        buffer = ""
        buf_start = base_offset
        pos = 0  # position within `text`

        for sent in sentences:
            if not sent.strip():
                pos += len(sent) + 1  # +1 for the split separator
                continue

            if len(buffer) + len(sent) > max_chars and buffer:
                chunks.append((buffer.strip(), buf_start))
                buffer = sent
                buf_start = base_offset + pos
            else:
                if not buffer:
                    buf_start = base_offset + pos
                buffer += (" " if buffer else "") + sent

            pos += len(sent) + 1  # +1 for separator after sentence

        if buffer.strip():
            chunks.append((buffer.strip(), buf_start))

        return chunks

    def _merge_short_chunks(
        self,
        chunks: list[tuple[str, int]],
        min_chars: int,
        max_chars: int,
    ) -> list[tuple[str, int]]:
        """Merge consecutive chunks that are too small, up to max_chars."""
        if not chunks:
            return []

        merged = []
        buffer = chunks[0][0]
        buf_start = chunks[0][1]

        for chunk_text, chunk_start in chunks[1:]:
            if len(buffer) < min_chars and len(buffer) + len(chunk_text) <= max_chars:
                buffer += "\n\n" + chunk_text
            else:
                merged.append((buffer, buf_start))
                buffer = chunk_text
                buf_start = chunk_start

        merged.append((buffer, buf_start))
        return merged

    def _add_overlap(
        self, chunks: list[tuple[str, int]], overlap_chars: int
    ) -> list[tuple[str, int, str | None]]:
        """Add overlap text from previous chunk. Returns (text, offset, overlap_from_prev)."""
        result = []
        prev_text = ""
        for text, offset in chunks:
            if prev_text and overlap_chars > 0 and len(text) > overlap_chars:
                overlap = prev_text[-overlap_chars:]
                # Check for partial content at boundary
                if len(overlap) >= 10:
                    result.append((text, offset, overlap))
                    prev_text = text
                    continue
            result.append((text, offset, None))
            prev_text = text
        return result

    def _build_chunks(
        self, chunks: list[tuple[str, int, str | None]], source_text: str
    ) -> list[Chunk]:
        """Build final Chunk objects with metadata."""
        results = []
        for i, (text, offset, _overlap) in enumerate(chunks):
            token_count = max(1, len(text) // self._chars_per_token)
            results.append(
                Chunk(
                    text=text,
                    index=i,
                    token_count=token_count,
                    content_type="text",
                    metadata={
                        "char_offset_start": offset,
                        "char_offset_end": offset + len(text),
                    },
                )
            )
        return results
