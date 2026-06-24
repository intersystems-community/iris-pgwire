"""
Unit tests for conversions/ddl_idempotency.py — DdlResult, DdlErrorHandler.
Goal: ≥85% coverage.
"""

import pytest

from iris_pgwire.conversions.ddl_idempotency import DdlErrorHandler, DdlResult


# ---------------------------------------------------------------------------
# DdlResult dataclass
# ---------------------------------------------------------------------------


class TestDdlResult:
    def test_defaults(self):
        r = DdlResult(success=True)
        assert r.success is True
        assert r.skipped is False
        assert r.object_name is None
        assert r.object_type is None
        assert r.command is None
        assert r.warning is None
        assert r.error is None

    def test_failure_with_error(self):
        err = ValueError("something failed")
        r = DdlResult(success=False, error=err)
        assert r.success is False
        assert r.error is err

    def test_skipped_result(self):
        r = DdlResult(
            success=True,
            skipped=True,
            object_name="my_table",
            object_type="TABLE",
            warning="Object my_table already exists",
        )
        assert r.skipped is True
        assert r.object_name == "my_table"
        assert r.object_type == "TABLE"
        assert "my_table" in r.warning


# ---------------------------------------------------------------------------
# DdlErrorHandler — has_if_not_exists
# ---------------------------------------------------------------------------


class TestHasIfNotExists:
    @pytest.fixture
    def handler(self):
        return DdlErrorHandler()

    def test_if_not_exists_present(self, handler):
        assert handler.has_if_not_exists("CREATE TABLE IF NOT EXISTS t (id INT)") is True

    def test_if_not_exists_absent(self, handler):
        assert handler.has_if_not_exists("CREATE TABLE t (id INT)") is False

    def test_if_not_exists_case_insensitive(self, handler):
        assert handler.has_if_not_exists("create table if not exists t (id int)") is True

    def test_if_not_exists_marker_comment(self, handler):
        assert handler.has_if_not_exists("CREATE TABLE t (id INT) /* IF_NOT_EXISTS */") is True

    def test_marker_with_spaces(self, handler):
        assert handler.has_if_not_exists("CREATE TABLE t (id INT) /*  IF_NOT_EXISTS  */") is True


# ---------------------------------------------------------------------------
# DdlErrorHandler — extract_object_name
# ---------------------------------------------------------------------------


class TestExtractObjectName:
    @pytest.fixture
    def handler(self):
        return DdlErrorHandler()

    def test_create_table(self, handler):
        assert handler.extract_object_name("CREATE TABLE my_table (id INT)") == "my_table"

    def test_create_table_if_not_exists(self, handler):
        assert (
            handler.extract_object_name("CREATE TABLE IF NOT EXISTS my_table (id INT)")
            == "my_table"
        )

    def test_create_index(self, handler):
        assert (
            handler.extract_object_name("CREATE INDEX my_idx ON t (col)") == "my_idx"
        )

    def test_create_unique_index(self, handler):
        assert (
            handler.extract_object_name("CREATE UNIQUE INDEX my_uidx ON t (col)") == "my_uidx"
        )

    def test_create_index_if_not_exists(self, handler):
        assert (
            handler.extract_object_name("CREATE INDEX IF NOT EXISTS my_idx ON t (col)")
            == "my_idx"
        )

    def test_create_table_with_comment_marker(self, handler):
        sql = "CREATE TABLE /* IF_NOT_EXISTS */ t (id INT)"
        # comment is stripped before extraction
        assert handler.extract_object_name(sql) == "t"

    def test_unrecognised_ddl_returns_none(self, handler):
        assert handler.extract_object_name("DROP TABLE t") is None


# ---------------------------------------------------------------------------
# DdlErrorHandler — _extract_object_type
# ---------------------------------------------------------------------------


class TestExtractObjectType:
    @pytest.fixture
    def handler(self):
        return DdlErrorHandler()

    def test_table_type(self, handler):
        assert handler._extract_object_type("CREATE TABLE t (id INT)") == "TABLE"

    def test_index_type(self, handler):
        assert handler._extract_object_type("CREATE INDEX i ON t (c)") == "INDEX"

    def test_unique_index_type(self, handler):
        assert handler._extract_object_type("CREATE UNIQUE INDEX i ON t (c)") == "INDEX"

    def test_unknown_type_is_none(self, handler):
        assert handler._extract_object_type("DROP TABLE t") is None

    def test_case_insensitive_table(self, handler):
        assert handler._extract_object_type("create table t (id int)") == "TABLE"


# ---------------------------------------------------------------------------
# DdlErrorHandler — _is_duplicate_error
# ---------------------------------------------------------------------------


class TestIsDuplicateError:
    @pytest.fixture
    def handler(self):
        return DdlErrorHandler()

    def test_already_exists(self, handler):
        assert handler._is_duplicate_error("Object already exists") is True

    def test_already_exists_case_insensitive(self, handler):
        assert handler._is_duplicate_error("ALREADY exists") is True

    def test_duplicate_table_name(self, handler):
        assert handler._is_duplicate_error("Duplicate table name 'foo'") is True

    def test_duplicate_index_name(self, handler):
        assert handler._is_duplicate_error("Duplicate index name 'idx'") is True

    def test_sqlcode_pattern(self, handler):
        assert handler._is_duplicate_error("SQLCODE: -201") is True

    def test_non_duplicate_error(self, handler):
        assert handler._is_duplicate_error("Syntax error at token 'CREATE'") is False

    def test_empty_message(self, handler):
        assert handler._is_duplicate_error("") is False


# ---------------------------------------------------------------------------
# DdlErrorHandler — handle() integration
# ---------------------------------------------------------------------------


class TestHandle:
    @pytest.fixture
    def handler(self):
        return DdlErrorHandler()

    def test_duplicate_with_if_not_exists_skipped(self, handler):
        sql = "CREATE TABLE IF NOT EXISTS my_table (id INT)"
        error = Exception("Table already exists")
        result = handler.handle(sql, error)
        assert result.success is True
        assert result.skipped is True
        assert result.object_name == "my_table"
        assert result.object_type == "TABLE"
        assert "my_table" in result.warning

    def test_duplicate_without_if_not_exists_fails(self, handler):
        sql = "CREATE TABLE my_table (id INT)"
        error = Exception("Table already exists")
        result = handler.handle(sql, error)
        assert result.success is False
        assert result.error is error

    def test_non_duplicate_error_fails(self, handler):
        sql = "CREATE TABLE IF NOT EXISTS my_table (id INT)"
        error = Exception("Syntax error")
        result = handler.handle(sql, error)
        assert result.success is False
        assert result.error is error

    def test_duplicate_index_with_if_not_exists(self, handler):
        sql = "CREATE INDEX IF NOT EXISTS my_idx ON t (col)"
        error = Exception("Duplicate index name 'my_idx'")
        result = handler.handle(sql, error)
        assert result.success is True
        assert result.skipped is True
        assert result.object_name == "my_idx"
        assert result.object_type == "INDEX"

    def test_command_field_matches_type(self, handler):
        sql = "CREATE TABLE IF NOT EXISTS t (id INT)"
        error = Exception("already exists")
        result = handler.handle(sql, error)
        assert result.command == "TABLE"

    def test_handle_with_comment_marker(self, handler):
        """IF_NOT_EXISTS comment marker should also trigger skip."""
        sql = "CREATE TABLE t (id INT) /* IF_NOT_EXISTS */"
        error = Exception("already exists")
        result = handler.handle(sql, error)
        assert result.success is True
        assert result.skipped is True
