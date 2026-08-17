"""
Unit Tests: CatalogRouter Extended Coverage

Tests for catalog_router.py to bring coverage above 70%.
Uses unittest.mock; no live IRIS required.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris_pgwire.catalog.catalog_router import CatalogQueryResult, CatalogRouter
from iris_pgwire.catalog.oid_generator import OIDGenerator
from iris_pgwire.schema_mapper import IRIS_SCHEMA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_router():
    return CatalogRouter()


def make_executor(tables_rows=None, columns_rows=None, constraints_rows=None, success=True):
    """Build an async mock executor whose execute_query returns canned data."""
    executor = MagicMock()

    async def execute_query(sql, session_id=None):
        sql_upper = sql.upper()
        if "TABLE_CONSTRAINTS" in sql_upper:
            return {"success": success, "rows": constraints_rows or []}
        if "KEY_COLUMN_USAGE" in sql_upper:
            return {"success": success, "rows": columns_rows or []}
        if "INFORMATION_SCHEMA.TABLES" in sql_upper:
            return {"success": success, "rows": tables_rows or []}
        if "INFORMATION_SCHEMA.COLUMNS" in sql_upper:
            return {"success": success, "rows": columns_rows or []}
        return {"success": success, "rows": []}

    executor.execute_query = execute_query
    return executor


# ---------------------------------------------------------------------------
# CatalogQueryResult
# ---------------------------------------------------------------------------


class TestCatalogQueryResult:
    def test_to_dict_success(self):
        result = CatalogQueryResult(
            success=True,
            rows=[(1, "foo")],
            columns=[{"name": "id"}],
            row_count=1,
            command_tag="SELECT",
            error=None,
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["rows"] == [(1, "foo")]
        assert d["row_count"] == 1
        assert d["error"] is None

    def test_to_dict_error(self):
        result = CatalogQueryResult(success=False, error="oops")
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "oops"

    def test_defaults(self):
        result = CatalogQueryResult(success=True)
        assert result.rows == []
        assert result.columns == []
        assert result.row_count == 0
        assert result.command_tag == "SELECT"
        assert result.error is None


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    def test_pg_catalog_prefix(self):
        router = make_router()
        assert router.can_handle("SELECT * FROM pg_catalog.pg_class") is True

    def test_information_schema_prefix(self):
        router = make_router()
        assert router.can_handle("SELECT * FROM information_schema.tables") is True

    def test_pg_table_no_prefix(self):
        router = make_router()
        assert router.can_handle("SELECT * FROM pg_class WHERE relname = 'x'") is True

    def test_regular_query_not_handled(self):
        router = make_router()
        assert router.can_handle("SELECT * FROM users WHERE id = 1") is False

    def test_empty_query(self):
        router = make_router()
        assert router.can_handle("SELECT 1") is False


# ---------------------------------------------------------------------------
# extract_catalog_tables
# ---------------------------------------------------------------------------


class TestExtractCatalogTables:
    def test_extracts_pg_class(self):
        router = make_router()
        tables = router.extract_catalog_tables("SELECT * FROM pg_class")
        assert "pg_class" in tables

    def test_extracts_multiple_tables(self):
        router = make_router()
        tables = router.extract_catalog_tables(
            "SELECT * FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        )
        assert "pg_class" in tables
        assert "pg_namespace" in tables

    def test_extracts_information_schema_table(self):
        router = make_router()
        tables = router.extract_catalog_tables(
            "SELECT * FROM information_schema.columns WHERE table_name = 'users'"
        )
        assert "information_schema.columns" in tables

    def test_no_catalog_tables_in_regular_query(self):
        router = make_router()
        tables = router.extract_catalog_tables("SELECT * FROM users")
        assert len(tables) == 0

    def test_pg_attribute(self):
        router = make_router()
        tables = router.extract_catalog_tables("SELECT attname FROM pg_attribute WHERE attrelid = 1")
        assert "pg_attribute" in tables


# ---------------------------------------------------------------------------
# has_array_param / translate_array_param
# ---------------------------------------------------------------------------


class TestArrayParam:
    def test_has_array_param_true(self):
        router = make_router()
        assert router.has_array_param("SELECT * FROM pg_class WHERE oid = ANY($1)") is True

    def test_has_array_param_false(self):
        router = make_router()
        assert router.has_array_param("SELECT * FROM pg_class WHERE oid = 123") is False

    def test_translate_string_values(self):
        router = make_router()
        q = "SELECT * FROM pg_class WHERE relname = ANY($1)"
        result = router.translate_array_param(q, ["users", "posts"], param_index=1)
        assert "IN ('users', 'posts')" in result
        assert "ANY" not in result

    def test_translate_int_values(self):
        router = make_router()
        q = "SELECT * FROM pg_class WHERE oid = ANY($1)"
        result = router.translate_array_param(q, [100, 200, 300])
        assert "IN (100, 200, 300)" in result

    def test_translate_empty_values(self):
        router = make_router()
        q = "SELECT * FROM pg_class WHERE oid = ANY($1)"
        result = router.translate_array_param(q, [])
        assert "IN (NULL)" in result

    def test_translate_none_values(self):
        router = make_router()
        q = "SELECT * FROM pg_class WHERE oid = ANY($1)"
        result = router.translate_array_param(q, [None, 42])
        assert "NULL" in result
        assert "42" in result

    def test_translate_string_with_single_quote(self):
        router = make_router()
        q = "SELECT * FROM pg_class WHERE relname = ANY($1)"
        result = router.translate_array_param(q, ["it's"])
        assert "it''s" in result

    def test_translate_param_index_2(self):
        router = make_router()
        q = "SELECT * FROM pg_class WHERE oid = ANY($2)"
        result = router.translate_array_param(q, [5, 6], param_index=2)
        assert "IN (5, 6)" in result
        assert "ANY" not in result


# ---------------------------------------------------------------------------
# has_regclass_cast / resolve_regclass / translate_regclass_casts
# ---------------------------------------------------------------------------


class TestRegclass:
    def test_has_regclass_cast_true(self):
        router = make_router()
        assert router.has_regclass_cast("WHERE attrelid = 'users'::regclass") is True

    def test_has_regclass_cast_false(self):
        router = make_router()
        assert router.has_regclass_cast("WHERE id = 1") is False

    def test_resolve_regclass_simple(self):
        router = make_router()
        oid = router.resolve_regclass("users")
        assert isinstance(oid, int)
        assert oid > 0

    def test_resolve_regclass_with_schema_prefix(self):
        router = make_router()
        oid1 = router.resolve_regclass("public.users")
        oid2 = router.resolve_regclass("users", schema="public")
        # Both should return an int; exact equality depends on OIDGenerator
        assert isinstance(oid1, int)
        assert isinstance(oid2, int)

    def test_resolve_regclass_quoted_identifier(self):
        router = make_router()
        oid = router.resolve_regclass('"MyTable"')
        assert isinstance(oid, int)

    def test_translate_regclass_casts(self):
        router = make_router()
        oid_gen = OIDGenerator()
        expected_oid = oid_gen.get_table_oid("users", IRIS_SCHEMA)
        router2 = CatalogRouter(oid_generator=oid_gen)
        q = "SELECT * FROM pg_attribute WHERE attrelid = 'users'::regclass"
        result = router2.translate_regclass_casts(q, schema=IRIS_SCHEMA)
        assert str(expected_oid) in result
        assert "::regclass" not in result


# ---------------------------------------------------------------------------
# get_target_catalog
# ---------------------------------------------------------------------------


class TestGetTargetCatalog:
    def test_pg_class_priority(self):
        router = make_router()
        q = "SELECT * FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        assert router.get_target_catalog(q) == "pg_class"

    def test_pg_attribute_second_priority(self):
        router = make_router()
        q = "SELECT attname FROM pg_attribute a JOIN pg_namespace n ON n.oid = 1"
        # pg_attribute appears in priority before pg_namespace
        result = router.get_target_catalog(q)
        assert result in ("pg_attribute", "pg_namespace")

    def test_no_catalog_tables_returns_none(self):
        router = make_router()
        assert router.get_target_catalog("SELECT * FROM users") is None

    def test_single_table(self):
        router = make_router()
        assert router.get_target_catalog("SELECT * FROM pg_index") == "pg_index"


# ---------------------------------------------------------------------------
# _build_pg_enum_columns
# ---------------------------------------------------------------------------


class TestBuildPgEnumColumns:
    def test_with_aliases(self):
        router = make_router()
        sql = "SELECT enumlabel AS label, enumtypid AS type_id FROM pg_enum"
        columns = router._build_pg_enum_columns(sql)
        names = [c["name"] for c in columns]
        assert "label" in names
        assert "type_id" in names

    def test_without_aliases_returns_defaults(self):
        router = make_router()
        sql = "SELECT * FROM pg_enum"
        columns = router._build_pg_enum_columns(sql)
        names = [c["name"] for c in columns]
        assert "oid" in names
        assert "enumlabel" in names


# ---------------------------------------------------------------------------
# _filter_pg_type_rows_by_name
# ---------------------------------------------------------------------------


class TestFilterPgTypeRowsByName:
    def test_filters_by_name(self):
        router = make_router()
        rows = [[1, "int4", 10], [2, "text", 10], [3, "bool", 10]]
        result = router._filter_pg_type_rows_by_name("WHERE typname = 'int4'", rows)
        assert len(result) == 1
        assert result[0][1] == "int4"

    def test_no_filter_returns_all(self):
        router = make_router()
        rows = [[1, "int4", 10], [2, "text", 10]]
        result = router._filter_pg_type_rows_by_name("SELECT * FROM pg_type", rows)
        assert result == rows


# ---------------------------------------------------------------------------
# _filter_pg_type_rows_by_namespace
# ---------------------------------------------------------------------------


class TestFilterPgTypeRowsByNamespace:
    def test_no_params_returns_all(self):
        router = make_router()
        rows = [[1, "int4"], [2, "text"]]
        assert router._filter_pg_type_rows_by_namespace(rows, None) == rows
        assert router._filter_pg_type_rows_by_namespace(rows, []) == rows

    def test_pg_catalog_namespace_included(self):
        router = make_router()
        rows = [[1, "int4"], [2, "text"]]
        result = router._filter_pg_type_rows_by_namespace(rows, [["pg_catalog"]])
        assert result == rows

    def test_non_pg_catalog_namespace_excluded(self):
        router = make_router()
        rows = [[1, "int4"], [2, "text"]]
        result = router._filter_pg_type_rows_by_namespace(rows, [["public"]])
        assert result == []


# ---------------------------------------------------------------------------
# _project_pg_type_columns
# ---------------------------------------------------------------------------


class TestProjectPgTypeColumns:
    def test_no_select_match_returns_original(self):
        router = make_router()
        columns = [{"name": "oid"}, {"name": "typname"}]
        rows = [[1, "int4"]]
        result_cols, result_rows = router._project_pg_type_columns(
            "SOMETHING weird", columns, rows
        )
        assert result_cols == columns
        assert result_rows == rows

    def test_projects_specific_columns(self):
        router = make_router()
        columns = [{"name": "oid"}, {"name": "typname"}, {"name": "typlen"}]
        rows = [[1, "int4", 4]]
        result_cols, result_rows = router._project_pg_type_columns(
            "SELECT typname FROM pg_type", columns, rows
        )
        # typname should be projected
        col_names = [c["name"] for c in result_cols]
        assert "typname" in col_names


# ---------------------------------------------------------------------------
# _filter_namespace_rows
# ---------------------------------------------------------------------------


class TestFilterNamespaceRows:
    def test_no_params_returns_all(self):
        router = make_router()
        rows = [(1, "public"), (2, "private")]
        assert router._filter_namespace_rows(rows, None) == rows

    def test_filter_by_name_list(self):
        router = make_router()
        rows = [(1, "public"), (2, "private")]
        result = router._filter_namespace_rows(rows, [["public"]])
        assert len(result) == 1
        assert result[0][1] == "public"

    def test_empty_params_returns_all(self):
        router = make_router()
        rows = [(1, "public")]
        assert router._filter_namespace_rows(rows, []) == rows


# ---------------------------------------------------------------------------
# _project_namespace_columns
# ---------------------------------------------------------------------------


class TestProjectNamespaceColumns:
    def test_returns_none_without_select(self):
        router = make_router()
        cols = [{"name": "oid"}, {"name": "nspname"}]
        rows = [(1, "public")]
        result = router._project_namespace_columns("no from clause", cols, rows)
        assert result is None

    def test_projects_nspname_only(self):
        router = make_router()
        cols = [{"name": "oid"}, {"name": "nspname"}]
        rows = [(1, "public"), (2, "private")]
        result = router._project_namespace_columns(
            "SELECT nspname FROM pg_namespace", cols, rows
        )
        assert result is not None
        assert result["success"] is True
        # Should project just nspname
        col_names = [c["name"] for c in result["columns"]]
        assert "nspname" in col_names

    def test_oid_and_nspname_not_projected(self):
        router = make_router()
        cols = [{"name": "oid"}, {"name": "nspname"}]
        rows = [(1, "public")]
        result = router._project_namespace_columns(
            "SELECT oid, nspname FROM pg_namespace", cols, rows
        )
        assert result is None


# ---------------------------------------------------------------------------
# _matches_pg_constraint / _is_check_constraint_query
# ---------------------------------------------------------------------------


class TestConstraintHelpers:
    def test_matches_pg_constraint_direct(self):
        router = make_router()
        assert router._matches_pg_constraint("SELECT * FROM PG_CONSTRAINT") is True

    def test_matches_pg_constraint_via_alias(self):
        router = make_router()
        assert router._matches_pg_constraint("WHERE CONSTR.CONNAME = 'pk'") is True

    def test_does_not_match_random(self):
        router = make_router()
        assert router._matches_pg_constraint("SELECT * FROM users") is False

    def test_is_check_constraint_query(self):
        router = make_router()
        sql = "SELECT * FROM pg_constraint WHERE contype NOT IN ('P','U','F') AND CONTYPE = 'c'"
        assert router._is_check_constraint_query(sql) is True

    def test_is_not_check_constraint_query(self):
        router = make_router()
        sql = "SELECT * FROM pg_constraint"
        assert router._is_check_constraint_query(sql) is False


# ---------------------------------------------------------------------------
# _matches_prisma_column_info
# ---------------------------------------------------------------------------


class TestMatchesPrismaColumnInfo:
    def test_matches_valid_prisma_query(self):
        router = make_router()
        sql = (
            "SELECT INFO.TABLE_NAME, INFO.COLUMN_NAME, FORMAT_TYPE(a.atttypid, a.atttypmod) "
            "FROM information_schema.columns INFO"
        )
        assert router._matches_prisma_column_info(sql, sql.upper()) is True

    def test_does_not_match_without_info_table_name(self):
        router = make_router()
        sql = "SELECT column_name, data_type FROM information_schema.columns"
        assert router._matches_prisma_column_info(sql, sql.upper()) is False


# ---------------------------------------------------------------------------
# _extract_filter_names
# ---------------------------------------------------------------------------


class TestExtractFilterNames:
    def test_list_param(self):
        router = make_router()
        result = router._extract_filter_names(["public", "private"])
        assert result == ["public", "private"]

    def test_json_list_string(self):
        router = make_router()
        result = router._extract_filter_names('["public", "private"]')
        assert result == ["public", "private"]

    def test_json_scalar_string(self):
        router = make_router()
        result = router._extract_filter_names('"public"')
        assert result == ["public"]

    def test_curly_brace_format(self):
        router = make_router()
        result = router._extract_filter_names('{"public","private"}')
        assert "public" in result
        assert "private" in result

    def test_square_bracket_format(self):
        router = make_router()
        result = router._extract_filter_names("['public','private']")
        assert "public" in result
        assert "private" in result

    def test_plain_string(self):
        router = make_router()
        result = router._extract_filter_names("public")
        assert result == ["public"]

    def test_non_string_param(self):
        router = make_router()
        result = router._extract_filter_names(42)
        assert result == ["42"]

    def test_empty_curly_brace(self):
        # "{}" is valid JSON (empty dict) so json.loads succeeds; it's not a list,
        # so the result is [str({})] = ["{}"]
        router = make_router()
        result = router._extract_filter_names("{}")
        assert result == ["{}"]

    def test_empty_square_bracket(self):
        # "[]" is valid JSON (empty list) so json.loads succeeds and returns []
        router = make_router()
        result = router._extract_filter_names("[]")
        assert result == []


# ---------------------------------------------------------------------------
# _build_success_response / _empty_emulator_response
# ---------------------------------------------------------------------------


class TestBuildSuccessResponse:
    def test_row_count(self):
        router = make_router()
        rows = [(1,), (2,), (3,)]
        columns = [{"name": "id"}]
        result = router._build_success_response(rows, columns)
        assert result["success"] is True
        assert result["row_count"] == 3
        assert result["command_tag"] == "SELECT 3"

    def test_empty_rows(self):
        router = make_router()
        result = router._build_success_response([], [{"name": "id"}])
        assert result["row_count"] == 0
        assert result["command_tag"] == "SELECT 0"

    def test_empty_emulator_response(self):
        from iris_pgwire.catalog.pg_index import PgIndexEmulator

        router = make_router()
        emulator = PgIndexEmulator(OIDGenerator())
        result = router._empty_emulator_response(emulator)
        assert result["success"] is True
        assert result["rows"] == []
        assert len(result["columns"]) > 0


# ---------------------------------------------------------------------------
# handle_catalog_query (async)
# ---------------------------------------------------------------------------


class TestHandleCatalogQuery:
    @pytest.mark.asyncio
    async def test_handle_pg_enum(self):
        router = make_router()
        sql = "SELECT oid, enumlabel FROM pg_enum WHERE enumtypid = 1"
        result = await router.handle_catalog_query(sql)
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_handle_pg_type(self):
        router = make_router()
        sql = "SELECT oid, typname FROM pg_type"
        result = await router.handle_catalog_query(sql)
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_handle_pg_extension(self):
        router = make_router()
        sql = "SELECT * FROM pg_extension"
        result = await router.handle_catalog_query(sql)
        assert result is not None
        assert result["success"] is True
        col_names = [c["name"] for c in result["columns"]]
        assert "extname" in col_names

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT oid, nspname FROM pg_namespace",
            "SELECT oid, relname FROM pg_class",
            "SELECT oid, relname FROM pg_class WHERE relkind = 'r'",
            "SELECT n.oid, n.nspname FROM pg_namespace n "
            "JOIN pg_class c ON c.relnamespace = n.oid",
            "SELECT conname, contype FROM pg_constraint",
            # Prisma's own shape: a pg_* *function* name in the select list used
            # to count as a targeted catalog table, so this was not recognised as
            # fully view-backed and the pg_class handler answered it.
            "SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace",
        ],
    )
    async def test_view_backed_tables_are_declined_not_answered(self, sql):
        """Feature 044 moved pg_namespace, pg_class and pg_constraint to IRIS views.

        These used to be answered by row emulators here. They are now declined
        so the query reaches IRIS, which can evaluate projections, aliases and
        joins the emulators could only approximate. Answering them again would
        make the views dead code.
        """
        router = make_router()
        assert await router.handle_catalog_query(sql, executor=None) is None

    @pytest.mark.asyncio
    async def test_pg_attribute_is_declined(self):
        """Served by an IRIS view since T015b; the emulator no longer runs."""
        router = make_router()
        sql = "SELECT attname, atttypid FROM pg_attribute WHERE attrelid = 1"
        assert await router.handle_catalog_query(sql) is None

    @pytest.mark.asyncio
    async def test_handle_pg_constraint_is_declined(self):
        """pg_constraint is served by an IRIS view since T015.

        The emulator these two tests exercised no longer runs. What must hold is
        that the router declines, so the query reaches the view — the handler
        answering was not merely redundant: on Prisma's constraints query, which
        also names pg_class, it replied with pg_class's own 32 columns and the
        client failed on `relfrozenxid` typed `xid`.
        """
        router = make_router()
        sql = "SELECT conname, contype FROM pg_constraint WHERE conrelid = 1"
        assert await router.handle_catalog_query(sql, executor=None) is None

    @pytest.mark.asyncio
    async def test_handle_pg_constraint_check_constraint_query_is_declined(self):
        router = make_router()
        sql = (
            "SELECT conname FROM pg_constraint "
            "WHERE contype NOT IN ('P','U','F') AND CONTYPE = 'c'"
        )
        assert await router.handle_catalog_query(sql, executor=None) is None

    @pytest.mark.asyncio
    async def test_handle_pg_index(self):
        router = make_router()
        sql = "SELECT * FROM pg_index WHERE indrelid = 1"
        result = await router.handle_catalog_query(sql)
        assert result is not None
        assert result["success"] is True
        assert result["rows"] == []

    @pytest.mark.asyncio
    async def test_pg_attrdef_is_declined(self):
        """Served by an IRIS view since T015b; the emulator no longer runs."""
        router = make_router()
        sql = "SELECT * FROM pg_attrdef WHERE adrelid = 1"
        assert await router.handle_catalog_query(sql) is None

    @pytest.mark.asyncio
    async def test_fallback_empty_response_for_unrecognized_pg_table(self):
        router = make_router()
        # pg_roles is in CATALOG_TABLES but has no dedicated handler
        sql = "SELECT * FROM pg_roles"
        result = await router.handle_catalog_query(sql)
        assert result is not None
        assert result["success"] is True
        assert result["rows"] == []

    @pytest.mark.asyncio
    async def test_returns_none_for_non_catalog_query(self):
        router = make_router()
        result = await router.handle_catalog_query("SELECT * FROM users")
        assert result is None


# ---------------------------------------------------------------------------
# _handle_pg_type with name filter and namespace filter
# ---------------------------------------------------------------------------


class TestHandlePgTypeFiltering:
    @pytest.mark.asyncio
    async def test_pg_type_with_typname_filter(self):
        router = make_router()
        sql = "SELECT oid, typname FROM pg_type WHERE typname = 'int4'"
        result = await router.handle_catalog_query(sql)
        assert result is not None
        # rows should only contain int4 if it exists in the emulator
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_pg_type_with_namespace_filter_pg_catalog(self):
        router = make_router()
        sql = "SELECT typname FROM pg_type WHERE typnamespace = $1"
        result = await router.handle_catalog_query(sql, params=[["pg_catalog"]])
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_pg_type_with_non_pg_catalog_namespace(self):
        router = make_router()
        sql = "SELECT typname FROM pg_type WHERE typnamespace = $1"
        result = await router.handle_catalog_query(sql, params=[["public"]])
        assert result is not None
        assert result["success"] is True
        assert result["rows"] == []


# ---------------------------------------------------------------------------
# _build_pg_constraint_rows (with executor)
# ---------------------------------------------------------------------------


class TestBuildPgConstraintRows:
    """pg_constraint is served by an IRIS view since T015 (spec FR-016…FR-021).

    Same shape as TestBuildPgClassResponse below: the row builder no longer
    runs, so what is worth asserting is that the table is declined whatever
    executor the router is handed — including one that would raise, since a
    fallback answering with an empty result would tell a client the schema has
    no constraints at all.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT conname, contype FROM pg_constraint WHERE conrelid = 1",
            "SELECT conname FROM pg_constraint WHERE conrelid = 1",
            "SELECT conname, conkey, confkey FROM pg_constraint WHERE contype = 'f'",
        ],
    )
    async def test_pg_constraint_is_declined(self, sql):
        router = make_router()
        executor = make_executor(
            constraints_rows=[
                ("public", "users", "users_pkey", "PRIMARY KEY"),
                ("public", "users", "users_email_key", "UNIQUE"),
            ],
            columns_rows=[("id",)],
        )
        assert await router.handle_catalog_query(sql, executor=executor) is None

    @pytest.mark.asyncio
    async def test_declining_happens_before_the_executor_is_touched(self):
        async def bad_execute(sql, session_id=None):
            raise AssertionError("the router must not query for a view-backed table")

        executor = MagicMock()
        executor.execute_query = bad_execute

        router = make_router()
        assert await router.handle_catalog_query(
            "SELECT conname FROM pg_constraint WHERE conrelid = 1", executor=executor
        ) is None


