"""T011h: a column's declared type must not depend on whether rows came back.

The `dbapi` backend took every column type from `cursor.description`, which
arrived as varchar for every column, and then *refined* the varchars from the
first row's Python value. A statement Describe runs the query with dummy
parameters, which match nothing, so there is no first row and no refinement:

    Execute  (7 rows) -> is_partition 16,   has_row_level_security 23
    Describe (0 rows) -> is_partition 1043, has_row_level_security 1043

A client that reads the statement Describe (Prisma's driver does) then decodes
DataRow bytes encoded per Execute: one byte of bool under a varchar declaration.
Measured with a raw wire client in
`specs/044-catalog-as-views/spikes/probe_statement_describe.py`.

Those varchars were our own `_map_dbapi_type_to_oid` discarding good numeric type
codes, not a driver limitation — this file originally said IRIS reported
type_code 4 for everything, which measurement disproved (T015c). The module is
needed either way: no type code can say that a 0/1 integer is a PostgreSQL bool.

The cure is to resolve what the SQL already says, independent of any row, so the
two paths agree by construction. This pins that resolver.
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.column_types import (
    boolean_expression_type_oid,
    cast_type_oid,
    catalog_column_type_oid,
    resolve_column_type_oids,
)

# Prisma's table-introspection query, captured verbatim off the wire.
PRISMA_TABLES = """SELECT
  tbl.relname AS table_name,
  namespace.nspname as namespace,
  (tbl.relhassubclass and tbl.relkind = 'p') as is_partition,
  (tbl.relhassubclass and tbl.relkind = 'r') as has_subclass,
  tbl.relrowsecurity as has_row_level_security,
  reloptions,
  obj_description(tbl.oid, 'pg_class') as description
FROM pg_class AS tbl
INNER JOIN pg_namespace AS namespace ON namespace.oid = tbl.relnamespace
WHERE
  (
    (tbl.relkind = 'r' AND tbl.relispartition = 'f')
      OR
    tbl.relkind = 'p'
  )
  AND namespace.nspname = ANY ( $1 )
