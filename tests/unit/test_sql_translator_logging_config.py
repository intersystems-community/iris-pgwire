"""
Unit tests for sql_translator/logging_config.py

Targets ≥80% coverage of:
- setup_translation_logging
- _create_handlers
- setup_performance_logging
- add_translation_context
- add_constitutional_compliance
- JSONFormatter
- ConsoleFormatter
- TranslationLogger (all log_ methods)
- get_translation_logger
- configure_server_integration
"""

import json
import logging
import sys
from datetime import datetime
from io import StringIO
from unittest.mock import MagicMock, patch, call

import pytest

from iris_pgwire.sql_translator.logging_config import (
    JSONFormatter,
    ConsoleFormatter,
    TranslationLogger,
    add_constitutional_compliance,
    add_translation_context,
    configure_server_integration,
    get_translation_logger,
    setup_performance_logging,
    setup_translation_logging,
    _create_handlers,
    DDL_SKIP_FORMAT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_log_record(msg="test message", level=logging.INFO, name="test.logger"):
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="test_file.py",
        lineno=42,
        msg=msg,
        args=(),
        exc_info=None,
    )
    return record


# ---------------------------------------------------------------------------
# DDL_SKIP_FORMAT constant
# ---------------------------------------------------------------------------


def test_ddl_skip_format_is_string():
    assert isinstance(DDL_SKIP_FORMAT, str)
    assert "{}" in DDL_SKIP_FORMAT


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------


class TestJSONFormatter:
    def setup_method(self):
        self.formatter = JSONFormatter()

    def test_output_is_valid_json(self):
        record = make_log_record("hello json")
        output = self.formatter.format(record)
        data = json.loads(output)
        assert isinstance(data, dict)

    def test_contains_required_fields(self):
        record = make_log_record("check fields")
        data = json.loads(self.formatter.format(record))
        for key in ("timestamp", "level", "logger", "message", "module", "function", "line"):
            assert key in data, f"Missing key: {key}"

    def test_message_content(self):
        record = make_log_record("my message")
        data = json.loads(self.formatter.format(record))
        assert data["message"] == "my message"

    def test_level_name(self):
        record = make_log_record(level=logging.WARNING)
        data = json.loads(self.formatter.format(record))
        assert data["level"] == "WARNING"

    def test_extra_fields_included(self):
        record = make_log_record()
        record.extra = {"custom_key": "custom_value"}
        data = json.loads(self.formatter.format(record))
        assert data.get("custom_key") == "custom_value"

    def test_exception_info_included(self):
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = make_log_record()
        record.exc_info = exc_info
        data = json.loads(self.formatter.format(record))
        assert "exception" in data

    def test_line_number_correct(self):
        record = make_log_record()
        record.lineno = 99
        data = json.loads(self.formatter.format(record))
        assert data["line"] == 99

    def test_no_extra_attribute(self):
        record = make_log_record()
        # No extra attribute set — should not raise
        output = self.formatter.format(record)
        data = json.loads(output)
        assert "message" in data


# ---------------------------------------------------------------------------
# ConsoleFormatter
# ---------------------------------------------------------------------------


class TestConsoleFormatter:
    def setup_method(self):
        self.formatter = ConsoleFormatter()

    def test_output_is_string(self):
        record = make_log_record("console msg")
        output = self.formatter.format(record)
        assert isinstance(output, str)

    def test_output_contains_message(self):
        record = make_log_record("hello console")
        output = self.formatter.format(record)
        assert "hello console" in output

    def test_format_string_set(self):
        # Check that the formatter has a format string with expected elements
        assert self.formatter._fmt is not None
        assert "levelname" in self.formatter._fmt or "%(levelname" in self.formatter._fmt


# ---------------------------------------------------------------------------
# add_translation_context
# ---------------------------------------------------------------------------


