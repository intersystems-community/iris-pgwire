"""
Structured Logging Configuration for SQL Translation

Integrates SQL translation logging with existing PostgreSQL wire protocol server
logging infrastructure using structlog for constitutional compliance and observability.

Constitutional Compliance: Comprehensive audit trail and performance monitoring.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from .performance_monitor import get_monitor

# DDL warning formats
DDL_SKIP_FORMAT = "[DDL-SKIP] {} ignored"


def setup_translation_logging(
    log_level: str = "INFO",
    log_file: str | None = None,
    enable_json: bool = True,
    enable_console: bool = True,
    enable_performance_log: bool = True,
) -> None:
    """
    Setup structured logging for SQL translation system

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional log file path
        enable_json: Enable JSON structured logging
        enable_console: Enable console logging
        enable_performance_log: Enable separate performance log
    """

    # Configure structlog processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        add_translation_context,
        add_constitutional_compliance,
    ]

    if enable_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper())),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Setup standard library logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(message)s",
        handlers=_create_handlers(log_file, enable_console, enable_json),
    )

    # Setup performance logging if enabled
    if enable_performance_log:
        setup_performance_logging(log_file)

    # Log configuration completion
    logger = structlog.get_logger("iris_pgwire.sql_translator.logging")
    logger.info(
        "SQL translation logging configured",
        log_level=log_level,
        json_enabled=enable_json,
        console_enabled=enable_console,
        performance_logging=enable_performance_log,
        log_file=log_file,
    )


def _create_handlers(
    log_file: str | None, enable_console: bool, enable_json: bool
) -> list[logging.Handler]:
    """Create logging handlers based on configuration"""
    handlers = []

    # Console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        if enable_json:
            console_handler.setFormatter(JSONFormatter())
        else:
            console_handler.setFormatter(ConsoleFormatter())
        handlers.append(console_handler)

    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JSONFormatter() if enable_json else ConsoleFormatter())
        handlers.append(file_handler)

    return handlers


def setup_performance_logging(base_log_file: str | None = None) -> None:
    """Setup dedicated performance logging"""
    perf_logger = logging.getLogger("iris_pgwire.performance")

    # Create performance log file path
    if base_log_file:
        perf_log_file = str(Path(base_log_file).with_suffix(".performance.log"))
    else:
        perf_log_file = "iris_pgwire_performance.log"

    # Setup dedicated file handler for performance metrics
    perf_handler = logging.FileHandler(perf_log_file)
    perf_handler.setFormatter(JSONFormatter())
    perf_logger.addHandler(perf_handler)
    perf_logger.setLevel(logging.INFO)

    # Prevent propagation to avoid duplicate logs
    perf_logger.propagate = False


def add_translation_context(logger, method_name, event_dict):
    """Add SQL translation context to log entries"""
    # Add translation-specific context
    event_dict["component"] = "sql_translator"

    # Add session information if available
    if "session_id" not in event_dict and hasattr(logger, "_context"):
        context = getattr(logger, "_context", {})
        if "session_id" in context:
            event_dict["session_id"] = context["session_id"]

    # Add correlation ID for request tracing
    if "correlation_id" not in event_dict and hasattr(logger, "_context"):
        context = getattr(logger, "_context", {})
        if "correlation_id" in context:
            event_dict["correlation_id"] = context["correlation_id"]

    return event_dict


def add_constitutional_compliance(logger, method_name, event_dict):
    """Add constitutional compliance information to log entries"""
    # Add constitutional compliance context
    event_dict["constitutional"] = {
        "sla_requirement_ms": 5.0,
        "audit_trail": True,
        "performance_monitoring": True,
    }

    # Add performance compliance if available
    if "translation_time_ms" in event_dict:
        time_ms = event_dict["translation_time_ms"]
        event_dict["constitutional"]["sla_compliant"] = time_ms <= 5.0
        if time_ms > 5.0:
            event_dict["constitutional"]["sla_violation"] = {
                "actual_ms": time_ms,
                "violation_amount_ms": time_ms - 5.0,
            }

    return event_dict


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""

    def format(self, record):
        log_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields
        if hasattr(record, "extra"):
            log_data.update(record.extra)

        # Add exception information
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


class ConsoleFormatter(logging.Formatter):
    """Console formatter for human-readable logging"""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s [%(levelname)8s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )


class TranslationLogger:
    """
    Specialized logger for SQL translation operations

    Provides convenient methods for logging translation events with
    proper context and constitutional compliance tracking.
    """

    def __init__(self, logger_name: str = "iris_pgwire.sql_translator"):
        self.logger = structlog.get_logger(logger_name)
        self.performance_monitor = get_monitor()

    def log_translation_start(
        self, session_id: str, original_sql: str, correlation_id: str | None = None
    ) -> None:
        """Log the start of a translation operation"""
        self.logger.info(
            "Translation started",
            session_id=session_id,
            correlation_id=correlation_id,
            sql_length=len(original_sql),
            sql_preview=original_sql[:100] + "..." if len(original_sql) > 100 else original_sql,
            event_type="translation_start",
        )

    def log_translation_complete(
        self,
        session_id: str,
        original_sql: str,
        translated_sql: str,
        constructs_translated: int,
        translation_time_ms: float,
        cache_hit: bool,
        correlation_id: str | None = None,
    ) -> None:
        """Log the completion of a translation operation"""
        self.logger.info(
            "Translation completed",
            session_id=session_id,
            correlation_id=correlation_id,
            original_length=len(original_sql),
            translated_length=len(translated_sql),
            constructs_translated=constructs_translated,
            translation_time_ms=translation_time_ms,
            cache_hit=cache_hit,
            sla_compliant=translation_time_ms <= 5.0,
            event_type="translation_complete",
        )

    def log_translation_error(
        self,
        session_id: str,
        original_sql: str,
        error: Exception,
        correlation_id: str | None = None,
    ) -> None:
        """Log a translation error"""
        self.logger.error(
            "Translation failed",
            session_id=session_id,
            correlation_id=correlation_id,
            sql_preview=original_sql[:100] + "..." if len(original_sql) > 100 else original_sql,
            error_type=type(error).__name__,
            error_message=str(error),
            event_type="translation_error",
        )

    def log_construct_mapping(
        self,
        session_id: str,
        iris_construct: str,
        postgresql_equivalent: str,
        confidence: float,
        correlation_id: str | None = None,
    ) -> None:
        """Log a construct mapping decision"""
        self.logger.debug(
            "Construct mapped",
            session_id=session_id,
            correlation_id=correlation_id,
            iris_construct=iris_construct,
            postgresql_equivalent=postgresql_equivalent,
            confidence=confidence,
            high_confidence=confidence >= 0.9,
            event_type="construct_mapping",
        )

    def log_cache_operation(
        self,
        session_id: str,
        operation: str,
        cache_key: str,
        hit: bool,
        correlation_id: str | None = None,
    ) -> None:
        """Log a cache operation"""
        self.logger.debug(
            f"Cache {operation}",
            session_id=session_id,
            correlation_id=correlation_id,
            cache_operation=operation,
            cache_key_hash=hash(cache_key) % 10000,  # Partial key for privacy
            cache_hit=hit,
            event_type="cache_operation",
        )

    def log_validation_result(
        self,
        session_id: str,
        validation_success: bool,
        issues_count: int,
        confidence: float,
        correlation_id: str | None = None,
    ) -> None:
        """Log validation results"""
        level = "info" if validation_success else "warning"
        getattr(self.logger, level)(
            "Translation validated",
            session_id=session_id,
            correlation_id=correlation_id,
            validation_success=validation_success,
            issues_count=issues_count,
            validation_confidence=confidence,
            event_type="validation_result",
        )

    def log_performance_metrics(
        self, session_id: str, metrics: dict[str, Any], correlation_id: str | None = None
    ) -> None:
        """Log performance metrics"""
        # Use dedicated performance logger
        perf_logger = logging.getLogger("iris_pgwire.performance")

        perf_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            "correlation_id": correlation_id,
            "event_type": "performance_metrics",
            **metrics,
        }

        perf_logger.info(json.dumps(perf_data, default=str))


# Global logger instances
_translation_logger = None


def get_translation_logger() -> TranslationLogger:
    """Get the global translation logger instance"""
    global _translation_logger
    if _translation_logger is None:
        _translation_logger = TranslationLogger()
    return _translation_logger


def configure_server_integration():
    """
    Configure logging integration with existing PostgreSQL wire protocol server

    This function should be called during server startup to ensure consistent
    logging across all components.
    """
    # Setup base logging configuration
    setup_translation_logging(
        log_level="INFO", enable_json=True, enable_console=True, enable_performance_log=True
    )

    # Configure integration with existing server loggers
    server_loggers = ["iris_pgwire.server", "iris_pgwire.protocol", "iris_pgwire.iris_executor"]

    for logger_name in server_loggers:
        logger = logging.getLogger(logger_name)
        # Ensure consistent formatting
        for handler in logger.handlers:
            if not isinstance(handler.formatter, JSONFormatter | ConsoleFormatter):
                handler.setFormatter(JSONFormatter())

    # Log configuration completion
    logger = structlog.get_logger("iris_pgwire.logging")
    logger.info(
        "Server logging integration configured",
        integrated_loggers=server_loggers,
        structured_logging=True,
        constitutional_compliance=True,
    )


# Export main components
__all__ = [
    "setup_translation_logging",
    "setup_performance_logging",
    "TranslationLogger",
    "JSONFormatter",
    "ConsoleFormatter",
    "get_translation_logger",
    "configure_server_integration",
]
