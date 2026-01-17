import pytest

from iris_pgwire.sql_translator.identifier_normalizer import IdentifierNormalizer


def test_cast_syntax_removal():
    nm = IdentifierNormalizer()
    sql = "CREATE TABLE t1 (col1 text DEFAULT 'val'::text)"
    expected = "CREATE TABLE T1 (COL1 TEXT DEFAULT 'val')"
    result, _ = nm.normalize(sql)
    assert result == expected


def test_cast_syntax_multiple_removal_custom():
    nm = IdentifierNormalizer()
    sql = "INSERT INTO t1 VALUES ('a'::text, 'b'::varchar(10))"
    expected = "INSERT INTO T1 VALUES ('a', 'b')"
    result, _ = nm.normalize(sql)
    assert result == expected


def test_cast_syntax_quoted_type_removal():
    nm = IdentifierNormalizer()
    sql = "SELECT 'val'::\"MyType\""
    expected = "SELECT 'val'"
    result, _ = nm.normalize(sql)
    assert result == expected
