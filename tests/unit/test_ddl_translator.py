"""Unit tests for DDLTranslator (src/iris_pgwire/sql_translator/ddl_translator.py)."""

from __future__ import annotations

import pytest

from iris_pgwire.config import DDLTranslationConfig
from iris_pgwire.sql_translator.ddl_parser import (
    ColumnDefinition,
    ConstraintDefinition,
    ConstraintType,
    DDLParser,
)
from iris_pgwire.sql_translator.ddl_translator import (
    DDLStatement,
    DDLTranslationError,
    DDLTranslator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_column(
    name: str = "id",
    pg_type: str = "integer",
    iris_type: str = "INTEGER",
    nullable: bool = True,
    default: str | None = None,
    is_primary_key: bool = False,
) -> ColumnDefinition:
    return ColumnDefinition(
        name=name,
        pg_type=pg_type,
        iris_type=iris_type,
        nullable=nullable,
        default=default,
        is_primary_key=is_primary_key,
    )


def make_create_table_stmt(
    table_name: str = "users",
    schema_name: str | None = None,
    columns: tuple[ColumnDefinition, ...] = (),
    constraints: tuple[ConstraintDefinition, ...] = (),
) -> DDLStatement:
    return DDLStatement(
        raw_sql="CREATE TABLE users (id INTEGER)",
        statement_type="CREATE_TABLE",
        table_name=table_name,
        schema_name=schema_name,
        columns=columns,
        constraints=constraints,
    )


# ---------------------------------------------------------------------------
# DDLTranslationError
# ---------------------------------------------------------------------------


class TestDDLTranslationError:
    def test_str_without_fix(self):
        err = DDLTranslationError(
            error_code="E001",
            message="bad type",
            suggested_fix=None,
            original_sql="CREATE TABLE t (x BADTYPE)",
        )
        assert str(err) == "E001: bad type"

    def test_str_with_fix(self):
        err = DDLTranslationError(
            error_code="E002",
            message="overflow",
            suggested_fix="reduce precision",
            original_sql="",
        )
        # __str__ only uses error_code + message
        assert "E002" in str(err)
        assert "overflow" in str(err)


# ---------------------------------------------------------------------------
# DDLStatement dataclass
# ---------------------------------------------------------------------------


class TestDDLStatement:
    def test_defaults(self):
        stmt = DDLStatement(raw_sql="", statement_type="CREATE_TABLE")
        assert stmt.translated_sql is None
        assert stmt.is_translatable is True
        assert stmt.columns == ()
        assert stmt.constraints == ()
        assert stmt.translation_warnings == ()

    def test_fields_preserved(self):
        stmt = DDLStatement(
            raw_sql="raw",
            statement_type="DROP_TABLE",
            table_name="t",
            is_translatable=False,
            skip_reason="dropped",
        )
        assert stmt.table_name == "t"
        assert not stmt.is_translatable
        assert stmt.skip_reason == "dropped"


# ---------------------------------------------------------------------------
# DDLTranslator.translate_statement dispatch
# ---------------------------------------------------------------------------


class TestTranslateStatementDispatch:
    @pytest.fixture
    def translator(self):
        return DDLTranslator()

    def test_create_table_dispatched(self, translator):
        col = make_column("id", "integer", "INTEGER")
        stmt = make_create_table_stmt(columns=(col,))
        result = translator.translate_statement(stmt)
        assert result.statement_type == "CREATE_TABLE"
        assert result.is_translatable

    def test_drop_table_dispatched(self, translator):
        stmt = DDLStatement(
            raw_sql="DROP TABLE users",
            statement_type="DROP_TABLE",
            table_name="users",
        )
        result = translator.translate_statement(stmt)
        assert not result.is_translatable
        assert "DROP TABLE" in result.skip_reason

    def test_unsupported_statement_type(self, translator):
        stmt = DDLStatement(
            raw_sql="CREATE VIEW v AS SELECT 1",
            statement_type="CREATE_VIEW",
        )
        result = translator.translate_statement(stmt)
        assert not result.is_translatable
        assert "Unsupported statement type" in result.skip_reason

    def test_alter_add_column_dispatched(self, translator):
        col = make_column("email", "text", "VARCHAR(32767)")
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users ADD COLUMN email TEXT",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="ADD_COLUMN",
            columns=(col,),
        )
        result = translator.translate_statement(stmt)
        assert result.is_translatable
        assert "ALTER TABLE" in result.translated_sql

    def test_alter_drop_column_dispatched(self, translator):
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users DROP COLUMN email",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="DROP_COLUMN",
            operation_details={"column_name": "email"},
        )
        result = translator.translate_statement(stmt)
        assert result.is_translatable
        assert "DROP COLUMN" in result.translated_sql

    def test_alter_rename_column_dispatched(self, translator):
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users RENAME COLUMN foo TO bar",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="RENAME_COLUMN",
        )
        result = translator.translate_statement(stmt)
        assert not result.is_translatable
        assert "RENAME COLUMN" in result.skip_reason

    def test_alter_unsupported_operation(self, translator):
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users RENAME TO new_users",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="RENAME_TABLE",
        )
        result = translator.translate_statement(stmt)
        assert not result.is_translatable
        assert "Unsupported ALTER TABLE operation" in result.skip_reason

    def test_exception_during_translation_caught(self, translator, monkeypatch):
        """Generic exceptions inside translate_create_table are caught and reported."""

        def boom(stmt):
            raise ValueError("unexpected boom")

        monkeypatch.setattr(translator, "translate_create_table", boom)
        col = make_column()
        stmt = make_create_table_stmt(columns=(col,))
        result = translator.translate_statement(stmt)
        assert not result.is_translatable
        assert "unexpected boom" in result.skip_reason


