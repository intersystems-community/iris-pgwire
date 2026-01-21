import pytest

from iris_pgwire.schema_mapper import IRIS_SCHEMA
from iris_pgwire.sql_translator.normalizer import SQLTranslator


class TestSQLNormalizerFixes:
    @pytest.fixture
    def translator(self):
        return SQLTranslator()

    def test_normalize_sql_strips_comments_before_splitting(self, translator):
        """FR-001: SQL normalization should handle leading comments safely"""
        sql = "-- comment\nCREATE TABLE test (id INT);"
        # The goal is to ensure it doesn't corrupt or mis-parse
        normalized = translator.normalize_sql(sql)
        assert f'CREATE TABLE {IRIS_SCHEMA}."TEST"' in normalized

    def test_normalize_sql_avoids_no_op_injection(self, translator):
        """Ensure no-op SELECT 1 is not injected for skipped DDL during normalization"""
        # This relates to the sim.ai observation
        sql = "CREATE EXTENSION IF NOT EXISTS plpython3u;"
        normalized = translator.normalize_sql(sql)
        # If it's a skip, it should be empty or a comment, not SELECT 1
        assert "SELECT 1" not in normalized
        assert "SELECT TOP 1" not in normalized
