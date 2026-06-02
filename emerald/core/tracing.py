"""OpenTelemetry tracing setup for Emerald.

Lightweight manual instrumentation:
- FastAPI requests are auto-instrumented via OpentelemetryMiddleware.
- Key business operations (add, search, compute) get manual spans.
- Celery tasks receive trace context via traceparent header.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_tracer: Any = None


def init_tracing() -> None:
    """Initialise the global TracerProvider and OTLP exporter.

    When ``otel_exporter_otlp_endpoint`` is not configured, a no-op provider
    is still installed so that manual spans work without sending anywhere.
    """
    global _tracer

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    from emerald.config import get_settings

    settings = get_settings()

    if not settings.otel_exporter_otlp_endpoint:
        # No OTLP endpoint — install a minimal provider so get_tracer() works
        trace.set_tracer_provider(TracerProvider())
        _tracer = trace.get_tracer(__name__)
        logger.info("tracing.disabled", reason="no_otlp_endpoint")
        return

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": "0.3.0",
        }
    )
    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(__name__)

    logger.info(
        "tracing.initialised",
        endpoint=settings.otel_exporter_otlp_endpoint,
        service=settings.otel_service_name,
        sampler=settings.otel_traces_sampler,
    )


def shutdown_tracing() -> None:
    """Flush pending spans and shut down the tracer provider."""
    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    try:
        if hasattr(provider, "force_flush"):
            provider.force_flush()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception as exc:
        logger.warning("tracing.shutdown_failed", error=str(exc))
    logger.info("tracing.shutdown")


def get_tracer() -> Any:
    """Return the global tracer, initialising a no-op tracer if necessary."""
    global _tracer
    if _tracer is None:
        from opentelemetry import trace

        _tracer = trace.get_tracer(__name__)
    return _tracer


def get_traceparent() -> str | None:
    """Serialize the current span context to a W3C traceparent string.

    Returns ``None`` when there is no active span.
    """
    from opentelemetry import trace
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    span = trace.get_current_span()
    if span is None or not span.get_span_context().is_valid:
        return None

    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    return carrier.get("traceparent")


def attach_traceparent(traceparent: str | None) -> Any | None:
    """Attach a traceparent to the current context.

    Returns a token that should be passed to :func:`detach` when done.
    """
    if not traceparent:
        return None

    from opentelemetry import context
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    propagator = TraceContextTextMapPropagator()
    ctx = propagator.extract({"traceparent": traceparent})
    return context.attach(ctx)


def detach(token: Any | None) -> None:
    """Detach a previously attached context token."""
    if token is None:
        return
    from opentelemetry import context

    context.detach(token)