# ---------------------------------------------------------------------------
# translate_create_table
# ---------------------------------------------------------------------------


class TestTranslateCreateTable:
    @pytest.fixture
    def translator(self):
        return DDLTranslator()

    def test_simple_table(self, translator):
        col = make_column("id", "integer", "INTEGER", nullable=False, is_primary_key=True)
        stmt = make_create_table_stmt(columns=(col,))
        result = translator.translate_create_table(stmt)
        assert result.is_translatable
        sql = result.translated_sql
        assert "CREATE TABLE" in sql
        assert "users" in sql.lower() or "users" in sql

    def test_schema_qualified_table(self, translator):
        col = make_column("id", "integer", "INTEGER")
        stmt = make_create_table_stmt(
            table_name="users", schema_name="public", columns=(col,)
        )
        result = translator.translate_create_table(stmt)
        assert result.is_translatable
        assert "public" in result.translated_sql.lower() or "PUBLIC" in result.translated_sql

    def test_missing_table_name_returns_not_translatable(self, translator):
        col = make_column()
        stmt = DDLStatement(
            raw_sql="CREATE TABLE (id INTEGER)",
            statement_type="CREATE_TABLE",
            table_name=None,
            columns=(col,),
        )
        result = translator.translate_create_table(stmt)
        assert not result.is_translatable
        assert "Missing table name" in result.skip_reason

    def test_empty_columns_produces_empty_body(self, translator):
        stmt = make_create_table_stmt(columns=())
        result = translator.translate_create_table(stmt)
        assert result.is_translatable
        assert "()" in result.translated_sql

    def test_multiple_columns(self, translator):
        cols = (
            make_column("id", "integer", "INTEGER", nullable=False, is_primary_key=True),
            make_column("name", "text", "VARCHAR(32767)", nullable=False),
            make_column("score", "numeric", "NUMERIC", nullable=True),
        )
        stmt = make_create_table_stmt(columns=cols)
        result = translator.translate_create_table(stmt)
        assert result.is_translatable
        assert "NOT NULL" in result.translated_sql

    def test_with_primary_key_constraint(self, translator):
        col = make_column("id", "integer", "INTEGER")
        pk_constraint = ConstraintDefinition(
            constraint_type=ConstraintType.PRIMARY_KEY, columns=("id",)
        )
        stmt = make_create_table_stmt(columns=(col,), constraints=(pk_constraint,))
        result = translator.translate_create_table(stmt)
        assert result.is_translatable

    def test_column_with_default_value(self, translator):
        col = make_column(
            "created_at",
            "timestamp",
            "TIMESTAMP",
            default="CURRENT_TIMESTAMP",
        )
        stmt = make_create_table_stmt(columns=(col,))
        result = translator.translate_create_table(stmt)
        assert result.is_translatable
        assert "DEFAULT" in result.translated_sql

    def test_column_with_skip_default(self, translator):
        col = make_column("id", "uuid", "UUID", default="__SKIP_DEFAULT__")
        stmt = make_create_table_stmt(columns=(col,))
        result = translator.translate_create_table(stmt)
        assert result.is_translatable
        # __SKIP_DEFAULT__ should not appear in output
        assert "__SKIP_DEFAULT__" not in result.translated_sql


