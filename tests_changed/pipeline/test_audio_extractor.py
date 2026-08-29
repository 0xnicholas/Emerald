"""Tests for AudioExtractor.

faster-whisper is mocked so tests run without heavy deps.
"""

from unittest.mock import MagicMock, patch

import pytest

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.audio import AudioExtractor


@pytest.fixture
def extractor():
    return AudioExtractor()


# ---- Supports ----

@pytest.mark.asyncio
async def test_supports_audio(extractor):
    assert extractor.supports("audio") is True
    assert extractor.supports("text") is False


# ---- Missing deps ----

@pytest.mark.asyncio
async def test_extract_missing_deps(extractor):
    with patch.dict("sys.modules", {"faster_whisper": None}):
        with pytest.raises(ExtractionError, match="faster-whisper is not installed"):
            await extractor.extract(b"fake_wav")


# ---- Normal extraction ----

@pytest.mark.asyncio
async def test_extract_transcription(extractor):
    """Successful transcription returns segments with timestamps."""
    seg1 = MagicMock(start=0.0, end=2.5, text="Hello world")
    seg2 = MagicMock(start=2.5, end=5.0, text="How are you")
    segments = [seg1, seg2]

    mock_info = MagicMock()
    mock_info.language = "en"

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (segments, mock_info)

    with patch("faster_whisper.WhisperModel", return_value=mock_model):
        result = await extractor.extract(b"fake_audio", model_size="tiny")

    assert "[0.0s-2.5s] Hello world" in result.text
    assert "[2.5s-5.0s] How are you" in result.text
    assert result.content_type == "audio"
    assert result.metadata["language"] == "en"
    assert result.metadata["duration_seconds"] == 5.0


@pytest.mark.asyncio
async def test_extract_empty_audio(extractor):
    """Empty audio returns zero-duration result."""
    mock_info = MagicMock()
    mock_info.language = "en"

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([], mock_info)

    with patch("faster_whisper.WhisperModel", return_value=mock_model):
        result = await extractor.extract(b"silence")

    assert result.text == ""
    assert result.metadata["duration_seconds"] == 0


# ---- Transcription error ----

@pytest.mark.asyncio
async def test_extract_transcription_error(extractor):
    """Whisper failure raises retryable ExtractionError."""
    mock_model = MagicMock()
    mock_model.transcribe.side_effect = RuntimeError("CUDA out of memory")

    with patch("faster_whisper.WhisperModel", return_value=mock_model):
        with pytest.raises(ExtractionError, match="Transcription failed"):
            await extractor.extract(b"fake_audio")


# ---- Temp file cleanup ----

@pytest.mark.asyncio
async def test_extract_cleans_temp_file(extractor):
    """Temporary audio file is deleted after transcription."""
    mock_info = MagicMock()
    mock_info.language = "en"

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([], mock_info)

    created_paths = []
    original_unlink = __import__("os").unlink

    def tracking_unlink(path):
        created_paths.append(path)
        original_unlink(path)

    with patch("faster_whisper.WhisperModel", return_value=mock_model):
        with patch("os.unlink", side_effect=tracking_unlink):
            await extractor.extract(b"audio_data")

    assert len(created_paths) == 1
    assert created_paths[0].endswith(".wav")
