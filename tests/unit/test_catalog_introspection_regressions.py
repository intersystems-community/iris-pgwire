"""Regression tests for the catalog/introspection defects fixed 2026-08-16.

Each test pins one defect found while running `prisma db pull` against a real
IRIS 2026.2 instance. See docs/orm-introspection-findings.md for the full
investigation.

These are pure-function tests over real code paths — no mocks and no fakes.
The IRIS-dependent behaviour is covered separately by the E2E suite; what is
pinned here is the logic that was wrong regardless of backend, which is why
every one of these defects reproduced identically on both.
"""

from __future__ import annotations

import asyncio

import pytest

from iris_pgwire.catalog import catalog_router as cr
from iris_pgwire.catalog.catalog_router import CatalogRouter

# The production function itself, not a copy of it — a mirrored implementation
# would keep passing if protocol.py were reverted.
from iris_pgwire.protocol import build_command_complete_tag as build_command_tag
from iris_pgwire.sql_translator import SQLInterceptor


class TestCommandCompleteTag:
    """Defect 3: `SELECT 0 0` — an invalid CommandComplete tag.

    catalog_router emits command_tag="SELECT 0" with the count already in it.
    _send_command_complete treated its argument as a bare verb and appended the
    count again, producing "SELECT 0 0". Clients reject that with "could not
    interpret result from server", so every emulated catalog query failed at
    the protocol level rather than returning rows.
    """

    @pytest.mark.parametrize(
        ("command", "row_count", "expected"),
        [
            # The regression: a tag that already carries its count.
            ("SELECT 0", 0, "SELECT 0"),
            ("SELECT 3", 3, "SELECT 3"),
            ("INSERT 0 1", 1, "INSERT 0 1"),
            # Bare verbs must keep appending the count, as before.
            ("SELECT", 5, "SELECT 5"),
            ("SELECT", 0, "SELECT 0"),
            ("INSERT", 1, "INSERT 1"),
            ("UPDATE", 2, "UPDATE 2"),
            ("DELETE", 1, "DELETE 1"),
            ("CREATE TABLE", 0, "CREATE TABLE 0"),
            ("BEGIN", 0, "BEGIN 0"),
        ],
    )
    def test_tag_is_never_double_counted(self, command, row_count, expected):
        assert build_command_tag(command, row_count) == expected

    def test_catalog_router_tag_survives_the_protocol_layer(self):
        """The router's own tag must pass through unchanged."""
        router = CatalogRouter()
        result = asyncio.run(
            router.handle_catalog_query("SELECT nspname FROM pg_namespace", None, "t", None)
        )
        assert result is not None
        tag = result["command_tag"]
        assert build_command_tag(tag, result["row_count"]) == tag, (
            f"router tag {tag!r} was rewritten by the protocol layer"
        )


class TestSchemaQualifiedCatalogNames:
    """Defect 1a: `FROM pg_catalog.pg_namespace` was not matched.

    The handler required a bare `FROM PG_NAMESPACE`, so the schema-qualified
    form real clients emit fell to the router's empty fallback and returned
    zero rows.
    """

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT nspname FROM pg_namespace",
            "SELECT nspname FROM pg_catalog.pg_namespace",
            "SELECT nspname FROM PG_CATALOG.PG_NAMESPACE",
            "select nspname from pg_catalog.pg_namespace;",
        ],
    )
    def test_both_qualified_and_bare_forms_resolve(self, sql):
        router = CatalogRouter()
        result = asyncio.run(router.handle_catalog_query(sql, None, "t", None))
        assert result is not None, f"{sql!r} was not intercepted"
        assert result["row_count"] > 0, f"{sql!r} returned no namespaces"

    def test_public_schema_is_reported(self):
        """Introspection asks whether `public` exists; it must be listed."""
        router = CatalogRouter()
        result = asyncio.run(
            router.handle_catalog_query(
                "SELECT nspname FROM pg_catalog.pg_namespace", None, "t", None
            )
        )
        names = {row[0] for row in result["rows"]}
        assert "public" in names, f"public missing from {names}"


