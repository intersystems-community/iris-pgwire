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

    The SQL side (PGWire.PG_OID, installed from catalog/functions.py) is
    verified against these same values in the E2E suite; what is pinned here is
    the contract it has to meet.
    """

    # Verified equal against the installed PGWire.PG_OID on IRIS 2026.2.
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
            "PGWire.PG_OID must produce the same value"
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


class TestArrayMembershipRewrite:
    """T011a: `col = ANY($n)` must become `col %INLIST $n`.

    IRIS has no ANY(array) construct — the parser rejects it outright with
    "SELECT expected, ? found" (SQLCODE -1). The first attempt at this
    substituted the values at execute time, which cannot work: Describe
    prepares the statement with nothing bound, so it fails before any value
    exists. %INLIST is the shape that survives preparation *and* keeps one
    placeholder in the source mapped to one in the target, so the parameter
    count the client is told at Describe still holds at Bind.

    See specs/044-catalog-as-views/research-t011a.md.
    """

    def test_any_becomes_inlist(self):
        from iris_pgwire.sql_translator.array_params import rewrite_any_to_inlist

        sql = rewrite_any_to_inlist(
            "SELECT nspname FROM pg_namespace WHERE nspname = ANY($1)"
        )
        assert sql == (
            "SELECT nspname FROM pg_namespace WHERE nspname %INLIST PGWire.PG_ARRAY($1)"
        )

    def test_rewrite_does_not_need_the_values(self):
        """The whole point: it must work at Describe, before anything is bound."""
        from iris_pgwire.sql_translator.array_params import rewrite_any_to_inlist

        assert "%INLIST" in rewrite_any_to_inlist("SELECT a FROM t WHERE a = ANY(?)")

    def test_placeholder_numbering_is_preserved(self):
        """A moved parameter position would misbind every later parameter."""
        from iris_pgwire.sql_translator.array_params import rewrite_any_to_inlist

        sql = rewrite_any_to_inlist("SELECT a FROM t WHERE b = $1 AND a = ANY($2) AND c = $3")
        assert sql == (
            "SELECT a FROM t WHERE b = $1 AND a %INLIST PGWire.PG_ARRAY($2) AND c = $3"
        )

    def test_not_all_becomes_negated_inlist(self):
        from iris_pgwire.sql_translator.array_params import rewrite_any_to_inlist

        sql = rewrite_any_to_inlist("SELECT a FROM t WHERE t.k <> ALL($1)")
        assert sql == "SELECT a FROM t WHERE NOT (t.k %INLIST PGWire.PG_ARRAY($1))"

    def test_any_over_a_subquery_is_left_alone(self):
        """`ANY (SELECT …)` is standard SQL that IRIS parses natively.

        Verified against real IRIS rather than assumed — see the C0 case in
        spikes/probe_list_constructs.py. Rewriting it would break a construct
        that already works.
        """
        from iris_pgwire.sql_translator.array_params import rewrite_any_to_inlist

        original = "SELECT a FROM t WHERE a = ANY (SELECT k FROM u)"
        assert rewrite_any_to_inlist(original) == original

    def test_array_literal_becomes_an_in_list(self):
        """No parameter to bind, and IRIS has no $LIST literal syntax."""
        from iris_pgwire.sql_translator.array_params import expand_array_literals

        sql = expand_array_literals("SELECT a FROM t WHERE a = ANY('{public,other}')")
        assert sql == "SELECT a FROM t WHERE a IN ('public', 'other')"

    def test_empty_array_literal_matches_nothing_rather_than_failing(self):
        from iris_pgwire.sql_translator.array_params import expand_array_literals

        sql = expand_array_literals("SELECT a FROM t WHERE a = ANY('{}')")
        assert "IN (NULL)" in sql, "an empty set must be a real answer, not a parse error"

    def test_quotes_in_literal_values_are_escaped(self):
        from iris_pgwire.sql_translator.array_params import expand_array_literals

        sql = expand_array_literals("""SELECT a FROM t WHERE a = ANY('{"O''Brien"}')""")
        assert "'O''Brien'" in sql

    def test_scalar_parameters_are_untouched(self):
        from iris_pgwire.sql_translator.array_params import (
            encode_inlist_params,
            has_array_param,
            rewrite_any_to_inlist,
        )

        sql = "SELECT a FROM t WHERE a = $1"
        assert not has_array_param(sql)
        assert rewrite_any_to_inlist(sql) == sql
        assert encode_inlist_params(sql, [5]) == [5]

    def test_bound_array_is_encoded_for_pg_array(self):
        from iris_pgwire.sql_translator.array_params import encode_inlist_params

        params = encode_inlist_params(
            "SELECT nspname FROM pg_namespace WHERE nspname %INLIST PGWire.PG_ARRAY($1)",
            [["public", "pg_catalog"]],
        )
        assert params == ["2|6:public10:pg_catalog"]

    def test_only_the_inlist_parameter_is_encoded(self):
        from iris_pgwire.sql_translator.array_params import encode_inlist_params

        params = encode_inlist_params(
            "SELECT a FROM t WHERE b = $1 AND a %INLIST PGWire.PG_ARRAY($2) AND c = $3",
            ["scalar", ["x"], 7],
        )
        assert params == ["scalar", "1|1:x", 7]

    def test_a_binary_array_must_arrive_as_a_list_not_a_vector_literal(self):
        """Prisma binds text[] in *binary* format; the decoder used to stringify it.

        `_decode_array_binary_parameter` renders a pgvector literal, which is
        right for float arrays and wrong for every other element type: the
        string "[public]" was then encoded as a one-element set containing that
        text, so `nspname = ANY($1)` matched nothing. No error, no rows — after
        the construct itself already worked.
        """
        import inspect

        from iris_pgwire import protocol

        source = inspect.getsource(protocol.PGWireProtocol._decode_array_binary_parameter)
        assert "element_oid not in (700, 701)" in source, (
            "the binary decoder must return elements as a list for non-vector "
            "arrays; a rendered literal binds as a single element"
        )

    def test_array_arrives_from_bind_as_text_and_is_still_encoded(self):
        """Bind decodes a text[] to the string `{a,b}`, never to a Python list.

        This is why the first attempt never fired: it tested isinstance(list)
        against a value the protocol layer does not produce.
        """
        from iris_pgwire.sql_translator.array_params import encode_inlist_params

        params = encode_inlist_params(
            "SELECT a FROM t WHERE a %INLIST PGWire.PG_ARRAY($1)", ["{public,pg_catalog}"]
        )
        assert params == ["2|6:public10:pg_catalog"]

    def test_empty_array_needs_no_special_case(self):
        """`0|` builds an empty list, so it matches nothing without a NULL detour."""
        from iris_pgwire.sql_translator.array_params import encode_inlist_params

        sql = "SELECT a FROM t WHERE a %INLIST PGWire.PG_ARRAY($1)"
        assert encode_inlist_params(sql, [[]]) == ["0|"]
        assert encode_inlist_params(sql, ["{}"]) == ["0|"]

    def test_describe_dummy_parameter_survives(self):
        """Describe prepares with None; that must stay None, not become bytes."""
        from iris_pgwire.sql_translator.array_params import encode_inlist_params

        sql = "SELECT a FROM t WHERE a %INLIST PGWire.PG_ARRAY($1)"
        assert encode_inlist_params(sql, [None]) == [None]

    def test_both_executors_rewrite_array_membership(self):
        """Principle IV: a construct must not work on only one backend."""
        import inspect

        from iris_pgwire import dbapi_executor, iris_executor

        for module in (iris_executor, dbapi_executor):
            source = inspect.getsource(module)
            assert "rewrite_any_to_inlist(" in source, (
                f"{module.__name__} never rewrites ANY(array); "
                "it would reach IRIS as a parse error on this backend"
            )
            assert "encode_inlist_params(" in source, (
                f"{module.__name__} rewrites to %INLIST but never encodes the "
                "bound array, so IRIS would answer SQLCODE -400"
            )


class TestPublicLiteralAgainstCatalogViews:
    """A literal `'public'` must survive when the query targets a catalog view.

    schema_mapper rewrites `'public'` to the IRIS schema name, which is right
    when comparing against IRIS's own catalog and wrong against the emulated
    views, where `public` is the stored value. The guard that scopes the
    rewrite originally excluded any name preceded by a dot — which is exactly
    the `pg_catalog.pg_namespace` spelling clients use, so the defect stayed
    live for every schema-qualified query. Caught end-to-end, not by review.
    """

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT nspname FROM pg_namespace WHERE nspname = 'public'",
            "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname = 'public'",
            "SELECT NSPNAME FROM PG_CATALOG.PG_NAMESPACE WHERE NSPNAME IN ('public')",
            "SELECT relname FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public'",
        ],
    )
    def test_public_is_preserved(self, sql):
        from iris_pgwire.schema_mapper import IRIS_SCHEMA, translate_input_schema

        translated = translate_input_schema(sql)
        assert "'public'" in translated.lower(), (
            f"the literal was rewritten: {translated}"
        )
        assert f"'{IRIS_SCHEMA}'".lower() not in translated.lower()

    def test_non_catalog_queries_still_map_public_to_the_iris_schema(self):
        """The rewrite must stay in force where it is correct."""
        from iris_pgwire.schema_mapper import IRIS_SCHEMA, translate_input_schema

        translated = translate_input_schema(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'public'"
        )
        assert f"'{IRIS_SCHEMA}'" in translated

    def test_a_name_merely_ending_in_a_catalog_name_does_not_count(self):
        """`my_pg_class` is an ordinary user table, not a catalog view."""
        from iris_pgwire.schema_mapper import IRIS_SCHEMA, translate_input_schema

        translated = translate_input_schema(
            "SELECT a FROM my_pg_class WHERE schema_name = 'public'"
        )
        assert f"'{IRIS_SCHEMA}'" in translated


class TestPostgresArrayLiteralParsing:
    """The text format a client sends for an array parameter."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("{}", []),
            ("{a}", ["a"]),
            ("{a,b}", ["a", "b"]),
            ("{ a , b }", ["a", "b"]),
            ('{"a,b",c}', ["a,b", "c"]),
            ('{"say \\"hi\\""}', ['say "hi"']),
            ("{NULL}", [None]),
            ("{null,a}", [None, "a"]),
            ('{"NULL"}', ["NULL"]),
            ('{""}', [""]),
        ],
    )
    def test_parsing(self, text, expected):
        from iris_pgwire.sql_translator.array_params import parse_pg_array_literal

        assert parse_pg_array_literal(text) == expected

    @pytest.mark.parametrize("text", ["public", "", "{a", 'a}', "{{1,2},{3,4}}", '{"unclosed}'])
    def test_non_arrays_are_declined_not_guessed(self, text):
        """Nested arrays have no %INLIST equivalent; flattening would be a lie."""
        from iris_pgwire.sql_translator.array_params import parse_pg_array_literal

        assert parse_pg_array_literal(text) is None

    def test_a_bare_scalar_is_treated_as_a_one_element_set(self):
        from iris_pgwire.sql_translator.array_params import encode_inlist_params

        params = encode_inlist_params(
            "SELECT a FROM t WHERE a %INLIST PGWire.PG_ARRAY($1)", ["public"]
        )
        assert params == ["1|6:public"]
