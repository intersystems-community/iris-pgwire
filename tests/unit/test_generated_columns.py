import pytest
from iris_pgwire.sql_translator.identifier_normalizer import IdentifierNormalizer
from iris_pgwire.sql_translator.enum_registry import EnumTypeRegistry


def test_generated_column_skip():
    nm = IdentifierNormalizer()
    sql = "CREATE TABLE t1 (id int, col1 int GENERATED ALWAYS AS (id * 2) STORED)"
    expected = "CREATE TABLE T1 (ID INT)"
    result, _ = nm.normalize(sql)
    assert result == expected


def test_generated_column_multiple_skip():
    nm = IdentifierNormalizer()
    sql = "CREATE TABLE t1 (id int, col1 int GENERATED ALWAYS AS (id * 2) STORED, col2 text)"
    expected = "CREATE TABLE T1 (ID INT, COL2 TEXT)"
    result, _ = nm.normalize(sql)
    assert result == expected
