import pytest

from iris_pgwire.sql_translator.normalizer import SQLTranslator


class TestDefaultValuesRewrite:
    @pytest.fixture
    def translator(self):
        return SQLTranslator()

    def test_rewrite_default_in_values(self, translator):
        """FR-003: Omit columns with DEFAULT in VALUES"""
        sql = "INSERT INTO users (id, name, created_at) VALUES (1, 'alice', DEFAULT);"
        # Expected: Omit created_at and DEFAULT
        normalized = translator.normalize_sql(sql)
        assert "created_at" not in normalized.lower()
        assert "DEFAULT" not in normalized
        assert "(id, name)" in normalized.lower()
        assert "(1, 'alice')" in normalized

    def test_multiple_defaults_in_values(self, translator):
        """FR-003: Omit multiple DEFAULTs"""
        sql = "INSERT INTO users (id, name, age, status) VALUES (1, DEFAULT, 25, DEFAULT);"
        normalized = translator.normalize_sql(sql)
        assert "id" in normalized.lower()
        assert "age" in normalized.lower()
        assert "name" not in normalized.lower()
        assert "status" not in normalized.lower()
        assert "(1, 25)" in normalized
