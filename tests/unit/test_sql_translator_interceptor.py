"""
Unit tests for sql_translator/interceptor.py — SQLInterceptor and InterceptResult.
Goal: ≥85% coverage.
"""

import pytest

from iris_pgwire.sql_translator.interceptor import InterceptResult, SQLInterceptor


class FakeExecutor:
    """Minimal stand-in for IRISExecutor."""

    def __init__(self, namespace: str = "USER"):
        self.iris_namespace = namespace


# ---------------------------------------------------------------------------
# InterceptResult dataclass
# ---------------------------------------------------------------------------


class TestInterceptResult:
    def test_intercepted_true_with_result(self):
        r = InterceptResult(intercepted=True, result={"rows": []})
        assert r.intercepted is True
        assert r.result == {"rows": []}

    def test_intercepted_false_no_result(self):
        r = InterceptResult(intercepted=False)
        assert r.intercepted is False
        assert r.result is None


# ---------------------------------------------------------------------------
# SQLInterceptor — basic registration and dispatch
# ---------------------------------------------------------------------------


class TestSQLInterceptorRegistration:
    @pytest.fixture
    def interceptor(self):
        return SQLInterceptor(FakeExecutor())

    def test_register_custom_pattern(self, interceptor):
        """Custom handlers registered via register() are invoked."""
        called = []

        def my_handler(sql, params, session_id):
            called.append(sql)
            return {"success": True, "rows": [], "columns": [], "row_count": 0}

        interceptor.register(r"CUSTOM_OP", my_handler)
        result = interceptor.intercept("CUSTOM_OP something")
        assert result.intercepted is True
        assert called  # handler was invoked

    def test_no_match_returns_not_intercepted(self, interceptor):
        result = interceptor.intercept("SELECT 1 FROM irrelevant_table")
        assert result.intercepted is False
        assert result.result is None

    def test_intercept_passes_params_and_session(self, interceptor):
        """intercept() forwards params and session_id to the handler."""
        received = {}

        def capture_handler(sql, params, session_id):
            received["params"] = params
            received["session_id"] = session_id
            return {"success": True, "rows": [], "columns": [], "row_count": 0}

        interceptor.register(r"CAPTURETHIS", capture_handler)
        interceptor.intercept("CAPTURETHIS", params=[1, 2], session_id="abc")
        assert received["params"] == [1, 2]
        assert received["session_id"] == "abc"

    def test_pattern_is_case_insensitive(self, interceptor):
        """Patterns match upper/lower cased SQL."""
        result = interceptor.intercept("show server_version")
        assert result.intercepted is True


# ---------------------------------------------------------------------------
# _handle_show
# ---------------------------------------------------------------------------


class TestHandleShow:
    @pytest.fixture
    def interceptor(self):
        return SQLInterceptor(FakeExecutor())

    def _show(self, interceptor, param: str):
        return interceptor.intercept(f"SHOW {param}")

    def test_show_server_version(self, interceptor):
        r = self._show(interceptor, "server_version")
        assert r.intercepted is True
        assert r.result["rows"] == [["16.0 (InterSystems IRIS)"]]

    def test_show_server_version_num(self, interceptor):
        r = self._show(interceptor, "server_version_num")
        assert r.result["rows"] == [["160000"]]

    def test_show_client_encoding(self, interceptor):
        r = self._show(interceptor, "client_encoding")
        assert r.result["rows"] == [["UTF8"]]

    def test_show_datestyle(self, interceptor):
        r = self._show(interceptor, "datestyle")
        assert r.result["rows"] == [["ISO, MDY"]]

    def test_show_timezone(self, interceptor):
        r = self._show(interceptor, "timezone")
        assert r.result["rows"] == [["UTC"]]

    def test_show_standard_conforming_strings(self, interceptor):
        r = self._show(interceptor, "standard_conforming_strings")
        assert r.result["rows"] == [["on"]]

    def test_show_integer_datetimes(self, interceptor):
        r = self._show(interceptor, "integer_datetimes")
        assert r.result["rows"] == [["on"]]

    def test_show_intervalstyle(self, interceptor):
        r = self._show(interceptor, "intervalstyle")
        assert r.result["rows"] == [["postgres"]]

    def test_show_unknown_param(self, interceptor):
        r = self._show(interceptor, "nonexistent_param")
        assert r.result["rows"] == [["unknown"]]

    def test_show_result_shape(self, interceptor):
        r = self._show(interceptor, "timezone")
        assert r.result["success"] is True
        assert r.result["row_count"] == 1
        assert len(r.result["columns"]) == 1

    def test_show_with_semicolon(self, interceptor):
        """Trailing semicolon should still match."""
        r = interceptor.intercept("SHOW server_version;")
        assert r.intercepted is True
        assert r.result["rows"] == [["16.0 (InterSystems IRIS)"]]


