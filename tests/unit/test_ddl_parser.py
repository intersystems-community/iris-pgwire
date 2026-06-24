"""Unit tests for DDLParser — pure Python, no IRIS container required."""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.ddl_parser import (
    ColumnDefinition,
    ConstraintDefinition,
    ConstraintType,
    DDLParser,
)
from iris_pgwire.sql_translator.ddl_translator import DDLStatement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def parser() -> DDLParser:
    return DDLParser()


def _first(result: list[DDLStatement]) -> DDLStatement:
    assert len(result) >= 1, "Expected at least one DDLStatement"
    return result[0]


def _column(stmt: DDLStatement, name: str) -> ColumnDefinition:
    for col in stmt.columns:
        if col.name.strip('"') == name or col.name == name:
            return col
    raise KeyError(f"Column {name!r} not found. Available: {[c.name for c in stmt.columns]}")


# ---------------------------------------------------------------------------
# Empty / whitespace / comment-only input
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_empty_string(self, parser):
        assert parser.parse("") == []

    def test_whitespace_only(self, parser):
        assert parser.parse("   \n\t  ") == []

    def test_comment_only_single_line(self, parser):
        assert parser.parse("-- this is a comment") == []

    def test_comment_only_multiple_lines(self, parser):
        sql = "-- comment one\n-- comment two\n"
        assert parser.parse(sql) == []


# ---------------------------------------------------------------------------
# CREATE TABLE — basic structure
# ---------------------------------------------------------------------------


class TestCreateTableBasic:
    def test_returns_one_statement(self, parser):
        sql = "CREATE TABLE users (id INTEGER)"
        result = parser.parse(sql)
        assert len(result) == 1

    def test_statement_type(self, parser):
        sql = "CREATE TABLE users (id INTEGER)"
        stmt = _first(parser.parse(sql))
        assert stmt.statement_type == "CREATE_TABLE"

    def test_table_name_simple(self, parser):
        sql = "CREATE TABLE orders (id INTEGER)"
        stmt = _first(parser.parse(sql))
        assert stmt.table_name == "orders"
        assert stmt.schema_name is None

    def test_table_name_schema_qualified(self, parser):
        sql = "CREATE TABLE public.customers (id INTEGER)"
        stmt = _first(parser.parse(sql))
        assert stmt.table_name == "customers"
        assert stmt.schema_name == "public"

    def test_raw_sql_preserved(self, parser):
        sql = "CREATE TABLE t (id INTEGER)"
        stmt = _first(parser.parse(sql))
        assert "CREATE TABLE" in stmt.raw_sql
        assert "t" in stmt.raw_sql


# ---------------------------------------------------------------------------
# CREATE TABLE — column types
# ---------------------------------------------------------------------------


class TestCreateTableColumnTypes:
    @pytest.mark.parametrize(
        "col_def,expected_type_fragment",
        [
            ("id INTEGER", "INTEGER"),
            ("val BIGINT", "BIGINT"),
            ("name TEXT", "TEXT"),
            ("label VARCHAR(255)", "VARCHAR"),
            ("flag BOOLEAN", "BOOLEAN"),
            ("data JSONB", "JSONB"),
            ("uid UUID", "UUID"),
            ("created_at TIMESTAMP", "TIMESTAMP"),
            ("embedding VECTOR(1536)", "VECTOR"),
        ],
    )
    def test_column_pg_type(self, parser, col_def, expected_type_fragment):
        sql = f"CREATE TABLE t ({col_def})"
        stmt = _first(parser.parse(sql))
        assert len(stmt.columns) >= 1
        col = stmt.columns[0]
        assert expected_type_fragment.upper() in col.pg_type.upper()

    def test_multiple_columns(self, parser):
        sql = """
        CREATE TABLE products (
            id INTEGER,
            name TEXT,
            price BIGINT,
            active BOOLEAN
        )
        """
        stmt = _first(parser.parse(sql))
        assert len(stmt.columns) == 4
        names = [c.name for c in stmt.columns]
        assert "id" in names
        assert "name" in names
        assert "price" in names
        assert "active" in names

    def test_varchar_with_length(self, parser):
        sql = "CREATE TABLE t (label VARCHAR(255))"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert "VARCHAR" in col.pg_type.upper()
        assert "255" in col.pg_type


