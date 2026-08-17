"""T015: the pg_constraint view, driven against real IRIS metadata.

The unit tests pin what is decided in Python — the column list, the code
mappings, the routing. None of that proves the view *runs*, or that the numbers
in it are right. Two things here are only checkable against a real table:

* `conkey` must carry the column's position **in the table**. IRIS's
  `KEY_COLUMN_USAGE.ORDINAL_POSITION` is its position within the constraint, so a
  single-column foreign key on the table's second column would report `{1}`
  instead of `{2}` — a wrong answer that no amount of SQL inspection reveals.
* `conrelid` must equal the OID `pg_class` reports for the same table, or a join
  between the two views matches nothing and every relation silently disappears.

Marked `integration`; needs the IRIS instance with the catalog functions and
views installed (the server installs both at startup).
"""

from __future__ import annotations

import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.iris_integration]

PARENT = "T015Parent"
CHILD = "T015Child"

SETUP = [
    f"DROP TABLE IF EXISTS SQLUser.{CHILD}",
    f"DROP TABLE IF EXISTS SQLUser.{PARENT}",
    f"CREATE TABLE SQLUser.{PARENT} "
    "(id INT NOT NULL PRIMARY KEY, code VARCHAR(10) UNIQUE, name VARCHAR(50))",
    # parent_id is deliberately the *second* column: a conkey built from
    # ORDINAL_POSITION would report {1} and look plausible.
    f"CREATE TABLE SQLUser.{CHILD} "
    "(cid INT NOT NULL PRIMARY KEY, parent_id INT, tag VARCHAR(10), "
    f"CONSTRAINT fk_child_parent FOREIGN KEY (parent_id) REFERENCES SQLUser.{PARENT}(id) "
    "ON DELETE CASCADE)",
]


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
    connection = _connect()
    cur = connection.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM pg_catalog.pg_constraint")
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            "pg_catalog.pg_constraint is not installed in the reachable IRIS instance. "
            "Start the pgwire server against it once so the catalog objects are created "
            f"({exc})"
        )
    for sql in SETUP:
        try:
            cur.execute(sql)
        except Exception as exc:  # noqa: BLE001
            if "DROP" not in sql:
                pytest.fail(f"fixture setup failed: {sql[:60]} -> {exc}")
    yield cur
    for name in (CHILD, PARENT):
        try:
            cur.execute(f"DROP TABLE IF EXISTS SQLUser.{name}")
        except Exception:  # noqa: BLE001, S110
            pass


