"""Structured logging configuration via structlog.

Produces JSON logs to stdout for aggregation by Fluentd/Loki/CloudWatch.
"""

from __future__ import annotations

import logging
import os

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for structured JSON output.

    Called once at application startup. All modules then use
    `structlog.get_logger(__name__)` for consistent formatting.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if os.environ.get("EMERALD_LOG_FORMAT") == "console"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Silence noisy third-party loggers
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.WARNING)
