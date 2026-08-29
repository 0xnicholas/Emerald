"""Unit tests for exceptions module."""


from emerald.core.exceptions import (
    AuthenticationError,
    ContentTooLargeError,
    DuplicateError,
    EmbeddingError,
    EmeraldError,
    EmptyContentError,
    ExtractionError,
    NotFoundError,
    PermissionDeniedError,
    PipelineError,
    UnsupportedContentTypeError,
)


def test_emerald_error_is_base():
    """All exceptions are subclasses of EmeraldError."""
    assert issubclass(ExtractionError, EmeraldError)
    assert issubclass(EmbeddingError, EmeraldError)
    assert issubclass(NotFoundError, EmeraldError)


def test_extraction_error_retryable_flag():
    """ExtractionError carries a retryable flag."""
    e = ExtractionError("pdf", "corrupted file", retryable=False)
    assert e.retryable is False
    assert e.content_type == "pdf"

    e2 = ExtractionError("url", "timeout", retryable=True)
    assert e2.retryable is True


def test_not_found_error_message():
    """NotFoundError message includes resource type and ID."""
    e = NotFoundError("Memory", "mem_abc123")
    assert "Memory" in str(e)
    assert "mem_abc123" in str(e)


def test_pipeline_error_includes_stage():
    """PipelineError includes pipeline_id and stage."""
    e = PipelineError("pipe_1", "extracting", "timeout")
    assert "pipe_1" in str(e)
    assert "extracting" in str(e)
    assert "timeout" in str(e)


def test_content_too_large_error():
    """ContentTooLargeError includes size and limit."""
    e = ContentTooLargeError(size_bytes=60_000_000, max_bytes=50_000_000)
    assert "60000000" in str(e)
    assert "50000000" in str(e)


def test_authentication_error():
    e = AuthenticationError()
    assert isinstance(e, EmeraldError)


def test_permission_denied_error():
    e = PermissionDeniedError(required="write", actual=["read"])
    assert "write" in str(e)
    assert "read" in str(e)


def test_empty_content_error():
    e = EmptyContentError()
    assert isinstance(e, EmeraldError)


def test_unsupported_content_type_lists_supported():
    e = UnsupportedContentTypeError("exe", supported=["text", "pdf"])
    assert "exe" in str(e)
    assert "text" in str(e)


def test_duplicate_error():
    e = DuplicateError("Entity", "user_123")
    assert "Entity" in str(e)
    assert "user_123" in str(e)