ORDER BY namespace, table_name;"""


class TestTheQueryThatBlockedIntrospection:
    def test_the_three_boolean_columns_resolve_to_bool(self):
        """The three that made `prisma db pull` fail, and why each one does."""
        oids = resolve_column_type_oids(PRISMA_TABLES)
        assert oids[2] == 16, "(a and b = 'p') is a boolean expression"
        assert oids[3] == 16, "same shape, second one"
        assert oids[4] == 16, "relrowsecurity is a documented bool, renamed by the client"

    def test_resolution_does_not_need_a_row(self):
        """The whole point: no values are passed in, and it still resolves."""
        assert resolve_column_type_oids(PRISMA_TABLES)[2] == 16

    def test_one_entry_per_select_list_item(self):
        assert len(resolve_column_type_oids(PRISMA_TABLES)) == 7

    def test_unknown_columns_resolve_to_none_rather_than_a_guess(self):
        """`None` means "no opinion" so the caller keeps what IRIS said."""
        oids = resolve_column_type_oids(PRISMA_TABLES)
        assert oids[0] is None, "relname's type comes from IRIS, not from us"
        assert oids[6] is None, "obj_description(...) is a call, not a catalog column"

    def test_reloptions_keeps_its_array_type(self):
        assert resolve_column_type_oids(PRISMA_TABLES)[5] == 1009


class TestCastDetection:
    @pytest.mark.parametrize(
        ("sql", "column", "expected"),
        [
            ("SELECT CAST(CASE WHEN a <> 0 THEN 1 ELSE 0 END AS BIT) AS flag FROM t", "flag", 16),
            ("SELECT CAST(x AS INTEGER) AS n FROM t", "n", 23),
            ("SELECT $1::bool AS flag FROM t", "flag", 16),
            ("SELECT CAST(x AS TIMESTAMP) AS ts FROM t", "ts", 1114),
        ],
    )
    def test_a_cast_names_the_type(self, sql, column, expected):
        assert cast_type_oid(sql, column) == expected

    def test_a_subquery_that_merely_looks_like_a_cast_is_declined(self):
        """`(SELECT b AS c) AS flag` matches the tail pattern but is not a cast."""
        assert cast_type_oid("SELECT (SELECT b AS c) AS flag FROM t", "flag") is None

    def test_no_cast_means_no_opinion(self):
        assert cast_type_oid("SELECT a AS flag FROM t", "flag") is None


class TestCatalogColumnDetection:
    def test_a_renamed_catalog_column_keeps_its_type(self):
        sql = "SELECT tbl.relrowsecurity as has_row_level_security FROM pg_class tbl"
        assert catalog_column_type_oid(sql, 0) == 16

    def test_a_quoted_and_qualified_reference_still_resolves(self):
        sql = 'SELECT "tbl"."relispartition" AS p FROM pg_class tbl'
        assert catalog_column_type_oid(sql, 0) == 16

    def test_an_aggregate_over_a_catalog_column_is_not_that_column(self):
        """COUNT(relrowsecurity) is an int8, and claiming bool would be worse."""
        sql = "SELECT COUNT(relrowsecurity) AS n FROM pg_class"
        assert catalog_column_type_oid(sql, 0) is None

    def test_an_index_past_the_select_list_is_declined(self):
        assert catalog_column_type_oid("SELECT relname FROM pg_class", 5) is None


class TestBooleanExpressionDetection:
    @pytest.mark.parametrize(
        "expression",
        [
            "(tbl.relhassubclass and tbl.relkind = 'p')",
            "(a = 1 OR b = 2)",
            "(x <> 0 AND y IS NOT NULL)",
        ],
    )
    def test_a_parenthesised_predicate_is_bool(self, expression):
        assert boolean_expression_type_oid(f"SELECT {expression} AS flag FROM t", 0) == 16

    @pytest.mark.parametrize(
        "expression",
        [
            "tbl.relname",
            "(a + b)",
            "COUNT(*)",
            "(SELECT max(x) FROM t2)",
        ],
    )
    def test_everything_else_is_not(self, expression):
        assert boolean_expression_type_oid(f"SELECT {expression} AS c FROM t", 0) is None


class TestPrecedence:
    def test_a_cast_wins_over_the_catalog_table(self):
        """An explicit cast is the client's own statement of intent."""
        sql = "SELECT CAST(relrowsecurity AS INTEGER) AS n FROM pg_class"
        assert resolve_column_type_oids(sql)[0] == 23

    def test_a_catalog_column_wins_over_the_boolean_heuristic(self):
        sql = "SELECT reloptions FROM pg_class"
        assert resolve_column_type_oids(sql)[0] == 1009


class TestBothExecutorsUseIt:
    """The defect existed because the same logic lived in only one executor.

    `backend_selector` builds `DBAPIExecutor` for the dbapi backend and
    `IRISExecutor` for the embedded one. T011g fixed the second; the first kept
    inferring from values. A shared resolver is only a fix if both call it.
    """

    def test_the_dbapi_executor_resolves_from_sql(self):
        import inspect

        from iris_pgwire import dbapi_executor

        source = inspect.getsource(dbapi_executor)
        assert "resolve_column_type_oids" in source, (
            "DBAPIExecutor still types columns from row values alone; a Describe "
            "with no rows will declare varchar for a bool"
        )

    def test_the_embedded_executor_resolves_from_sql(self):
        import inspect

        from iris_pgwire import iris_executor

        source = inspect.getsource(iris_executor)
        assert "resolve_column_type_oids" in source or "catalog_column_type_oid" in source


class TestNonCatalogQueriesAreUntouched:
    """Ordinary SQL must not acquire opinions it did not have (FR-013/FR-014)."""

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT id, name FROM customer",
            "SELECT COUNT(*) FROM orders",
            "SELECT a.id, b.total FROM a JOIN b ON b.a_id = a.id",
        ],
    )
    def test_no_opinion_on_ordinary_columns(self, sql):
        assert all(oid is None for oid in resolve_column_type_oids(sql))
