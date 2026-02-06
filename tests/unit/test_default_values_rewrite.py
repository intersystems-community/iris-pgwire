import pytest

from iris_pgwire.sql_translator.default_values import DefaultValuesTranslator
from iris_pgwire.sql_translator.metadata_cache import MetadataCache
from iris_pgwire.sql_translator.normalizer import SQLTranslator


class TestDefaultValuesRewrite:
    @pytest.fixture
    def translator(self):
        return SQLTranslator()

    def test_rewrite_default_in_values(self, translator):
        """FR-003: Omit columns with DEFAULT in VALUES"""
        sql = "INSERT INTO users (id, name, created_at) VALUES (1, 'alice', DEFAULT);"
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


class DummyExecutor:
    def __init__(self, rows):
        self._rows = rows

    async def execute_query(self, query, params):
        return {"rows": self._rows}


class TestSmartDefaultHandling:
    def _translator(self, rows):
        cache = MetadataCache()
        executor = DummyExecutor(rows)
        return DefaultValuesTranslator(metadata_cache=cache, executor=executor)

    def test_column_list_defaults_removed(self):
        rows = [
            ("ID", None, "NO"),
            ("STATUS", "'ACTIVE'", "NO"),
            ("DESCRIPTION", None, "YES"),
        ]
        translator = self._translator(rows)
        sql = 'INSERT INTO SQLUSER."USERS" (id, status, description) VALUES (1, DEFAULT, DEFAULT);'
        normalized = translator.translate(sql)
        assert "status" not in normalized.lower()
        assert "description" in normalized.lower()
        assert "NULL" in normalized

    def test_replace_default_without_column_list(self):
        rows = [
            ("ID", "nextval('users_seq'::regclass)", "NO"),
            ("VALUE", None, "NO"),
        ]
        translator = self._translator(rows)
        sql = 'INSERT INTO SQLUSER."USERS" VALUES (DEFAULT, 5);'
        normalized = translator.translate(sql)
        assert "nextval('users_seq'::regclass)" in normalized
        assert "DEFAULT" not in normalized

    def test_raises_when_not_null_without_default(self):
        rows = [("ID", None, "NO"), ("NAME", None, "NO")]
        translator = self._translator(rows)
        sql = 'INSERT INTO SQLUSER."USERS" (id, name) VALUES (DEFAULT, DEFAULT);'
        with pytest.raises(ValueError):
            translator.translate(sql)
