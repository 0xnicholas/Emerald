"""Emerald exception hierarchy."""

from __future__ import annotations


class EmeraldError(Exception):
    """Base exception for all Emerald errors."""


# -- Pipeline errors --
class PipelineError(EmeraldError):
    """Raised when a pipeline stage fails."""

    def __init__(self, pipeline_id: str, stage: str, reason: str) -> None:
        self.pipeline_id = pipeline_id
        self.stage = stage
        self.reason = reason
        super().__init__(f"[{pipeline_id}] {stage} failed: {reason}")


class ExtractionError(EmeraldError):
    """Raised when content extraction fails."""

    def __init__(
        self,
        content_type: str,
        reason: str,
        retryable: bool = True,
    ) -> None:
        self.content_type = content_type
        self.reason = reason
        self.retryable = retryable
        super().__init__(f"Extraction failed for {content_type}: {reason}")


class ChunkingError(EmeraldError):
    """Raised when chunking fails."""

    def __init__(self, content_type: str, reason: str) -> None:
        self.content_type = content_type
        self.reason = reason
        super().__init__(f"Chunking failed for {content_type}: {reason}")


class EmbeddingError(EmeraldError):
    """Raised when embedding generation fails."""

    def __init__(self, reason: str, retryable: bool = True) -> None:
        self.reason = reason
        self.retryable = retryable
        super().__init__(f"Embedding failed: {reason}")


class IndexingError(EmeraldError):
    """Raised when graph/vector indexing fails."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Indexing failed: {reason}")


# -- Content errors --
class UnsupportedContentTypeError(EmeraldError):
    """Raised when content type is not supported."""

    def __init__(self, content_type: str, supported: list[str] | None = None) -> None:
        self.content_type = content_type
        msg = f"Unsupported content type: '{content_type}'"
        if supported:
            msg += f". Supported: {supported}"
        super().__init__(msg)


class EmptyContentError(EmeraldError):
    """Raised when content is empty after cleaning."""


class ContentTooLargeError(EmeraldError):
    """Raised when content exceeds size limits."""

    def __init__(self, size_bytes: int, max_bytes: int) -> None:
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes
        super().__init__(
            f"Content size {size_bytes} bytes exceeds limit of {max_bytes} bytes"
        )


# -- Storage errors --
class NotFoundError(EmeraldError):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource_type: str, resource_id: str) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(f"{resource_type} not found: {resource_id}")


class DuplicateError(EmeraldError):
    """Raised when attempting to create a duplicate resource."""

    def __init__(self, resource_type: str, identifier: str) -> None:
        self.resource_type = resource_type
        self.identifier = identifier
        super().__init__(f"{resource_type} already exists: {identifier}")


# -- Auth errors --
class AuthenticationError(EmeraldError):
    """Raised when authentication fails."""


class PermissionDeniedError(EmeraldError):
    """Raised when the caller lacks required permissions."""

    def __init__(self, required: str, actual: list[str]) -> None:
        self.required = required
        self.actual = actual
        super().__init__(
            f"Permission denied: requires '{required}', has {actual}"
        )


# -- Connector errors --
class ConnectorError(EmeraldError):
    """Base for connector-related errors."""


class UnsupportedConnectorError(ConnectorError):
    """Raised when a connector provider is not supported."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"No connector for provider: '{provider}'")


class ConnectorAuthError(ConnectorError):
    """Raised when OAuth authentication fails."""
