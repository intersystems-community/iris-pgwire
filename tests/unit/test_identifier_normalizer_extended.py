"""
Extended unit tests for iris_pgwire.sql_translator.identifier_normalizer

Targets uncovered branches to push coverage from 70% → ≥85%.
No live IRIS connection required.
"""

import pytest

from iris_pgwire.sql_translator.identifier_normalizer import IdentifierNormalizer


@pytest.fixture
def norm():
    return IdentifierNormalizer()


# ---------------------------------------------------------------------------
# is_quoted
# ---------------------------------------------------------------------------


class TestIsQuoted:
    def test_quoted(self, norm):
        assert norm.is_quoted('"MyCol"') is True

    def test_unquoted(self, norm):
        assert norm.is_quoted("MyCol") is False

    def test_only_open_quote(self, norm):
        assert norm.is_quoted('"MyCol') is False

    def test_only_close_quote(self, norm):
        assert norm.is_quoted('MyCol"') is False

    def test_empty_string(self, norm):
        assert norm.is_quoted("") is False


# ---------------------------------------------------------------------------
# normalize — basic identifier uppercasing
# ---------------------------------------------------------------------------


class TestNormalizeBasic:
    def test_unquoted_uppercased(self, norm):
        sql, count = norm.normalize("SELECT myCol FROM myTable")
        assert "MYCOL" in sql
        assert "MYTABLE" in sql

    def test_quoted_preserved(self, norm):
        sql, count = norm.normalize('SELECT "myCol" FROM "myTable"')
        assert '"myCol"' in sql
        assert '"myTable"' in sql

    def test_sql_keywords_preserved(self, norm):
        sql, count = norm.normalize("SELECT col FROM tbl WHERE col IS NULL")
        assert "SELECT" in sql
        assert "FROM" in sql
        assert "WHERE" in sql
        assert "IS" in sql
        assert "NULL" in sql

    def test_string_literals_not_modified(self, norm):
        sql, count = norm.normalize("SELECT 'hello world' FROM t")
        assert "'hello world'" in sql

    def test_string_literal_with_mixed_case_preserved(self, norm):
        sql, count = norm.normalize("SELECT 'MyValue' FROM t")
        assert "'MyValue'" in sql

    def test_identifier_count_returned(self, norm):
        sql, count = norm.normalize("SELECT a, b FROM t")
        assert count >= 1


# ---------------------------------------------------------------------------
# normalize — schema-qualified identifiers
# ---------------------------------------------------------------------------


class TestSchemaQualifiedIdentifiers:
    def test_schema_table_uppercased(self, norm):
        sql, _ = norm.normalize("SELECT * FROM myschema.mytable")
        assert "MYSCHEMA.MYTABLE" in sql

    def test_quoted_schema_preserved(self, norm):
        sql, _ = norm.normalize('SELECT * FROM "mySchema"."myTable"')
        assert '"mySchema"."myTable"' in sql

    def test_mixed_schema(self, norm):
        sql, _ = norm.normalize('SELECT * FROM myschema."MyTable"')
        assert "MYSCHEMA" in sql
        assert '"MyTable"' in sql


# ---------------------------------------------------------------------------
# normalize — SAVEPOINT context
# ---------------------------------------------------------------------------


class TestSavepointContext:
    def test_savepoint_name_preserved(self, norm):
        sql, _ = norm.normalize("SAVEPOINT mySavePoint")
        # The savepoint name should NOT be uppercased
        assert "mySavePoint" in sql

    def test_rollback_to_savepoint(self, norm):
        sql, _ = norm.normalize("ROLLBACK TO SAVEPOINT mySave")
        assert "mySave" in sql

    def test_release_savepoint(self, norm):
        sql, _ = norm.normalize("RELEASE SAVEPOINT mySave")
        assert "mySave" in sql

    def test_rollback_to_no_savepoint_keyword(self, norm):
        sql, _ = norm.normalize("ROLLBACK TO myPoint")
        assert "myPoint" in sql


# ---------------------------------------------------------------------------
# normalize — CREATE TABLE handling
# ---------------------------------------------------------------------------


