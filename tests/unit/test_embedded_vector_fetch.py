"""Embedded backend: a SELECT that projects a VECTOR column must return its rows.

Measured 2026-10-17 on IRIS 2026.2.0.221.0com: iterating an `iris.sql.exec` result whose
projection contains a VECTOR value raises
`<OBJECT DISPATCH>next+9^%SYS.Python.SQLResultSet.1 *Invalid argument type`, and the embedded
executor caught that, logged a warning and returned zero rows with a normal CommandComplete.

The fix re-fetches a read-only statement through `%SQL.Statement` in ODBC select mode, where a
vector arrives as text, and converts the three types whose ODBC form differs from their logical
form back to logical, so every non-vector value is exactly what the logical path produced. The
expected values below are the logical values IRIS returned for the same rows in that measurement.
Every other fetch error now propagates instead of becoming an empty success.
"""

import pytest

from iris_pgwire.embedded_vector_fetch import (
    inline_none_params,
    is_read_only_statement,
    is_vector_fetch_error,
    odbc_to_logical,
)
from iris_pgwire.iris_executor import IRISExecutor

VECTOR_FETCH_ERROR = RuntimeError(
    "<OBJECT DISPATCH>next+9^%SYS.Python.SQLResultSet.1 *Invalid argument type"
)


class TestIsVectorFetchError:
    def test_the_measured_error_is_recognised(self):
        assert is_vector_fetch_error(VECTOR_FETCH_ERROR)

    @pytest.mark.parametrize(
        "error",
        [
            RuntimeError("<UNDEFINED>zfoo+1^bar"),
            ValueError("Invalid argument type"),
            RuntimeError("SQLResultSet closed"),
        ],
    )
    def test_other_errors_are_not(self, error):
        assert not is_vector_fetch_error(error)


class TestIsReadOnlyStatement:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT id, v FROM t",
            "  select * from t where id = ?",
            "\n-- comment\nSELECT v FROM t",
            "/* c */ SELECT v FROM t",
            "(SELECT v FROM t)",
            "WITH q AS (SELECT v FROM t) SELECT * FROM q",
        ],
    )
    def test_reads(self, sql):
        assert is_read_only_statement(sql)

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO t (v) SELECT v FROM s",
            "UPDATE t SET v = TO_VECTOR('[1]', DOUBLE)",
            "DELETE FROM t",
            "CALL p()",
            "",
            "-- only a comment",
        ],
    )
    def test_writes_and_others_are_never_re_executed(self, sql):
        assert not is_read_only_statement(sql)


class TestOdbcToLogical:
    def test_date(self):
        assert odbc_to_logical("2026-10-17", "%Library.Date") == 67860

    def test_time(self):
        assert odbc_to_logical("12:34:56", "%Library.Time") == 45296

    def test_posixtime_fractional(self):
        assert odbc_to_logical("2026-10-17 12:34:56.5", "%Library.PosixTime") == (
            1154713745103346976
        )

    def test_posixtime_microseconds(self):
        assert odbc_to_logical("2026-10-17 12:34:56.123456", "%Library.PosixTime") == (
            1154713745102970432
        )

    @pytest.mark.parametrize(
        "type_class", ["%Library.Date", "%Library.Time", "%Library.PosixTime"]
    )
    def test_null_stays_null(self, type_class):
        # IRIS returns '' for SQL NULL in both modes; the caller's null normaliser handles it.
        assert odbc_to_logical("", type_class) == ""

    @pytest.mark.parametrize(
        "value,type_class",
        [
            (".1,.2", "%Library.Vector"),
            ("x", "%Library.String"),
            ("\x00", "%Library.String"),
            (9007199254740993, "%Library.BigInt"),
            (1, "%Library.Boolean"),
            (12.345, "%Library.Numeric"),
            ("2026-10-17 12:34:56", "%Library.TimeStamp"),
            ("anything", None),
        ],
    )
    def test_types_identical_in_both_modes_pass_through(self, value, type_class):
        assert odbc_to_logical(value, type_class) == value


class TestInlineNoneParams:
    """Extracted from `_safe_execute` unchanged, so the re-fetch binds exactly as the first run."""

    def test_no_none_binds_as_given(self):
        assert inline_none_params("SELECT ? , ?", [1, "a"]) == ("SELECT ? , ?", [1, "a"])

    def test_none_inlines_every_value(self):
        sql, params = inline_none_params(
            "SELECT * FROM t WHERE a = ? AND b = ? AND c = ? AND d = ?",
            [None, True, 2.5, "it's"],
        )
        assert sql == "SELECT * FROM t WHERE a = NULL AND b = 1 AND c = 2.5 AND d = 'it''s'"
        assert params == []

    def test_no_params(self):
        assert inline_none_params("SELECT 1", None) == ("SELECT 1", None)


class _RaisingResult:
    """Iterates like an `iris.sql.exec` result whose first fetch raises."""

    _meta = None

    def __init__(self, error):
        self._error = error

    def __iter__(self):
        raise self._error


class TestMaterialiseEmbeddedResult:
    @pytest.fixture
    def executor(self):
        return IRISExecutor.__new__(IRISExecutor)

    def test_a_fetch_error_is_raised_not_turned_into_zero_rows(self, executor):
        with pytest.raises(RuntimeError, match="UNDEFINED"):
            executor._materialize_embedded_result(
                _RaisingResult(RuntimeError("<UNDEFINED>zfoo+1^bar")),
                "SELECT a FROM t",
                "SELECT A FROM T",
                "SELECT a FROM t",
                None,
                executed_sql="SELECT a FROM t",
                params=None,
            )

    def test_the_vector_error_on_a_write_is_raised_not_re_executed(self, executor, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "iris_pgwire.iris_executor.refetch_in_odbc_mode",
            lambda *a, **k: calls.append(a) or [],
        )
        sql = "INSERT INTO t (v) VALUES (TO_VECTOR('[1]', DOUBLE))"
        with pytest.raises(RuntimeError, match="Invalid argument type"):
            executor._materialize_embedded_result(
                _RaisingResult(VECTOR_FETCH_ERROR), sql, sql.upper(), sql, None,
                executed_sql=sql, params=None,
            )
        assert calls == []

    def test_the_vector_error_on_a_read_uses_the_re_fetched_rows(self, executor, monkeypatch):
        monkeypatch.setattr(
            "iris_pgwire.iris_executor.refetch_in_odbc_mode",
            lambda iris_module, sql, params: [[1, ".1,.2"], [2, ""]],
        )
        monkeypatch.setattr(executor, "_import_iris", lambda: object(), raising=False)
        monkeypatch.setattr(
            executor, "_discover_metadata",
            lambda *a, **k: [
                {"name": "id", "type_oid": 23, "type_size": -1, "type_modifier": -1,
                 "format_code": 0},
                {"name": "v", "type_oid": 1043, "type_size": -1, "type_modifier": -1,
                 "format_code": 0},
            ],
            raising=False,
        )
        sql = "SELECT id, v FROM t WHERE id > ?"
        rows, columns = executor._materialize_embedded_result(
            _RaisingResult(VECTOR_FETCH_ERROR), sql, sql.upper(), sql, None,
            executed_sql=sql, params=[0],
        )
        assert rows == [[1, ".1,.2"], [2, None]]
        assert [c["name"] for c in columns] == ["id", "v"]
