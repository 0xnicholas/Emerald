"""Audio extractor — speech-to-text transcription.

Requires faster-whisper. Gracefully degrades when deps are missing.
"""

from __future__ import annotations

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent


class AudioExtractor(BaseExtractor):
    """Transcribes audio to text using Faster-Whisper."""

    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ExtractionError(
                content_type="audio",
                reason="faster-whisper is not installed. Install with: pip install faster-whisper",
                retryable=False,
            )

        try:
            import tempfile
            import os

            model_size = kwargs.get("model_size", "small")

            # Write bytes to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(content)
                temp_path = f.name

            try:
                model = WhisperModel(model_size, device="cpu", compute_type="int8")
                segments, info = model.transcribe(temp_path, beam_size=5)
                language = info.language

                text_parts = []
                for segment in segments:
                    text_parts.append(f"[{segment.start:.1f}s-{segment.end:.1f}s] {segment.text}")

                full_text = "\n".join(text_parts)

                return ExtractedContent(
                    text=full_text,
                    content_type="audio",
                    metadata={
                        "language": language,
                        "duration_seconds": segments[-1].end if text_parts else 0,
                    },
                )
            finally:
                os.unlink(temp_path)

        except Exception as e:
            raise ExtractionError(
                content_type="audio",
                reason=f"Transcription failed: {e}",
                retryable=True,
            )

    def supports(self, content_type: str) -> bool:
        return content_type == "audio"
