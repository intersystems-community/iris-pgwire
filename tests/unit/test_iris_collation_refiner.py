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
