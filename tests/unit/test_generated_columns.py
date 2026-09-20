"""`GENERATED ALWAYS AS ... STORED` columns are dropped on the way to IRIS.

The expectations here uppercased column names, which the normalizer stopped
doing deliberately — see `_normalize_create_table_columns` and the
CREATE TABLE branch of `normalize`, which lowercase column names so a
PostgreSQL client that wrote `id` gets `id` back from the catalog. The table
name is still uppercased for IRIS. Measured in IRIS 2026.1: a table created
this way stores `id,name` and resolves both `SELECT ID` and `SELECT id`, so
the case of a column name is cosmetic on the read path.

So each test below asserts the thing it was written for — the generated column
is gone — and pins the surviving column's case separately, where a future
change to it is legible instead of arriving as a mystery diff.
"""

import pytest

from iris_pgwire.sql_translator.enum_registry import EnumTypeRegistry
from iris_pgwire.sql_translator.identifier_normalizer import IdentifierNormalizer


def test_generated_column_skip():
    nm = IdentifierNormalizer()
    sql = "CREATE TABLE t1 (id int, col1 int GENERATED ALWAYS AS (id * 2) STORED)"
    expected = "CREATE TABLE T1 (id INT)"
    result, _ = nm.normalize(sql)
    assert "col1" not in result.lower(), "the generated column reached IRIS"
    assert result == expected


def test_generated_column_multiple_skip():
    nm = IdentifierNormalizer()
    sql = "CREATE TABLE t1 (id int, col1 int GENERATED ALWAYS AS (id * 2) STORED, col2 text)"
    expected = "CREATE TABLE T1 (id INT, col2 TEXT)"
    result, _ = nm.normalize(sql)
    assert "col1" not in result.lower(), "the generated column reached IRIS"
    assert result == expected