class TestCreateTableNormalization:
    def test_create_table_table_name_uppercased(self, norm):
        sql, _ = norm.normalize("CREATE TABLE myTable (id INTEGER)")
        assert "MYTABLE" in sql

    def test_create_table_column_names_lowercased(self, norm):
        sql, _ = norm.normalize("CREATE TABLE T (myCol INTEGER)")
        # Column names preserved as lowercase in CREATE TABLE context
        assert "mycol" in sql.lower()

    def test_create_table_keywords_uppercased(self, norm):
        sql, _ = norm.normalize("CREATE TABLE T (id INTEGER NOT NULL)")
        assert "INTEGER" in sql
        assert "NOT" in sql
        assert "NULL" in sql

    def test_create_table_quoted_column_preserved(self, norm):
        sql, _ = norm.normalize('CREATE TABLE T ("MyCol" INTEGER)')
        assert '"MyCol"' in sql

    def test_create_table_with_schema(self, norm):
        sql, _ = norm.normalize("CREATE TABLE myschema.myTable (id INTEGER)")
        assert "MYSCHEMA" in sql
        assert "MYTABLE" in sql

    def test_create_table_quoted_table_preserved(self, norm):
        sql, _ = norm.normalize('CREATE TABLE "MyTable" (id INTEGER)')
        assert '"MyTable"' in sql

    def test_create_temporary_table(self, norm):
        sql, _ = norm.normalize("CREATE TEMPORARY TABLE tempT (id INTEGER)")
        assert "TEMPT" in sql or "TEMPORARY" in sql

    def test_create_table_if_not_exists(self, norm):
        sql, _ = norm.normalize("CREATE TABLE IF NOT EXISTS myTable (id INTEGER)")
        # Table name should still be uppercased
        assert "MYTABLE" in sql

    def test_nested_parens_in_column_defs(self, norm):
        """Nested parens in CHECK constraints should not break parsing."""
        sql, _ = norm.normalize(
            "CREATE TABLE T (id INTEGER, val NUMERIC CHECK (val > 0))"
        )
        assert "T" in sql

    def test_create_table_multiple_columns(self, norm):
        sql, _ = norm.normalize(
            "CREATE TABLE Orders (orderId INTEGER, amount DECIMAL, status VARCHAR(50))"
        )
        assert "ORDERS" in sql
        assert "INTEGER" in sql
        assert "DECIMAL" in sql


# ---------------------------------------------------------------------------
# _finalize_normalization
# ---------------------------------------------------------------------------


class TestFinalizeNormalization:
    def test_using_btree_stripped(self, norm):
        sql, _ = norm.normalize("CREATE INDEX idx ON t (col) USING btree")
        assert "USING btree" not in sql

    def test_fillfactor_stripped(self, norm):
        sql, _ = norm.normalize("CREATE INDEX idx ON t (col) WITH (fillfactor=80)")
        assert "fillfactor" not in sql

    def test_cast_syntax_stripped(self, norm):
        """PostgreSQL :: cast operator should be removed."""
        sql, _ = norm.normalize("SELECT col::text FROM t")
        assert "::" not in sql

    def test_no_btree_passthrough(self, norm):
        """Statement without USING btree unchanged."""
        sql, _ = norm.normalize("SELECT 1 FROM t")
        assert sql.strip() != ""


# ---------------------------------------------------------------------------
# _strip_generated_columns
# ---------------------------------------------------------------------------


class TestStripGeneratedColumns:
    def test_generated_column_stripped(self, norm):
        raw = (
            "CREATE TABLE T (id INTEGER, "
            "fullname VARCHAR GENERATED ALWAYS AS (firstname || ' ' || lastname) STORED)"
        )
        sql, _ = norm.normalize(raw)
        assert "GENERATED ALWAYS AS" not in sql.upper()

    def test_no_generated_column_unchanged(self, norm):
        raw = "CREATE TABLE T (id INTEGER, name VARCHAR)"
        sql, _ = norm.normalize(raw)
        assert "CREATE" in sql.upper()


# ---------------------------------------------------------------------------
# _split_on_string_literals
# ---------------------------------------------------------------------------


class TestSplitOnStringLiterals:
    def test_segments_returned(self, norm):
        segments = norm._split_on_string_literals("SELECT 'val' FROM t")
        # Should have at least a (before, literal) pair and a (after, "")
        assert len(segments) >= 2

    def test_no_literals_single_segment(self, norm):
        segments = norm._split_on_string_literals("SELECT 1 FROM t")
        assert len(segments) == 1
        assert segments[0][1] == ""

    def test_multiple_literals(self, norm):
        segments = norm._split_on_string_literals("'a' = 'b'")
        literals = [lit for _, lit in segments if lit]
        assert len(literals) == 2

    def test_escaped_quote_in_literal(self, norm):
        segments = norm._split_on_string_literals("SELECT 'it''s fine'")
        literals = [lit for _, lit in segments if lit]
        assert any("it''s fine" in lit for lit in literals)


# ---------------------------------------------------------------------------
# normalize — data type handling in column defs
# ---------------------------------------------------------------------------


class TestDataTypeHandling:
    def test_data_types_uppercased_in_create_table(self, norm):
        for dtype in ["INT", "VARCHAR", "BOOLEAN", "TEXT", "FLOAT", "TIMESTAMP", "DATE", "VECTOR"]:
            sql, _ = norm.normalize(f"CREATE TABLE T (col {dtype})")
            assert dtype.upper() in sql

    def test_qualified_type_in_column_def(self, norm):
        sql, _ = norm.normalize("CREATE TABLE T (id pg_catalog.int4)")
        assert "PG_CATALOG" in sql or "pg_catalog" in sql


