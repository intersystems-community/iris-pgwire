"""
Unit tests for iris_log_handler.py.

Tests IRISLogHandler and setup_iris_logging without live IRIS — the iris
module is mocked at import time.
"""

from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to reload the module under controlled IRIS availability
# ---------------------------------------------------------------------------


def _reload_module(iris_available: bool):
    """Reload iris_log_handler with or without a fake iris module available."""
    fake_iris = MagicMock()
    # Remove any cached version first
    for key in list(sys.modules.keys()):
        if "iris_log_handler" in key:
            del sys.modules[key]

    if iris_available:
        sys.modules["iris"] = fake_iris
        import iris_pgwire.iris_log_handler as mod
    else:
        # Ensure iris is NOT importable
        sys.modules.pop("iris", None)
        # Temporarily make 'iris' raise ImportError on import
        with patch.dict(sys.modules, {"iris": None}):
            import iris_pgwire.iris_log_handler as mod
            # Re-import to pick up the patched state
            import importlib
            importlib.reload(mod)

    return mod, fake_iris if iris_available else None


# ---------------------------------------------------------------------------
# IRISLogHandler — IRIS available
# ---------------------------------------------------------------------------


class TestIRISLogHandlerWithIRIS:
    """IRISLogHandler behaviour when iris module is importable."""

    def setup_method(self):
        # Remove any cached module so the try/except import block re-runs
        for key in list(sys.modules.keys()):
            if "iris_log_handler" in key:
                del sys.modules[key]
        self.fake_iris = MagicMock()
        self.fake_cls = MagicMock()
        self.fake_iris.cls.return_value = self.fake_cls
        # Also set up iris.cls("%SYS.System") path
        sys.modules["iris"] = self.fake_iris

        import iris_pgwire.iris_log_handler as mod
        import importlib
        importlib.reload(mod)
        self.mod = mod

    def teardown_method(self):
        sys.modules.pop("iris", None)
        for key in list(sys.modules.keys()):
            if "iris_log_handler" in key:
                del sys.modules[key]

    def _make_handler(self, level=logging.INFO) -> "logging.Handler":
        return self.mod.IRISLogHandler(level=level)

    def test_init_sets_iris_available_true(self):
        handler = self._make_handler()
        assert handler.iris_available is True

    def test_default_level_is_info(self):
        handler = self._make_handler()
        assert handler.level == logging.INFO

    def test_custom_level_respected(self):
        handler = self._make_handler(level=logging.DEBUG)
        assert handler.level == logging.DEBUG

    def test_emit_calls_write_to_console_log(self):
        handler = self._make_handler()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="hello iris", args=(), exc_info=None
        )
        handler.emit(record)
        self.fake_iris.cls.assert_called_with("%SYS.System")

    def test_emit_exception_calls_handle_error(self):
        """If iris.cls raises, handleError should be called instead of crashing."""
        self.fake_iris.cls.side_effect = RuntimeError("boom")
        handler = self._make_handler()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="hello", args=(), exc_info=None
        )
        with patch.object(handler, "handleError") as mock_handle_error:
            handler.emit(record)
        mock_handle_error.assert_called_once_with(record)


# ---------------------------------------------------------------------------
# IRISLogHandler — IRIS NOT available
# ---------------------------------------------------------------------------


class TestIRISLogHandlerWithoutIRIS:
    """IRISLogHandler behaviour when iris module is NOT importable."""

    def setup_method(self):
        for key in list(sys.modules.keys()):
            if "iris_log_handler" in key:
                del sys.modules[key]
        sys.modules.pop("iris", None)
        # Mark iris as not importable
        sys.modules["iris"] = None  # causes ImportError on 'import iris'

        import importlib
        import iris_pgwire.iris_log_handler as mod
        importlib.reload(mod)
        self.mod = mod

    def teardown_method(self):
        sys.modules.pop("iris", None)
        for key in list(sys.modules.keys()):
            if "iris_log_handler" in key:
                del sys.modules[key]

    def test_init_sets_iris_available_false(self):
        handler = self.mod.IRISLogHandler()
        assert handler.iris_available is False

    def test_emit_is_noop_when_iris_unavailable(self):
        handler = self.mod.IRISLogHandler()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="ignored", args=(), exc_info=None
        )
        # Should not raise; handleError should NOT be called
        with patch.object(handler, "handleError") as mock_he:
            handler.emit(record)
        mock_he.assert_not_called()

    def test_module_level_iris_available_false(self):
        assert self.mod.IRIS_AVAILABLE is False


# ---------------------------------------------------------------------------
# set_iris_log_level
# ---------------------------------------------------------------------------


class TestSetIrisLogLevel:
    """Mapping of Python log levels to IRIS levels."""

    def setup_method(self):
        for key in list(sys.modules.keys()):
            if "iris_log_handler" in key:
                del sys.modules[key]
        sys.modules["iris"] = None  # no iris
        import importlib
        import iris_pgwire.iris_log_handler as mod
        importlib.reload(mod)
        self.handler = mod.IRISLogHandler()

    def teardown_method(self):
        sys.modules.pop("iris", None)
        for key in list(sys.modules.keys()):
            if "iris_log_handler" in key:
                del sys.modules[key]

    def test_error_level_returns_2(self):
        assert self.handler.set_iris_log_level(logging.ERROR) == 2

    def test_critical_level_returns_2(self):
        assert self.handler.set_iris_log_level(logging.CRITICAL) == 2

    def test_warning_level_returns_1(self):
        assert self.handler.set_iris_log_level(logging.WARNING) == 1

    def test_info_level_returns_0(self):
        assert self.handler.set_iris_log_level(logging.INFO) == 0

    def test_debug_level_returns_0(self):
        assert self.handler.set_iris_log_level(logging.DEBUG) == 0


# ---------------------------------------------------------------------------
# setup_iris_logging
# ---------------------------------------------------------------------------


class TestSetupIrisLogging:
    """setup_iris_logging adds handler to the supplied (or root) logger."""

    def setup_method(self):
        for key in list(sys.modules.keys()):
            if "iris_log_handler" in key:
                del sys.modules[key]
        sys.modules["iris"] = None
        import importlib
        import iris_pgwire.iris_log_handler as mod
        importlib.reload(mod)
        self.mod = mod

    def teardown_method(self):
        sys.modules.pop("iris", None)
        for key in list(sys.modules.keys()):
            if "iris_log_handler" in key:
                del sys.modules[key]

    def test_adds_iris_handler_to_given_logger(self):
        logger = logging.getLogger("test_setup_iris_logging_given")
        # Remove any existing handlers first
        logger.handlers.clear()
        self.mod.setup_iris_logging(logger)
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "IRISLogHandler" in handler_types

    def test_adds_iris_handler_to_root_when_none_given(self):
        root = logging.getLogger()
        before = len(root.handlers)
        self.mod.setup_iris_logging(None)
        after = len(root.handlers)
        assert after == before + 1
        # Clean up
        for h in root.handlers[:]:
            if type(h).__name__ == "IRISLogHandler":
                root.removeHandler(h)

    def test_formatter_is_set_on_handler(self):
        logger = logging.getLogger("test_setup_iris_logging_fmt")
        logger.handlers.clear()
        self.mod.setup_iris_logging(logger)
        handler = logger.handlers[-1]
        assert handler.formatter is not None
