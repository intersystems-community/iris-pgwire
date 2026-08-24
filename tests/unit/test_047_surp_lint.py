"""Unit tests for surp lint + ERD support (feature 047).

Covers:
- rewrite_array_literals (ARRAY[...] → '{...}')
- rewrite_any_col_to_instr (expr = ANY(col) → INSTR(...))
- format() dispatch (rewrite_pg_function_calls extension)
- jsonb_build_object() dispatch
- catalog view DDL presence (pg_index, pg_policy, pg_rewrite)
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# T005 — rewrite_array_literals
# ---------------------------------------------------------------------------

class TestRewriteArrayLiterals:
    def _fn(self, sql: str) -> str:
        from iris_pgwire.sql_translator.array_literal import rewrite_array_literals
        return rewrite_array_literals(sql)

    def test_single_element(self):
        assert self._fn("SELECT ARRAY['PERFORMANCE']") == "SELECT '{PERFORMANCE}'"

    def test_multi_element(self):
        assert self._fn("SELECT ARRAY['a', 'b', 'c']") == "SELECT '{a,b,c}'"

    def test_empty_array(self):
        assert self._fn("SELECT ARRAY[]") == "SELECT '{}'"

    def test_case_insensitive(self):
        assert self._fn("SELECT array['x']") == "SELECT '{x}'"
        assert self._fn("SELECT Array['y']") == "SELECT '{y}'"

    def test_whitespace_tolerance(self):
        result = self._fn("SELECT ARRAY[ 'foo' , 'bar' ]")
        assert result == "SELECT '{foo,bar}'"

    def test_no_rewrite_plain_string(self):
        sql = "SELECT 'hello'"
        assert self._fn(sql) == sql

    def test_no_rewrite_array_param(self):
        # = ANY($1) should not be touched by this rewriter
        sql = "SELECT col = ANY($1)"
        assert self._fn(sql) == sql

    def test_full_select_context(self):
        sql = "SELECT id, ARRAY['PERFORMANCE', 'SCHEMA'] AS cats FROM t"
        result = self._fn(sql)
        assert "ARRAY" not in result
        assert "'{PERFORMANCE,SCHEMA}'" in result

    def test_not_touching_subsequent_text(self):
        sql = "SELECT ARRAY['x'] AS col, name FROM t WHERE id = 1"
        result = self._fn(sql)
        assert "name FROM t WHERE id = 1" in result


# ---------------------------------------------------------------------------
# T006 — rewrite_any_col_to_instr
# ---------------------------------------------------------------------------

class TestRewriteAnyColToInstr:
    def _fn(self, sql: str) -> str:
        from iris_pgwire.sql_translator.array_params import rewrite_any_col_to_instr
        return rewrite_any_col_to_instr(sql)

    def test_basic_column_reference(self):
        result = self._fn("WHERE attnum = ANY(con.conkey)")
        assert "INSTR(" in result
        assert "REPLACE" in result
        assert "CAST(attnum AS VARCHAR)" in result
        assert "con.conkey" in result

    def test_qualified_both_sides(self):
        result = self._fn("WHERE a.col = ANY(b.col)")
        assert "INSTR(" in result
        assert "a.col" not in result.split("INSTR")[1].split(")")[0]  # lhs moved into cast
        assert "CAST(a.col AS VARCHAR)" in result

    def test_does_not_match_param_placeholder(self):
        sql = "WHERE col = ANY($1)"
        assert self._fn(sql) == sql

    def test_does_not_match_param_question_mark(self):
        sql = "WHERE col = ANY(?)"
        assert self._fn(sql) == sql

    def test_does_not_match_string_literal(self):
        sql = "WHERE col = ANY('{a,b}')"
        assert self._fn(sql) == sql

    def test_instr_strips_braces(self):
        result = self._fn("WHERE attnum = ANY(conkey)")
        assert "REPLACE(REPLACE(conkey, '{', ''), '}', '')" in result

    def test_result_no_any_keyword(self):
        result = self._fn("WHERE attnum = ANY(con.conkey)")
        # The original ANY(col) pattern should be gone
        assert "ANY(con.conkey)" not in result

    def test_erd_pattern(self):
        # From surp's ERD query: a.attnum = ANY(con.conkey)
        sql = "AND a.attnum = ANY(con.conkey)"
        result = self._fn(sql)
        assert "INSTR(" in result
        assert "CAST(a.attnum AS VARCHAR)" in result


# ---------------------------------------------------------------------------
# T011 — format() dispatch
# ---------------------------------------------------------------------------

class TestFormatDispatch:
    def _fn(self, sql: str) -> str:
        from iris_pgwire.sql_translator.pg_functions import rewrite_pg_function_calls
        return rewrite_pg_function_calls(sql)

    def test_two_arg_dispatch(self):
        result = self._fn("SELECT format('%s', name)")
        assert "PGWire.FORMAT2(" in result
        assert "format(" not in result.lower().replace("PGWire.FORMAT2(", "")

    def test_three_arg_dispatch(self):
        result = self._fn("SELECT format('%I %s', schema, table)")
        assert "PGWire.FORMAT3(" in result

    def test_four_arg_passes_through(self):
        sql = "SELECT format('%s %s %s', a, b, c)"
        result = self._fn(sql)
        # 4-arg (counting pattern + 3 args) passes through unchanged
        assert "FORMAT2" not in result
        assert "FORMAT3" not in result

    def test_already_qualified_not_rewritten(self):
        sql = "SELECT pg_catalog.format('%s', x)"
        result = self._fn(sql)
        assert "FORMAT2" not in result
        assert "FORMAT3" not in result

    def test_does_not_rewrite_other_functions(self):
        sql = "SELECT obj_description(oid, 'pg_class')"
        result = self._fn(sql)
        assert "OBJ_DESCRIPTION(" in result
        assert "FORMAT" not in result


# ---------------------------------------------------------------------------
# T012 — jsonb_build_object() dispatch
# ---------------------------------------------------------------------------

class TestJsonbBuildObjectDispatch:
    def _fn(self, sql: str) -> str:
        from iris_pgwire.sql_translator.pg_functions import rewrite_pg_function_calls
        return rewrite_pg_function_calls(sql)

    def test_four_arg_dispatch(self):
        result = self._fn("SELECT jsonb_build_object('type', 'lint', 'check_id', x)")
        assert "PGWire.JSONB_BUILD_OBJECT4(" in result
        assert "jsonb_build_object(" not in result.lower().replace("pgwire.jsonb_build_object4(", "")

    def test_six_arg_dispatch(self):
        result = self._fn("SELECT jsonb_build_object('a', 1, 'b', 2, 'c', 3)")
        assert "PGWire.JSONB_BUILD_OBJECT6(" in result

    def test_odd_arg_passes_through(self):
        sql = "SELECT jsonb_build_object('a', 1, 'b')"
        result = self._fn(sql)
        assert "JSONB_BUILD_OBJECT4" not in result
        assert "JSONB_BUILD_OBJECT6" not in result

    def test_already_qualified_not_rewritten(self):
        sql = "SELECT pg_catalog.jsonb_build_object('k', 'v')"
        result = self._fn(sql)
        assert "JSONB_BUILD_OBJECT" not in result


# ---------------------------------------------------------------------------
# T020 — pg_index view DDL columns (US2)
# ---------------------------------------------------------------------------

class TestPgIndexViewDDL:
    def _get_view(self):
        from iris_pgwire.catalog.views.definitions import CATALOG_VIEWS
        for v in CATALOG_VIEWS:
            if v.name == "pg_index":
                return v
        return None

    def test_pg_index_view_registered(self):
        view = self._get_view()
        assert view is not None, "pg_index not found in CATALOG_VIEWS"

    def test_pg_index_has_indisprimary(self):
        view = self._get_view()
        assert view is not None
        assert "indisprimary" in view.columns

    def test_pg_index_has_indkey(self):
        view = self._get_view()
        assert view is not None
        assert "indkey" in view.columns

    def test_pg_index_has_indisunique(self):
        view = self._get_view()
        assert view is not None
        assert "indisunique" in view.columns

    def test_rewrite_any_col_for_erd(self):
        # Verify the rewrite handles the ERD join pattern correctly
        from iris_pgwire.sql_translator.array_params import rewrite_any_col_to_instr
        sql = "JOIN pg_index idx ON a.attnum = ANY(idx.indkey)"
        result = rewrite_any_col_to_instr(sql)
        assert "ANY(idx.indkey)" not in result
        assert "INSTR(" in result


# ---------------------------------------------------------------------------
# T024 — pg_policy and pg_rewrite view DDL (US3)
# ---------------------------------------------------------------------------

class TestPgPolicyPgRewriteViewDDL:
    def _get_view(self, name: str):
        from iris_pgwire.catalog.views.definitions import CATALOG_VIEWS
        for v in CATALOG_VIEWS:
            if v.name == name:
                return v
        return None

    def test_pg_policy_registered(self):
        assert self._get_view("pg_policy") is not None, "pg_policy not in CATALOG_VIEWS"

    def test_pg_policy_has_required_columns(self):
        view = self._get_view("pg_policy")
        assert view is not None
        for col in ("oid", "polname", "polrelid", "polcmd", "polpermissive", "polroles", "polqual", "polwithcheck"):
            assert col in view.columns, f"pg_policy missing column: {col}"

    def test_pg_rewrite_registered(self):
        assert self._get_view("pg_rewrite") is not None, "pg_rewrite not in CATALOG_VIEWS"

    def test_pg_rewrite_has_required_columns(self):
        view = self._get_view("pg_rewrite")
        assert view is not None
        for col in ("oid", "rulename", "ev_class", "ev_type", "ev_enabled", "is_instead", "ev_qual", "ev_action"):
            assert col in view.columns, f"pg_rewrite missing column: {col}"
