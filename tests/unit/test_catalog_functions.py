"""Tests for the PGWire SQL functions and their installer (feature 044).

These functions are the foundation the catalog views stand on — every view calls
PG_OID or PG_PUBLIC_SCHEMA, and `= ANY($n)` translation calls PG_ARRAY. Until
this installer existed they had to be loaded by hand and nothing in the codebase
did it, so the views only worked on an instance someone had already prepared.

What runs inside IRIS is verified against a real instance by the E2E suite. What
is pinned here is the DDL contract, the install ordering, and the two rules that
DDL has to obey to survive the round trip.
"""

from __future__ import annotations

import asyncio

import pytest

from iris_pgwire.catalog.functions import (
    CATALOG_FUNCTIONS,
    CATALOG_SCHEMA,
    PG_ARRAY,
    PG_OID,
    PG_PUBLIC_SCHEMA,
)


class TestDefinitions:
    def test_functions_live_in_the_pgwire_schema(self):
        assert CATALOG_SCHEMA == "PGWire"
        for function in CATALOG_FUNCTIONS:
            assert function.qualified_name == f"PGWire.{function.name}"

    def test_create_sql_is_a_replaceable_objectscript_function(self):
        sql = PG_OID.create_sql()
        assert sql.startswith("CREATE OR REPLACE FUNCTION PGWire.PG_OID(")
        assert "LANGUAGE OBJECTSCRIPT" in sql

    def test_no_colon_loops(self):
        """`for i = 1:1:4` is read by the SQL parser as a host variable.

        It fails with "Parameter Name error, First value cannot be a digit", so
        every loop in a function body has to be a `while`.
        """
        for function in CATALOG_FUNCTIONS:
            assert " for " not in function.body, (
                f"{function.name} uses a for loop; a ranged one would be parsed as a "
                "host variable. Use while."
            )

    def test_no_class_names_in_declarations(self):
        """Declarations are uppercased in transit, and class names are case-sensitive.

        `RETURNS %Library.List` arrives as `%LIBRARY.LIST` and fails to compile.
        SQL type names survive because they are case-insensitive.
        """
        for function in CATALOG_FUNCTIONS:
            declaration = f"{function.signature} {function.returns}"
            assert "%" not in declaration, (
                f"{function.name} names a class in its signature or return type; "
                "it will be uppercased and will not resolve"
            )

    def test_public_is_never_a_literal(self):
        """The translation layer rewrites a literal 'public' to the IRIS schema."""
        for function in CATALOG_FUNCTIONS:
            assert '"public"' not in function.body
            assert "'public'" not in function.body

    def test_pg_oid_keeps_the_user_range_offset_not_a_modulus(self):
        """A modulus would give one object different OIDs on the two code paths."""
        assert "16384" in PG_OID.body
        assert "#" not in PG_OID.body

    def test_pg_array_is_strict_about_malformed_input(self):
        """A slid parse must error, not return plausible-looking wrong rows."""
        assert PG_ARRAY.body.count("throw") >= 3

    def test_pg_array_accepts_the_describe_dummy(self):
        """Describe prepares the statement with a NULL bound; that must not throw."""
        assert 'if encoded = "" { quit "" }' in PG_ARRAY.body

    def test_pg_public_schema_takes_no_arguments(self):
        assert PG_PUBLIC_SCHEMA.signature == ""


class _RecordingExecutor:
    def __init__(self, fail_on: str | None = None):
        self.executed: list[str] = []
        self.fail_on = fail_on

    async def execute_query(self, sql, session_id=None):
        self.executed.append(sql)
        if self.fail_on and self.fail_on in sql:
            return {"success": False, "error": "insufficient privilege"}
        return {"success": True}


class TestInstaller:
    def test_installs_every_function(self):
        from iris_pgwire.catalog.function_installer import CatalogFunctionInstaller

        executor = _RecordingExecutor()
        installed = asyncio.run(CatalogFunctionInstaller(executor).install())

        assert installed == [f.qualified_name for f in CATALOG_FUNCTIONS]
        for function in CATALOG_FUNCTIONS:
            assert function.create_sql() in executor.executed

    def test_install_is_idempotent(self):
        """CREATE OR REPLACE converges, so no DROP is needed first."""
        from iris_pgwire.catalog.function_installer import CatalogFunctionInstaller

        executor = _RecordingExecutor()
        installer = CatalogFunctionInstaller(executor)
        first = asyncio.run(installer.install())
        midpoint = len(executor.executed)
        second = asyncio.run(installer.install())

        assert first == second
        assert len(executor.executed) == midpoint * 2
        assert all("DROP" not in sql for sql in executor.executed)

    def test_install_error_is_raised_not_swallowed(self):
        """A missing function means every view fails; startup must abort (FR-009)."""
        from iris_pgwire.catalog.function_installer import (
            CatalogFunctionInstaller,
            CatalogFunctionInstallError,
        )

        executor = _RecordingExecutor(fail_on="PG_ARRAY")
        with pytest.raises(CatalogFunctionInstallError, match="insufficient privilege"):
            asyncio.run(CatalogFunctionInstaller(executor).install())

    def test_ddl_is_executed_verbatim(self):
        """Translating our own ObjectScript is what broke this the first time.

        `$SYSTEM.Encryption` was uppercased to `%SYSTEM.ENCRYPTION` — class names
        are case-sensitive — and the declared parameter was cased differently
        from its uses in the body. Both installed cleanly and then failed on
        every call.
        """
        from iris_pgwire.catalog.function_installer import CatalogFunctionInstaller
        from iris_pgwire.sql_translator.verbatim import is_verbatim

        seen: list[bool] = []

        class _Executor:
            async def execute_query(self, sql, session_id=None):
                seen.append(is_verbatim())
                return {"success": True}

        asyncio.run(CatalogFunctionInstaller(_Executor()).install())
        assert seen and all(seen), "function DDL must execute with translation suppressed"

    def test_guard_is_released_afterwards(self):
        from iris_pgwire.catalog.function_installer import CatalogFunctionInstaller
        from iris_pgwire.sql_translator.verbatim import is_verbatim

        asyncio.run(CatalogFunctionInstaller(_RecordingExecutor()).install())
        assert is_verbatim() is False


class TestStartupOrdering:
    def test_functions_install_before_views(self):
        """Every view calls one of these; the reverse order cannot work."""
        import inspect

        from iris_pgwire import server

        source = inspect.getsource(server)
        functions_at = source.index("await self._install_catalog_functions()")
        views_at = source.index("await self._install_catalog_views()")
        assert functions_at < views_at

    def test_both_installers_run_on_startup(self):
        import inspect

        from iris_pgwire import server

        source = inspect.getsource(server.PGWireServer.start)
        assert "_install_catalog_functions" in source
        assert "_install_catalog_views" in source
