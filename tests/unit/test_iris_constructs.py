"""
Unit tests for iris_pgwire.iris_constructs module.

Tests all translators and the main coordinator without requiring IRIS.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from iris_pgwire.iris_constructs import (
    IRISConstructTranslator,
    IRISConstructType,
    IRISDataTypeTranslator,
    IRISFunctionTranslator,
    IRISJSONFunctionTranslator,
    IRISSQLExtensionTranslator,
    IRISSystemFunctionTranslator,
    _compile_func_patterns,
    _translate_functions,
    create_custom_iris_functions,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_mock_monitor():
    """Return a mock that satisfies get_monitor().measure_translation()."""
    measurement = {}

    @contextmanager
    def _measure(sql, constructs):
        yield measurement

    monitor = MagicMock()
    monitor.measure_translation.side_effect = _measure
    return monitor


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestCompileFuncPatterns:
    def test_returns_compiled_pattern_for_each_key(self):
        func_map = {"FOO": "bar", "BAZ_FUNC": "qux"}
        patterns = _compile_func_patterns(func_map)
        assert set(patterns.keys()) == {"FOO", "BAZ_FUNC"}
        for p in patterns.values():
            assert isinstance(p, re.Pattern)

    def test_pattern_matches_function_call(self):
        patterns = _compile_func_patterns({"MYFUNC": "other"})
        assert patterns["MYFUNC"].search("SELECT MYFUNC(x) FROM t")

    def test_pattern_does_not_match_mid_word(self):
        patterns = _compile_func_patterns({"FOO": "bar"})
        assert not patterns["FOO"].search("XFOO(x)")

    def test_empty_func_map(self):
        assert _compile_func_patterns({}) == {}


class TestTranslateFunctions:
    def test_simple_replacement(self):
        func_map = {"IRIS_UPPER": "UPPER"}
        patterns = _compile_func_patterns(func_map)
        result = _translate_functions("SELECT IRIS_UPPER(name) FROM t", func_map, patterns)
        assert "UPPER(name)" in result

    def test_no_match_returns_unchanged(self):
        func_map = {"IRIS_UPPER": "UPPER"}
        patterns = _compile_func_patterns(func_map)
        sql = "SELECT name FROM t"
        assert _translate_functions(sql, func_map, patterns) == sql

    def test_multiple_replacements_in_single_sql(self):
        func_map = {"IRIS_UPPER": "UPPER", "IRIS_LOWER": "LOWER"}
        patterns = _compile_func_patterns(func_map)
        result = _translate_functions(
            "SELECT IRIS_UPPER(a), IRIS_LOWER(b) FROM t", func_map, patterns
        )
        assert "UPPER(a)" in result
        assert "LOWER(b)" in result


# ---------------------------------------------------------------------------
# IRISConstructType enum
# ---------------------------------------------------------------------------


class TestIRISConstructType:
    def test_all_enum_members_exist(self):
        values = {e.value for e in IRISConstructType}
        assert "system_function" in values
        assert "sql_extension" in values
        assert "data_type" in values
        assert "iris_function" in values
        assert "json_function" in values


# ---------------------------------------------------------------------------
# IRISSystemFunctionTranslator
# ---------------------------------------------------------------------------


class TestIRISSystemFunctionTranslator:
    @pytest.fixture
    def t(self):
        return IRISSystemFunctionTranslator()

    def test_translate_version_function_with_percent(self, t):
        sql = "SELECT %SYSTEM.Version.%GetNumber() FROM dual"
        result = t.translate(sql)
        assert "%SYSTEM.Version.%GetNumber" not in result

    def test_translate_version_function_no_percent(self, t):
        sql = "SELECT %SYSTEM.Version.GetNumber() FROM dual"
        result = t.translate(sql)
        assert "version()" in result.lower() or "version" in result.lower()

    def test_translate_get_user(self, t):
        sql = "SELECT %SYSTEM.Security.%GetUser() AS u"
        result = t.translate(sql)
        assert "%SYSTEM.Security.%GetUser" not in result

    def test_translate_get_statement(self, t):
        sql = "SELECT %SYSTEM.SQL.%GetStatement() AS q"
        result = t.translate(sql)
        assert "%SYSTEM.SQL.%GetStatement" not in result

    def test_translate_ml_model_exists(self, t):
        sql = "SELECT %SYSTEM.ML.%ModelExists('mymodel')"
        result = t.translate(sql)
        assert "%SYSTEM.ML.%ModelExists" not in result

    def test_translate_parallel(self, t):
        sql = "SELECT %SYSTEM.SQL.%PARALLEL()"
        result = t.translate(sql)
        assert "%SYSTEM.SQL.%PARALLEL" not in result

    def test_no_match_returns_unchanged(self, t):
        sql = "SELECT 1 + 1"
        assert t.translate(sql) == sql

    def test_function_with_params(self, t):
        sql = "SELECT %SYSTEM.ML.%ModelExists('model_name') FROM t"
        result = t.translate(sql)
        # Should include the param in some form
        assert "model_name" in result

    def test_function_without_params_produces_no_extra_parens(self, t):
        sql = "SELECT %SYSTEM.Version.%GetNumber()"
        result = t.translate(sql)
        # Result should not have dangling empty double parens from wrapping
        assert "(())" not in result


# ---------------------------------------------------------------------------
# IRISSQLExtensionTranslator
# ---------------------------------------------------------------------------


class TestIRISSQLExtensionTranslator:
    @pytest.fixture
    def t(self):
        return IRISSQLExtensionTranslator()

    def test_translate_top_clause(self, t):
        sql = "SELECT TOP 10 name FROM employees"
        result = t.translate(sql)
        assert "LIMIT 10" in result
        assert "TOP 10" not in result

    def test_translate_top_clause_larger_number(self, t):
        sql = "SELECT TOP 100 id, name FROM t"
        result = t.translate(sql)
        assert "LIMIT 100" in result

    def test_no_limit_duplicated_when_already_present(self, t):
        # After TOP removal, if somehow LIMIT already exists, it shouldn't duplicate
        sql = "SELECT TOP 5 id FROM t LIMIT 5"
        result = t.translate(sql)
        # LIMIT 5 should appear but not twice
        assert result.count("LIMIT 5") == 1

    def test_translate_top_percent(self, t):
        sql = "SELECT TOP 10 PERCENT id FROM t"
        result = t.translate(sql)
        # Should produce some LIMIT statement (approximate conversion)
        assert "LIMIT" in result

    def test_translate_full_outer_join(self, t):
        sql = "SELECT * FROM a %FULL OUTER JOIN b ON a.id = b.id"
        result = t.translate(sql)
        assert "%FULL" not in result
        assert "FULL OUTER JOIN" in result

    def test_translate_joins_no_match_unchanged(self, t):
        sql = "SELECT * FROM a INNER JOIN b ON a.id = b.id"
        assert t.translate(sql) == sql

    def test_translate_top_clause_only(self, t):
        sql = "SELECT TOP 5 x FROM t"
        result = t.translate_top_clause(sql)
        assert "LIMIT 5" in result

    def test_translate_joins_only(self, t):
        sql = "SELECT * FROM a %FULL OUTER JOIN b ON a.id = b.id"
        result = t.translate_joins(sql)
        assert "%FULL" not in result


# ---------------------------------------------------------------------------
# IRISFunctionTranslator
# ---------------------------------------------------------------------------


class TestIRISFunctionTranslator:
    @pytest.fixture
    def t(self):
        return IRISFunctionTranslator()

    def test_translate_sqlupper(self, t):
        sql = "SELECT %SQLUPPER(name) FROM t"
        result = t.translate(sql)
        assert "UPPER(name)" in result

    def test_translate_sqllower(self, t):
        sql = "SELECT %SQLLOWER(name) FROM t"
        result = t.translate(sql)
        assert "LOWER(name)" in result

    def test_translate_sqlupper_no_percent(self, t):
        sql = "SELECT SQLUPPER(name) FROM t"
        result = t.translate(sql)
        assert "UPPER(name)" in result

    def test_translate_sqllower_no_percent(self, t):
        sql = "SELECT SQLLOWER(name) FROM t"
        result = t.translate(sql)
        assert "LOWER(name)" in result

    def test_translate_horolog(self, t):
        sql = "SELECT %HOROLOG()"
        result = t.translate(sql)
        assert "%HOROLOG" not in result

    def test_translate_external(self, t):
        sql = "SELECT %EXTERNAL(field) FROM t"
        result = t.translate(sql)
        assert "%EXTERNAL" not in result

    def test_translate_internal(self, t):
        sql = "SELECT %INTERNAL(field) FROM t"
        result = t.translate(sql)
        assert "%INTERNAL" not in result

    def test_translate_datediff_microseconds(self, t):
        sql = "SELECT DATEDIFF_MICROSECONDS(a, b) FROM t"
        result = t.translate(sql)
        assert "DATEDIFF_MICROSECONDS" not in result

    def test_translate_exact(self, t):
        sql = "SELECT %EXACT(col) FROM t"
        result = t.translate(sql)
        assert "%EXACT" not in result

    def test_no_match_unchanged(self, t):
        sql = "SELECT UPPER(name) FROM t"
        assert t.translate(sql) == sql


# ---------------------------------------------------------------------------
# IRISDataTypeTranslator
# ---------------------------------------------------------------------------


class TestIRISDataTypeTranslator:
    @pytest.fixture
    def t(self):
        return IRISDataTypeTranslator()

    def test_translate_rowversion_in_create_table(self, t):
        sql = "CREATE TABLE t (id INT, ver ROWVERSION)"
        result = t.translate(sql)
        assert "BIGINT" in result
        assert "ROWVERSION" not in result

    def test_translate_money_in_create_table(self, t):
        sql = "CREATE TABLE t (price MONEY)"
        result = t.translate(sql)
        assert "NUMERIC(19,4)" in result

    def test_translate_posixtime_in_create_table(self, t):
        sql = "CREATE TABLE t (ts POSIXTIME)"
        result = t.translate(sql)
        assert "TIMESTAMP" in result

    def test_translate_percent_list_in_create_table(self, t):
        sql = "CREATE TABLE t (data %List)"
        result = t.translate(sql)
        assert "BYTEA" in result

    def test_translate_percent_stream_in_create_table(self, t):
        sql = "CREATE TABLE t (data %Stream)"
        result = t.translate(sql)
        assert "BYTEA" in result

    def test_translate_percent_timestamp_in_create_table(self, t):
        sql = "CREATE TABLE t (ts %TimeStamp)"
        result = t.translate(sql)
        assert "TIMESTAMP" in result

    def test_translate_percent_date_in_create_table(self, t):
        sql = "CREATE TABLE t (d %Date)"
        result = t.translate(sql)
        assert "DATE" in result

    def test_translate_percent_time_in_create_table(self, t):
        sql = "CREATE TABLE t (tm %Time)"
        result = t.translate(sql)
        assert "TIME" in result

    def test_translate_embedding_in_create_table(self, t):
        sql = "CREATE TABLE t (v EMBEDDING(128))"
        result = t.translate(sql)
        assert "VECTOR" in result

    def test_skips_non_ddl(self, t):
        sql = "SELECT ROWVERSION FROM t"
        # No CREATE/ALTER TABLE — should not translate
        assert t.translate(sql) == sql

    def test_alter_table_gets_translated(self, t):
        sql = "ALTER TABLE t ADD COLUMN ver ROWVERSION"
        result = t.translate(sql)
        assert "BIGINT" in result

    def test_type_map_keys_present(self, t):
        assert "ROWVERSION" in IRISDataTypeTranslator.TYPE_MAP
        assert "MONEY" in IRISDataTypeTranslator.TYPE_MAP
        assert "POSIXTIME" in IRISDataTypeTranslator.TYPE_MAP


# ---------------------------------------------------------------------------
# IRISJSONFunctionTranslator
# ---------------------------------------------------------------------------


class TestIRISJSONFunctionTranslator:
    @pytest.fixture
    def t(self):
        return IRISJSONFunctionTranslator()

    def test_translate_json_object(self, t):
        sql = "SELECT JSON_OBJECT('k', v)"
        result = t.translate(sql)
        assert "json_build_object" in result

    def test_translate_json_array(self, t):
        sql = "SELECT JSON_ARRAY(1, 2, 3)"
        result = t.translate(sql)
        assert "json_build_array" in result

    def test_translate_json_value(self, t):
        sql = "SELECT JSON_VALUE(doc, '$.name')"
        result = t.translate(sql)
        assert "jsonb_extract_path_text" in result

    def test_translate_json_arrayagg(self, t):
        sql = "SELECT JSON_ARRAYAGG(x) FROM t"
        result = t.translate(sql)
        assert "json_agg" in result

    def test_translate_json_length(self, t):
        sql = "SELECT JSON_LENGTH(data)"
        result = t.translate(sql)
        # JSON_LENGTH gets special CASE WHEN treatment
        assert "jsonb_typeof" in result or "jsonb_array_length" in result

    def test_translate_json_valid(self, t):
        sql = "SELECT JSON_VALID(doc)"
        result = t.translate(sql)
        assert "iris_json_valid" in result

    def test_translate_json_table_with_dollar_path(self, t):
        sql = "SELECT * FROM JSON_TABLE(data, '$' COLUMNS (id INT PATH '$.id', name TEXT PATH '$.name'))"
        result = t.translate(sql)
        assert "jsonb_to_recordset" in result

    def test_translate_json_table_with_nested_path(self, t):
        sql = "SELECT * FROM JSON_TABLE(data, '$.items' COLUMNS (id INT PATH '$.id'))"
        result = t.translate(sql)
        assert "jsonb_path_query_array" in result

    def test_parse_json_table_columns_with_path(self):
        entries = IRISJSONFunctionTranslator._parse_json_table_columns(
            "id INT PATH '$.id', name TEXT PATH '$.name'"
        )
        assert len(entries) == 2
        assert "id INT" in entries

    def test_parse_json_table_columns_without_path(self):
        # Entries without PATH keyword should not appear
        entries = IRISJSONFunctionTranslator._parse_json_table_columns("id INT, name TEXT")
        assert entries == []

    def test_translate_docdb_filter_equality(self, t):
        sql = "SELECT * FROM t WHERE doc -> 'status' = 'active'"
        result = t.translate_docdb_filters(sql)
        assert "#>>" in result or "status" in result

    def test_translate_docdb_filter_like(self, t):
        sql = "SELECT * FROM t WHERE doc -> 'name' LIKE '%foo%'"
        result = t.translate_docdb_filters(sql)
        assert "LIKE" in result

    def test_translate_docdb_filter_contains(self, t):
        sql = "SELECT * FROM t WHERE doc -> 'tags' CONTAINS 'foo'"
        result = t.translate_docdb_filters(sql)
        assert "@>" in result

    def test_translate_array_filter(self, t):
        sql = "SELECT * FROM t WHERE items[*].price > 100"
        result = t.translate_docdb_filters(sql)
        assert "jsonb_path_exists" in result

    def test_translate_docdb_filter_not_equal(self, t):
        sql = "SELECT * FROM t WHERE doc -> 'status' != 'inactive'"
        result = t.translate_docdb_filters(sql)
        assert "!=" in result


# ---------------------------------------------------------------------------
# create_custom_iris_functions
# ---------------------------------------------------------------------------


class TestCreateCustomIrisFunctions:
    def test_returns_list_of_strings(self):
        result = create_custom_iris_functions()
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(s, str) for s in result)

    def test_contains_iris_sql_parallel(self):
        sqls = " ".join(create_custom_iris_functions())
        assert "iris_sql_parallel_info" in sqls

    def test_contains_iris_ml_model_exists(self):
        sqls = " ".join(create_custom_iris_functions())
        assert "iris_ml_model_exists" in sqls

    def test_contains_iris_datediff_microseconds(self):
        sqls = " ".join(create_custom_iris_functions())
        assert "iris_datediff_microseconds" in sqls

    def test_contains_iris_pattern_match(self):
        sqls = " ".join(create_custom_iris_functions())
        assert "iris_pattern_match" in sqls

    def test_all_are_create_or_replace(self):
        for stmt in create_custom_iris_functions():
            assert "CREATE OR REPLACE FUNCTION" in stmt


# ---------------------------------------------------------------------------
# IRISConstructTranslator (main coordinator)
# ---------------------------------------------------------------------------


class TestIRISConstructTranslator:
    """Tests the main coordinator with mocked monitor."""

    @pytest.fixture(autouse=True)
    def patch_monitor(self):
        """Patch get_monitor so tests don't need the real monitor."""
        mock_monitor = _make_mock_monitor()
        with patch("iris_pgwire.iris_constructs.get_monitor", return_value=mock_monitor):
            yield mock_monitor

    @pytest.fixture
    def t(self):
        return IRISConstructTranslator()

    def test_init_creates_sub_translators(self, t):
        assert isinstance(t.system_function_translator, IRISSystemFunctionTranslator)
        assert isinstance(t.sql_extension_translator, IRISSQLExtensionTranslator)
        assert isinstance(t.function_translator, IRISFunctionTranslator)
        assert isinstance(t.data_type_translator, IRISDataTypeTranslator)
        assert isinstance(t.json_function_translator, IRISJSONFunctionTranslator)

    def test_translate_sql_returns_tuple(self, t):
        sql = "SELECT 1"
        result = t.translate_sql(sql)
        assert isinstance(result, tuple)
        assert len(result) == 2
        translated, stats = result
        assert isinstance(translated, str)
        assert isinstance(stats, dict)

    def test_translate_sql_top_clause(self, t):
        sql = "SELECT TOP 5 id FROM t"
        translated, stats = t.translate_sql(sql)
        assert "LIMIT 5" in translated
        assert stats["sql_extensions"] >= 1

    def test_translate_sql_sqlupper(self, t):
        sql = "SELECT %SQLUPPER(name) FROM t"
        translated, stats = t.translate_sql(sql)
        assert "UPPER(name)" in translated
        assert stats["iris_functions"] >= 1

    def test_translate_sql_data_type_in_ddl(self, t):
        sql = "CREATE TABLE t (ver ROWVERSION)"
        translated, stats = t.translate_sql(sql)
        assert "BIGINT" in translated
        assert stats["data_types"] >= 1

    def test_translate_sql_json_function(self, t):
        sql = "SELECT JSON_OBJECT('k', v)"
        translated, stats = t.translate_sql(sql)
        assert "json_build_object" in translated
        assert stats["json_functions"] >= 1

    def test_translate_sql_no_iris_constructs(self, t):
        sql = "SELECT id, name FROM users WHERE id = 1"
        translated, stats = t.translate_sql(sql)
        assert translated == sql
        assert sum(stats.values()) == 0

    def test_needs_iris_translation_true_for_top(self, t):
        assert t.needs_iris_translation("SELECT TOP 10 x FROM t") is True

    def test_needs_iris_translation_true_for_percent_system(self, t):
        assert t.needs_iris_translation("SELECT %SYSTEM.Version.GetNumber()") is True

    def test_needs_iris_translation_true_for_sqlupper(self, t):
        assert t.needs_iris_translation("SELECT %SQLUPPER(name) FROM t") is True

    def test_needs_iris_translation_true_for_horolog(self, t):
        assert t.needs_iris_translation("SELECT %HOROLOG()") is True

    def test_needs_iris_translation_false_for_plain_sql(self, t):
        assert t.needs_iris_translation("SELECT 1") is False

    def test_needs_iris_translation_true_for_json_constructs(self, t):
        assert t.needs_iris_translation("SELECT JSON_OBJECT('k', v)") is True

    def test_needs_iris_translation_true_for_rowversion(self, t):
        assert t.needs_iris_translation("CREATE TABLE t (v ROWVERSION)") is True

    def test_needs_iris_translation_true_for_pattern(self, t):
        assert t.needs_iris_translation("SELECT %PATTERN.MATCH(x, y)") is True

    def test_empty_stats_structure(self, t):
        stats = t._empty_stats()
        expected_keys = {"data_types", "sql_extensions", "system_functions", "iris_functions", "json_functions"}
        assert set(stats.keys()) == expected_keys
        assert all(v == 0 for v in stats.values())

    def test_get_translation_summary_after_translation(self, t):
        t.translate_sql("SELECT TOP 5 id FROM t")
        summary = t.get_translation_summary()
        assert "total_translations" in summary
        assert "by_type" in summary
        assert "most_common" in summary

    def test_get_translation_summary_with_no_translations(self, t):
        summary = t.get_translation_summary()
        assert summary["total_translations"] == 0
        assert summary["most_common"] is None

    def test_get_translation_summary_most_common_identifies_dominant(self, t):
        t.translate_sql("SELECT TOP 5 id FROM t")
        summary = t.get_translation_summary()
        # sql_extensions was changed, most_common should reflect that
        if summary["most_common"]:
            key, count = summary["most_common"]
            assert count >= 1

    def test_debug_mode_translator(self, patch_monitor):
        """Translator with debug_mode=True exercises tracer code paths."""
        mock_tracer = MagicMock()
        mock_tracer.start_trace.return_value = "trace-001"

        with patch("iris_pgwire.iris_constructs.get_tracer", return_value=mock_tracer):
            t = IRISConstructTranslator(debug_mode=True)
            translated, stats = t.translate_sql("SELECT TOP 5 id FROM t")
            assert "LIMIT 5" in translated
            mock_tracer.start_trace.assert_called_once()
            mock_tracer.finish_trace.assert_called_once()

    def test_translate_sql_system_function(self, t):
        sql = "SELECT %SYSTEM.Version.GetNumber()"
        translated, stats = t.translate_sql(sql)
        assert "%SYSTEM.Version.GetNumber" not in translated
        assert stats["system_functions"] >= 1

    def test_translate_sql_stats_reset_each_call(self, t):
        t.translate_sql("SELECT TOP 10 id FROM t")
        # Second call with no IRIS constructs should reset stats to 0
        _, stats2 = t.translate_sql("SELECT 1")
        assert sum(stats2.values()) == 0

    def test_apply_translation_steps_returns_string(self, t):
        result = t._apply_translation_steps("SELECT 1", None)
        assert isinstance(result, str)
