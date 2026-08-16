"""Tests for pg_catalog exposed as IRIS views (feature 044).

Covers the parts that are pure logic: OID parity between the Python and
ObjectScript implementations, view DDL shape, and the routing invariant that
exactly one path answers any catalog table.

The database-side behaviour — that IRIS evaluates projections, aliases, joins
and CTEs over these views — is covered by the E2E suite against real IRIS, per
Constitution Principle II. No mock IRIS is used here or anywhere.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from iris_pgwire.catalog.catalog_router import CatalogRouter
from iris_pgwire.catalog.oid_generator import OIDGenerator
from iris_pgwire.catalog.views import (
    CATALOG_SCHEMA,
    CATALOG_VIEWS,
    VIEW_BACKED_TABLES,
)
from iris_pgwire.catalog.views.definitions import PG_CLASS, PG_NAMESPACE


class TestOidParity:
    """T002: the SQL and Python OID implementations must agree.

    Both paths are live during incremental migration — a view-backed table gets
    its OIDs from PGWire.PG_OID, a handler-backed one from OIDGenerator. If they
    disagree, a client joining pg_class to pg_attribute across the two paths
    silently matches nothing.

    The ObjectScript side (src/iris_pgwire/objectscript/PGWire.Catalog.cls) is
    verified against these same values in the E2E suite; what is pinned here is
    the contract it has to meet.
    """

    # Verified equal against PGWire.Catalog.PgOid on IRIS 2026.2.
    KNOWN_VALUES = {
        ("table", "customer", "sqluser"): 3909377549,
        ("table", "orderline", "sqluser"): 1128014727,
    }

    @pytest.mark.parametrize(("identity", "expected"), list(KNOWN_VALUES.items()))
    def test_python_matches_objectscript(self, identity, expected):
        object_type, object_name, namespace = identity
        actual = OIDGenerator().get_oid(object_type, object_name, namespace)
        assert actual == expected, (
            "Python and ObjectScript OID implementations have diverged; "
            "PGWire.Catalog.PgOid must produce the same value"
        )

    def test_oids_are_stable(self):
        first = OIDGenerator().get_oid("table", "customer", "sqluser")
        second = OIDGenerator().get_oid("table", "customer", "sqluser")
        assert first == second

    def test_oids_are_distinct(self):
        gen = OIDGenerator()
        names = ["customer", "customerorder", "orderline", "iadcheck"]
        oids = {gen.get_oid("table", n, "sqluser") for n in names}
        assert len(oids) == len(names), "OID collision across distinct tables"

    def test_oids_are_in_user_range(self):
        gen = OIDGenerator()
        for name in ("customer", "orderline"):
            assert gen.get_oid("table", name, "sqluser") >= 16384


class TestViewDefinitions:
    """T003: the view registry is well formed."""

    def test_views_live_in_the_pg_catalog_schema(self):
        assert CATALOG_SCHEMA == "pg_catalog"
        for view in CATALOG_VIEWS:
            assert view.qualified_name == f"pg_catalog.{view.name}"

    def test_create_sql_is_a_view_over_the_declared_body(self):
        sql = PG_NAMESPACE.create_sql()
        assert sql.startswith("CREATE VIEW pg_catalog.pg_namespace AS")
        assert "nspname" in sql

    def test_public_schema_is_exposed(self):
        """The original blocker: introspection concluded `public` did not exist."""
        assert str(2200) in PG_NAMESPACE.body, "the public namespace OID must be present"
        assert "PG_PUBLIC_SCHEMA()" in PG_NAMESPACE.body, (
            "the public schema name must come from the SqlProc"
        )

    def test_public_is_never_a_literal_in_ddl(self):
        """A literal 'public' is silently rewritten to the IRIS schema name.

        The SQL translation layer maps public -> IRIS schema on the way in, so a
        view defined with the literal reports 'SQLUser' to clients — the exact
        value the mapping exists to hide. Observed live before this was changed.
        """
        for view in CATALOG_VIEWS:
            assert "'public'" not in view.body.lower(), (
                f"{view.name} embeds a literal 'public'; the translation layer will "
                "rewrite it. Use PGWire.PG_PUBLIC_SCHEMA() instead."
            )

    def test_pg_class_declares_postgresql_column_order(self):
        """Clients read by name, but positional access must work too."""
        assert PG_CLASS.columns[0] == "oid"
        assert PG_CLASS.columns[1] == "relname"
        assert PG_CLASS.columns[2] == "relnamespace"
        assert "relkind" in PG_CLASS.columns

    def test_every_declared_column_appears_in_the_body(self):
        for view in CATALOG_VIEWS:
            for column in view.columns:
                assert re.search(rf"\b{re.escape(column)}\b", view.body), (
                    f"{view.name} declares column {column!r} that its body never produces"
                )

    def test_pg_class_reads_the_live_schema(self):
        """No cache to invalidate — a new table must show up immediately."""
        assert "INFORMATION_SCHEMA.TABLES" in PG_CLASS.body

    def test_pg_class_computes_oids_in_sql(self):
        assert "PGWire.PG_OID(" in PG_CLASS.body


class TestExactlyOnePathPerTable:
    """T007: a table is served by a view or by a handler, never both.

    A table in both places means the handler intercepts first and the view is
    dead code — the failure would look like the emulator simply being wrong.
    """

    def test_declined_set_matches_the_view_registry(self):
        assert VIEW_BACKED_TABLES == frozenset(v.name for v in CATALOG_VIEWS)

    @pytest.mark.parametrize(
        ("sql", "expect_declined"),
        [
            ("SELECT nspname FROM pg_namespace", True),
            ("SELECT nspname FROM pg_catalog.pg_namespace", True),
            ("SELECT relname FROM pg_class", True),
            ("SELECT relname FROM pg_catalog.pg_class", True),
            ("SELECT relname FROM pg_catalog.pg_class WHERE relkind = 'r'", True),
            (
                "SELECT t.relname AS table_name FROM pg_class t "
                "JOIN pg_namespace s ON s.oid = t.relnamespace",
                True,
            ),
            # Not yet view-backed — the handler must still answer these.
            ("SELECT attname FROM pg_attribute", False),
            (
                "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid",
                False,
            ),
        ],
    )
    def test_routing(self, sql, expect_declined):
        router = CatalogRouter()
        result = asyncio.run(router.handle_catalog_query(sql, None, "t", None))
        declined = result is None
        assert declined is expect_declined, (
            f"{sql!r}: expected {'view' if expect_declined else 'handler'} to serve it"
        )

    def test_schema_qualifier_is_not_mistaken_for_a_table(self):
        """`pg_catalog` matches the pg_ prefix heuristic but is a schema."""
        router = CatalogRouter()
        tables = router.extract_catalog_tables("SELECT relname FROM pg_catalog.pg_class")
        assert "pg_catalog" in tables, "precondition: the heuristic still picks it up"
        result = asyncio.run(
            router.handle_catalog_query("SELECT relname FROM pg_catalog.pg_class", None, "t", None)
        )
        assert result is None, "the qualifier must not block declining a view-backed table"

    def test_a_mixed_query_stays_with_the_handler(self):
        """Declining a query the views cannot fully answer would lose the join."""
        router = CatalogRouter()
        result = asyncio.run(
            router.handle_catalog_query(
                "SELECT c.relname, a.attname FROM pg_class c "
                "JOIN pg_attribute a ON a.attrelid = c.oid",
                None,
                "t",
                None,
            )
        )
        assert result is not None


class TestInstallerContract:
    """T005: installation is idempotent and fails loudly.

    A silently half-installed catalog answers introspection with empty results
    — the exact failure mode this feature removes (spec FR-009).
    """

    def test_install_error_is_raised_not_swallowed(self):
        from iris_pgwire.catalog.views import CatalogViewInstallError, CatalogViewInstaller

        class _FailingExecutor:
            async def execute_query(self, sql, session_id=None):
                if sql.startswith("CREATE VIEW"):
                    return {"success": False, "error": "insufficient privilege"}
                return {"success": True}

        installer = CatalogViewInstaller(_FailingExecutor())
        with pytest.raises(CatalogViewInstallError, match="insufficient privilege"):
            asyncio.run(installer.install())

    def test_install_is_idempotent(self):
        """Each view drops before it creates, so a second run converges."""
        from iris_pgwire.catalog.views import CatalogViewInstaller

        executed: list[str] = []

        class _RecordingExecutor:
            async def execute_query(self, sql, session_id=None):
                executed.append(sql)
                return {"success": True}

        installer = CatalogViewInstaller(_RecordingExecutor())
        first = asyncio.run(installer.install())
        midpoint = len(executed)
        second = asyncio.run(installer.install())

        assert first == second, "installation is not deterministic"
        assert len(executed) == midpoint * 2, "second run did different work"
        for view in CATALOG_VIEWS:
            assert view.drop_sql() in executed
            assert view.create_sql() in executed
