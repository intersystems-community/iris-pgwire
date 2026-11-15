import pytest

from iris_pgwire.sql_translator.refiner import RefinerConfig, SQLRefiner


class TestIRISCollationRefiner:
    @pytest.fixture
    def refiner(self):
        return SQLRefiner(RefinerConfig(enforce_exact_collation=True))

    def test_refine_select_distinct_single_col(self, refiner):
        sql = "SELECT DISTINCT FirstName FROM DNames"
        refined = refiner.refine(sql)
        # We expect it to be wrapped in %EXACT and aliased to preserve name
        assert "%EXACT FIRSTNAME AS FIRSTNAME" in refined.upper()

    def test_refine_select_distinct_multiple_cols(self, refiner):
        sql = "SELECT DISTINCT FirstName, LastName FROM DNames"
        refined = refiner.refine(sql)
        assert "%EXACT FIRSTNAME AS FIRSTNAME" in refined.upper()
        assert "%EXACT LASTNAME AS LASTNAME" in refined.upper()

    def test_refine_select_distinct_with_alias(self, refiner):
        sql = "SELECT DISTINCT FirstName AS FN FROM DNames"
        refined = refiner.refine(sql)
        assert "%EXACT FIRSTNAME AS FN" in refined.upper()

    def test_refine_union(self, refiner):
        sql = "SELECT FirstName FROM DNames UNION SELECT LastName FROM DNames"
        refined = refiner.refine(sql)
        assert "%EXACT FIRSTNAME AS FIRSTNAME" in refined.upper()
        assert "%EXACT LASTNAME AS LASTNAME" in refined.upper()
        assert "UNION" in refined.upper()

    def test_refine_union_all_no_change(self, refiner):
        # User said UNION ALL is fine, so we might skip it or just apply it anyway.
        # If we apply it anyway, it's safer. Let's see what the user said.
        # "UNION ALL returns the results without applying the default SQLUPPER collation."
        # So we can skip it for UNION ALL if we want to be efficient.
        sql = "SELECT FirstName FROM DNames UNION ALL SELECT LastName FROM DNames"
        refined = refiner.refine(sql)
        # If it's UNION ALL, we don't strictly need to wrap it.
        # But for consistency, maybe we should? No, let's follow the advice and only do UNION.
        assert "%EXACT" not in refined.upper()

    def test_refine_simple_select_no_change(self, refiner):
        sql = "SELECT FirstName FROM DNames"
        refined = refiner.refine(sql)
        assert "%EXACT" not in refined.upper()


class TestGroupByAndCountDistinctUseExactValues:
    """IRIS groups by its default collation (SQLUPPER): 'alpha' and 'Alpha' were one group, sent
    back as 'ALPHA'. PostgreSQL keeps them apart and returns the stored value. The rewrites below
    are the forms IRIS 2026.2 was seen to answer as PostgreSQL does (lab, 2026-11-14)."""

    @pytest.fixture
    def refiner(self):
        return SQLRefiner(RefinerConfig(enforce_exact_collation=True))

    def test_group_by_column_is_exact(self, refiner):
        assert (
            refiner.refine("SELECT name, count(*) FROM t GROUP BY name")
            == "SELECT name, count(*) FROM t GROUP BY %EXACT(name)"
        )

    def test_group_by_several_items_before_having_and_order_by(self, refiner):
        sql = "SELECT a, t.b, count(*) FROM t GROUP BY a, t.b HAVING count(*) > 1 ORDER BY a"
        assert refiner.refine(sql) == (
            "SELECT a, t.b, count(*) FROM t GROUP BY %EXACT(a), %EXACT(t.b) "
            "HAVING count(*) > 1 ORDER BY a"
        )

    def test_group_by_an_ordinal_is_left_alone(self, refiner):
        # %EXACT(1) would group by the constant 1. A resolvable ordinal becomes its column first
        # (test_positional_group_by.py); one that cannot be resolved stays a bare number.
        sql = "SELECT * FROM t GROUP BY 1"
        assert refiner.refine(sql) == sql

    def test_count_distinct_is_exact(self, refiner):
        assert (
            refiner.refine("SELECT COUNT(DISTINCT name) FROM t")
            == "SELECT COUNT(DISTINCT %EXACT(name)) FROM t"
        )

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT name, count(*) FROM t GROUP BY name",
            "SELECT COUNT(DISTINCT name) FROM t",
            "SELECT DISTINCT name FROM t ORDER BY name",
        ],
    )
    def test_refining_again_changes_nothing(self, refiner, sql):
        # Parse, Describe and Execute each translate the same statement.
        once = refiner.refine(sql)
        assert refiner.refine(once) == once


class TestDistinctWithOrderBy:
    def test_order_by_the_distinct_column_stays_a_plain_reference(self, refiner_default):
        # Refined twice it used to become ORDER BY DISTINCT %EXACT name: SQLCODE -12.
        sql = "SELECT DISTINCT name FROM t ORDER BY name"
        twice = refiner_default.refine(refiner_default.refine(sql))
        assert twice == "SELECT DISTINCT %EXACT name AS name FROM t ORDER BY name"

    @pytest.fixture
    def refiner_default(self):
        return SQLRefiner()
