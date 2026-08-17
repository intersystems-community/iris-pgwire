"""T015a: the pg_views view, driven against real IRIS.

An empty `pg_views` is the right answer for a schema with no views, which makes
it a poor test on its own — a view that always returns nothing would pass. So
every assertion here is made against a view this test creates, and there is an
explicit guard that the empty case means "none" rather than "broken".

Marked `integration`; needs the IRIS instance with the catalog views installed
(the server installs them at startup).
"""

from __future__ import annotations

import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.iris_integration]

BASE = "T015aBase"
VIEW = "T015aView"


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
        cur.execute("SELECT COUNT(*) FROM pg_catalog.pg_views")
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            "pg_catalog.pg_views is not installed in the reachable IRIS instance. "
            f"Start the pgwire server against it once so the catalog objects are created ({exc})"
        )
    for sql in (
        f"DROP VIEW IF EXISTS SQLUser.{VIEW}",
        f"DROP TABLE IF EXISTS SQLUser.{BASE}",
        f"CREATE TABLE SQLUser.{BASE} (id INT NOT NULL PRIMARY KEY, label VARCHAR(20))",
        f"CREATE VIEW SQLUser.{VIEW} AS SELECT id, label FROM SQLUser.{BASE} WHERE id > 0",
    ):
        try:
            cur.execute(sql)
        except Exception as exc:  # noqa: BLE001
            if not sql.startswith("DROP"):
                pytest.fail(f"fixture setup failed: {sql[:60]} -> {exc}")
    yield cur
    for sql in (f"DROP VIEW IF EXISTS SQLUser.{VIEW}", f"DROP TABLE IF EXISTS SQLUser.{BASE}"):
        try:
            cur.execute(sql)
        except Exception:  # noqa: BLE001, S110
            pass


def _rows(cursor, sql, *params):
    cursor.execute(sql, params if params else None)
    columns = [d[0].lower() for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


class TestTheViewReportsRealViews:
    def test_a_created_view_appears(self, cursor):
        rows = _rows(
            cursor,
            "SELECT schemaname, viewname, definition FROM pg_catalog.pg_views "
            f"WHERE viewname = '{VIEW.lower()}'",
        )
        assert len(rows) == 1, "the view this test created is not reported"

    def test_the_schema_is_reported_as_public_not_as_the_iris_schema(self, cursor):
        """A literal 'public' in the DDL would have been rewritten to SQLUser."""
        rows = _rows(
            cursor,
            f"SELECT schemaname FROM pg_catalog.pg_views WHERE viewname = '{VIEW.lower()}'",
        )
        assert rows[0]["schemaname"] == "public"

    def test_the_name_is_lowercased_as_a_client_expects(self, cursor):
        rows = _rows(cursor, "SELECT viewname FROM pg_catalog.pg_views")
        names = {row["viewname"] for row in rows}
        assert VIEW.lower() in names
        assert VIEW not in names, "PostgreSQL folds unquoted identifiers to lower case"

    def test_the_definition_is_carried(self, cursor):
        rows = _rows(
            cursor,
            f"SELECT definition FROM pg_catalog.pg_views WHERE viewname = '{VIEW.lower()}'",
        )
        definition = rows[0]["definition"]
        assert definition, "an ORM writes this into a generated schema; empty is useless"
        assert "label" in definition.lower()


class TestPgwiresOwnViewsAreNotReported:
    """The instance really does contain pg_catalog.pg_class and friends.

    Reporting them would have an ORM generate models for pgwire's own emulation.
    """

    def test_the_catalog_emulation_views_are_absent(self, cursor):
        names = {row["viewname"] for row in _rows(cursor, "SELECT viewname FROM pg_catalog.pg_views")}
        for own in ("pg_class", "pg_namespace", "pg_constraint", "pg_views"):
            assert own not in names, f"{own} is pgwire's own emulation, not a user view"


class TestPrismasOwnQuery:
    def test_the_join_to_pg_namespace_resolves(self, cursor):
        """schemaname is joined to nspname as text, so the two must agree."""
        rows = _rows(
            cursor,
            "SELECT views.viewname, views.schemaname FROM pg_catalog.pg_views views "
            "INNER JOIN pg_catalog.pg_namespace ns ON views.schemaname = ns.nspname",
        )
        assert rows, (
            "the join produced nothing: pg_views.schemaname does not match any "
            "pg_namespace.nspname, so a client sees no views at all"
        )
        assert VIEW.lower() in {row["viewname"] for row in rows}

    def test_the_join_to_pg_class_resolves_by_name(self, cursor):
        """Prisma also joins pg_class on relname = viewname, and needs relkind 'v'."""
        rows = _rows(
            cursor,
            "SELECT c.relname, c.relkind FROM pg_catalog.pg_views v "
            "INNER JOIN pg_catalog.pg_class c ON c.relname = v.viewname "
            f"WHERE v.viewname = '{VIEW.lower()}'",
        )
        assert len(rows) == 1, "pg_class does not report the view under the same name"
        assert rows[0]["relkind"] == "v"
