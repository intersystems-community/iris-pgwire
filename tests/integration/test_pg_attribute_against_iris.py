"""T015b: pg_attribute, pg_attrdef and reltype, against real IRIS.

The numbers here cannot be checked by reading SQL. `atttypmod` in particular is
decoded by `format_type`, and PostgreSQL's encoding was measured against
postgres:15-alpine rather than recalled: `varchar(100)` is 104 and
`numeric(10,2)` is 655366. A wrong value makes a client report the wrong column
width, silently — the failure mode this whole feature exists to remove.

`pg_attrdef` is empty for a schema whose columns have no defaults, which makes it
a poor test on its own, so the fixture creates a column with one.

Marked `integration`; needs the IRIS instance with the catalog views installed
(the server installs them at startup).
"""

from __future__ import annotations

import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.iris_integration]

TABLE = "T015bCols"


def _connect():
    dbapi = pytest.importorskip("iris.dbapi", reason="intersystems-irispython not installed")
    try:
        return dbapi.connect(
            hostname=os.environ.get("IRIS_HOST", "localhost"),
            port=int(os.environ.get("IRIS_PORT", "1972")),
            namespace=os.environ.get("IRIS_NAMESPACE", "USER"),
            username=os.environ.get("IRIS_USER", "_SYSTEM"),
            password=os.environ.get("IRIS_PASSWORD", "SYS"),
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"IRIS not reachable: {exc}")


@pytest.fixture(scope="module")
def cursor():
    cur = _connect().cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM pg_catalog.pg_attribute")
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            "pg_catalog.pg_attribute is not installed in the reachable IRIS instance. "
            f"Start the pgwire server against it once so the catalog objects are created ({exc})"
        )
    for sql in (
        f"DROP TABLE IF EXISTS SQLUser.{TABLE}",
        f"CREATE TABLE SQLUser.{TABLE} ("
        "  id INT NOT NULL,"
        "  label VARCHAR(100),"
        "  wide VARCHAR(200) NOT NULL,"
        "  amount NUMERIC(10,2),"
        "  stamp TIMESTAMP,"
        "  status VARCHAR(10) DEFAULT 'new'"
        ")",
    ):
        try:
            cur.execute(sql)
        except Exception as exc:  # noqa: BLE001
            if not sql.startswith("DROP"):
                pytest.fail(f"fixture setup failed: {sql[:70]} -> {exc}")
    yield cur
    try:
        cur.execute(f"DROP TABLE IF EXISTS SQLUser.{TABLE}")
    except Exception:  # noqa: BLE001, S110
        pass


def _cols(cursor):
    cursor.execute(
        "SELECT a.attname, a.atttypid, a.atttypmod, a.attnum, a.attnotnull, a.atthasdef, a.attlen "
        "FROM pg_catalog.pg_attribute a "
        "JOIN pg_catalog.pg_class c ON c.oid = a.attrelid "
        f"WHERE c.relname = '{TABLE.lower()}' ORDER BY a.attnum"
    )
    names = ("attname", "atttypid", "atttypmod", "attnum", "attnotnull", "atthasdef", "attlen")
    return {row[0]: dict(zip(names, row)) for row in cursor.fetchall()}


class TestReltypeSurvivesPrismasFilter:
    """The measurement that reordered T015b: 0 of 9 rows used to survive."""

    def test_every_table_has_a_positive_reltype(self, cursor):
        cursor.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN reltype > 0 THEN 1 ELSE 0 END) AS positive "
            "FROM pg_catalog.pg_class"
        )
        total, positive = cursor.fetchall()[0]
        assert total > 0, "pg_class is empty, so this proves nothing"
        assert positive == total, "Prisma filters its pg_class subquery on reltype > 0"

    def test_reltype_differs_from_the_tables_own_oid(self, cursor):
        cursor.execute(
            f"SELECT oid, reltype FROM pg_catalog.pg_class WHERE relname = '{TABLE.lower()}'"
        )
        rows = cursor.fetchall()
        assert rows, "the fixture table is missing from pg_class"
        oid, reltype = rows[0]
        assert oid != reltype, "the row type is a different object from the table"


class TestColumnsAreReported:
    def test_every_column_appears_once_in_order(self, cursor):
        columns = _cols(cursor)
        assert [c["attname"] for c in sorted(columns.values(), key=lambda c: c["attnum"])] == [
            "id",
            "label",
            "wide",
            "amount",
            "stamp",
            "status",
        ]

    def test_attnum_is_the_tables_own_ordinal(self, cursor):
        columns = _cols(cursor)
        assert columns["id"]["attnum"] == 1
        assert columns["amount"]["attnum"] == 4


class TestTypeOidsAndModifiers:
    """atttypmod is decoded by format_type; the encoding is PostgreSQL's."""

    def test_integer(self, cursor):
        column = _cols(cursor)["id"]
        assert column["atttypid"] == 23
        assert column["atttypmod"] == -1, "int4 has no type modifier"
        assert column["attlen"] == 4

    def test_varchar_carries_its_length_plus_four(self, cursor):
        columns = _cols(cursor)
        assert columns["label"]["atttypid"] == 1043
        assert columns["label"]["atttypmod"] == 104, "varchar(100) is 104, measured on PG 15"
        assert columns["wide"]["atttypmod"] == 204, "varchar(200) is 204"
        assert columns["label"]["attlen"] == -1, "varlena"

    def test_numeric_packs_precision_and_scale(self, cursor):
        column = _cols(cursor)["amount"]
        assert column["atttypid"] == 1700
        assert column["atttypmod"] == (10 * 65536) + 2 + 4, "numeric(10,2) is 655366, measured"

    def test_timestamp(self, cursor):
        column = _cols(cursor)["stamp"]
        assert column["atttypid"] == 1114
        assert column["attlen"] == 8