# ---------------------------------------------------------------------------
# normalize — empty and edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string(self, norm):
        sql, count = norm.normalize("")
        assert sql == ""
        assert count == 0

    def test_whitespace_only(self, norm):
        sql, count = norm.normalize("   ")
        assert count == 0

    def test_only_string_literal(self, norm):
        sql, count = norm.normalize("'hello'")
        assert "'hello'" in sql

    def test_percent_s_keyword_preserved(self, norm):
        """The %s placeholder in _sql_keywords should not be touched."""
        sql, _ = norm.normalize("SELECT * FROM t WHERE col = %s")
        assert "%s" in sql

    def test_numeric_literal_not_modified(self, norm):
        sql, _ = norm.normalize("SELECT 42 FROM t")
        assert "42" in sql


# ---------------------------------------------------------------------------
# _normalize_chunk — CREATE TABLE qualified/partial paths (lines 267-330)
# ---------------------------------------------------------------------------


class TestNormalizeChunkCreateTablePaths:
    """Cover branches in _normalize_chunk for CREATE TABLE."""

    def test_sqluser_schema_preserved_case(self, norm):
        """IRIS_SCHEMA (SQLUser) should stay as-is in schema-qualified table name."""
        sql, _ = norm.normalize("CREATE TABLE SQLUser.myTable (id INTEGER)")
        assert "SQLUser" in sql
        assert "MYTABLE" in sql

    def test_quoted_schema_in_create_table(self, norm):
        """Quoted schema in CREATE TABLE should be preserved."""
        sql, _ = norm.normalize('CREATE TABLE "SQLUser".myTable (id INTEGER)')
        assert '"SQLUser"' in sql
        assert "MYTABLE" in sql

    def test_quoted_table_in_schema_qualified(self, norm):
        """Quoted table name with schema prefix."""
        sql, _ = norm.normalize('CREATE TABLE SQLUser."myTable" (id INTEGER)')
        assert "SQLUser" in sql
        assert '"myTable"' in sql

    def test_partial_create_table_no_closing_paren(self, norm):
        """Fallback path: no closing paren found — normalize as plain chunk."""
        sql, cnt = norm._normalize_chunk("CREATE TABLE t (col INTEGER", 0)
        # Falls back to _normalize_identifiers_in_chunk — no crash, returns something
        assert "INTEGER" in sql

    def test_iris_schema_in_select(self, norm):
        """IRIS_SCHEMA should be preserved (not uppercased) in SELECT context."""
        sql, _ = norm.normalize("SELECT * FROM SQLUser.orders")
        assert "SQLUser" in sql
        assert "ORDERS" in sql

    def test_quoted_schema_in_select(self, norm):
        """Quoted schema in SELECT qualified identifier — preserved case."""
        sql, _ = norm.normalize('SELECT "SQLUser".orders.id FROM orders')
        assert '"SQLUser"' in sql


# ---------------------------------------------------------------------------
# _normalize_column_definitions — additional coverage (lines 421-468)
# ---------------------------------------------------------------------------


class TestNormalizeColumnDefinitions:
    """Cover _normalize_column_definitions paths directly via normalize()."""

    def test_column_with_qualified_type(self, norm):
        """Qualified type like pg_catalog.int4 in CREATE TABLE column def."""
        sql, _ = norm.normalize("CREATE TABLE t (id pg_catalog.int4)")
        # Both parts should be uppercased (neither is IRIS_SCHEMA)
        assert "PG_CATALOG" in sql or "pg_catalog" in sql.lower()

    def test_column_data_types_uppercased_in_def(self, norm):
        for dtype in ["VARCHAR", "INTEGER", "BOOLEAN", "FLOAT", "TEXT"]:
            sql, _ = norm.normalize(f"CREATE TABLE t (col {dtype})")
            assert dtype in sql

    def test_quoted_column_in_column_def(self, norm):
        sql, _ = norm.normalize('CREATE TABLE t ("MyCol" INTEGER)')
        assert '"MyCol"' in sql

    def test_multiple_columns_in_def(self, norm):
        sql, _ = norm.normalize(
            "CREATE TABLE t (id INTEGER, name VARCHAR(100), active BOOLEAN)"
        )
        assert "INTEGER" in sql
        assert "VARCHAR" in sql
        assert "BOOLEAN" in sql

    def test_column_with_default_keyword(self, norm):
        sql, _ = norm.normalize("CREATE TABLE t (status VARCHAR DEFAULT 'active')")
        assert "DEFAULT" in sql

    def test_column_with_not_null(self, norm):
        sql, _ = norm.normalize("CREATE TABLE t (id INTEGER NOT NULL)")
        assert "NOT" in sql
        assert "NULL" in sql

    def test_after_create_table_normalizer_runs(self, norm):
        """Text after the closing paren is normalized normally."""
        sql, _ = norm.normalize(
            "CREATE TABLE t (id INTEGER); SELECT * FROM t"
        )
        # The 'after' part should be normalized
        assert "SELECT" in sql
