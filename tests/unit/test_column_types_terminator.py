"""A trailing semicolon must not change what the statement says about its column types.

Found 2026-10-24 through the ADBC PostgreSQL driver. The simple-query path appends `;` before it
executes a statement (an IRIS workaround for string literals), and the statement-text type
resolver took the semicolon as part of the last alias: `AS v;`. The alias lookup then matched
nothing, so `resolve_column_type_oids` returned `[None]` for every statement on that path. The same
query therefore reported `varchar` over the simple protocol and `date` over the extended one, and a
binary client that had been told `date` by Describe was sent ten bytes of text by COPY.
"""

import pytest

from iris_pgwire.sql_translator.column_types import (
    boolean_expression_type_oid,
    cast_type_oid,
    catalog_column_type_oid,
    resolve_column_type_oids,
)

DATE, TIMESTAMP, BOOL = 1082, 1114, 16

TERMINATORS = ["", ";", " ;", ";\n", "  ;  ", ";;"]


@pytest.mark.parametrize("end", TERMINATORS)
class TestAnExplicitCast:
    def test_cast_to_date(self, end):
        assert resolve_column_type_oids(f"SELECT CAST('2026-10-24' AS DATE) AS v{end}") == [DATE]

    def test_cast_to_timestamp_with_other_columns(self, end):
        sql = f"SELECT 1 AS a, CAST('2026-10-24 12:00:00' AS TIMESTAMP) AS t, 'x' AS b{end}"
        assert resolve_column_type_oids(sql) == [None, TIMESTAMP, None]

    def test_cast_of_a_parameter(self, end):
        assert resolve_column_type_oids(f"SELECT CAST(? AS DATE) AS v{end}") == [DATE]

    def test_postgres_style_parameter_cast(self, end):
        assert cast_type_oid(f"SELECT $1::bool AS flag{end}", "flag") == BOOL

    def test_the_last_item_is_not_special(self, end):
        sql = f"SELECT CAST(1 AS BIT) AS a, CAST('2026-10-24' AS DATE) AS b{end}"
        assert resolve_column_type_oids(sql) == [BOOL, DATE]


@pytest.mark.parametrize("end", TERMINATORS)
class TestTheOtherEvidenceSources:
    def test_a_catalog_column(self, end):
        sql = f"SELECT relispartition FROM pg_catalog.pg_class{end}"
        assert catalog_column_type_oid(sql, 0) == resolve_column_type_oids(sql)[0]
        assert resolve_column_type_oids(sql) == [BOOL]

    def test_a_boolean_expression(self, end):
        sql = f"SELECT (t.a = 1 AND t.b = 2) AS flag FROM t{end}"
        assert boolean_expression_type_oid(sql, 0) == BOOL
        assert resolve_column_type_oids(sql) == [BOOL]


class TestNothingElseChanges:
    @pytest.mark.parametrize("sql", ["SELECT 1 AS n", "SELECT 'a' AS s", "SELECT a, b FROM t"])
    def test_statements_that_say_nothing_still_say_nothing(self, sql):
        assert all(oid is None for oid in resolve_column_type_oids(sql + ";"))

    def test_a_semicolon_inside_a_string_literal_is_left_alone(self):
        sql = "SELECT CAST('a;b' AS DATE) AS v;"
        assert resolve_column_type_oids(sql) == [DATE]