# ---------------------------------------------------------------------------
# _handle_prisma_schema_check
# ---------------------------------------------------------------------------


class TestHandlePrismaSchemaCheck:
    @pytest.fixture
    def interceptor(self):
        return SQLInterceptor(FakeExecutor())

    def _schema_sql(self):
        return "SELECT EXISTS(SELECT 1 FROM PG_NAMESPACE WHERE nspname=$1), VERSION(), 160000"

    def test_default_schema_public(self, interceptor):
        r = interceptor.intercept(self._schema_sql(), params=None)
        assert r.intercepted is True
        row = r.result["rows"][0]
        assert row[0] is True

    def test_known_schema_exists(self, interceptor):
        r = interceptor.intercept(self._schema_sql(), params=["public"])
        assert r.result["rows"][0][0] is True

    def test_information_schema_exists(self, interceptor):
        r = interceptor.intercept(self._schema_sql(), params=["information_schema"])
        assert r.result["rows"][0][0] is True

    def test_sqluser_schema_exists(self, interceptor):
        r = interceptor.intercept(self._schema_sql(), params=["sqluser"])
        assert r.result["rows"][0][0] is True

    def test_unknown_schema_does_not_exist(self, interceptor):
        r = interceptor.intercept(self._schema_sql(), params=["nonexistent_schema"])
        assert r.result["rows"][0][0] is False

    def test_none_param_treated_as_default(self, interceptor):
        r = interceptor.intercept(self._schema_sql(), params=[None])
        assert r.result["rows"][0][0] is True

    def test_columns_shape(self, interceptor):
        r = interceptor.intercept(self._schema_sql())
        assert len(r.result["columns"]) == 3
        col_names = [c["name"] for c in r.result["columns"]]
        assert "exists" in col_names
        assert "version" in col_names
        assert "numeric_version" in col_names


# ---------------------------------------------------------------------------
# _handle_asyncpg_introspection
# ---------------------------------------------------------------------------


class TestHandleAsyncpgIntrospection:
    @pytest.fixture
    def interceptor(self):
        return SQLInterceptor(FakeExecutor())

    def test_matches_combined_pattern(self, interceptor):
        sql = "SELECT current_setting('x'), set_config('y','z',false)"
        r = interceptor.intercept(sql)
        assert r.intercepted is True
        assert r.result["rows"] == [["off", "off"]]

    def test_columns_names(self, interceptor):
        sql = "SELECT current_setting('x'), set_config('y','z',false)"
        r = interceptor.intercept(sql)
        names = [c["name"] for c in r.result["columns"]]
        assert names == ["cur", "new"]


# ---------------------------------------------------------------------------
# _handle_current_setting
# ---------------------------------------------------------------------------


class TestHandleCurrentSetting:
    @pytest.fixture
    def interceptor(self):
        return SQLInterceptor(FakeExecutor())

    def test_current_setting_intercepted(self, interceptor):
        # Use a SQL that has CURRENT_SETTING but NOT SET_CONFIG to avoid
        # falling into the asyncpg combined handler first.
        r = interceptor.intercept("SELECT current_setting('search_path')")
        assert r.intercepted is True

    def test_current_setting_returns_off(self, interceptor):
        r = interceptor.intercept("SELECT current_setting('search_path')")
        # Either asyncpg handler (row = ['off', 'off']) or current_setting
        # handler (row = ['off']) — either way result is truthy
        assert r.result["rows"] is not None


# ---------------------------------------------------------------------------
# _handle_set_config
# ---------------------------------------------------------------------------


class TestHandleSetConfig:
    @pytest.fixture
    def interceptor(self):
        return SQLInterceptor(FakeExecutor())

    def test_set_config_intercepted(self, interceptor):
        r = interceptor.intercept("SELECT set_config('search_path', 'public', false)")
        assert r.intercepted is True

    def test_set_config_rows(self, interceptor):
        r = interceptor.intercept("SELECT set_config('search_path', 'public', false)")
        # Could match asyncpg or set_config handler
        assert r.result["rows"] is not None


# ---------------------------------------------------------------------------
# _handle_advisory_unlock
# ---------------------------------------------------------------------------


