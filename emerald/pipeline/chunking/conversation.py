"""Conversation chunker — turn-based splitting preserving speaker identity."""

from __future__ import annotations

import re

from emerald.pipeline.chunking.base import BaseChunker, Chunk

# Matches speaker labels at the start of a line:
# Plain text: "User:", "Assistant:", "System:"
# Markdown bold: "**User**:", "**Assistant**:", "**System**:"
_SPEAKER_RE = re.compile(
    r"^(?:\*\*)?(User|Assistant|System|AI|Human|Bot)(?:\*\*)?\s*:\s*",
    re.IGNORECASE | re.MULTILINE,
)


class ConversationChunker(BaseChunker):
    """Splits conversations by speaker turn. No overlap.

    target_size: 512 tokens (per turn max)
    overlap_size: 0 (conversations don't overlap — each turn is independent context)
    """

    target_size = 512
    overlap_size = 0
    _chars_per_token = 4

    async def chunk(self, text: str, **kwargs) -> list[Chunk]:
        if not text.strip():
            return []

        # Detect if text has speaker labels
        turns = self._split_turns(text)

        if not turns:
            # Fallback: no speaker labels, chunk by size
            return self._chunk_by_size(text)

        chunks = []
        for i, (speaker, turn_text, offset) in enumerate(turns):
            token_count = max(1, len(turn_text) // self._chars_per_token)
            chunks.append(
                Chunk(
                    text=f"{speaker}: {turn_text}" if speaker else turn_text,
                    index=i,
                    token_count=token_count,
                    content_type="conversation",
                    metadata={
                        "speaker": speaker or "unknown",
                        "turn_index": i,
                        "char_offset_start": offset,
                        "char_offset_end": offset + len(turn_text),
                    },
                )
            )
        return chunks

    def _split_turns(self, text: str) -> list[tuple[str, str, int]]:
        """Split text by speaker turns. Returns (speaker, text, offset) list."""
        turns = []
        matches = list(_SPEAKER_RE.finditer(text))

        if not matches:
            return []

        for i, match in enumerate(matches):
            speaker = match.group(1)
            start = match.end()  # After "Speaker: "
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            turn_text = text[start:end].strip()
            turns.append((speaker, turn_text, start))

        return turns

    def _chunk_by_size(self, text: str) -> list[Chunk]:
        """Fallback chunking when no speaker labels detected."""
        target_chars = self.target_size * self._chars_per_token
        sentences = re.split(r"(?<=[.!?。！？\n])\s*", text)
        chunks = []
        buffer = ""
        index = 0

        for sent in sentences:
            if not sent.strip():
                continue
            if len(buffer) + len(sent) > target_chars and buffer:
                token_count = max(1, len(buffer) // self._chars_per_token)
                chunks.append(
                    Chunk(
                        text=buffer.strip(),
                        index=index,
                        token_count=token_count,
                        content_type="conversation",
                        metadata={"turn_index": index},
                    )
                )
                index += 1
                buffer = sent
            else:
                buffer += sent + " "

        if buffer.strip():
            token_count = max(1, len(buffer) // self._chars_per_token)
            chunks.append(
                Chunk(
                    text=buffer.strip(),
                    index=index,
                    token_count=token_count,
                    content_type="conversation",
                    metadata={"turn_index": index},
                )
            )

        return chunks