# ---------------------------------------------------------------------------
# translate_alter_add_column
# ---------------------------------------------------------------------------


class TestTranslateAlterAddColumn:
    @pytest.fixture
    def translator(self):
        return DDLTranslator()

    def test_basic_add_column(self, translator):
        col = make_column("email", "text", "VARCHAR(32767)")
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users ADD COLUMN email TEXT",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="ADD_COLUMN",
            columns=(col,),
        )
        result = translator.translate_alter_add_column(stmt)
        assert result.is_translatable
        assert "ALTER TABLE" in result.translated_sql
        assert "ADD COLUMN" in result.translated_sql

    def test_missing_table_name(self, translator):
        col = make_column("email", "text", "VARCHAR(32767)")
        stmt = DDLStatement(
            raw_sql="ALTER TABLE ADD COLUMN email TEXT",
            statement_type="ALTER_TABLE",
            table_name=None,
            operation="ADD_COLUMN",
            columns=(col,),
        )
        result = translator.translate_alter_add_column(stmt)
        assert not result.is_translatable
        assert "Missing table name" in result.skip_reason

    def test_missing_column_definition(self, translator):
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users ADD COLUMN",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="ADD_COLUMN",
            columns=(),
        )
        result = translator.translate_alter_add_column(stmt)
        assert not result.is_translatable
        assert "Missing column definition" in result.skip_reason


# ---------------------------------------------------------------------------
# translate_alter_drop_column
# ---------------------------------------------------------------------------


class TestTranslateAlterDropColumn:
    @pytest.fixture
    def translator(self):
        return DDLTranslator()

    def test_basic_drop_column(self, translator):
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users DROP COLUMN email",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="DROP_COLUMN",
            operation_details={"column_name": "email"},
        )
        result = translator.translate_alter_drop_column(stmt)
        assert result.is_translatable
        assert "DROP COLUMN" in result.translated_sql

    def test_missing_table_name(self, translator):
        stmt = DDLStatement(
            raw_sql="ALTER TABLE DROP COLUMN email",
            statement_type="ALTER_TABLE",
            table_name=None,
            operation="DROP_COLUMN",
            operation_details={"column_name": "email"},
        )
        result = translator.translate_alter_drop_column(stmt)
        assert not result.is_translatable
        assert "Missing table name" in result.skip_reason

    def test_missing_column_name(self, translator):
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users DROP COLUMN",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="DROP_COLUMN",
            operation_details={},
        )
        result = translator.translate_alter_drop_column(stmt)
        assert not result.is_translatable
        assert "Missing column name" in result.skip_reason

    def test_missing_operation_details(self, translator):
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users DROP COLUMN",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="DROP_COLUMN",
            operation_details=None,
        )
        result = translator.translate_alter_drop_column(stmt)
        assert not result.is_translatable


# ---------------------------------------------------------------------------
# translate_alter_rename_column
# ---------------------------------------------------------------------------


