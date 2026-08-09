"""Upload content-type resolution tests (spec issue #1).

The upload route detects a MIME type from the file name; the pipeline must
then map that MIME string to a structured content type so JSON/CSV uploads
are chunked structurally rather than as raw text.
"""

from __future__ import annotations

from emerald.api.routes.v1.upload import _detect_mime


def test_detect_mime_json_extension():
    assert _detect_mime("data.json") == "application/json"


def test_detect_mime_csv_extension():
    assert _detect_mime("data.csv") == "text/csv"


def test_detect_mime_existing_types_unchanged():
    assert _detect_mime("report.pdf") == "application/pdf"
    assert _detect_mime("notes.txt") == "text/plain"
    assert _detect_mime("image.png") == "image/png"
    assert _detect_mime("archive.bin") == "application/octet-stream"


def test_detect_mime_without_filename():
    assert _detect_mime(None) == "application/octet-stream"
