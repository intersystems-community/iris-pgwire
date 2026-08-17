"""T011g: a CAST tells us the column's type; the detector only saw one shape.

`_detect_cast_type_oid` exists so a column whose type IRIS does not report can
still be described accurately — it was added for asyncpg, which was getting
integers where it expected booleans. It matched only `CAST(? AS BIT) AS col`: a
cast of a *parameter*.

T011b's boolean-projection rewrite emits a cast of a `CASE` expression:

    CAST(CASE WHEN a <> 0 AND b = 'p' THEN 1 ELSE 0 END AS BIT) AS is_partition

so the detector missed it and the column went out as OID 23 (int4). Prisma asks
for results in *binary* format and reads that column as a `bool` — one byte
where four arrive — so it received all five tables and then exited without
writing a schema, with no error printed.
"""

from __future__ import annotations

import pytest

from iris_pgwire.iris_executor import IRISExecutor

BOOL_OID = 16
INT4_OID = 23
VARCHAR_OID = 1043


@pytest.fixture(scope="module")
def detect():
    return IRISExecutor.__dict__["_detect_cast_type_oid"].__get__(
        object.__new__(IRISExecutor), IRISExecutor
    )


class TestCastOfAnExpression:
    """The shape T011b produces."""

    def test_cast_of_a_case_expression(self, detect):
        sql = (
            "SELECT CAST(CASE WHEN TBL.RELHASSUBCLASS <> 0 AND TBL.RELKIND = 'p' "
            "THEN 1 ELSE 0 END AS BIT) AS IS_PARTITION FROM PG_CATALOG.PG_CLASS AS TBL"
        )
        assert detect(sql, "is_partition") == BOOL_OID

    def test_two_casts_in_one_select_list(self, detect):
        sql = (
            "SELECT CAST(CASE WHEN A = 1 THEN 1 ELSE 0 END AS BIT) AS IS_PARTITION, "
            "CAST(CASE WHEN B = 1 THEN 1 ELSE 0 END AS BIT) AS HAS_SUBCLASS FROM T"
        )
        assert detect(sql, "is_partition") == BOOL_OID
        assert detect(sql, "has_subclass") == BOOL_OID

    @pytest.mark.parametrize(
        ("cast_type", "expected"),
        [
            ("BIT", BOOL_OID),
            ("BOOLEAN", BOOL_OID),
            ("INTEGER", INT4_OID),
            ("VARCHAR", VARCHAR_OID),
        ],
    )
    def test_cast_target_types(self, detect, cast_type, expected):
        sql = f"SELECT CAST(CASE WHEN A = 1 THEN 1 ELSE 0 END AS {cast_type}) AS FLAG FROM T"
        assert detect(sql, "flag") == expected

    def test_cast_of_a_column(self, detect):
        sql = "SELECT CAST(RELHASSUBCLASS AS BIT) AS FLAG FROM T"
        assert detect(sql, "flag") == BOOL_OID

    def test_cast_of_a_nested_function_call(self, detect):
        sql = "SELECT CAST(COALESCE(MAX(A), 0) AS INTEGER) AS N FROM T"
        assert detect(sql, "n") == INT4_OID


class TestStillHandlesTheOriginalShapes:
    """The asyncpg fix this was written for must keep working."""

    def test_cast_of_a_parameter(self, detect):
        assert detect("SELECT CAST(? AS BIT) AS FLAG FROM T", "flag") == BOOL_OID

    def test_postgres_style_cast(self, detect):
        assert detect("SELECT $1::BOOL AS FLAG FROM T", "flag") == BOOL_OID


class TestNoFalsePositives:
    """Guessing a type wrongly is worse than not guessing."""

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT A AS FLAG FROM T",
            "SELECT COUNT(*) AS FLAG FROM T",
            # A subquery ending in an alias is not a cast.
            "SELECT (SELECT B AS C FROM U) AS FLAG FROM T",
            # A cast on a *different* column tells us nothing about this one.
            "SELECT CAST(X AS BIT) AS OTHER, A AS FLAG FROM T",
            # An unknown cast target must not be invented.
            "SELECT CAST(A AS SOMETHINGELSE) AS FLAG FROM T",
        ],
    )
    def test_returns_none(self, detect, sql):
        assert detect(sql, "flag") is None

    def test_a_column_whose_name_is_a_suffix_of_another(self, detect):
        """`flag` must not pick up the cast belonging to `is_flag`."""
        sql = "SELECT CAST(X AS BIT) AS IS_FLAG, A AS FLAG FROM T"
        assert detect(sql, "flag") is None
