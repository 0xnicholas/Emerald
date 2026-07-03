"""OpenTelemetry auto-instrumentation entry point.

Enabled via::

    from emerald.core.tracing_instrumentation import instrument_all
    instrument_all()

Safe to call multiple times (idempotent).

NOTE: FastAPI instrumentation is wired in ``emerald/api/app.py`` (~line 200).
This module handles: httpx, asyncpg, redis, celery.  Neo4j falls back to
manual spans because ``opentelemetry-instrumentation-neo4j`` does NOT exist
on PyPI.
"""
from __future__ import annotations

from typing import Any

import structlog

from emerald.config import get_settings

logger = structlog.get_logger(__name__)

_INSTRUMENTED = False


def instrument_all() -> None:
    """Apply auto-instrumentation based on config toggles.

    Idempotent — safe to call multiple times.
    """
    global _INSTRUMENTED
    if _INSTRUMENTED:
        return

    settings = get_settings()

    if settings.otel_instrument_httpx:
        _safe_instrument("httpx", _instrument_httpx)

    if settings.otel_instrument_asyncpg:
        _safe_instrument("asyncpg", _instrument_asyncpg)

    # Neo4j: opentelemetry-instrumentation-neo4j does NOT exist on PyPI.
    # Neo4j tracing is done via manual spans in pipeline/tasks.py.

    if settings.otel_instrument_redis:
        _safe_instrument("redis", _instrument_redis)

    if settings.otel_instrument_celery:
        _safe_instrument("celery", _instrument_celery)

    if settings.otel_console_exporter:
        _add_console_exporter()

    _INSTRUMENTED = True
    logger.info("otel.instrumentation_complete")


def _safe_instrument(name: str, fn: Any) -> None:
    """Run an instrumentor, logging (not raising) on failure."""
    try:
        fn()
        logger.info("otel.instrumented", target=name)
    except Exception:
        logger.warning("otel.instrumentation_failed", target=name, exc_info=True)


def _instrument_httpx() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    HTTPXClientInstrumentor().instrument()


def _instrument_asyncpg() -> None:
    from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
    AsyncPGInstrumentor().instrument()


def _instrument_redis() -> None:
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    RedisInstrumentor().instrument()


def _instrument_celery() -> None:
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from emerald.pipeline.celery import celery_app
    CeleryInstrumentor().instrument(celery_app)


def _add_console_exporter() -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = trace.get_tracer_provider()
    if hasattr(provider, "add_span_processor"):
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