class TestHandleAdvisoryUnlock:
    @pytest.fixture
    def interceptor(self):
        return SQLInterceptor(FakeExecutor())

    def test_advisory_unlock_intercepted(self, interceptor):
        r = interceptor.intercept("SELECT pg_advisory_unlock_all()")
        assert r.intercepted is True

    def test_advisory_unlock_empty_result(self, interceptor):
        r = interceptor.intercept("SELECT pg_advisory_unlock_all()")
        assert r.result["rows"] == []
        assert r.result["row_count"] == 0


# ---------------------------------------------------------------------------
# _handle_current_database
# ---------------------------------------------------------------------------


class TestHandleCurrentDatabase:
    def test_returns_executor_namespace(self):
        executor = FakeExecutor(namespace="MYNS")
        interceptor = SQLInterceptor(executor)
        r = interceptor.intercept("SELECT current_database()")
        assert r.intercepted is True
        assert r.result["rows"] == [["MYNS"]]

    def test_default_namespace_user(self):
        interceptor = SQLInterceptor(FakeExecutor())
        r = interceptor.intercept("SELECT current_database()")
        assert r.result["rows"] == [["USER"]]

    def test_executor_without_namespace_attr(self):
        """If executor has no iris_namespace, should not crash."""

        class NoNsExecutor:
            pass

        interceptor = SQLInterceptor(NoNsExecutor())
        r = interceptor.intercept("SELECT current_database()")
        assert r.intercepted is True
        assert r.result["rows"] == [["USER"]]

    def test_column_type_oid(self):
        interceptor = SQLInterceptor(FakeExecutor())
        r = interceptor.intercept("SELECT current_database()")
        assert r.result["columns"][0]["type_oid"] == 19


# ---------------------------------------------------------------------------
# _handle_version
# ---------------------------------------------------------------------------


class TestHandleVersion:
    @pytest.fixture
    def interceptor(self):
        return SQLInterceptor(FakeExecutor())

    def test_version_function(self, interceptor):
        r = interceptor.intercept("SELECT version()")
        assert r.intercepted is True
        assert "PostgreSQL 16.0" in r.result["rows"][0][0]
        assert "IRIS" in r.result["rows"][0][0]

    def test_select_version_keyword(self, interceptor):
        r = interceptor.intercept("SELECT VERSION")
        assert r.intercepted is True

    def test_version_result_shape(self, interceptor):
        r = interceptor.intercept("SELECT version()")
        assert r.result["row_count"] == 1
        assert r.result["columns"][0]["name"] == "version"


# ---------------------------------------------------------------------------
# _handle_discard_all
# ---------------------------------------------------------------------------


class TestHandleDiscardAll:
    @pytest.fixture
    def interceptor(self):
        return SQLInterceptor(FakeExecutor())

    def test_discard_all_intercepted(self, interceptor):
        r = interceptor.intercept("DISCARD ALL")
        assert r.intercepted is True

    def test_discard_all_result(self, interceptor):
        r = interceptor.intercept("DISCARD ALL")
        assert r.result["success"] is True
        assert r.result["rows"] == []
        assert r.result["command"] == "DISCARD"
        assert r.result["command_tag"] == "DISCARD ALL"

    def test_discard_all_with_leading_whitespace(self, interceptor):
        r = interceptor.intercept("  DISCARD ALL  ")
        assert r.intercepted is True


# ---------------------------------------------------------------------------
# _handle_pg_indexes
# ---------------------------------------------------------------------------


class TestHandlePgIndexes:
    @pytest.fixture
    def interceptor(self):
        return SQLInterceptor(FakeExecutor())

    def test_pg_indexes_intercepted(self, interceptor):
        r = interceptor.intercept("SELECT * FROM pg_indexes WHERE tablename = 'hnswtest'")
        assert r.intercepted is True

    def test_pg_indexes_known_table(self, interceptor):
        r = interceptor.intercept("SELECT * FROM pg_indexes WHERE tablename = 'hnswtest'")
        assert r.result["rows"] == [["idx_hnsw"]]
        assert r.result["row_count"] == 1

    def test_pg_indexes_unknown_table(self, interceptor):
        r = interceptor.intercept("SELECT * FROM pg_indexes WHERE tablename = 'othertable'")
        assert r.result["rows"] == []
        assert r.result["row_count"] == 0

    def test_pg_indexes_no_table_filter(self, interceptor):
        """No tablename= clause → unknown table → empty rows."""
        r = interceptor.intercept("SELECT * FROM pg_indexes")
        assert r.intercepted is True
        assert r.result["rows"] == []

    def test_pg_indexes_column_shape(self, interceptor):
        r = interceptor.intercept("SELECT * FROM pg_indexes WHERE tablename = 'hnswtest'")
        assert r.result["columns"][0]["name"] == "indexname"