# ---------------------------------------------------------------------------
# CREATE TABLE — NOT NULL
# ---------------------------------------------------------------------------


class TestNotNullConstraint:
    def test_column_nullable_by_default(self, parser):
        sql = "CREATE TABLE t (name TEXT)"
        stmt = _first(parser.parse(sql))
        col = _column(stmt, "name")
        assert col.nullable is True

    def test_column_not_null(self, parser):
        sql = "CREATE TABLE t (name TEXT NOT NULL)"
        stmt = _first(parser.parse(sql))
        col = _column(stmt, "name")
        assert col.nullable is False

    def test_multiple_columns_mixed_nullability(self, parser):
        sql = "CREATE TABLE t (a TEXT NOT NULL, b TEXT, c INTEGER NOT NULL)"
        stmt = _first(parser.parse(sql))
        assert _column(stmt, "a").nullable is False
        assert _column(stmt, "b").nullable is True
        assert _column(stmt, "c").nullable is False


# ---------------------------------------------------------------------------
# CREATE TABLE — DEFAULT values
# ---------------------------------------------------------------------------


class TestDefaultValues:
    def test_no_default(self, parser):
        sql = "CREATE TABLE t (val INTEGER)"
        stmt = _first(parser.parse(sql))
        assert stmt.columns[0].default is None

    def test_integer_default(self, parser):
        sql = "CREATE TABLE t (count INTEGER DEFAULT 0)"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default is not None
        assert "0" in col.default

    def test_string_default(self, parser):
        sql = "CREATE TABLE t (status TEXT DEFAULT 'active')"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default is not None
        assert "active" in col.default

    def test_current_timestamp_default(self, parser):
        sql = "CREATE TABLE t (created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default == "CURRENT_TIMESTAMP"

    def test_now_default_normalized_to_current_timestamp(self, parser):
        sql = "CREATE TABLE t (created_at TIMESTAMP DEFAULT NOW())"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default == "CURRENT_TIMESTAMP"

    def test_true_default_normalized_to_1(self, parser):
        sql = "CREATE TABLE t (active BOOLEAN DEFAULT TRUE)"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default == "1"

    def test_false_default_normalized_to_0(self, parser):
        sql = "CREATE TABLE t (active BOOLEAN DEFAULT FALSE)"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default == "0"

    def test_gen_random_uuid_default_skipped(self, parser):
        sql = "CREATE TABLE t (id UUID DEFAULT gen_random_uuid())"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default == "__SKIP_DEFAULT__"


# ---------------------------------------------------------------------------
# CREATE TABLE — PRIMARY KEY
# ---------------------------------------------------------------------------


class TestPrimaryKey:
    def test_inline_primary_key(self, parser):
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY)"
        stmt = _first(parser.parse(sql))
        col = _column(stmt, "id")
        assert col.is_primary_key is True
        assert col.nullable is False

    def test_table_level_primary_key_constraint(self, parser):
        sql = "CREATE TABLE t (id INTEGER, name TEXT, PRIMARY KEY (id))"
        stmt = _first(parser.parse(sql))
        # Table-level PK becomes a constraint, not inline column flag
        pk_constraints = [
            c for c in stmt.constraints if c.constraint_type == ConstraintType.PRIMARY_KEY
        ]
        assert len(pk_constraints) == 1
        assert "id" in pk_constraints[0].columns

    def test_composite_primary_key(self, parser):
        sql = "CREATE TABLE t (a INTEGER, b INTEGER, PRIMARY KEY (a, b))"
        stmt = _first(parser.parse(sql))
        pk_constraints = [
            c for c in stmt.constraints if c.constraint_type == ConstraintType.PRIMARY_KEY
        ]
        assert len(pk_constraints) == 1
        cols = pk_constraints[0].columns
        assert "a" in cols
        assert "b" in cols

    def test_named_primary_key_constraint(self, parser):
        sql = "CREATE TABLE t (id INTEGER, CONSTRAINT pk_t PRIMARY KEY (id))"
        stmt = _first(parser.parse(sql))
        pk_constraints = [
            c for c in stmt.constraints if c.constraint_type == ConstraintType.PRIMARY_KEY
        ]
        assert len(pk_constraints) == 1

    def test_non_pk_column_is_not_primary_key(self, parser):
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"
        stmt = _first(parser.parse(sql))
        col = _column(stmt, "name")
        assert col.is_primary_key is False


