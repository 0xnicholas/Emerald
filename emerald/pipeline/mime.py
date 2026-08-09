"""MIME → pipeline content-type resolution (spec issue #1).

Uploads and external sources carry MIME strings ("application/json",
"text/csv"); the pipeline registries are keyed by short content types
("json", "csv", "text"). This helper maps between the two.

- ``application/*`` → suffix: application/json → json, application/pdf → pdf
- ``text/*``, ``image/*``, ``audio/*``, ``video/*`` → the group name
- Anything without a ``/`` (already a pipeline content type) is unchanged
"""

from __future__ import annotations

_KNOWN_PIPELINE_TYPES = {
    "text", "code", "markdown", "pdf", "conversation", "json", "csv",
    "url", "image", "audio", "video",
}

_MIME_PREFIX_TO_TYPE = {
    "text": "text",
    "image": "image",
    "audio": "audio",
    "video": "video",
}


def resolve_pipeline_content_type(content_type: str) -> str:
    """Map a MIME string to a pipeline content type.

    Resolution order:
    1. A known pipeline type as the suffix wins: text/csv → csv,
       application/json → json, text/markdown → markdown.
    2. Otherwise the MIME group name: image/png → image, audio/mpeg → audio.
    3. Otherwise the raw suffix (unknown application/* types), so callers
       still get a clear UnsupportedContentType.
    """
    if "/" not in content_type:
        return content_type
    prefix, suffix = content_type.split("/", 1)
    if suffix in _KNOWN_PIPELINE_TYPES:
        return suffix
    return _MIME_PREFIX_TO_TYPE.get(prefix, suffix)
