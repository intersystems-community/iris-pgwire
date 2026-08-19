"""T011g: a catalog column's PostgreSQL type must survive being aliased.

Clients read catalog columns at their PostgreSQL types. `relrowsecurity` is a
`bool` and `reloptions` is a `text[]`; the views hold 0 and NULL, and the
embedded backend infers a column's type from the *value* it got back — which is
a Python `int` even for a `CAST(… AS BIT)` column (measured). So both went out
as the wrong type.

Prisma aliases them:

    tbl.relrowsecurity as has_row_level_security

so matching on the output name cannot work either. The expression behind the
alias is what has to be looked up.

Getting this wrong is not cosmetic: Prisma asks for results in binary format,
where a bool is one byte and an int4 is four, so it read the rows and exited
without writing a schema — no error printed.
"""

from __future__ import annotations

import pytest

from iris_pgwire.catalog.views.definitions import CATALOG_COLUMN_TYPE_OIDS
from iris_pgwire.iris_executor import IRISExecutor

BOOL_OID = 16
TEXT_ARRAY_OID = 1009
VARCHAR_OID = 1043


@pytest.fixture(scope="module")
def detect():
    instance = object.__new__(IRISExecutor)
    return lambda sql, index: IRISExecutor._detect_catalog_column_type_oid(instance, sql, index)


class TestRegistry:
    def test_boolean_columns_map_to_bool(self):
        for column in ("relhassubclass", "relrowsecurity", "relispartition", "indisprimary"):
            assert CATALOG_COLUMN_TYPE_OIDS[column] == BOOL_OID

    def test_array_columns_map_to_text_array(self):
        for column in ("reloptions", "relacl", "nspacl"):
            assert CATALOG_COLUMN_TYPE_OIDS[column] == TEXT_ARRAY_OID

    def test_every_boolean_catalog_column_is_covered(self):
        from iris_pgwire.catalog.views.definitions import BOOLEAN_CATALOG_COLUMNS

        missing = BOOLEAN_CATALOG_COLUMNS - CATALOG_COLUMN_TYPE_OIDS.keys()
        assert not missing, f"boolean columns with no declared OID: {sorted(missing)}"


class TestAliasedCatalogColumns:
    """The shape Prisma emits."""

    PRISMA = (
        "SELECT TBL.RELNAME AS TABLE_NAME, "
        "NAMESPACE.NSPNAME AS NAMESPACE, "
        "TBL.RELROWSECURITY AS HAS_ROW_LEVEL_SECURITY, "
        "RELOPTIONS "
        "FROM PG_CATALOG.PG_CLASS AS TBL"
    )

    def test_aliased_boolean_column(self, detect):
        assert detect(self.PRISMA, 2) == BOOL_OID

    def test_unaliased_array_column(self, detect):
        assert detect(self.PRISMA, 3) == TEXT_ARRAY_OID

    def test_ordinary_columns_are_not_claimed(self, detect):
        """relname and nspname are text; the registry must not answer for them."""
        assert detect(self.PRISMA, 0) is None
        assert detect(self.PRISMA, 1) is None

    @pytest.mark.parametrize(
        "expression",
        [
            "relrowsecurity",
            "RELROWSECURITY",
            "tbl.relrowsecurity",
            "TBL.RELROWSECURITY",
            '"relrowsecurity"',
            'tbl."relrowsecurity"',
        ],
    )
    def test_spellings(self, detect, expression):
        sql = f"SELECT {expression} AS flag FROM pg_class tbl"
        assert detect(sql, 0) == BOOL_OID


class TestNoFalsePositives:
    @pytest.mark.parametrize(
        "expression",
        [
            # An expression over the column is no longer that column.
            "COUNT(relrowsecurity)",
            "CASE WHEN relrowsecurity = 1 THEN 'y' ELSE 'n' END",
            "relrowsecurity + 1",
            "relrowsecurity || 'x'",
            # A user column that merely shares the name of nothing in particular.
            "some_other_column",
            "tbl.description",
        ],
    )
    def test_returns_none(self, detect, expression):
        sql = f"SELECT {expression} AS flag FROM t"
        assert detect(sql, 0) is None

    def test_out_of_range_index_is_safe(self, detect):
        assert detect("SELECT a FROM t", 5) is None

    def test_a_statement_with_no_select_list(self, detect):
        assert detect("UPDATE t SET a = 1", 0) is None