# ---------------------------------------------------------------------------
# CREATE TABLE — comments stripped before parse
# ---------------------------------------------------------------------------


class TestCommentStripping:
    def test_inline_comment_stripped(self, parser):
        sql = "-- leading comment\nCREATE TABLE t (id INTEGER)"
        result = parser.parse(sql)
        assert len(result) == 1
        assert result[0].statement_type == "CREATE_TABLE"

    def test_trailing_inline_comment(self, parser):
        sql = "CREATE TABLE t (id INTEGER) -- trailing comment"
        result = parser.parse(sql)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# CREATE INDEX
# ---------------------------------------------------------------------------


class TestCreateIndex:
    def test_basic_create_index(self, parser):
        sql = "CREATE INDEX idx_name ON users (email)"
        result = parser.parse(sql)
        assert len(result) == 1
        stmt = result[0]
        assert stmt.statement_type == "CREATE_INDEX"

    def test_create_unique_index(self, parser):
        sql = "CREATE UNIQUE INDEX idx_unique_email ON users (email)"
        result = parser.parse(sql)
        assert len(result) == 1
        stmt = result[0]
        assert stmt.statement_type == "CREATE_INDEX"

    def test_basic_index_is_translatable(self, parser):
        sql = "CREATE INDEX idx_name ON users (email)"
        stmt = _first(parser.parse(sql))
        assert stmt.is_translatable is True
        assert len(stmt.translation_warnings) == 0

    def test_partial_index_not_translatable(self, parser):
        sql = "CREATE INDEX idx_active ON users (id) WHERE active = TRUE"
        stmt = _first(parser.parse(sql))
        assert stmt.is_translatable is False
        assert any("partial" in w.lower() for w in stmt.translation_warnings)

    def test_include_index_not_translatable(self, parser):
        sql = "CREATE INDEX idx_inc ON users (id) INCLUDE (email)"
        stmt = _first(parser.parse(sql))
        assert stmt.is_translatable is False
        assert any("INCLUDE" in w for w in stmt.translation_warnings)

    def test_expression_index_not_translatable(self, parser):
        sql = "CREATE INDEX idx_lower ON users (LOWER(email))"
        stmt = _first(parser.parse(sql))
        assert stmt.is_translatable is False
        assert any("expression" in w.lower() for w in stmt.translation_warnings)

    def test_raw_sql_preserved_for_index(self, parser):
        sql = "CREATE INDEX idx_x ON t (col)"
        stmt = _first(parser.parse(sql))
        assert "CREATE INDEX" in stmt.raw_sql


# ---------------------------------------------------------------------------
# ALTER TABLE
# ---------------------------------------------------------------------------


