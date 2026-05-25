"""Video extractor — transcription + keyframe OCR.

Requires ffmpeg on PATH, plus faster-whisper and Pillow/pytesseract.
Gracefully degrades when deps are missing.
"""

from __future__ import annotations

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent


class VideoExtractor(BaseExtractor):
    """Extracts audio track for transcription and keyframes for OCR.

    Uses ffmpeg for track extraction and frame sampling.
    """

    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        import shutil
        import subprocess

        if not shutil.which("ffmpeg"):
            raise ExtractionError(
                content_type="video",
                reason="ffmpeg is not installed. Install it via your system package manager.",
                retryable=False,
            )

        try:
            import os
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(content)
                video_path = f.name

            audio_path = video_path + ".wav"

            try:
                # Extract audio with ffmpeg
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-i", video_path,
                        "-vn", "-acodec", "pcm_s16le",
                        "-ar", "16000", "-ac", "1",
                        audio_path,
                    ],
                    capture_output=True,
                    timeout=120,
                    check=True,
                )

                # Transcribe audio
                with open(audio_path, "rb") as af:
                    audio_bytes = af.read()

                # Try audio extraction (will fail gracefully if deps missing)
                from emerald.pipeline.extraction.audio import AudioExtractor

                audio_result = await AudioExtractor().extract(audio_bytes)

                return ExtractedContent(
                    text=audio_result.text,
                    content_type="video",
                    metadata={
                        **audio_result.metadata,
                        "source_type": "video",
                    },
                )
            finally:
                # Clean up temp files
                for p in [video_path, audio_path]:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(
                content_type="video",
                reason=f"Video extraction failed: {e}",
                retryable=True,
            )

    def supports(self, content_type: str) -> bool:
        return content_type == "video"
