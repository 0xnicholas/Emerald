"""Integration tests for OpenTelemetry auto-instrumentation."""
from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


@pytest.fixture
def memory_exporter():
    """Provide in-memory span exporter for assertions."""
    # Reset global tracer provider
    trace.set_tracer_provider(TracerProvider())

    provider = trace.get_tracer_provider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    yield exporter

    exporter.clear()


@pytest.fixture
def enable_instrumentation(monkeypatch):
    """Force-enable all instrumentation toggles."""
    from emerald.config import get_settings

    settings = get_settings()
    for field in (
        "otel_instrument_httpx",
        "otel_instrument_asyncpg",
        "otel_instrument_redis",
        "otel_instrument_celery",
    ):
        monkeypatch.setattr(settings, field, True)


def test_instrument_all_is_idempotent(enable_instrumentation):
    """Calling instrument_all twice should not double-instrument."""
    from emerald.core.tracing_instrumentation import instrument_all

    instrument_all()
    instrument_all()  # Should be a no-op

    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("test"):
        pass


def test_manual_span_recorded(memory_exporter, enable_instrumentation):
    """Manual spans should appear in the in-memory exporter."""
    from emerald.core.tracing_instrumentation import instrument_all

    instrument_all()

    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("manual-span"):
        pass

    spans = memory_exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert "manual-span" in span_names


def test_log_includes_trace_id(enable_instrumentation):
    """structlog output should include trace_id when in a span context."""
    import io

    import structlog

    from emerald.core.logging import _add_trace_context

    output = io.StringIO()
    structlog.configure(
        processors=[
            _add_trace_context,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger("INFO"),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=output),
    )

    tracer = trace.get_tracer(__name__)
    log = structlog.get_logger(__name__)

    with tracer.start_as_current_span("trace-test"):
        log.info("inside.span")

    log_output = output.getvalue()
    assert "trace_id" in log_output
    assert "span_id" in log_output
