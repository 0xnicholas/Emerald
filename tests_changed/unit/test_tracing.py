"""Unit tests for OpenTelemetry tracing setup."""

from __future__ import annotations

import pytest

from emerald.core.tracing import (
    attach_traceparent,
    detach,
    get_traceparent,
    get_tracer,
    init_tracing,
    shutdown_tracing,
)


class TestTracing:
    """Verify tracing utilities initialise and propagate correctly."""

    def test_init_tracing_noop_without_endpoint(self):
        """When no OTLP endpoint is configured, init_tracing should not crash."""
        # This test relies on the default empty endpoint in Settings
        init_tracing()
        # get_tracer should still return a usable tracer (no-op)
        tracer = get_tracer()
        assert tracer is not None
        shutdown_tracing()

    def test_get_tracer_returns_tracer(self):
        tracer = get_tracer()
        assert tracer is not None

    def test_traceparent_roundtrip(self):
        """Serialising and deserialising a traceparent should attach the context."""
        init_tracing()
        tracer = get_tracer()

        with tracer.start_as_current_span("test.span"):
            tp = get_traceparent()
            assert tp is not None
            assert tp.startswith("00-")

            token = attach_traceparent(tp)
            assert token is not None
            detach(token)

        shutdown_tracing()

    def test_attach_traceparent_none(self):
        """Passing None should return None without error."""
        token = attach_traceparent(None)
        assert token is None
        detach(token)
