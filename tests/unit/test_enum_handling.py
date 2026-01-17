import pytest

from iris_pgwire.sql_translator.enum_registry import EnumTypeRegistry
from iris_pgwire.sql_translator.normalizer import SQLTranslator


def test_enum_registration():
    registry = EnumTypeRegistry()
    registry.register("public.status")
    assert registry.is_registered("status") is True
    assert registry.is_registered("STATUS") is True


def test_enum_column_translation():
    translator = SQLTranslator()
    registry = translator.enum_registry
    registry.clear()
    registry.register("status")

    sql = "CREATE TABLE t1 (id int, col1 status)"
    # SQLTranslator.normalize_sql returns the translated SQL
    result = translator.normalize_sql(sql)
    assert "VARCHAR(64)" in result
    assert "T1" in result
