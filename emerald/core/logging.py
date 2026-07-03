"""Structured logging configuration via structlog.

Produces JSON logs to stdout for aggregation by Fluentd/Loki/CloudWatch.
In production, PII is automatically sanitized from log output.
"""

from __future__ import annotations

import logging
import os

import structlog


def _add_trace_context(_: object, __: object, event_dict: dict) -> dict:
    """Inject current trace_id and span_id into log records."""
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            ctx = span.get_span_context()
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except Exception:
        pass  # otel not installed or span context unavailable
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for structured JSON output.

    Called once at application startup. All modules then use
    `structlog.get_logger(__name__)` for consistent formatting.

    In production (``EMERALD_ENV=production``), PII sanitization is
    enabled automatically.  Set ``EMERALD_LOG_SANITIZE=false`` to
    disable it explicitly.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    env = os.environ.get("EMERALD_ENV", "development")
    sanitize_enabled = os.environ.get("EMERALD_LOG_SANITIZE", "true").lower() != "false"
    use_sanitizer = env == "production" and sanitize_enabled

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_trace_context,
    ]

    if use_sanitizer:
        from emerald.core.sanitizer import sanitize_event_dict
        processors.append(sanitize_event_dict)

    if os.environ.get("EMERALD_LOG_FORMAT") == "console":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Silence noisy third-party loggers
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.WARNING)
