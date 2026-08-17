"""T015a: `pg_views`, and the invariant its absence exposed.

With `pg_constraint` served by a view, `prisma db pull` advances to

    SELECT views.viewname AS view_name, views.definition AS view_sql,
           views.schemaname AS namespace, obj_description(class.oid, 'pg_class')
    FROM pg_catalog.pg_views views
    INNER JOIN pg_catalog.pg_namespace ns ON views.schemaname = ns.nspname
    INNER JOIN pg_catalog.pg_class class ON class.relnamespace = ns.oid
                                        AND class.relname = views.viewname
    WHERE schemaname = ANY ( $1 )

and fails with the *same* message as before, `Column type 'xid' could not be
deserialized`. The reason is structural rather than particular to any table: the
router walks a priority list and calls the first handler whose table appears
**anywhere** in the query, so `pg_class` — mentioned only in a JOIN — answered a
question about `pg_views` with pg_class's own 32 columns.

Two things are pinned here, and the second matters more than the first:

1. `pg_views` exists as a view, so this query is answerable.
2. A handler may only answer for the relation the query is **about**. Answering
   with a different table's column set is wrong whatever else is missing, and the
   next unserved catalog table would otherwise reproduce this exactly.
"""

from __future__ import annotations

import asyncio

import pytest

from iris_pgwire.catalog.catalog_router import CatalogRouter
from iris_pgwire.catalog.views.definitions import (
    CATALOG_VIEWS,
    PG_VIEWS,
    VIEW_BACKED_TABLES,
)

# PostgreSQL 15's pg_views, measured against postgres:15-alpine.
POSTGRES_15_COLUMNS = ("schemaname", "viewname", "viewowner", "definition")

PRISMA_VIEWS_QUERY = (
    "SELECT\n"
    "    views.viewname AS view_name,\n"
    "    views.definition AS view_sql,\n"
    "    views.schemaname AS namespace,\n"
    "    obj_description(class.oid, 'pg_class') AS description\n"
    "FROM pg_catalog.pg_views views\n"
    "INNER JOIN pg_catalog.pg_namespace ns ON views.schemaname = ns.nspname\n"
    "INNER JOIN pg_catalog.pg_class class ON class.relnamespace = ns.oid "
    "AND class.relname = views.viewname\n"
    "WHERE schemaname = ANY ( ? )"
)


class TestPgViewsIsAView:
    def test_the_column_list_matches_postgresql(self):
        assert PG_VIEWS.columns == POSTGRES_15_COLUMNS

    def test_it_is_registered_and_declined_by_the_router(self):
        assert PG_VIEWS in CATALOG_VIEWS
        assert "pg_views" in VIEW_BACKED_TABLES

    def test_the_schema_mapper_knows_it_too(self):
        """A second list; a bare pg_views is not qualified without it."""
        from iris_pgwire.schema_mapper import VIEW_BACKED_TABLES as MAPPER_TABLES

        assert "pg_views" in MAPPER_TABLES

    def test_the_schema_name_is_not_a_literal(self):
        """`'public'` in view DDL is rewritten to the IRIS schema on its way in.

        pg_namespace hit this first: a literal would make the view report
        'SQLUser' to clients. The function exists to say `public` without
        writing it.
        """
        assert "PGWire.PG_PUBLIC_SCHEMA()" in PG_VIEWS.body
        assert "'public'" not in PG_VIEWS.body

    def test_only_user_schema_views_are_reported(self):
        """Our own pg_catalog views must not appear as the user's views.

        The instance really does contain pg_catalog.pg_class and friends — plus
        leftovers from earlier spikes — and reporting them would have an ORM
        generate models for pgwire's own emulation.
        """
        from iris_pgwire.schema_mapper import IRIS_SCHEMA

        assert f"TABLE_SCHEMA = '{IRIS_SCHEMA}'" in PG_VIEWS.body


class TestTheRoutingInvariant:
    """A handler may only answer for the relation the query is about."""

    def test_prismas_views_query_is_not_answered_by_the_pg_class_handler(self):
        router = CatalogRouter()
        result = asyncio.run(router.handle_catalog_query(PRISMA_VIEWS_QUERY, session_id="t"))
        assert result is None, (
            "a question about pg_views was answered with another table's column set; "
            f"got {len(result.get('columns', [])) if result else 0} columns"
        )

    @pytest.mark.parametrize(
        ("sql", "expected"),
        [
            ("SELECT * FROM pg_views", "pg_views"),
            ("SELECT * FROM pg_catalog.pg_views views", "pg_views"),
            (
                "SELECT v.viewname FROM pg_views v JOIN pg_class c ON c.relname = v.viewname",
                "pg_views",
            ),
            (
                "SELECT a.attname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid",
                "pg_attribute",
            ),
            ("SELECT 1", None),
        ],
    )
    def test_the_primary_relation_is_the_one_in_the_from_clause(self, sql, expected):
        """Not the first match in a priority list — the relation being queried."""
        assert CatalogRouter().primary_catalog_relation(sql) == expected

    def test_a_join_partner_does_not_become_the_answering_table(self):
        """The precise defect: pg_class appears, but the query is about pg_views."""
        router = CatalogRouter()
        assert router.primary_catalog_relation(PRISMA_VIEWS_QUERY) == "pg_views"

    def test_an_unserved_primary_relation_is_declined_not_substituted(self):
        """pg_matviews has no view and no handler.

        Declining lets IRIS report the missing relation, which reaches the client
        as 42P01 — an honest answer. Substituting pg_class's shape is not.
        """
        router = CatalogRouter()
        sql = (
            "SELECT m.matviewname FROM pg_matviews m "
            "JOIN pg_class c ON c.relname = m.matviewname"
        )
        assert asyncio.run(router.handle_catalog_query(sql, session_id="t")) is None

    def test_a_lone_unhandled_table_still_gets_the_empty_fallback(self):
        """The boundary with T020, stated so it is a decision and not an oversight.

        `pg_roles` has no view and no handler, and nothing else in the statement
        does either — so there is no substitution to prevent. It still receives a
        fabricated empty result, which FR-008c forbids and T020 removes with its
        own verification pass. Narrowing this task to the substitution case keeps
        that change from arriving unannounced under an unrelated scope.
        """
        router = CatalogRouter()
        result = asyncio.run(router.handle_catalog_query("SELECT * FROM pg_roles", session_id="t"))
        assert result is not None, "T020 has landed; delete this test and its rationale"
        assert result["rows"] == []

    def test_a_handled_table_queried_directly_still_answers(self):
        """The invariant must not disable the handlers that remain in use.

        pg_type is one of the few left: pg_attribute and pg_attrdef became views
        in T015b, pg_class and pg_namespace before them.
        """
        router = CatalogRouter()
        result = asyncio.run(
            router.handle_catalog_query(
                "SELECT typname FROM pg_type WHERE typname = 'int4'",
                session_id="t",
            )
        )
        assert result is not None
        assert result["success"] is True