class TestAlterTable:
    def test_add_column_statement_type(self, parser):
        sql = "ALTER TABLE users ADD COLUMN age INTEGER"
        stmt = _first(parser.parse(sql))
        assert stmt.statement_type == "ALTER_TABLE"

    def test_add_column_operation(self, parser):
        sql = "ALTER TABLE users ADD COLUMN age INTEGER"
        stmt = _first(parser.parse(sql))
        assert stmt.operation == "ADD_COLUMN"

    def test_add_column_table_name(self, parser):
        sql = "ALTER TABLE users ADD COLUMN age INTEGER"
        stmt = _first(parser.parse(sql))
        assert stmt.table_name == "users"

    def test_add_column_column_definition(self, parser):
        sql = "ALTER TABLE users ADD COLUMN age INTEGER"
        stmt = _first(parser.parse(sql))
        assert len(stmt.columns) == 1
        col = stmt.columns[0]
        assert col.name == "age"
        assert "INTEGER" in col.pg_type.upper()

    def test_add_column_not_null(self, parser):
        sql = "ALTER TABLE users ADD COLUMN email TEXT NOT NULL"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.nullable is False

    def test_add_column_with_default(self, parser):
        sql = "ALTER TABLE users ADD COLUMN active BOOLEAN DEFAULT TRUE"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default == "1"

    def test_add_column_if_not_exists(self, parser):
        sql = "ALTER TABLE users ADD COLUMN IF NOT EXISTS score INTEGER"
        stmt = _first(parser.parse(sql))
        assert stmt.operation == "ADD_COLUMN"
        assert len(stmt.columns) == 1
        assert stmt.columns[0].name == "score"

    def test_drop_column_operation(self, parser):
        sql = "ALTER TABLE users DROP COLUMN old_field"
        stmt = _first(parser.parse(sql))
        assert stmt.operation == "DROP_COLUMN"

    def test_drop_column_details(self, parser):
        sql = "ALTER TABLE users DROP COLUMN old_field"
        stmt = _first(parser.parse(sql))
        assert stmt.operation_details is not None
        assert stmt.operation_details.get("column_name") == "old_field"

    def test_drop_column_if_exists(self, parser):
        sql = "ALTER TABLE users DROP COLUMN IF EXISTS old_field"
        stmt = _first(parser.parse(sql))
        assert stmt.operation == "DROP_COLUMN"
        assert stmt.operation_details is not None

    def test_rename_column_operation(self, parser):
        sql = "ALTER TABLE users RENAME COLUMN old_name TO new_name"
        stmt = _first(parser.parse(sql))
        assert stmt.operation == "RENAME_COLUMN"

    def test_rename_column_details(self, parser):
        sql = "ALTER TABLE users RENAME COLUMN old_name TO new_name"
        stmt = _first(parser.parse(sql))
        assert stmt.operation_details is not None
        assert stmt.operation_details.get("old_column") == "old_name"
        assert stmt.operation_details.get("new_column") == "new_name"

    def test_rename_table_operation(self, parser):
        sql = "ALTER TABLE users RENAME TO customers"
        stmt = _first(parser.parse(sql))
        assert stmt.operation == "RENAME_TABLE"

    def test_add_constraint_operation(self, parser):
        sql = "ALTER TABLE users ADD CONSTRAINT uq_email UNIQUE (email)"
        stmt = _first(parser.parse(sql))
        assert stmt.operation == "ADD_CONSTRAINT"

    def test_unsupported_alter_has_warning(self, parser):
        sql = "ALTER TABLE users ALTER COLUMN age TYPE BIGINT"
        stmt = _first(parser.parse(sql))
        assert len(stmt.translation_warnings) > 0


# ---------------------------------------------------------------------------
# DROP TABLE
# ---------------------------------------------------------------------------


class TestDropTable:
    def test_drop_table_statement_type(self, parser):
        sql = "DROP TABLE users"
        stmt = _first(parser.parse(sql))
        assert stmt.statement_type == "DROP_TABLE"

    def test_drop_table_table_name(self, parser):
        sql = "DROP TABLE orders"
        stmt = _first(parser.parse(sql))
        assert stmt.table_name == "orders"

    def test_drop_table_operation(self, parser):
        sql = "DROP TABLE users"
        stmt = _first(parser.parse(sql))
        assert stmt.operation == "DROP_TABLE"

    def test_drop_table_not_translatable(self, parser):
        sql = "DROP TABLE users"
        stmt = _first(parser.parse(sql))
        assert stmt.is_translatable is False

    def test_drop_table_has_warning(self, parser):
        sql = "DROP TABLE users"
        stmt = _first(parser.parse(sql))
        assert len(stmt.translation_warnings) > 0

    def test_drop_table_schema_qualified(self, parser):
        sql = "DROP TABLE public.users"
        stmt = _first(parser.parse(sql))
        assert stmt.table_name == "users"
        assert stmt.schema_name == "public"


# ---------------------------------------------------------------------------
# Multiple statements
# ---------------------------------------------------------------------------


class TestMultipleStatements:
    def test_two_create_tables(self, parser):
        sql = """
        CREATE TABLE users (id INTEGER, name TEXT);
        CREATE TABLE orders (id INTEGER, user_id INTEGER);
        """
        result = parser.parse(sql)
        types = [s.statement_type for s in result]
        assert types.count("CREATE_TABLE") == 2

    def test_mixed_ddl_types(self, parser):
        sql = """
        CREATE TABLE users (id INTEGER);
        CREATE INDEX idx_users ON users (id);
        DROP TABLE old_table;
        """
        result = parser.parse(sql)
        assert len(result) == 3
        stmt_types = {s.statement_type for s in result}
        assert "CREATE_TABLE" in stmt_types
        assert "CREATE_INDEX" in stmt_types
        assert "DROP_TABLE" in stmt_types

    def test_create_table_then_alter(self, parser):
        sql = """
        CREATE TABLE users (id INTEGER);
        ALTER TABLE users ADD COLUMN email TEXT;
        """
        result = parser.parse(sql)
        assert len(result) == 2
        assert result[0].statement_type == "CREATE_TABLE"
        assert result[1].statement_type == "ALTER_TABLE"