class TestNullabilityAndDefaults:
    def test_not_null_columns_report_attnotnull(self, cursor):
        columns = _cols(cursor)
        assert columns["id"]["attnotnull"] == 1
        assert columns["wide"]["attnotnull"] == 1
        assert columns["label"]["attnotnull"] == 0

    def test_a_column_with_a_default_reports_atthasdef(self, cursor):
        assert _cols(cursor)["status"]["atthasdef"] == 1

    def test_pg_attrdef_carries_the_default_and_joins_back(self, cursor):
        cursor.execute(
            "SELECT d.adnum, d.adbin FROM pg_catalog.pg_attrdef d "
            "JOIN pg_catalog.pg_class c ON c.oid = d.adrelid "
            f"WHERE c.relname = '{TABLE.lower()}'"
        )
        rows = cursor.fetchall()
        assert len(rows) == 1, "exactly the one column with a default"
        adnum, adbin = rows[0]
        assert adnum == _cols(cursor)["status"]["attnum"]
        assert adbin and "new" in str(adbin), (
            "adbin has to carry something a client can render as the default"
        )

    def test_columns_without_defaults_are_absent_from_pg_attrdef(self, cursor):
        cursor.execute(
            "SELECT COUNT(*) FROM pg_catalog.pg_attrdef d "
            "JOIN pg_catalog.pg_class c ON c.oid = d.adrelid "
            f"WHERE c.relname = '{TABLE.lower()}'"
        )
        assert cursor.fetchall()[0][0] == 1, "one row per defaulted column, not per column"


class TestPrismasJoinShape:
    def test_the_subquery_join_resolves(self, cursor):
        """`oid.oid = att.attrelid` against the reltype-filtered subquery."""
        cursor.execute(
            "SELECT COUNT(*) FROM pg_catalog.pg_attribute att "
            "JOIN (SELECT pg_catalog.pg_class.oid, relname FROM pg_catalog.pg_class "
            "      WHERE reltype > 0) AS oid ON oid.oid = att.attrelid "
            f"WHERE relname = '{TABLE.lower()}'"
        )
        assert cursor.fetchall()[0][0] == 6, "all six columns of the fixture table"


class TestFormatTypeMatchesPostgreSQL:
    """The rendered type string is what an ORM writes into a generated schema.

    Every expectation is what postgres:15-alpine printed for the same arguments,
    measured rather than recalled. The easy mistakes are covered deliberately: no
    parentheses when there is no modifier, and PostgreSQL's own spellings
    (`double precision`, not `float8`).
    """

    @pytest.mark.parametrize(
        ("type_oid", "type_mod", "expected"),
        [
            (23, -1, "integer"),
            (20, -1, "bigint"),
            (16, -1, "boolean"),
            (25, -1, "text"),
            (701, -1, "double precision"),
            (1082, -1, "date"),
            (1083, -1, "time without time zone"),
            (1114, -1, "timestamp without time zone"),
            (1043, 104, "character varying(100)"),
            (1043, -1, "character varying"),
            (1042, 14, "character(10)"),
            (1700, 655366, "numeric(10,2)"),
            (1700, -1, "numeric"),
            (99999, -1, "???"),
        ],
    )
    def test_each_rendering_is_byte_identical(self, cursor, type_oid, type_mod, expected):
        cursor.execute(f"SELECT PGWire.FORMAT_TYPE({type_oid}, {type_mod})")
        assert cursor.fetchall()[0][0] == expected

    def test_it_renders_the_fixture_tables_own_columns(self, cursor):
        """End to end: pg_attribute's atttypmod through format_type."""
        cursor.execute(
            "SELECT a.attname, PGWire.FORMAT_TYPE(a.atttypid, a.atttypmod) AS rendered "
            "FROM pg_catalog.pg_attribute a "
            "JOIN pg_catalog.pg_class c ON c.oid = a.attrelid "
            f"WHERE c.relname = '{TABLE.lower()}' ORDER BY a.attnum"
        )
        rendered = dict(cursor.fetchall())
        assert rendered["id"] == "integer"
        assert rendered["label"] == "character varying(100)"
        assert rendered["wide"] == "character varying(200)"
        assert rendered["amount"] == "numeric(10,2)"
        assert rendered["stamp"] == "timestamp without time zone"


class TestTheOtherTwoFunctions:
    def test_pg_get_expr_returns_the_default_it_is_given(self, cursor):
        cursor.execute(
            "SELECT PGWire.PG_GET_EXPR(d.adbin, d.adrelid) AS rendered "
            "FROM pg_catalog.pg_attrdef d "
            "JOIN pg_catalog.pg_class c ON c.oid = d.adrelid "
            f"WHERE c.relname = '{TABLE.lower()}'"
        )
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert "new" in str(rows[0][0]), "the default has to survive the round trip"

    def test_col_description_is_null_not_invented(self, cursor):
        cursor.execute("SELECT PGWire.COL_DESCRIPTION(1, 1)")
        assert cursor.fetchall()[0][0] is None
