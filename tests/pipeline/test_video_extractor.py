"""Tests for VideoExtractor.

ffmpeg, faster-whisper, and Pillow/pytesseract are mocked.
"""

import os
import subprocess
import tempfile
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.video import VideoExtractor


@pytest.fixture
def extractor():
    return VideoExtractor()


# ---- Supports ----

@pytest.mark.asyncio
async def test_supports_video(extractor):
    assert extractor.supports("video") is True
    assert extractor.supports("text") is False


# ---- ffmpeg missing ----

@pytest.mark.asyncio
async def test_extract_ffmpeg_not_installed(extractor):
    with patch("shutil.which", return_value=None):
        with pytest.raises(ExtractionError, match="ffmpeg is not installed"):
            await extractor.extract(b"fake_video")


# ---- Normal extraction ----

@pytest.mark.asyncio
async def test_extract_audio_track(extractor):
    """Audio track is extracted and transcribed."""
    mock_info = MagicMock()
    mock_info.language = "en"

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([], mock_info)

    def mock_ffmpeg(cmd, **kwargs):
        # cmd[-1] is the audio output path
        audio_path = cmd[-1]
        with open(audio_path, "wb") as f:
            f.write(b"fake_wav_data")
        return MagicMock(returncode=0)

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("subprocess.run", side_effect=mock_ffmpeg):
            with patch("faster_whisper.WhisperModel", return_value=mock_model):
                result = await extractor.extract(b"fake_mp4")

    assert result.content_type == "video"
    assert result.metadata.get("source_type") == "video"


@pytest.mark.asyncio
async def test_extract_ffmpeg_error(extractor):
    """ffmpeg failure raises retryable ExtractionError."""
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
        ):
            with pytest.raises(ExtractionError, match="Video extraction failed"):
                await extractor.extract(b"fake_mp4")


# ---- Delegation to AudioExtractor ----

@pytest.mark.asyncio
async def test_extract_delegates_to_audio_extractor(extractor):
    """VideoExtractor delegates transcription to AudioExtractor."""
    mock_audio_result = MagicMock()
    mock_audio_result.text = "delegated text"
    mock_audio_result.metadata = {"language": "zh", "duration_seconds": 10.0}

    def mock_ffmpeg(cmd, **kwargs):
        audio_path = cmd[-1]
        with open(audio_path, "wb") as f:
            f.write(b"fake_wav_data")
        return MagicMock(returncode=0)

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("subprocess.run", side_effect=mock_ffmpeg):
            with patch(
                "emerald.pipeline.extraction.audio.AudioExtractor.extract",
                return_value=mock_audio_result,
            ) as mock_audio:
                result = await extractor.extract(b"fake_mp4")

    assert result.text == "delegated text"
    assert result.metadata["language"] == "zh"
    mock_audio.assert_awaited_once()


# ---- Temp file cleanup ----

@pytest.mark.asyncio
async def test_extract_cleans_temp_files(extractor):
    """Both video and audio temp files are deleted."""
    mock_info = MagicMock()
    mock_info.language = "en"

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([], mock_info)

    removed_paths = []
    original_unlink = os.unlink

    def tracking_unlink(path):
        removed_paths.append(path)
        original_unlink(path)

    def mock_ffmpeg(cmd, **kwargs):
        audio_path = cmd[-1]
        with open(audio_path, "wb") as f:
            f.write(b"fake_wav_data")
        return MagicMock(returncode=0)

    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("subprocess.run", side_effect=mock_ffmpeg):
            with patch("faster_whisper.WhisperModel", return_value=mock_model):
                with patch("os.unlink", side_effect=tracking_unlink):
                    await extractor.extract(b"video_data")

    # VideoExtractor cleans up both video and audio temp files.
    # AudioExtractor may also clean up its own temp file, so total can be 2-3.
    assert any(p.endswith(".mp4") for p in removed_paths)
    assert any(p.endswith(".wav") for p in removed_paths)