# ---------------------------------------------------------------------------
# DDLParser internal helpers (direct unit tests)
# ---------------------------------------------------------------------------


class TestSplitDefinitions:
    def test_simple_split(self, parser):
        result = parser._split_definitions("a, b, c")
        assert result == ["a", "b", "c"]

    def test_nested_parens_not_split(self, parser):
        result = parser._split_definitions("a(1, 2), b")
        assert len(result) == 2
        assert result[0] == "a(1, 2)"

    def test_single_quoted_comma_not_split(self, parser):
        result = parser._split_definitions("a 'x,y', b")
        assert len(result) == 2

    def test_double_quoted_comma_not_split(self, parser):
        result = parser._split_definitions('"col,name" TEXT, other INTEGER')
        assert len(result) == 2

    def test_empty_string(self, parser):
        result = parser._split_definitions("")
        assert result == []


class TestSplitQualifiedIdentifier:
    def test_simple_name(self, parser):
        schema, table = parser._split_qualified_identifier("users")
        assert schema is None
        assert table == "users"

    def test_schema_and_table(self, parser):
        schema, table = parser._split_qualified_identifier("public.users")
        assert schema == "public"
        assert table == "users"

    def test_quoted_identifier(self, parser):
        schema, table = parser._split_qualified_identifier('"mySchema"."myTable"')
        assert schema == '"mySchema"'
        assert table == '"myTable"'

    def test_empty_string(self, parser):
        schema, table = parser._split_qualified_identifier("")
        assert schema is None
        assert table is None


class TestNormalizeDefault:
    def test_current_timestamp_variants(self, parser):
        assert parser._normalize_default_expression("CURRENT_TIMESTAMP") == "CURRENT_TIMESTAMP"
        assert parser._normalize_default_expression("current_timestamp()") == "CURRENT_TIMESTAMP"

    def test_now_becomes_current_timestamp(self, parser):
        assert parser._normalize_default_expression("now()") == "CURRENT_TIMESTAMP"

    def test_true_becomes_1(self, parser):
        assert parser._normalize_default_expression("true") == "1"
        assert parser._normalize_default_expression("TRUE") == "1"

    def test_false_becomes_0(self, parser):
        assert parser._normalize_default_expression("false") == "0"
        assert parser._normalize_default_expression("FALSE") == "0"

    def test_gen_random_uuid_skip(self, parser):
        assert parser._normalize_default_expression("gen_random_uuid()") == "__SKIP_DEFAULT__"
        assert parser._normalize_default_expression("GEN_RANDOM_UUID()") == "__SKIP_DEFAULT__"

    def test_plain_value_returned_as_is(self, parser):
        assert parser._normalize_default_expression("42") == "42"
        assert parser._normalize_default_expression("'hello'") == "'hello'"


class TestDetermineAlterOperation:
    @pytest.mark.parametrize(
        "clause,expected",
        [
            ("ADD COLUMN foo INTEGER", "ADD_COLUMN"),
            ("DROP COLUMN bar", "DROP_COLUMN"),
            ("RENAME COLUMN old TO new", "RENAME_COLUMN"),
            ("RENAME TO new_table", "RENAME_TABLE"),
            ("ADD CONSTRAINT uq UNIQUE (col)", "ADD_CONSTRAINT"),
            ("DROP CONSTRAINT uq", "DROP_CONSTRAINT"),
            ("SOME UNKNOWN OPERATION", None),
            ("", None),
        ],
    )
    def test_operation_detection(self, parser, clause, expected):
        result = parser._determine_alter_operation(clause)
        assert result == expected