class TestAddTranslationContext:
    def test_adds_component_field(self):
        event_dict = {}
        result = add_translation_context(MagicMock(), "info", event_dict)
        assert result["component"] == "sql_translator"

    def test_existing_component_overwritten(self):
        event_dict = {"component": "other"}
        result = add_translation_context(MagicMock(), "info", event_dict)
        assert result["component"] == "sql_translator"

    def test_session_id_from_context(self):
        mock_logger = MagicMock()
        mock_logger._context = {"session_id": "sess-123"}
        event_dict = {}
        result = add_translation_context(mock_logger, "info", event_dict)
        assert result.get("session_id") == "sess-123"

    def test_session_id_not_overwritten_if_present(self):
        mock_logger = MagicMock()
        mock_logger._context = {"session_id": "from_context"}
        event_dict = {"session_id": "already_set"}
        result = add_translation_context(mock_logger, "info", event_dict)
        assert result["session_id"] == "already_set"

    def test_correlation_id_from_context(self):
        mock_logger = MagicMock()
        mock_logger._context = {"correlation_id": "corr-456"}
        event_dict = {}
        result = add_translation_context(mock_logger, "info", event_dict)
        assert result.get("correlation_id") == "corr-456"

    def test_no_context_attribute(self):
        mock_logger = MagicMock(spec=[])  # No _context
        event_dict = {}
        result = add_translation_context(mock_logger, "info", event_dict)
        assert result["component"] == "sql_translator"

    def test_returns_event_dict(self):
        event_dict = {"foo": "bar"}
        result = add_translation_context(MagicMock(), "info", event_dict)
        assert result is event_dict


# ---------------------------------------------------------------------------
# add_constitutional_compliance
# ---------------------------------------------------------------------------


class TestAddConstitutionalCompliance:
    def test_adds_constitutional_field(self):
        event_dict = {}
        result = add_constitutional_compliance(MagicMock(), "info", event_dict)
        assert "constitutional" in result

    def test_constitutional_has_required_fields(self):
        result = add_constitutional_compliance(MagicMock(), "info", {})
        c = result["constitutional"]
        assert "sla_requirement_ms" in c
        assert "audit_trail" in c
        assert "performance_monitoring" in c

    def test_sla_compliant_when_fast(self):
        event_dict = {"translation_time_ms": 2.0}
        result = add_constitutional_compliance(MagicMock(), "info", event_dict)
        assert result["constitutional"]["sla_compliant"] is True

    def test_sla_violation_when_slow(self):
        event_dict = {"translation_time_ms": 10.0}
        result = add_constitutional_compliance(MagicMock(), "info", event_dict)
        assert result["constitutional"]["sla_compliant"] is False
        assert "sla_violation" in result["constitutional"]

    def test_sla_violation_amount_correct(self):
        event_dict = {"translation_time_ms": 8.0}
        result = add_constitutional_compliance(MagicMock(), "info", event_dict)
        violation = result["constitutional"]["sla_violation"]
        assert violation["actual_ms"] == 8.0
        assert abs(violation["violation_amount_ms"] - 3.0) < 0.001

    def test_no_translation_time_no_sla_fields(self):
        event_dict = {}
        result = add_constitutional_compliance(MagicMock(), "info", event_dict)
        assert "sla_compliant" not in result["constitutional"]

    def test_exactly_at_sla_limit_is_compliant(self):
        event_dict = {"translation_time_ms": 5.0}
        result = add_constitutional_compliance(MagicMock(), "info", event_dict)
        assert result["constitutional"]["sla_compliant"] is True

    def test_returns_event_dict(self):
        event_dict = {"x": 1}
        result = add_constitutional_compliance(MagicMock(), "info", event_dict)
        assert result is event_dict


# ---------------------------------------------------------------------------
# _create_handlers
# ---------------------------------------------------------------------------


