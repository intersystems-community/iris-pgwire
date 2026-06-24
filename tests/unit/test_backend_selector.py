"""
Unit tests for backend_selector.py.

Tests BackendSelector configuration validation and executor creation,
covering all branches without requiring live IRIS.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from iris_pgwire.models.backend_config import BackendConfig, BackendType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dbapi_config(**kwargs) -> BackendConfig:
    """Return a minimal valid DBAPI BackendConfig."""
    defaults = dict(
        backend_type=BackendType.DBAPI,
        iris_password="secret",
        pool_size=5,
        pool_max_overflow=5,
        enable_otel=False,
    )
    defaults.update(kwargs)
    return BackendConfig(**defaults)


def _embedded_config(**kwargs) -> BackendConfig:
    """Return a minimal valid Embedded BackendConfig."""
    defaults = dict(
        backend_type=BackendType.EMBEDDED,
        enable_otel=False,
    )
    defaults.update(kwargs)
    return BackendConfig(**defaults)


# ---------------------------------------------------------------------------
# BackendSelector.__init__
# ---------------------------------------------------------------------------


class TestBackendSelectorInit:
    def test_creates_empty_executor_cache(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        assert selector._executors == {}


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------


class TestValidateConfig:
    def test_dbapi_with_password_is_valid(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _dbapi_config()
        assert selector.validate_config(config) is True

    def test_embedded_is_always_valid(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _embedded_config()
        assert selector.validate_config(config) is True

    def test_dbapi_without_password_raises(self):
        """BackendConfig model_validator catches this first — but if somehow
        we have a config that gets through, BackendSelector also validates."""
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        # Build a valid config then forcibly blank the password to bypass Pydantic
        config = _dbapi_config()
        object.__setattr__(config, "iris_password", None)

        with pytest.raises(ValueError, match="iris_password"):
            selector.validate_config(config)

    def test_pool_size_overflow_limit_raises(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        # Exceed 200 by direct object mutation
        config = _dbapi_config(pool_size=100, pool_max_overflow=20)
        object.__setattr__(config, "pool_size", 150)
        object.__setattr__(config, "pool_max_overflow", 100)

        with pytest.raises(ValueError, match="200"):
            selector.validate_config(config)

    def test_pool_exactly_200_is_valid(self):
        from iris_pgwire.backend_selector import BackendSelector

        # pool_size=100 + pool_max_overflow=100 = 200 (valid at model level)
        config = _dbapi_config(pool_size=100, pool_max_overflow=100)
        selector = BackendSelector()
        assert selector.validate_config(config) is True


# ---------------------------------------------------------------------------
# select_backend — dispatching
# ---------------------------------------------------------------------------


class TestSelectBackend:
    def test_selects_dbapi_executor(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _dbapi_config()

        mock_executor = MagicMock()
        mock_executor.backend_type = "dbapi"

        with patch.object(selector, "_create_dbapi_executor", return_value=mock_executor) as m:
            result = selector.select_backend(config)
            m.assert_called_once_with(config)
            assert result is mock_executor

    def test_selects_embedded_executor(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _embedded_config()

        mock_executor = MagicMock()
        mock_executor.backend_type = "embedded"

        with patch.object(selector, "_create_embedded_executor", return_value=mock_executor) as m:
            result = selector.select_backend(config)
            m.assert_called_once_with(config)
            assert result is mock_executor

    def test_invalid_backend_type_raises(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _embedded_config()
        # Inject an unrecognised backend_type object so .value doesn't break
        class _FakeType:
            value = "unknown_type"
            def __eq__(self, other):
                return False
        object.__setattr__(config, "backend_type", _FakeType())

        with pytest.raises(ValueError, match="Unsupported backend type"):
            selector.select_backend(config)

    def test_validation_failure_raises_before_dispatch(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _dbapi_config()
        object.__setattr__(config, "iris_password", None)

        with pytest.raises(ValueError):
            selector.select_backend(config)


# ---------------------------------------------------------------------------
# _create_dbapi_executor
# ---------------------------------------------------------------------------


class TestCreateDbApiExecutor:
    def test_creates_dbapi_executor_successfully(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _dbapi_config()

        mock_executor_class = MagicMock()
        mock_executor_instance = MagicMock()
        mock_executor_instance.backend_type = "dbapi"
        mock_executor_class.return_value = mock_executor_instance

        with patch("iris_pgwire.backend_selector.BackendSelector._create_dbapi_executor") as m:
            m.return_value = mock_executor_instance
            result = selector._create_dbapi_executor.__wrapped__(selector, config) if hasattr(
                selector._create_dbapi_executor, "__wrapped__"
            ) else None

        # Use patch at import level instead
        with patch.dict(
            "sys.modules",
            {"iris_pgwire.dbapi_executor": MagicMock(DBAPIExecutor=mock_executor_class)},
        ):
            result = selector._create_dbapi_executor(config)
            mock_executor_class.assert_called_once_with(config)
            assert result is mock_executor_instance

    def test_import_error_raises_informative_message(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _dbapi_config()

        with patch.dict("sys.modules", {"iris_pgwire.dbapi_executor": None}):
            with pytest.raises(ImportError, match="DBAPIExecutor not available"):
                selector._create_dbapi_executor(config)


# ---------------------------------------------------------------------------
# _create_embedded_executor
# ---------------------------------------------------------------------------


class TestCreateEmbeddedExecutor:
    def test_creates_embedded_executor_successfully(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _embedded_config()

        mock_executor_class = MagicMock()
        mock_executor_instance = MagicMock()
        mock_executor_instance.backend_type = "embedded"
        mock_executor_class.return_value = mock_executor_instance

        with patch.dict(
            "sys.modules",
            {"iris_pgwire.iris_executor": MagicMock(IRISExecutor=mock_executor_class)},
        ):
            result = selector._create_embedded_executor(config)
            # Verify IRISExecutor was called with iris_config dict + kwargs
            assert mock_executor_class.called
            call_args = mock_executor_class.call_args
            iris_config = call_args[0][0]
            assert iris_config["host"] == config.iris_hostname
            assert iris_config["port"] == config.iris_port
            assert iris_config["namespace"] == config.iris_namespace
            assert iris_config["username"] == config.iris_username
            assert iris_config["password"] == config.iris_password
            assert result is mock_executor_instance

    def test_embedded_executor_passes_pool_kwargs(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _embedded_config(pool_size=3, pool_timeout=15, query_timeout=60.0)

        mock_executor_class = MagicMock()
        mock_executor_instance = MagicMock()
        mock_executor_instance.backend_type = "embedded"
        mock_executor_class.return_value = mock_executor_instance

        with patch.dict(
            "sys.modules",
            {"iris_pgwire.iris_executor": MagicMock(IRISExecutor=mock_executor_class)},
        ):
            selector._create_embedded_executor(config)
            call_kwargs = mock_executor_class.call_args[1]
            assert call_kwargs["connection_pool_size"] == 3
            assert call_kwargs["connection_pool_timeout"] == 15.0
            assert call_kwargs["query_timeout"] == 60.0

    def test_import_error_raises_informative_message(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _embedded_config()

        with patch.dict("sys.modules", {"iris_pgwire.iris_executor": None}):
            with pytest.raises(ImportError, match="IRISExecutor not available"):
                selector._create_embedded_executor(config)


# ---------------------------------------------------------------------------
# close_all
# ---------------------------------------------------------------------------


class TestCloseAll:
    @pytest.mark.asyncio
    async def test_close_all_calls_close_on_each_executor(self):
        from unittest.mock import AsyncMock

        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()

        exec1 = MagicMock()
        exec1.close = AsyncMock()
        exec2 = MagicMock()
        exec2.close = AsyncMock()
        selector._executors = {"a": exec1, "b": exec2}

        await selector.close_all()

        exec1.close.assert_awaited_once()
        exec2.close.assert_awaited_once()
        assert selector._executors == {}

    @pytest.mark.asyncio
    async def test_close_all_handles_executor_close_error(self):
        """Errors during close should be swallowed (logged as warning)."""
        from unittest.mock import AsyncMock

        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        bad_exec = MagicMock()
        bad_exec.close = AsyncMock(side_effect=RuntimeError("connection already closed"))
        selector._executors = {"x": bad_exec}

        # Should not raise
        await selector.close_all()
        assert selector._executors == {}

    @pytest.mark.asyncio
    async def test_close_all_empty_executors(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        # No executors — should complete without error
        await selector.close_all()
        assert selector._executors == {}


# ---------------------------------------------------------------------------
# Integration: full select_backend round-trip with mocked imports
# ---------------------------------------------------------------------------


class TestSelectBackendIntegration:
    def test_dbapi_round_trip(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _dbapi_config()

        mock_executor = MagicMock()
        mock_executor.backend_type = "dbapi"
        mock_executor.enable_otel = config.enable_otel

        mock_cls = MagicMock(return_value=mock_executor)
        with patch.dict(
            "sys.modules",
            {"iris_pgwire.dbapi_executor": MagicMock(DBAPIExecutor=mock_cls)},
        ):
            result = selector.select_backend(config)
            assert result is mock_executor

    def test_embedded_round_trip(self):
        from iris_pgwire.backend_selector import BackendSelector

        selector = BackendSelector()
        config = _embedded_config()

        mock_executor = MagicMock()
        mock_executor.backend_type = "embedded"

        mock_cls = MagicMock(return_value=mock_executor)
        with patch.dict(
            "sys.modules",
            {"iris_pgwire.iris_executor": MagicMock(IRISExecutor=mock_cls)},
        ):
            result = selector.select_backend(config)
            assert result is mock_executor