class TestExtractClauseAfterKeyword:
    def test_basic(self, parser):
        result = parser._extract_clause_after_keyword("ADD COLUMN foo INTEGER", "ADD COLUMN")
        assert result == "foo INTEGER"

    def test_keyword_not_found(self, parser):
        result = parser._extract_clause_after_keyword("DROP COLUMN bar", "ADD COLUMN")
        assert result == ""

    def test_empty_clause(self, parser):
        result = parser._extract_clause_after_keyword("", "ADD COLUMN")
        assert result == ""


class TestStripIfClauses:
    def test_strip_if_not_exists(self, parser):
        result = parser._strip_if_not_exists_clause("IF NOT EXISTS col_name TEXT")
        assert result == "col_name TEXT"

    def test_strip_if_not_exists_noop(self, parser):
        result = parser._strip_if_not_exists_clause("col_name TEXT")
        assert result == "col_name TEXT"

    def test_strip_if_exists(self, parser):
        result = parser._strip_if_exists_clause("IF EXISTS col_name")
        assert result == "col_name"

    def test_strip_if_exists_noop(self, parser):
        result = parser._strip_if_exists_clause("col_name")
        assert result == "col_name"


# ---------------------------------------------------------------------------
# ConstraintDefinition and ColumnDefinition dataclasses
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_constraint_definition_frozen(self):
        cd = ConstraintDefinition(
            constraint_type=ConstraintType.PRIMARY_KEY, columns=("id",)
        )
        with pytest.raises((AttributeError, TypeError)):
            cd.columns = ("other",)  # type: ignore[misc]

    def test_column_definition_frozen(self):
        col = ColumnDefinition(
            name="id",
            pg_type="INTEGER",
            iris_type="",
            nullable=True,
            default=None,
            is_primary_key=False,
        )
        with pytest.raises((AttributeError, TypeError)):
            col.name = "other"  # type: ignore[misc]

    def test_constraint_type_values(self):
        assert ConstraintType.PRIMARY_KEY.value == "PRIMARY_KEY"
        assert ConstraintType.FOREIGN_KEY.value == "FOREIGN_KEY"
        assert ConstraintType.UNIQUE.value == "UNIQUE"
        assert ConstraintType.CHECK.value == "CHECK"


# ---------------------------------------------------------------------------
# Complex CREATE TABLE — realistic schemas
# ---------------------------------------------------------------------------


class TestComplexCreateTable:
    def test_full_users_table(self, parser):
        sql = """
        CREATE TABLE users (
            id UUID DEFAULT gen_random_uuid(),
            username VARCHAR(100) NOT NULL,
            email TEXT NOT NULL,
            age INTEGER,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id)
        )
        """
        stmt = _first(parser.parse(sql))
        assert stmt.statement_type == "CREATE_TABLE"
        assert stmt.table_name == "users"

        # Column count — 6 named columns + 1 table-level PK constraint
        assert len(stmt.columns) == 6

        id_col = _column(stmt, "id")
        assert id_col.default == "__SKIP_DEFAULT__"

        username_col = _column(stmt, "username")
        assert username_col.nullable is False

        active_col = _column(stmt, "active")
        assert active_col.default == "1"

        created_col = _column(stmt, "created_at")
        assert created_col.default == "CURRENT_TIMESTAMP"

        pk_constraints = [
            c for c in stmt.constraints if c.constraint_type == ConstraintType.PRIMARY_KEY
        ]
        assert len(pk_constraints) == 1

    def test_vector_table(self, parser):
        sql = """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL,
            embedding VECTOR(1536)
        )
        """
        stmt = _first(parser.parse(sql))
        assert len(stmt.columns) == 3

        id_col = _column(stmt, "id")
        assert id_col.is_primary_key is True

        embed_col = _column(stmt, "embedding")
        assert "VECTOR" in embed_col.pg_type.upper()

    def test_no_columns_parenthesis(self, parser):
        """Edge case: malformed CREATE TABLE with no parenthesis block."""
        # sqlparse may not create a Parenthesis token for a stripped-down form;
        # parser should return empty columns/constraints without crashing.
        sql = "CREATE TABLE t"
        result = parser.parse(sql)
        # May or may not match as CREATE TABLE depending on token count
        for stmt in result:
            if stmt.statement_type == "CREATE_TABLE":
                assert stmt.columns == ()
                assert stmt.constraints == ()