class TestTranslateAlterRenameColumn:
    @pytest.fixture
    def translator(self):
        return DDLTranslator()

    def test_rename_not_supported(self, translator):
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users RENAME COLUMN foo TO bar",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="RENAME_COLUMN",
        )
        result = translator.translate_alter_rename_column(stmt)
        assert not result.is_translatable
        assert "RENAME COLUMN" in result.skip_reason

    def test_rename_adds_warning(self, translator):
        stmt = DDLStatement(
            raw_sql="ALTER TABLE users RENAME COLUMN foo TO bar",
            statement_type="ALTER_TABLE",
            table_name="users",
            operation="RENAME_COLUMN",
        )
        result = translator.translate_alter_rename_column(stmt)
        assert len(result.translation_warnings) > 0


# ---------------------------------------------------------------------------
# translate_drop_table
# ---------------------------------------------------------------------------


class TestTranslateDropTable:
    @pytest.fixture
    def translator(self):
        return DDLTranslator()

    def test_drop_table_not_translatable(self, translator):
        stmt = DDLStatement(
            raw_sql="DROP TABLE users",
            statement_type="DROP_TABLE",
            table_name="users",
        )
        result = translator.translate_drop_table(stmt)
        assert not result.is_translatable
        assert "DROP TABLE" in result.skip_reason

    def test_drop_table_has_warning(self, translator):
        stmt = DDLStatement(
            raw_sql="DROP TABLE users",
            statement_type="DROP_TABLE",
            table_name="users",
        )
        result = translator.translate_drop_table(stmt)
        assert len(result.translation_warnings) > 0


# ---------------------------------------------------------------------------
# _build_column_clause
# ---------------------------------------------------------------------------


class TestBuildColumnClause:
    @pytest.fixture
    def translator(self):
        return DDLTranslator()

    def test_simple_column(self, translator):
        col = make_column("name", "text", "VARCHAR(32767)", nullable=True)
        clause = translator._build_column_clause(col)
        assert "VARCHAR(32767)" in clause

    def test_not_null_column(self, translator):
        col = make_column("name", "text", "VARCHAR(32767)", nullable=False)
        clause = translator._build_column_clause(col)
        assert "NOT NULL" in clause

    def test_primary_key_column(self, translator):
        col = make_column("id", "integer", "INTEGER", nullable=False, is_primary_key=True)
        clause = translator._build_column_clause(col)
        assert "PRIMARY KEY" in clause

    def test_default_value_included(self, translator):
        col = make_column("ts", "timestamp", "TIMESTAMP", default="CURRENT_TIMESTAMP")
        clause = translator._build_column_clause(col)
        assert "DEFAULT CURRENT_TIMESTAMP" in clause

    def test_skip_default_marker_omitted(self, translator):
        col = make_column("uid", "uuid", "UUID", default="__SKIP_DEFAULT__")
        clause = translator._build_column_clause(col)
        assert "__SKIP_DEFAULT__" not in clause
        assert "DEFAULT" not in clause

    def test_empty_default_omitted(self, translator):
        col = make_column("x", "integer", "INTEGER", default="   ")
        clause = translator._build_column_clause(col)
        assert "DEFAULT" not in clause


# ---------------------------------------------------------------------------
# _build_table_identifier
# ---------------------------------------------------------------------------


class TestBuildTableIdentifier:
    @pytest.fixture
    def translator(self):
        return DDLTranslator()

    def test_table_only(self, translator):
        result = translator._build_table_identifier(None, "users")
        assert result is not None
        assert "users" in result.lower() or "users" in result

    def test_schema_and_table(self, translator):
        result = translator._build_table_identifier("public", "users")
        assert result is not None
        assert "." in result

    def test_none_table_name_returns_none(self, translator):
        result = translator._build_table_identifier(None, None)
        assert result is None

    def test_empty_table_name_returns_none(self, translator):
        result = translator._build_table_identifier(None, "")
        assert result is None


# ---------------------------------------------------------------------------
# _quote_identifier
# ---------------------------------------------------------------------------


