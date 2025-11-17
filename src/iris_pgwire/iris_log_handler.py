"""
IRIS log handler for writing Python logs to IRIS messages.log.

Integrates Python logging with IRIS system logging for unified observability.

Constitutional Requirements:
- Principle V (Production Readiness): Centralized logging

Feature: 018-add-dbapi-option
"""

import logging

try:
    import iris

    IRIS_AVAILABLE = True
except ImportError:
    IRIS_AVAILABLE = False


class IRISLogHandler(logging.Handler):
    """
    Custom logging handler that writes to IRIS messages.log.

    Writes Python log records to IRIS system console log via ObjectScript.
    This integrates iris-pgwire logs with IRIS operational logs.

    Usage:
        handler = IRISLogHandler()
        logger = logging.getLogger("iris_pgwire")
        logger.addHandler(handler)
    """

    def __init__(self, level: int = logging.INFO):
        """
        Initialize IRIS log handler.

        Args:
            level: Minimum logging level to write to IRIS
        """
        super().__init__(level)
        self.iris_available = IRIS_AVAILABLE

        if not self.iris_available:
            # Running outside IRIS - handler will be no-op
            pass

    def emit(self, record: logging.LogRecord) -> None:
        """
        Write log record to IRIS messages.log.

        Args:
            record: Log record to write
        """
        if not self.iris_available:
            # Not running inside IRIS - skip
            return

        try:
            # Format the log message
            msg = self.format(record)

            # Write to IRIS console log
            # This appears in /usr/irissys/mgr/messages.log
            iris.cls("%SYS.System").WriteToConsoleLog(
                msg, 0, 1  # 0 = info, 1 = warning, 2 = error, 3 = severe  # 1 = write immediately
            )

        except Exception:
            # Don't let logging errors crash the application
            # Fall back to stderr
            self.handleError(record)

    def set_iris_log_level(self, record_level: int) -> int:
        """
        Map Python logging level to IRIS log level.

        Args:
            record_level: Python logging level

        Returns:
            IRIS log level (0-3)
        """
        if record_level >= logging.ERROR:
            return 2  # ERROR
        elif record_level >= logging.WARNING:
            return 1  # WARNING
        else:
            return 0  # INFO


def setup_iris_logging(logger: logging.Logger | None = None) -> None:
    """
    Setup IRIS log handler for a logger.

    Args:
        logger: Logger to configure (default: root logger)
    """
    if logger is None:
        logger = logging.getLogger()

    # Add IRIS handler
    iris_handler = IRISLogHandler()
    iris_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    logger.addHandler(iris_handler)

    if IRIS_AVAILABLE:
        logger.info("IRIS log handler configured - logs will appear in messages.log")
    else:
        logger.debug("IRIS not available - IRIS log handler disabled")