class TestUnevaluableExpressionsFallThrough:
    """Defect 1b: the router stole Prisma's schema probe.

    SQLInterceptor has a purpose-built handler for
        SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = $1), version(), ...
    but the catalog router ran first and answered a boolean question with raw
    namespace rows. Prisma read that as "public does not exist" and issued
    CREATE SCHEMA "public".

    The row emulators can project and filter columns; they cannot evaluate
    EXISTS(...) or call scalar functions, so those shapes must fall through.
    """

    PRISMA_PROBE = (
        "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'public'), "
        "version(), current_setting('server_version_num')"
    )

    def test_router_declines_the_prisma_probe(self):
        router = CatalogRouter()
        result = asyncio.run(router.handle_catalog_query(self.PRISMA_PROBE, None, "t", None))
        assert result is None, "router must not answer a query it cannot evaluate"

    def test_interceptor_answers_it_correctly(self):
        class _Executor:
            iris_namespace = "USER"

        outcome = SQLInterceptor(_Executor()).intercept(self.PRISMA_PROBE, None, "t")
        assert outcome.intercepted
        exists_value = outcome.result["rows"][0][0]
        assert exists_value is True, "the public schema must be reported as existing"

    def test_plain_catalog_queries_are_still_intercepted(self):
        """The guard must not disable ordinary catalog emulation."""
        router = CatalogRouter()
        result = asyncio.run(
            router.handle_catalog_query("SELECT nspname FROM pg_namespace", None, "t", None)
        )
        assert result is not None and result["row_count"] > 0


class TestNestedCatalogQueryGuard:
    """Defect 5: pg_class enumerated nothing.

    _build_pg_class_response answers by asking IRIS for
    INFORMATION_SCHEMA.TABLES through the executor. That inner query re-entered
    the router, which has no information_schema.tables handler, so the empty
    fallback swallowed it and returned zero rows — leaving pg_class permanently
    empty and ORM introspection with no tables to find.
    """

    INTERNAL_QUERY = (
        "SELECT TABLE_NAME, TABLE_TYPE, TABLE_SCHEMA FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW')"
    )

    def test_nested_query_reaches_iris(self):
        router = CatalogRouter()

        async def run():
            token = cr._IN_CATALOG_HANDLER.set(True)
            try:
                return await router.handle_catalog_query(self.INTERNAL_QUERY, None, "t", None)
            finally:
                cr._IN_CATALOG_HANDLER.reset(token)

        assert asyncio.run(run()) is None, (
            "a handler's own query must not be intercepted by the router"
        )

    def test_same_query_is_intercepted_at_top_level(self):
        """Only *nested* queries bypass; top-level behaviour is unchanged."""
        router = CatalogRouter()
        result = asyncio.run(router.handle_catalog_query(self.INTERNAL_QUERY, None, "t", None))
        assert result is not None

    def test_guard_is_released_after_dispatch(self):
        """A leaked guard would silently disable catalog emulation thereafter."""
        router = CatalogRouter()
        asyncio.run(router.handle_catalog_query("SELECT nspname FROM pg_namespace", None, "t", None))
        assert cr._IN_CATALOG_HANDLER.get() is False

    def test_guard_is_task_scoped_not_global(self):
        """Concurrent sessions must not suppress each other's interception.

        This is why the guard is a ContextVar rather than an instance flag.
        """
        router = CatalogRouter()

        async def nested_holder():
            token = cr._IN_CATALOG_HANDLER.set(True)
            try:
                await asyncio.sleep(0.01)
                return await router.handle_catalog_query(
                    "SELECT nspname FROM pg_namespace", None, "nested", None
                )
            finally:
                cr._IN_CATALOG_HANDLER.reset(token)

        async def other_session():
            await asyncio.sleep(0.005)
            return await router.handle_catalog_query(
                "SELECT nspname FROM pg_namespace", None, "other", None
            )

        async def run():
            return await asyncio.gather(nested_holder(), other_session())

        nested_result, other_result = asyncio.run(run())
        assert nested_result is None, "nested call should bypass"
        assert other_result is not None, "a concurrent session must be unaffected"


class TestDBAPIBackendParity:
    """Defect 2: session functions worked on embedded but not DBAPI.

    SQLInterceptor was instantiated only in IRISExecutor, so the DBAPI backend
    passed version() through to IRIS SQL, which resolved it as
    SQLUser.VERSION and errored. Constitution Principle IV requires both
    backends stay functional.
    """

    def test_both_executors_wire_up_the_interceptor(self):
        import inspect

        from iris_pgwire import dbapi_executor, iris_executor

        for module in (iris_executor, dbapi_executor):
            source = inspect.getsource(module)
            assert "SQLInterceptor(" in source, (
                f"{module.__name__} does not construct SQLInterceptor — "
                "session functions will fail on this backend"
            )
            assert "sql_interceptor.intercept(" in source, (
                f"{module.__name__} constructs SQLInterceptor but never calls it"
            )

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT version()",
            "SELECT current_database()",
        ],
    )
    def test_session_functions_are_intercepted(self, sql):
        class _Executor:
            iris_namespace = "USER"

        outcome = SQLInterceptor(_Executor()).intercept(sql, None, "t")
        assert outcome.intercepted, f"{sql!r} would fall through to IRIS SQL and error"
        assert outcome.result["row_count"] == 1
