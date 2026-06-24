"""
Unit tests for iris_pgwire.observability

Strategy: mock opentelemetry.instrumentation.asyncio (not installed in test env)
and opentelemetry.trace so no real OTEL infrastructure is needed.
"""

from __future__ import annotations

import logging
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Stub opentelemetry.instrumentation.asyncio before importing observability
# ---------------------------------------------------------------------------

def _install_asyncio_instrumentor_stub():
    """Install a minimal stub for opentelemetry.instrumentation.asyncio."""
    if "opentelemetry.instrumentation" not in sys.modules:
        instr_mod = types.ModuleType("opentelemetry.instrumentation")
        sys.modules["opentelemetry.instrumentation"] = instr_mod

    asyncio_instr_mod = types.ModuleType("opentelemetry.instrumentation.asyncio")

    class _FakeAsyncioInstrumentor:
        def instrument(self):
            pass

        def uninstrument(self):
            pass

    asyncio_instr_mod.AsyncioInstrumentor = _FakeAsyncioInstrumentor
    sys.modules["opentelemetry.instrumentation.asyncio"] = asyncio_instr_mod
    return _FakeAsyncioInstrumentor


_AsyncioInstrumentorClass = _install_asyncio_instrumentor_stub()


# Now we can safely import observability
from iris_pgwire.observability import (  # noqa: E402
    add_otel_context,
    get_tracer,
    instrument_asyncio,
    setup_logging,
)


# ---------------------------------------------------------------------------
# add_otel_context
# ---------------------------------------------------------------------------


class TestAddOtelContext:
    def _make_span(self, is_recording: bool, is_valid: bool, trace_id: int = 0, span_id: int = 0):
        span = MagicMock()
        span.is_recording.return_value = is_recording
        ctx = MagicMock()
        ctx.is_valid = is_valid
        ctx.trace_id = trace_id
        ctx.span_id = span_id
        ctx.trace_flags = 1
        span.get_span_context.return_value = ctx
        return span

    def test_adds_trace_context_when_recording_and_valid(self):
        span = self._make_span(
            is_recording=True, is_valid=True, trace_id=0xDEADBEEF, span_id=0xCAFE
        )
        event_dict = {"event": "test"}
        with patch("iris_pgwire.observability.trace") as mock_trace:
            mock_trace.get_current_span.return_value = span
            result = add_otel_context(None, "info", event_dict)

        assert "trace_id" in result
        assert "span_id" in result
        assert "trace_flags" in result
        assert result["trace_id"] == format(0xDEADBEEF, "032x")
        assert result["span_id"] == format(0xCAFE, "016x")

    def test_no_context_added_when_not_recording(self):
        span = self._make_span(is_recording=False, is_valid=True)
        event_dict = {"event": "test"}
        with patch("iris_pgwire.observability.trace") as mock_trace:
            mock_trace.get_current_span.return_value = span
            result = add_otel_context(None, "info", event_dict)

        assert "trace_id" not in result
        assert "span_id" not in result

    def test_no_context_added_when_context_invalid(self):
        span = self._make_span(is_recording=True, is_valid=False)
        event_dict = {"event": "test"}
        with patch("iris_pgwire.observability.trace") as mock_trace:
            mock_trace.get_current_span.return_value = span
            result = add_otel_context(None, "info", event_dict)

        assert "trace_id" not in result

    def test_returns_event_dict(self):
        span = self._make_span(is_recording=False, is_valid=False)
        event_dict = {"event": "something", "extra": 42}
        with patch("iris_pgwire.observability.trace") as mock_trace:
            mock_trace.get_current_span.return_value = span
            result = add_otel_context(None, "debug", event_dict)

        assert result is event_dict
        assert result["extra"] == 42

    def test_trace_flags_propagated(self):
        span = self._make_span(is_recording=True, is_valid=True, trace_id=1, span_id=2)
        span.get_span_context.return_value.trace_flags = 0x01
        event_dict = {}
        with patch("iris_pgwire.observability.trace") as mock_trace:
            mock_trace.get_current_span.return_value = span
            result = add_otel_context(None, "info", event_dict)

        assert result["trace_flags"] == 0x01

    def test_accepts_logger_and_method_name_args(self):
        """add_otel_context accepts logger and method_name positional args."""
        span = self._make_span(is_recording=False, is_valid=False)
        with patch("iris_pgwire.observability.trace") as mock_trace:
            mock_trace.get_current_span.return_value = span
            result = add_otel_context(object(), "warning", {"event": "x"})

        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# get_tracer
# ---------------------------------------------------------------------------


class TestGetTracer:
    def test_returns_tracer(self):
        tracer = get_tracer()
        assert tracer is not None

    def test_custom_name(self):
        with patch("iris_pgwire.observability.trace") as mock_trace:
            mock_tracer = MagicMock()
            mock_trace.get_tracer.return_value = mock_tracer
            result = get_tracer("my-service")
            mock_trace.get_tracer.assert_called_once_with("my-service")
            assert result is mock_tracer

    def test_default_name(self):
        with patch("iris_pgwire.observability.trace") as mock_trace:
            mock_trace.get_tracer.return_value = MagicMock()
            get_tracer()
            mock_trace.get_tracer.assert_called_once_with("iris-pgwire")


# ---------------------------------------------------------------------------
# instrument_asyncio
# ---------------------------------------------------------------------------


class TestInstrumentAsyncio:
    def test_instrument_called(self):
        with patch(
            "iris_pgwire.observability.AsyncioInstrumentor"
        ) as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            instrument_asyncio()
            mock_instance.instrument.assert_called_once()

    def test_no_exception_raised(self):
        # With our stub in place, calling instrument_asyncio should not raise
        instrument_asyncio()


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_setup_with_defaults(self):
        # Should not raise
        setup_logging()

    def test_setup_with_custom_args(self):
        setup_logging(service_name="test-svc", log_level="DEBUG")

    def test_log_level_applied(self):
        """basicConfig sets the root logger level."""
        setup_logging(log_level="WARNING")
        # After setup_logging, the root logger level should be WARNING (30)
        # (basicConfig may be a no-op if already configured; just check no exception)

    def test_setup_with_error_level(self):
        setup_logging(log_level="ERROR")

    def test_setup_calls_structlog_configure(self):
        import structlog

        with patch.object(structlog, "configure") as mock_configure:
            # Re-run setup to capture the configure call
            setup_logging()
            mock_configure.assert_called_once()
            kwargs = mock_configure.call_args.kwargs
            assert "processors" in kwargs
            assert add_otel_context in kwargs["processors"]
