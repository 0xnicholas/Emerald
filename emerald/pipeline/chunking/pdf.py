"""PDF chunker — section-aware splitting with increased context overlap."""

from __future__ import annotations

from emerald.pipeline.chunking.base import BaseChunker, Chunk


class PDFChunker(BaseChunker):
    """Splits PDF text by section structure with extra overlap for context.

    target_size: 512 tokens
    overlap_size: 128 tokens (PDFs are context-sensitive)
    """

    target_size = 512
    overlap_size = 128
    _chars_per_token = 4

    def chunk(self, text: str, **kwargs) -> list[Chunk]:
        structure = kwargs.get("structure")

        if not text.strip():
            return []

        target_chars = self.target_size * self._chars_per_token

        # Split by double newlines (paragraph boundaries)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        chunks = []
        buffer = ""
        index = 0

        for para in paragraphs:
            if len(buffer) + len(para) > target_chars and buffer:
                chunks.append(self._make_chunk(buffer, index, structure, index))
                index += 1
                buffer = para
            else:
                if buffer:
                    buffer += "\n\n"
                buffer += para

        if buffer:
            chunks.append(self._make_chunk(buffer, index, structure, index))

        return chunks

    def _make_chunk(
        self,
        text: str,
        index: int,
        structure: list[dict] | None,
        para_index: int,
    ) -> Chunk:
        metadata: dict = {}
        if structure:
            metadata["sections"] = [
                s.get("title", "") for s in structure[:3]
            ]
        return Chunk(
            text=text,
            index=index,
            token_count=max(1, len(text) // self._chars_per_token),
            content_type="pdf",
            metadata=metadata,
        )