# ---------------------------------------------------------------------------
# _build_pg_class_response (with executor)
# ---------------------------------------------------------------------------


class TestBuildPgClassResponse:
    """pg_class is served by an IRIS view since feature 044.

    The row emulator that these tests exercised no longer runs. What has to
    hold now is that the router declines the table under every shape, whatever
    executor it is handed — including one that would raise, since a fallback
    that answered with an empty result would look to a client like a database
    with no tables in it.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("sql", "params"),
        [
            ("SELECT oid, relname, relkind FROM pg_class", None),
            ("SELECT oid, relname FROM pg_class", None),
            ("SELECT oid, relname FROM pg_class", [["public"]]),
        ],
    )
    async def test_pg_class_is_declined(self, sql, params):
        router = make_router()
        executor = make_executor(tables_rows=[("users", "BASE TABLE", IRIS_SCHEMA)])
        assert await router.handle_catalog_query(sql, params=params, executor=executor) is None

    @pytest.mark.asyncio
    async def test_declining_happens_before_the_executor_is_touched(self):
        async def bad_execute(sql, session_id=None):
            raise AssertionError("the router must not query for a view-backed table")

        executor = MagicMock()
        executor.execute_query = bad_execute

        router = make_router()
        assert await router.handle_catalog_query(
            "SELECT oid, relname FROM pg_class", executor=executor
        ) is None


# ---------------------------------------------------------------------------
# _build_prisma_column_info_response (with executor)
# ---------------------------------------------------------------------------


class TestBuildPrismaColumnInfoResponse:
    def _prisma_sql(self):
        return (
            "SELECT INFO.TABLE_NAME, INFO.COLUMN_NAME, FORMAT_TYPE(a.atttypid, a.atttypmod) "
            "FROM information_schema.columns INFO "
            "JOIN pg_attribute a ON a.attname = INFO.COLUMN_NAME"
        )

    @pytest.mark.asyncio
    async def test_prisma_column_info_success(self):
        router = make_router()
        executor = make_executor(
            columns_rows=[
                ("public", "users", "id", "INTEGER", 10, 0, 0, "NO", "AUTOINCREMENT", 1),
                ("public", "users", "name", "VARCHAR", 0, 0, 255, "YES", None, 2),
                ("public", "posts", "score", "NUMERIC", 10, 2, 0, "NO", None, 1),
                ("public", "posts", "note", "TEXT", 0, 0, 0, "YES", "'default'", 2),
            ]
        )
        result = await router.handle_catalog_query(self._prisma_sql(), executor=executor)
        assert result is not None
        assert result["success"] is True
        assert len(result["rows"]) == 4
        # First row should be identity
        id_row = result["rows"][0]
        assert "YES" in id_row  # is_identity should be YES for AUTOINCREMENT

    @pytest.mark.asyncio
    async def test_prisma_column_info_no_executor_returns_empty(self):
        router = make_router()
        result = await router.handle_catalog_query(self._prisma_sql(), executor=None)
        assert result is not None
        assert result["success"] is True
        assert result["rows"] == []

    @pytest.mark.asyncio
    async def test_prisma_column_info_executor_failure_falls_back(self):
        router = make_router()
        executor = make_executor(success=False)
        result = await router.handle_catalog_query(self._prisma_sql(), executor=executor)
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_prisma_column_info_executor_exception_falls_back(self):
        router = make_router()

        async def bad_execute(sql, session_id=None):
            raise RuntimeError("fail")

        executor = MagicMock()
        executor.execute_query = bad_execute

        result = await router.handle_catalog_query(self._prisma_sql(), executor=executor)
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_prisma_column_info_varchar_with_length(self):
        router = make_router()
        executor = make_executor(
            columns_rows=[
                ("public", "users", "name", "VARCHAR", 0, 0, 100, "YES", None, 1),
            ]
        )
        result = await router.handle_catalog_query(self._prisma_sql(), executor=executor)
        assert result["success"] is True
        # Check that formatted type includes length
        row = result["rows"][0]
        # formatted_type is index 4 in the row tuple
        assert "100" in str(row)

    @pytest.mark.asyncio
    async def test_prisma_column_info_numeric_with_precision(self):
        router = make_router()
        executor = make_executor(
            columns_rows=[
                ("public", "accounts", "balance", "NUMERIC", 10, 2, 0, "NO", None, 1),
            ]
        )
        result = await router.handle_catalog_query(self._prisma_sql(), executor=executor)
        assert result["success"] is True
        row = result["rows"][0]
        assert "10" in str(row)

    @pytest.mark.asyncio
    async def test_prisma_with_rowversion_default_filtered(self):
        router = make_router()
        executor = make_executor(
            columns_rows=[
                ("public", "items", "ts", "INTEGER", 0, 0, 0, "NO", "ROWVERSION", 1),
            ]
        )
        result = await router.handle_catalog_query(self._prisma_sql(), executor=executor)
        assert result["success"] is True
        row = result["rows"][0]
        # column_default should be None (ROWVERSION filtered out)
        assert row[11] is None

    @pytest.mark.asyncio
    async def test_prisma_with_real_default_preserved(self):
        router = make_router()
        executor = make_executor(
            columns_rows=[
                ("public", "items", "status", "VARCHAR", 0, 0, 50, "NO", "active", 1),
            ]
        )
        result = await router.handle_catalog_query(self._prisma_sql(), executor=executor)
        assert result["success"] is True
        row = result["rows"][0]
        assert row[11] == "active"


# ---------------------------------------------------------------------------
# _namespace_filters
# ---------------------------------------------------------------------------


class TestNamespaceFilters:
    def test_default_public(self):
        router = make_router()
        result = router._namespace_filters(None)
        assert result == ["public"]

    def test_custom_params(self):
        router = make_router()
        result = router._namespace_filters([["myschema"]])
        assert result == ["myschema"]


# ---------------------------------------------------------------------------
# handle_catalog_query: information_schema.columns non-prisma path
# ---------------------------------------------------------------------------


class TestInformationSchemaFallback:
    @pytest.mark.asyncio
    async def test_plain_information_schema_columns_falls_to_fallback(self):
        """A plain information_schema.columns query without Prisma markers
        won't match the Prisma handler but will still be intercepted by fallback."""
        router = make_router()
        sql = "SELECT table_name FROM information_schema.tables"
        result = await router.handle_catalog_query(sql)
        # can_handle is True → fallback empty response
        assert result is not None
        assert result["success"] is True
