"""The ORDER BY alias fix must be idempotent.

`SQLRefiner._fix_order_by_aliases` replaces a select-list alias referenced in
ORDER BY with the expression behind it. Applied twice it replaced its own
output, and the extended query protocol translates the same statement at Parse,
Describe *and* Execute — so Prisma's

    namespace.nspname as namespace ... ORDER BY namespace

reached IRIS as

    ORDER BY NAMESPACE.NSPNAME.NSPNAME.NSPNAME

and failed with "Label 'NSPNAME.NSPNAME' is not listed among the applicable
tables". The alias shadows the table alias here, which is what let the
substitution keep finding a match in what it had just written.

Found by running `prisma db pull`, not by review: the single-pass unit coverage
could not see it.
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.refiner import SQLRefiner

PRISMA_ORDER_BY = (
    "SELECT tbl.relname AS table_name, namespace.nspname as namespace "
    "FROM pg_class AS tbl "
    "INNER JOIN pg_namespace AS namespace ON namespace.oid = tbl.relnamespace "
    "ORDER BY namespace, table_name"
)


@pytest.fixture
def refine():
    refiner = SQLRefiner()
    return refiner.refine if hasattr(refiner, "refine") else refiner.refine_sql


class TestIdempotence:
    def test_repeated_application_is_stable(self, refine):
        """Parse, Describe and Execute each translate the same statement."""
        once = refine(PRISMA_ORDER_BY)
        twice = refine(once)
        thrice = refine(twice)
        assert once == twice == thrice, (
            "the refiner rewrote its own output; the extended protocol applies "
            "it three times per statement"
        )

    def test_the_alias_is_not_expanded_into_itself(self, refine):
        result = refine(PRISMA_ORDER_BY)
        assert "nspname.nspname" not in result.lower(), f"alias expansion cascaded: {result}"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT a.b AS b FROM t a ORDER BY b",
            "SELECT x.y AS y, x.z AS z FROM x ORDER BY y, z",
            "SELECT t.c AS c FROM t ORDER BY c DESC",
            "SELECT t.n AS n FROM t ORDER BY n ASC, t.m DESC",
        ],
    )
    def test_shadowing_aliases_are_stable(self, sql, refine):
        """An alias equal to the column it comes from is the dangerous case."""
        once = refine(sql)
        assert refine(once) == once, f"not idempotent: {sql!r} -> {once!r}"


class TestStillDoesItsJob:
    def test_a_plain_alias_is_still_expanded(self, refine):
        """The refiner exists because IRIS rejects some alias references."""
        result = refine("SELECT count(*) AS total FROM t ORDER BY total")
        assert "count(*)" in result.lower()

    def test_an_already_qualified_reference_is_left_alone(self, refine):
        sql = "SELECT t.a AS a FROM t ORDER BY t.a"
        assert refine(sql) == sql

    def test_queries_without_order_by_are_untouched(self, refine):
        sql = "SELECT t.a AS a FROM t"
        assert refine(sql) == sql