class TestCreateHandlers:
    def test_returns_list(self):
        handlers = _create_handlers(None, True, True)
        assert isinstance(handlers, list)

    def test_console_handler_added_when_enabled(self):
        handlers = _create_handlers(None, enable_console=True, enable_json=True)
        assert any(isinstance(h, logging.StreamHandler) for h in handlers)

    def test_no_console_handler_when_disabled(self):
        handlers = _create_handlers(None, enable_console=False, enable_json=True)
        assert len(handlers) == 0

    def test_file_handler_added_when_path_given(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        handlers = _create_handlers(log_file, enable_console=False, enable_json=True)
        assert any(isinstance(h, logging.FileHandler) for h in handlers)
        # Clean up
        for h in handlers:
            h.close()

    def test_no_file_handler_when_no_path(self):
        handlers = _create_handlers(None, enable_console=True, enable_json=True)
        assert not any(isinstance(h, logging.FileHandler) for h in handlers)

    def test_json_formatter_on_console_when_json_enabled(self):
        from iris_pgwire.sql_translator.logging_config import JSONFormatter
        handlers = _create_handlers(None, enable_console=True, enable_json=True)
        console_handler = next(h for h in handlers if isinstance(h, logging.StreamHandler))
        assert isinstance(console_handler.formatter, JSONFormatter)

    def test_console_formatter_when_json_disabled(self):
        from iris_pgwire.sql_translator.logging_config import ConsoleFormatter
        handlers = _create_handlers(None, enable_console=True, enable_json=False)
        console_handler = next(h for h in handlers if isinstance(h, logging.StreamHandler))
        assert isinstance(console_handler.formatter, ConsoleFormatter)

    def test_both_handlers_when_both_enabled(self, tmp_path):
        log_file = str(tmp_path / "both.log")
        handlers = _create_handlers(log_file, enable_console=True, enable_json=True)
        assert len(handlers) == 2
        for h in handlers:
            h.close()


# ---------------------------------------------------------------------------
# setup_performance_logging
# ---------------------------------------------------------------------------


class TestSetupPerformanceLogging:
    def test_creates_performance_logger(self, tmp_path):
        log_file = str(tmp_path / "app.log")
        setup_performance_logging(log_file)
        perf_logger = logging.getLogger("iris_pgwire.performance")
        assert perf_logger is not None

    def test_performance_logger_does_not_propagate(self, tmp_path):
        log_file = str(tmp_path / "app2.log")
        setup_performance_logging(log_file)
        perf_logger = logging.getLogger("iris_pgwire.performance")
        assert perf_logger.propagate is False

    def test_without_base_file_uses_default_name(self):
        # Should not raise; uses default filename
        setup_performance_logging(None)
        import os
        # Clean up the file if created in cwd
        default_file = "iris_pgwire_performance.log"
        if os.path.exists(default_file):
            # Close any handlers to allow deletion
            perf_logger = logging.getLogger("iris_pgwire.performance")
            for h in list(perf_logger.handlers):
                h.close()
                perf_logger.removeHandler(h)
            os.remove(default_file)

    def test_performance_log_path_derived_from_base(self, tmp_path):
        log_file = str(tmp_path / "app.log")
        setup_performance_logging(log_file)
        expected_perf_file = str(tmp_path / "app.performance.log")
        perf_logger = logging.getLogger("iris_pgwire.performance")
        file_paths = [
            h.baseFilename
            for h in perf_logger.handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert expected_perf_file in file_paths


# ---------------------------------------------------------------------------
# setup_translation_logging
# ---------------------------------------------------------------------------


class TestSetupTranslationLogging:
    def test_runs_without_error(self):
        # Basic smoke test — just confirm it doesn't raise
        setup_translation_logging(
            log_level="WARNING",
            log_file=None,
            enable_json=False,
            enable_console=False,
            enable_performance_log=False,
        )

    def test_with_json_enabled(self):
        setup_translation_logging(
            log_level="ERROR",
            log_file=None,
            enable_json=True,
            enable_console=False,
            enable_performance_log=False,
        )

    def test_with_performance_log(self, tmp_path):
        setup_translation_logging(
            log_level="INFO",
            log_file=None,
            enable_json=False,
            enable_console=False,
            enable_performance_log=True,
        )
        import os
        default_file = "iris_pgwire_performance.log"
        if os.path.exists(default_file):
            perf_logger = logging.getLogger("iris_pgwire.performance")
            for h in list(perf_logger.handlers):
                h.close()
                perf_logger.removeHandler(h)
            os.remove(default_file)

    def test_with_log_file(self, tmp_path):
        log_file = str(tmp_path / "translation.log")
        setup_translation_logging(
            log_level="DEBUG",
            log_file=log_file,
            enable_json=True,
            enable_console=False,
            enable_performance_log=False,
        )


# ---------------------------------------------------------------------------
# TranslationLogger
# ---------------------------------------------------------------------------


class TestTranslationLogger:
    def setup_method(self):
        self.tl = TranslationLogger()

    def test_log_translation_start(self):
        # Should not raise
        self.tl.log_translation_start("sess-1", "SELECT * FROM t")

    def test_log_translation_start_with_long_sql(self):
        long_sql = "SELECT " + "x, " * 50 + "y FROM t"
        self.tl.log_translation_start("sess-1", long_sql, correlation_id="corr-1")

    def test_log_translation_complete_sla_compliant(self):
        self.tl.log_translation_complete(
            session_id="s1",
            original_sql="SELECT 1",
            translated_sql="SELECT 1",
            constructs_translated=0,
            translation_time_ms=1.0,
            cache_hit=True,
        )

    def test_log_translation_complete_sla_violation(self):
        self.tl.log_translation_complete(
            session_id="s1",
            original_sql="SELECT 1",
            translated_sql="SELECT 1",
            constructs_translated=3,
            translation_time_ms=10.0,
            cache_hit=False,
            correlation_id="corr-2",
        )

    def test_log_translation_error(self):
        self.tl.log_translation_error(
            session_id="s1",
            original_sql="BAD SQL",
            error=ValueError("syntax error"),
        )

    def test_log_translation_error_long_sql(self):
        long_sql = "BAD " * 50
        self.tl.log_translation_error(
            session_id="s1",
            original_sql=long_sql,
            error=RuntimeError("err"),
            correlation_id="c1",
        )

    def test_log_construct_mapping_high_confidence(self):
        self.tl.log_construct_mapping(
            session_id="s1",
            iris_construct="TOP n",
            postgresql_equivalent="LIMIT n",
            confidence=0.95,
        )

    def test_log_construct_mapping_low_confidence(self):
        self.tl.log_construct_mapping(
            session_id="s1",
            iris_construct="XYZ",
            postgresql_equivalent="abc",
            confidence=0.5,
            correlation_id="c1",
        )

    def test_log_cache_operation_hit(self):
        self.tl.log_cache_operation(
            session_id="s1",
            operation="get",
            cache_key="SELECT 1",
            hit=True,
        )

    def test_log_cache_operation_miss(self):
        self.tl.log_cache_operation(
            session_id="s1",
            operation="set",
            cache_key="SELECT 2",
            hit=False,
            correlation_id="c1",
        )

    def test_log_validation_result_success(self):
        self.tl.log_validation_result(
            session_id="s1",
            validation_success=True,
            issues_count=0,
            confidence=0.99,
        )

    def test_log_validation_result_failure(self):
        self.tl.log_validation_result(
            session_id="s1",
            validation_success=False,
            issues_count=3,
            confidence=0.4,
            correlation_id="c1",
        )

    def test_log_performance_metrics(self):
        self.tl.log_performance_metrics(
            session_id="s1",
            metrics={"translation_time_ms": 1.5, "cache_hits": 5},
        )

    def test_log_performance_metrics_with_correlation(self):
        self.tl.log_performance_metrics(
            session_id="s1",
            metrics={"throughput": 1000},
            correlation_id="c1",
        )

    def test_has_performance_monitor(self):
        assert self.tl.performance_monitor is not None


# ---------------------------------------------------------------------------
# get_translation_logger
# ---------------------------------------------------------------------------


class TestGetTranslationLogger:
    def test_returns_translation_logger_instance(self):
        from iris_pgwire.sql_translator import logging_config
        # Reset global state
        logging_config._translation_logger = None
        logger = get_translation_logger()
        assert isinstance(logger, TranslationLogger)

    def test_returns_same_instance_on_second_call(self):
        from iris_pgwire.sql_translator import logging_config
        logging_config._translation_logger = None
        l1 = get_translation_logger()
        l2 = get_translation_logger()
        assert l1 is l2

    def test_returns_existing_instance_when_set(self):
        from iris_pgwire.sql_translator import logging_config
        existing = TranslationLogger()
        logging_config._translation_logger = existing
        result = get_translation_logger()
        assert result is existing
        # Cleanup
        logging_config._translation_logger = None


# ---------------------------------------------------------------------------
# configure_server_integration
# ---------------------------------------------------------------------------


class TestConfigureServerIntegration:
    def test_runs_without_error(self):
        # configure_server_integration calls setup_translation_logging which
        # writes a performance log file. Patch to avoid filesystem side effects.
        with patch(
            "iris_pgwire.sql_translator.logging_config.setup_performance_logging"
        ):
            configure_server_integration()

    def test_applies_json_formatter_to_existing_handlers(self):
        # Add a handler with non-JSON formatter to a server logger
        test_logger = logging.getLogger("iris_pgwire.server")
        dummy_handler = logging.StreamHandler()
        dummy_handler.setFormatter(logging.Formatter("%(message)s"))
        test_logger.addHandler(dummy_handler)

        try:
            with patch(
                "iris_pgwire.sql_translator.logging_config.setup_performance_logging"
            ):
                configure_server_integration()

            # The formatter on the handler should now be JSONFormatter
            assert isinstance(dummy_handler.formatter, JSONFormatter)
        finally:
            test_logger.removeHandler(dummy_handler)
