"""
Observability setup for iris-pgwire.

Configures structured logging with OpenTelemetry trace context.
IRIS automatically exports OTEL telemetry - we just need to instrument our code.

Constitutional Requirements:
- Principle V (Production Readiness): Observability and monitoring

Feature: 018-add-dbapi-option
"""

import logging
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor


def setup_logging(service_name: str = "iris-pgwire", log_level: str = "INFO") -> None:
    """
    Setup structured logging with OpenTelemetry trace context.

    IRIS handles OTEL export automatically - we just add trace IDs to logs.

    Args:
        service_name: Service name for log entries
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper()),
    )

    # Configure structlog with OTEL trace context
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            add_otel_context,  # Add trace_id and span_id to logs
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger()
    logger.info(
        "Observability configured",
        service_name=service_name,
        log_level=log_level,
    )


def add_otel_context(logger: Any, method_name: str, event_dict: dict) -> dict:
    """
    Add OpenTelemetry trace context to log events.

    Extracts trace_id and span_id from current OTEL context and adds to logs.
    This allows correlating logs with distributed traces in IRIS.

    Args:
        logger: Logger instance
        method_name: Method name being called
        event_dict: Log event dictionary

    Returns:
        Updated event dictionary with trace context
    """
    # Get current span from OTEL context
    span = trace.get_current_span()

    if span.is_recording():
        ctx = span.get_span_context()
        if ctx.is_valid:
            # Add trace context to log event
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
            event_dict["trace_flags"] = ctx.trace_flags

    return event_dict


def instrument_asyncio() -> None:
    """
    Instrument asyncio for automatic OTEL tracing.

    This automatically creates spans for asyncio tasks and coroutines.
    IRIS will export these spans automatically.
    """
    AsyncioInstrumentor().instrument()
    logger = structlog.get_logger()
    logger.info("Asyncio instrumentation enabled")


def get_tracer(name: str = "iris-pgwire") -> trace.Tracer:
    """
    Get OpenTelemetry tracer for manual instrumentation.

    Args:
        name: Tracer name

    Returns:
        Tracer instance
    """
    return trace.get_tracer(name)
