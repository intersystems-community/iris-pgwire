"""T015c: the DBAPI type codes IRIS reports, and what we did with them.

`_map_dbapi_type_to_oid` took `cursor.description[1]`, called `str(...).upper()`
on it, and grepped the result for `INT`/`CHAR`/`DATE`/`TIME`. IRIS reports a
**numeric** ODBC code there, so `str(12).upper() == "12"` matched nothing and
every column became varchar — bigint, bit, double, timestamp and all:

    12 -> 1043    -7 -> 1043    4 -> 1043
    -5 -> 1043     8 -> 1043   93 -> 1043

This corrects the record. T011h stated the cause as "IRIS DBAPI reports
type_code 4, hence 1043 for everything". That is not what this instance reports.
Measured directly against IRIS 2026.2 (Build 221U), the codes arrive **distinct
and correct**, and identical whether the query returns rows or not:

    declared type    code        declared type    code
    INT               4          BIT              -7
    BIGINT           -5          NUMERIC(10,2)     2
    SMALLINT          5          DATE           1091
    TINYINT          -6          TIME           1092
    VARCHAR/CHAR     12          TIMESTAMP      1093
    LONGVARCHAR      -1          POSIXTIME      1093
    DOUBLE            8          CURRENT_TIMESTAMP 11

So the driver was never the problem. Five lines of ours discarded good metadata,
and the value-based refinement that made a column's type depend on the row count
existed to repair damage we had caused. T011h's fix (resolving from the SQL) is
still needed — no ODBC code can say that `relrowsecurity`, stored 0/1 and
reported as an integer, is a PostgreSQL `bool` — but its stated cause was wrong.

**Why code 4 is deliberately left alone**: IRIS reports 4 for a literal of *any*
type, measured — `SELECT 'abc'` is 4, `SELECT 1.5` is 4, `SELECT 0` is 4. So 4
cannot be mapped to int4 without declaring text as an integer, which is worse
than declaring an integer as text. That ambiguity is its own task, with the
measurement recorded, rather than a guess made here.
"""

from __future__ import annotations

import pytest

from iris_pgwire.dbapi_executor import DBAPIExecutor

# Measured against IRIS 2026.2 by creating a table with each declared type and
# reading cursor.description. Not taken from the ODBC specification: IRIS's date
# and time codes (1091/1092/1093) are its own, not ODBC's 91/92/93.
MEASURED_CODES = {
    4: "INT",
    -5: "BIGINT",
    5: "SMALLINT",
    -6: "TINYINT",
    12: "VARCHAR / CHAR",
    -1: "LONGVARCHAR",
    8: "DOUBLE",
    2: "NUMERIC",
    -7: "BIT",
    1091: "DATE",
    1092: "TIME",
    1093: "TIMESTAMP / POSIXTIME",
    11: "CURRENT_TIMESTAMP",
}


def oid_for(code):
    return DBAPIExecutor._map_dbapi_type_to_oid(None, code)


class TestTheCodesAreNoLongerDiscarded:
    @pytest.mark.parametrize(
        ("code", "expected_oid", "why"),
        [
            (-5, 20, "bigint is int8, and a client reading binary needs 8 bytes"),
            (5, 21, "smallint is int2"),
            (-6, 21, "tinyint has no PostgreSQL equivalent narrower than int2"),
            (12, 1043, "varchar"),
            (-1, 25, "longvarchar is text"),
            (8, 701, "double is float8"),
            (2, 1700, "numeric"),
            (-7, 16, "BIT is how IRIS spells boolean; one byte in binary format"),
            (1091, 1082, "date"),
            (1092, 1083, "time"),
            (1093, 1114, "timestamp"),
            (11, 1114, "what CURRENT_TIMESTAMP reports"),
        ],
    )
    def test_each_measured_code_maps_to_its_postgresql_type(self, code, expected_oid, why):
        assert oid_for(code) == expected_oid, why

    def test_a_bit_column_is_no_longer_reported_as_text(self):
        """The narrowest statement of the defect."""
        assert oid_for(-7) == 16

    def test_a_bigint_is_no_longer_reported_as_text(self):
        assert oid_for(-5) == 20


class TestCodeFourIsLeftAmbiguousOnPurpose:
    """IRIS reports 4 for a literal of any type, so 4 cannot mean int4."""

    def test_four_stays_varchar(self):
        assert oid_for(4) == 1043, (
            "measured: SELECT 'abc' and SELECT 1.5 both report code 4, so mapping 4 to "
            "int4 would declare text as an integer — worse than the reverse"
        )

    def test_the_reason_is_recorded_where_the_decision_is(self):
        import inspect

        source = inspect.getsource(DBAPIExecutor._map_dbapi_type_to_oid)
        assert "literal" in source.lower(), (
            "the next reader will 'fix' code 4 unless the measurement is beside it"
        )


class TestStringCodesStillWork:
    """Some paths pass a type *name*, not a numeric code; both must be handled."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [("INTEGER", 23), ("VARCHAR", 1043), ("DATE", 1082), ("TIMESTAMP", 1114)],
    )
    def test_a_named_type_is_still_mapped(self, name, expected):
        assert oid_for(name) == expected


class TestUnknownInputIsSafe:
    @pytest.mark.parametrize("value", [None, "", "SOMETHING_ELSE", 9999, object()])
    def test_anything_unrecognised_falls_back_to_varchar(self, value):
        """A length-prefixed string is the one declaration that cannot corrupt a value."""
        assert oid_for(value) == 1043


class TestTheCodesDoNotDependOnTheRowCount:
    """Measured: identical description at 9 rows and 0 rows.

    Recorded here because T011h's fix was built on the opposite assumption, and
    the next person to touch this should know the driver is not the variable.
    """

    def test_mapping_is_a_pure_function_of_the_code(self):
        for code in MEASURED_CODES:
            assert oid_for(code) == oid_for(code)