class TestQuoteIdentifier:
    @pytest.fixture
    def translator(self):
        return DDLTranslator()

    def test_none_returns_none(self, translator):
        assert translator._quote_identifier(None) is None

    def test_empty_string_returns_none(self, translator):
        assert translator._quote_identifier("") is None

    def test_whitespace_only_returns_none(self, translator):
        assert translator._quote_identifier("   ") is None

    def test_already_quoted_preserved(self, translator):
        result = translator._quote_identifier('"my_table"')
        assert result == '"my_table"'

    def test_plain_identifier_returned(self, translator):
        result = translator._quote_identifier("users")
        assert result is not None
        assert "users" in result

    def test_no_auto_quote_when_disabled(self):
        config = DDLTranslationConfig(auto_quote_reserved_words=False)
        translator = DDLTranslator(config=config)
        result = translator._quote_identifier("select")
        # Without auto-quoting, should return as-is
        assert result == "select"


# ---------------------------------------------------------------------------
# Integration: parse + translate via DDLParser
# ---------------------------------------------------------------------------


class TestParseAndTranslateIntegration:
    @pytest.fixture
    def translator(self):
        return DDLTranslator()

    @pytest.fixture
    def parser(self):
        return DDLParser()

    def test_create_table_roundtrip(self, parser, translator):
        sql = "CREATE TABLE orders (id INTEGER NOT NULL, amount NUMERIC(10,2))"
        stmts = parser.parse(sql)
        assert stmts
        result = translator.translate_statement(stmts[0])
        assert result.is_translatable
        assert result.translated_sql is not None

    def test_alter_add_column_roundtrip(self, parser, translator):
        sql = "ALTER TABLE orders ADD COLUMN notes TEXT"
        stmts = parser.parse(sql)
        assert stmts
        result = translator.translate_statement(stmts[0])
        assert result.is_translatable
        assert "notes" in result.translated_sql.lower() or "NOTES" in result.translated_sql

    def test_alter_drop_column_roundtrip(self, parser, translator):
        sql = "ALTER TABLE orders DROP COLUMN notes"
        stmts = parser.parse(sql)
        assert stmts
        result = translator.translate_statement(stmts[0])
        assert result.is_translatable

    def test_drop_table_roundtrip(self, parser, translator):
        sql = "DROP TABLE orders"
        stmts = parser.parse(sql)
        assert stmts
        result = translator.translate_statement(stmts[0])
        assert not result.is_translatable

    def test_create_table_with_primary_key(self, parser, translator):
        sql = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        stmts = parser.parse(sql)
        assert stmts
        result = translator.translate_statement(stmts[0])
        assert result.is_translatable
        assert "PRIMARY KEY" in result.translated_sql

    def test_create_table_with_schema(self, parser, translator):
        sql = "CREATE TABLE public.events (id INTEGER, ts TIMESTAMP)"
        stmts = parser.parse(sql)
        assert stmts
        result = translator.translate_statement(stmts[0])
        assert result.is_translatable

    def test_translation_warnings_preserved_on_error(self, translator):
        stmt = DDLStatement(
            raw_sql="CREATE TABLE ()",
            statement_type="CREATE_TABLE",
            table_name=None,
            translation_warnings=("pre-existing warning",),
        )
        result = translator.translate_statement(stmt)
        assert not result.is_translatable
        assert "pre-existing warning" in result.translation_warnings

    def test_ddl_translation_error_captured_in_translate_statement(
        self, translator, monkeypatch
    ):
        """DDLTranslationError raised inside translate_create_table is caught."""

        def raise_ddl_error(stmt):
            raise DDLTranslationError(
                error_code="E_TEST",
                message="test error",
                suggested_fix="do something",
                original_sql=stmt.raw_sql,
            )

        monkeypatch.setattr(translator, "translate_create_table", raise_ddl_error)
        col = make_column()
        stmt = make_create_table_stmt(columns=(col,))
        result = translator.translate_statement(stmt)
        assert not result.is_translatable
        assert "test error" in result.skip_reason
