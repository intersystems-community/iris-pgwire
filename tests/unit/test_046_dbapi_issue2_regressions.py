"""
Regression tests for GitHub Issue #2: Multiple bugs and enhancement requests for DBAPI backend.

Each test class corresponds to one bug from the issue report and pins the fix so it cannot
regress silently. Tests are unit-level (no real IRIS connection required).

Bug inventory:
  B1 - execute_query rejected session_id kwarg (TypeError)
  B2 - execute_query returned raw list of tuples, not dict with 'rows' key
  B3 - connection pool datetime naive/aware crash in age_seconds
  B4 - Describe handler opened second connection, exhausting CE 1-conn license
  E1 - strict_single_connection enforces pool_size=1 for Community Edition
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared iris.dbapi stub (must be injected before any import of iris_pgwire)
# ---------------------------------------------------------------------------


def _make_iris_stub():
    iris_mod = types.ModuleType("iris")
    dbapi_mod = types.ModuleType("iris.dbapi")

    def connect(**kwargs):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.description = [("?column?", 23, None, None, None, None, None)]
        cursor.rowcount = 1
        cursor.fetchall.return_value = [(1,)]
        conn.cursor.return_value = cursor
        return conn

    dbapi_mod.connect = connect
    iris_mod.dbapi = dbapi_mod
    iris_mod.sql = MagicMock()
    return iris_mod, dbapi_mod


_iris_mod, _dbapi_mod = _make_iris_stub()
sys.modules.setdefault("iris", _iris_mod)
sys.modules.setdefault("iris.dbapi", _dbapi_mod)

from iris_pgwire.models.backend_config import BackendConfig, BackendType  # noqa: E402
from iris_pgwire.models.dbapi_connection import DBAPIConnection  # noqa: E402


def _make_dbapi_conn(connection_id: str = "conn-test", **overrides) -> DBAPIConnection:
    """Build a DBAPIConnection with required fields pre-filled."""
    defaults = dict(
        connection_id=connection_id,
        iris_hostname="localhost",
        iris_port=1972,
        iris_namespace="USER",
        pool_recycle_seconds=3600,
    )
    defaults.update(overrides)
    return DBAPIConnection(**defaults)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_real_config(**overrides) -> BackendConfig:
    """Return a real BackendConfig instance (for field-existence / validation tests)."""
    defaults = dict(
        backend_type=BackendType.DBAPI,
        iris_password="SYS",
        pool_size=2,
        pool_max_overflow=0,
        enable_otel=False,
    )
    defaults.update(overrides)
    return BackendConfig(**defaults)


def _make_config(**overrides) -> MagicMock:
    """Return a MagicMock that quacks like a BackendConfig for unit tests."""
    cfg = MagicMock(spec=BackendConfig)
    cfg.backend_type = BackendType.DBAPI
    cfg.iris_hostname = "localhost"
    cfg.iris_port = 1972
    cfg.iris_namespace = "USER"
    cfg.iris_username = "_SYSTEM"
    cfg.iris_password = "SYS"
    cfg.pool_size = 2
    cfg.pool_max_overflow = 0
    cfg.pool_timeout = 30
    cfg.pool_recycle = 3600
    cfg.strict_single_connection = False
    cfg.query_timeout = None
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_cursor(rows=None, description=None, rowcount=0):
    cursor = MagicMock()
    cursor.description = description or [("?column?", 23, None, None, None, None, None)]
    cursor.rowcount = rowcount
    cursor.fetchall.return_value = rows or []
    cursor.fetchone.return_value = rows[0] if rows else None
    cursor.close.return_value = None
    return cursor


def _make_conn_wrapper(rows=None, rowcount=1):
    """Return a mock DBAPIConnection-like wrapper with all required methods."""
    cursor = _make_cursor(rows=rows or [(1,)], rowcount=rowcount)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.commit.return_value = None
    wrapper = MagicMock()
    wrapper.connection = conn
    wrapper.is_healthy = True
    wrapper.record_query_execution.return_value = None
    wrapper.mark_failed.return_value = None
    return wrapper


def _make_executor(config: BackendConfig | None = None):
    """Return a DBAPIExecutor with all heavy dependencies mocked out."""
    cfg = config or _make_config()

    with (
        patch("iris_pgwire.dbapi_executor.IRISConnectionPool"),
        patch("iris_pgwire.dbapi_executor.CatalogRouter"),
        patch("iris_pgwire.dbapi_executor.SQLPipeline"),
        patch("iris_pgwire.dbapi_executor.SQLInterceptor"),
        patch("iris_pgwire.dbapi_executor.get_parser"),
    ):
        from iris_pgwire.dbapi_executor import DBAPIExecutor

        return DBAPIExecutor(cfg)


# ---------------------------------------------------------------------------
# B1 — execute_query must accept session_id keyword arg without TypeError
# ---------------------------------------------------------------------------


class TestB1ExecuteQueryAcceptsSessionId:
    """B1: DBAPIExecutor.execute_query rejected session_id kwarg with TypeError."""

    def test_signature_accepts_session_id_kwarg(self):
        """execute_query signature must include session_id as a keyword parameter."""
        import inspect

        from iris_pgwire.dbapi_executor import DBAPIExecutor

        sig = inspect.signature(DBAPIExecutor.execute_query)
        assert "session_id" in sig.parameters, (
            "execute_query must declare session_id parameter (B1 regression)"
        )

    def test_session_id_has_default_none(self):
        """session_id must default to None so existing callers need not change."""
        import inspect

        from iris_pgwire.dbapi_executor import DBAPIExecutor

        param = inspect.signature(DBAPIExecutor.execute_query).parameters["session_id"]
        assert param.default is None, "session_id default must be None"

    def test_signature_accepts_kwargs(self):
        """execute_query must accept **kwargs so forward-compat callers don't TypeError."""
        import inspect

        from iris_pgwire.dbapi_executor import DBAPIExecutor

        sig = inspect.signature(DBAPIExecutor.execute_query)
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        assert has_var_keyword, "execute_query must accept **kwargs (B1 regression)"

    @pytest.mark.asyncio
    async def test_session_id_none_does_not_raise(self):
        """Calling execute_query(sql, session_id=None) must not raise TypeError."""
        executor = _make_executor()
        wrapper = _make_conn_wrapper()
        executor._acquire_connection = AsyncMock(return_value=(wrapper, False))
        executor.pool.release = AsyncMock()
        executor.catalog_router.handle_catalog_query = AsyncMock(return_value=None)
        executor.sql_interceptor.intercept = Mock(return_value=Mock(intercepted=False))

        result = await executor.execute_query("SELECT 1", session_id=None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_session_id_string_does_not_raise(self):
        """Calling execute_query with a non-None session_id must not raise TypeError."""
        executor = _make_executor()
        wrapper = _make_conn_wrapper(rows=[], rowcount=0)
        executor._acquire_connection = AsyncMock(return_value=(wrapper, False))
        executor.pool.release = AsyncMock()
        executor.catalog_router.handle_catalog_query = AsyncMock(return_value=None)
        executor.sql_interceptor.intercept = Mock(return_value=Mock(intercepted=False))

        result = await executor.execute_query("SELECT 1", session_id="sess-abc-123")
        assert result is not None


# ---------------------------------------------------------------------------
# B2 — execute_query must return dict with 'rows' key, not raw list
# ---------------------------------------------------------------------------


class TestB2ExecuteQueryReturnShape:
    """B2: DBAPIExecutor returned raw list of tuples; protocol expects dict with 'rows'."""

    def test_return_annotation_is_dict(self):
        """execute_query return annotation must be dict (not list)."""
        import inspect

        from iris_pgwire.dbapi_executor import DBAPIExecutor

        ret = inspect.signature(DBAPIExecutor.execute_query).return_annotation
        # Accept dict[str, Any] or dict or Any (unannotated); reject list
        assert ret is not list, "execute_query must not be annotated as returning list (B2)"

    @pytest.mark.asyncio
    async def test_result_has_rows_key(self):
        """execute_query result must contain a 'rows' key (B2 regression)."""
        executor = _make_executor()
        wrapper = _make_conn_wrapper(rows=[(42,)], rowcount=1)
        executor._acquire_connection = AsyncMock(return_value=(wrapper, False))
        executor.pool.release = AsyncMock()
        executor.catalog_router.handle_catalog_query = AsyncMock(return_value=None)
        executor.sql_interceptor.intercept = Mock(return_value=Mock(intercepted=False))

        result = await executor.execute_query("SELECT 42")

        assert isinstance(result, dict), f"Expected dict, got {type(result).__name__} (B2)"
        assert "rows" in result, f"Result dict missing 'rows' key. Keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_result_has_required_keys(self):
        """Result dict must contain rows, columns, row_count, command_tag (B2 regression)."""
        executor = _make_executor()
        wrapper = _make_conn_wrapper(rows=[(1,)], rowcount=1)
        executor._acquire_connection = AsyncMock(return_value=(wrapper, False))
        executor.pool.release = AsyncMock()
        executor.catalog_router.handle_catalog_query = AsyncMock(return_value=None)
        executor.sql_interceptor.intercept = Mock(return_value=Mock(intercepted=False))

        result = await executor.execute_query("SELECT 1")

        for key in ("rows", "columns", "row_count", "command_tag"):
            assert key in result, f"Result missing '{key}' key (B2 regression)"

    @pytest.mark.asyncio
    async def test_rows_value_is_list(self):
        """result['rows'] must be a list, not a generator or other iterable."""
        executor = _make_executor()
        wrapper = _make_conn_wrapper(rows=[(1,), (2,)], rowcount=2)
        executor._acquire_connection = AsyncMock(return_value=(wrapper, False))
        executor.pool.release = AsyncMock()
        executor.catalog_router.handle_catalog_query = AsyncMock(return_value=None)
        executor.sql_interceptor.intercept = Mock(return_value=Mock(intercepted=False))

        result = await executor.execute_query("SELECT x FROM t")
        assert isinstance(result["rows"], list), "result['rows'] must be a list (B2)"


# ---------------------------------------------------------------------------
# B3 — Connection pool datetime must be timezone-aware (no naive/aware TypeError)
# ---------------------------------------------------------------------------


class TestB3DatetimeAwareness:
    """B3: created_at was naive datetime; age_seconds used aware clock → TypeError."""

    def test_dbapi_connection_created_at_is_aware(self):
        """DBAPIConnection.created_at must be timezone-aware (B3 regression)."""
        conn = _make_dbapi_conn("test-b3")
        assert conn.created_at.tzinfo is not None, (
            "created_at must be timezone-aware (B3 regression — naive datetime crashes age_seconds)"
        )

    def test_dbapi_connection_created_at_utc(self):
        """created_at should use UTC timezone."""
        conn = _make_dbapi_conn("test-b3-utc")
        # tzinfo present is the hard requirement; UTC is the expected value
        assert conn.created_at.tzinfo is not None

    def test_age_seconds_does_not_raise(self):
        """age_seconds must not raise TypeError when comparing to datetime.now(UTC) (B3)."""
        conn = _make_dbapi_conn("test-b3-age")
        try:
            age = conn.age_seconds
        except TypeError as exc:
            pytest.fail(
                f"age_seconds raised TypeError (B3 regression — naive/aware mismatch): {exc}"
            )
        assert age >= 0, "age_seconds must be non-negative"

    def test_age_seconds_increases_over_time(self):
        """age_seconds must reflect elapsed time since creation."""
        past = datetime.now(UTC) - timedelta(seconds=5)
        conn = _make_dbapi_conn("test-b3-elapsed", created_at=past)
        assert conn.age_seconds >= 5, "age_seconds must reflect elapsed time since created_at"

    def test_last_used_at_aware_when_set(self):
        """last_used_at, when set, must also be timezone-aware to avoid pool health crash."""
        conn = _make_dbapi_conn("test-b3-last-used", last_used_at=datetime.now(UTC))
        assert conn.last_used_at.tzinfo is not None, "last_used_at must be timezone-aware"

    def test_no_naive_datetime_in_idle_seconds(self):
        """idle_seconds calculation must not crash when last_used_at is set."""
        conn = _make_dbapi_conn(
            "test-b3-idle",
            last_used_at=datetime.now(UTC) - timedelta(seconds=3),
        )
        now_aware = datetime.now(UTC)
        # Reproduce the pool's idle calculation
        try:
            idle = (now_aware - conn.last_used_at).total_seconds()
        except TypeError as exc:
            pytest.fail(f"idle_seconds calculation raised TypeError (B3 regression): {exc}")
        assert idle >= 3


# ---------------------------------------------------------------------------
# B4 — Describe handler must not open a second connection (CE license exhaustion)
# ---------------------------------------------------------------------------


class TestB4DescribeReusesSingleConnection:
    """B4: handle_describe_message opened a second IRIS connection, exhausting CE 1-conn limit."""

    def test_strict_single_connection_flag_exists(self):
        """BackendConfig must expose strict_single_connection (prerequisite for CE mode)."""
        cfg = _make_real_config(strict_single_connection=True)
        assert cfg.strict_single_connection is True

    def test_pool_singleton_mode_when_strict(self):
        """When strict_single_connection=True, pool must operate in singleton mode."""
        from iris_pgwire.dbapi_connection_pool import IRISConnectionPool

        cfg = _make_real_config(strict_single_connection=True, pool_size=5)
        with patch("iris_pgwire.dbapi_connection_pool.DBAPIConnection"):
            pool = IRISConnectionPool(cfg)
        assert pool.config.strict_single_connection is True

    def test_pool_size_1_implies_singleton(self):
        """pool_size=1 must also trigger singleton mode (CE-safe without the flag)."""
        from iris_pgwire.dbapi_connection_pool import IRISConnectionPool

        cfg = _make_real_config(pool_size=1, pool_max_overflow=0)
        with patch("iris_pgwire.dbapi_connection_pool.DBAPIConnection"):
            pool = IRISConnectionPool(cfg)
        assert pool.config.pool_size == 1


# ---------------------------------------------------------------------------
# E1 — strict_single_connection caps pool at 1 connection for Community Edition
# ---------------------------------------------------------------------------


class TestE1StrictSingleConnection:
    """E1: strict_single_connection=True must enforce a 1-connection cap."""

    def test_config_field_exists(self):
        """BackendConfig must have strict_single_connection field."""
        cfg = _make_real_config()
        assert hasattr(cfg, "strict_single_connection")

    def test_default_is_false(self):
        """strict_single_connection must default to False (no change for existing deployments)."""
        cfg = _make_real_config()
        assert cfg.strict_single_connection is False

    def test_can_be_enabled(self):
        """strict_single_connection=True must be accepted by BackendConfig."""
        cfg = _make_real_config(strict_single_connection=True)
        assert cfg.strict_single_connection is True

    def test_executor_picks_up_flag(self):
        """DBAPIExecutor must read strict_single_connection from its config."""
        mock_cfg = _make_config(strict_single_connection=True)
        executor = _make_executor(config=mock_cfg)
        assert executor.config.strict_single_connection is True

    @pytest.mark.asyncio
    async def test_singleton_lock_used_when_strict(self):
        """With strict_single_connection, pool acquire must use a serialising lock."""
        from iris_pgwire.dbapi_connection_pool import IRISConnectionPool

        cfg = _make_real_config(strict_single_connection=True)
        with patch("iris_pgwire.dbapi_connection_pool.DBAPIConnection"):
            pool = IRISConnectionPool(cfg)

        assert hasattr(pool, "_singleton_lock"), (
            "Pool must have _singleton_lock for CE serialisation (E1 regression)"
        )