def _rows(cursor, sql, *params):
    cursor.execute(sql, params if params else None)
    columns = [d[0].lower() for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


class TestTheViewAnswers:
    def test_each_constraint_appears_once(self, cursor):
        rows = _rows(
            cursor,
            "SELECT conname, contype FROM pg_catalog.pg_constraint "
            "WHERE conname IN ('fk_child_parent', 'T015CHILD_PKEY2', 'T015PARENT_PKEY2')",
        )
        by_name = {row["conname"]: row["contype"] for row in rows}
        assert by_name["fk_child_parent"] == "f"
        assert by_name["T015CHILD_PKEY2"] == "p"
        assert by_name["T015PARENT_PKEY2"] == "p"

    def test_a_unique_constraint_is_reported_as_u(self, cursor):
        rows = _rows(
            cursor,
            "SELECT contype FROM pg_catalog.pg_constraint "
            f"WHERE conname LIKE '%{PARENT.upper()}_CODE_UNIQUE%'",
        )
        assert rows, "the UNIQUE constraint on code is missing from the view"
        assert all(row["contype"] == "u" for row in rows)


class TestColumnPositionsAreTableRelative:
    """FR-018. The measurement that makes this test worth having."""

    def test_the_foreign_key_reports_the_tables_own_position(self, cursor):
        rows = _rows(
            cursor,
            "SELECT conkey, confkey FROM pg_catalog.pg_constraint "
            "WHERE conname = 'fk_child_parent'",
        )
        assert len(rows) == 1
        assert rows[0]["conkey"] == "{2}", (
            "parent_id is the table's second column; {1} means the position came "
            "from KEY_COLUMN_USAGE.ORDINAL_POSITION, which counts within the constraint"
        )
        assert rows[0]["confkey"] == "{1}", "the referenced column id is the parent's first"

    def test_a_primary_key_on_the_first_column_reports_one(self, cursor):
        rows = _rows(
            cursor,
            "SELECT conkey FROM pg_catalog.pg_constraint WHERE conname = 'T015CHILD_PKEY2'",
        )
        assert rows[0]["conkey"] == "{1}"

    def test_a_non_foreign_key_has_no_referenced_columns(self, cursor):
        rows = _rows(
            cursor,
            "SELECT confkey FROM pg_catalog.pg_constraint WHERE conname = 'T015PARENT_PKEY2'",
        )
        assert rows[0]["confkey"] is None


class TestTheJoinToPgClassResolves:
    """FR-017 — without this, relation discovery finds nothing, silently."""

    def test_conrelid_matches_the_tables_pg_class_oid(self, cursor):
        rows = _rows(
            cursor,
            "SELECT c.conname, c.conrelid, k.oid AS class_oid, k.relname "
            "FROM pg_catalog.pg_constraint c "
            "JOIN pg_catalog.pg_class k ON k.oid = c.conrelid "
            "WHERE c.conname = 'fk_child_parent'",
        )
        assert len(rows) == 1, "the join between the two views did not resolve"
        assert rows[0]["conrelid"] == rows[0]["class_oid"]
        assert rows[0]["relname"] == CHILD.lower()

    def test_confrelid_points_at_the_referenced_table(self, cursor):
        rows = _rows(
            cursor,
            "SELECT k.relname FROM pg_catalog.pg_constraint c "
            "JOIN pg_catalog.pg_class k ON k.oid = c.confrelid "
            "WHERE c.conname = 'fk_child_parent'",
        )
        assert len(rows) == 1
        assert rows[0]["relname"] == PARENT.lower()

    def test_a_non_foreign_key_has_confrelid_zero(self, cursor):
        rows = _rows(
            cursor,
            "SELECT confrelid FROM pg_catalog.pg_constraint WHERE conname = 'T015PARENT_PKEY2'",
        )
        assert rows[0]["confrelid"] == 0


class TestReferentialActions:
    def test_on_delete_cascade_is_reported_as_c(self, cursor):
        rows = _rows(
            cursor,
            "SELECT confdeltype, confupdtype, confmatchtype FROM pg_catalog.pg_constraint "
            "WHERE conname = 'fk_child_parent'",
        )
        assert rows[0]["confdeltype"] == "c"
        assert rows[0]["confupdtype"] == "a", "no explicit ON UPDATE means no action"
        assert rows[0]["confmatchtype"] == "s", "IRIS reports MATCH_OPTION NONE, i.e. simple"


class TestConstraintDefinitions:
    """FR-020: the text an ORM puts in a generated schema."""

    def test_a_primary_key_renders_as_postgresql_does(self, cursor):
        rows = _rows(
            cursor,
            "SELECT PGWire.PG_GET_CONSTRAINTDEF(oid) AS def FROM pg_catalog.pg_constraint "
            "WHERE conname = 'T015CHILD_PKEY2'",
        )
        assert rows[0]["def"] == "PRIMARY KEY (cid)"

    def test_a_foreign_key_carries_its_reference_and_action(self, cursor):
        rows = _rows(
            cursor,
            "SELECT PGWire.PG_GET_CONSTRAINTDEF(oid) AS def FROM pg_catalog.pg_constraint "
            "WHERE conname = 'fk_child_parent'",
        )
        assert rows[0]["def"] == (
            f"FOREIGN KEY (parent_id) REFERENCES {PARENT.lower()}(id) ON DELETE CASCADE"
        )

    def test_a_unique_constraint_renders_its_columns(self, cursor):
        rows = _rows(
            cursor,
            "SELECT PGWire.PG_GET_CONSTRAINTDEF(oid) AS def FROM pg_catalog.pg_constraint "
            f"WHERE conname LIKE '%{PARENT.upper()}_CODE_UNIQUE%'",
        )
        assert rows[0]["def"] == "UNIQUE (code)"

    def test_an_unknown_oid_yields_null_rather_than_an_error(self, cursor):
        """A caller may hold an OID for something we cannot resolve."""
        rows = _rows(cursor, "SELECT PGWire.PG_GET_CONSTRAINTDEF(1) AS def")
        assert rows[0]["def"] is None


class TestPrismasOwnQuery:
    """FR-021 and the CHK045 rule: evaluable, and legitimately empty."""

    def test_the_check_constraint_filter_returns_no_rows_without_erroring(self, cursor):
        rows = _rows(
            cursor,
            "SELECT constr.conname, constr.contype, "
            "PGWire.PG_GET_CONSTRAINTDEF(constr.oid) AS constraint_definition, "
            "constr.condeferrable AS is_deferrable, constr.condeferred AS is_deferred "
            "FROM pg_catalog.pg_constraint constr "
            "JOIN pg_catalog.pg_class AS tableinfo ON tableinfo.oid = constr.conrelid "
            "JOIN pg_catalog.pg_namespace AS schemainfo "
            "ON schemainfo.oid = tableinfo.relnamespace "
            "WHERE contype NOT IN ('p', 'u', 'f')",
        )
        assert rows == [], (
            "IRIS 2026.2 rejects table CHECK constraints, so there are none to report; "
            "the question is evaluable and the answer is zero rows"
        )

    def test_the_same_query_without_the_filter_does_return_rows(self, cursor):
        """Guards the test above: empty must mean "none", not "broken"."""
        rows = _rows(
            cursor,
            "SELECT constr.conname FROM pg_catalog.pg_constraint constr "
            "JOIN pg_catalog.pg_class AS tableinfo ON tableinfo.oid = constr.conrelid "
            "JOIN pg_catalog.pg_namespace AS schemainfo "
            "ON schemainfo.oid = tableinfo.relnamespace",
        )
        assert rows, "the same shape returns nothing at all, so the empty result above proves little"
