import pytest

from iris_pgwire.sql_translator.identifier_normalizer import IdentifierNormalizer


def test_using_btree_removal():
    nm = IdentifierNormalizer()
    sql = "CREATE INDEX idx1 ON t1 USING btree (col1)"
    expected = "CREATE INDEX IDX1 ON T1 (COL1)"
    result, _ = nm.normalize(sql)
    assert result == expected


def test_using_btree_case_insensitive_custom():
    nm = IdentifierNormalizer()
    sql = "CREATE INDEX idx1 ON t1 USING BTREE (col1)"
    expected = "CREATE INDEX IDX1 ON T1 (COL1)"
    result, _ = nm.normalize(sql)
    assert result == expected
