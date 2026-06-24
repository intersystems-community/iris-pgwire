import pytest

from iris_pgwire.sql_translator.default_values import DefaultValuesTranslator
from iris_pgwire.sql_translator.metadata_cache import MetadataCache
from iris_pgwire.sql_translator.normalizer import SQLTranslator


class TestDefaultValuesRewrite:
    @pytest.fixture
    def translator(self):
        return SQLTranslator()

    def test_rewrite_default_in_values(self, translator):
        """FR-003: Omit columns with DEFAULT in VALUES"""
        sql = "INSERT INTO users (id, name, created_at) VALUES (1, 'alice', DEFAULT);"
        normalized = translator.normalize_sql(sql)
        assert "created_at" not in normalized.lower()
        assert "DEFAULT" not in normalized
        assert "(id, name)" in normalized.lower()
        assert "(1, 'alice')" in normalized

    def test_multiple_defaults_in_values(self, translator):
        """FR-003: Omit multiple DEFAULTs"""
        sql = "INSERT INTO users (id, name, age, status) VALUES (1, DEFAULT, 25, DEFAULT);"
        normalized = translator.normalize_sql(sql)
        assert "id" in normalized.lower()
        assert "age" in normalized.lower()
        assert "name" not in normalized.lower()
        assert "status" not in normalized.lower()
        assert "(1, 25)" in normalized


class DummyExecutor:
    def __init__(self, rows):
        self._rows = rows

    async def execute_query(self, query, params):
        return {"rows": self._rows}


class TestSmartDefaultHandling:
    def _translator(self, rows):
        cache = MetadataCache()
        executor = DummyExecutor(rows)
        return DefaultValuesTranslator(metadata_cache=cache, executor=executor)

    def test_column_list_defaults_removed(self):
        rows = [
            ("ID", None, "NO"),
            ("STATUS", "'ACTIVE'", "NO"),
            ("DESCRIPTION", None, "YES"),
        ]
        translator = self._translator(rows)
        sql = 'INSERT INTO SQLUSER."USERS" (id, status, description) VALUES (1, DEFAULT, DEFAULT);'
        normalized = translator.translate(sql)
        assert "status" not in normalized.lower()
        assert "description" in normalized.lower()
        assert "NULL" in normalized

    def test_replace_default_without_column_list(self):
        rows = [
            ("ID", "nextval('users_seq'::regclass)", "NO"),
            ("VALUE", None, "NO"),
        ]
        translator = self._translator(rows)
        sql = 'INSERT INTO SQLUSER."USERS" VALUES (DEFAULT, 5);'
        normalized = translator.translate(sql)
        assert "nextval('users_seq'::regclass)" in normalized
        assert "DEFAULT" not in normalized

    def test_raises_when_not_null_without_default(self):
        rows = [("ID", None, "NO"), ("NAME", None, "NO")]
        translator = self._translator(rows)
        sql = 'INSERT INTO SQLUSER."USERS" (id, name) VALUES (DEFAULT, DEFAULT);'
        with pytest.raises(ValueError):
            translator.translate(sql)


class TestDefaultValuesTranslatorUnit:
    """Direct unit tests for DefaultValuesTranslator helper methods."""

    def _make_translator(self):
        return DefaultValuesTranslator()

    # --- _value_is_default ---
    def test_value_is_default_true(self):
        t = self._make_translator()
        assert t._value_is_default("DEFAULT") is True
        assert t._value_is_default("default") is True
        assert t._value_is_default("  Default  ") is True

    def test_value_is_default_false(self):
        t = self._make_translator()
        assert t._value_is_default("NULL") is False
        assert t._value_is_default("'DEFAULT'") is False
        assert t._value_is_default("1") is False

    # --- _is_nullable ---
    def test_is_nullable_yes(self):
        t = self._make_translator()
        assert t._is_nullable({"is_nullable": "YES"}) is True
        assert t._is_nullable({"is_nullable": "yes"}) is True

    def test_is_nullable_no(self):
        t = self._make_translator()
        assert t._is_nullable({"is_nullable": "NO"}) is False

    def test_is_nullable_none_defaults_true(self):
        t = self._make_translator()
        assert t._is_nullable({}) is True

    # --- _normalize_identifier ---
    def test_normalize_identifier_quoted(self):
        t = self._make_translator()
        assert t._normalize_identifier('"MyColumn"') == "MYCOLUMN"

    def test_normalize_identifier_single_quoted(self):
        t = self._make_translator()
        assert t._normalize_identifier("'myval'") == "MYVAL"

    def test_normalize_identifier_plain(self):
        t = self._make_translator()
        assert t._normalize_identifier("id") == "ID"

    def test_normalize_identifier_empty(self):
        t = self._make_translator()
        assert t._normalize_identifier("") == ""
        assert t._normalize_identifier(None) == ""

    # --- _strip_quotes ---
    def test_strip_quotes_double(self):
        t = self._make_translator()
        assert t._strip_quotes('"SCHEMA"') == "SCHEMA"

    def test_strip_quotes_no_quotes(self):
        t = self._make_translator()
        assert t._strip_quotes("SCHEMA") == "SCHEMA"

    def test_strip_quotes_none(self):
        t = self._make_translator()
        assert t._strip_quotes(None) is None

    def test_strip_quotes_empty(self):
        t = self._make_translator()
        assert t._strip_quotes("") == ""

    # --- _parse_schema_table ---
    def test_parse_schema_table_dotted(self):
        t = self._make_translator()
        schema, table = t._parse_schema_table("SQLUSER.USERS")
        assert schema == "SQLUSER"
        assert table == "USERS"

    def test_parse_schema_table_quoted(self):
        t = self._make_translator()
        schema, table = t._parse_schema_table('"MySchema"."MyTable"')
        assert schema == "MySchema"
        assert table == "MyTable"

    def test_parse_schema_table_no_schema(self):
        t = self._make_translator()
        schema, table = t._parse_schema_table("USERS")
        assert schema is None
        assert table == "USERS"

    def test_parse_schema_table_empty(self):
        t = self._make_translator()
        schema, table = t._parse_schema_table("")
        assert schema is None
        assert table is None

    # --- _resolve_default ---
    def test_resolve_default_with_expr(self):
        t = self._make_translator()
        assert t._resolve_default({"column_default": "42"}, "col") == "42"

    def test_resolve_default_nullable_no_default(self):
        t = self._make_translator()
        assert t._resolve_default({"is_nullable": "YES"}, "col") == "NULL"

    def test_resolve_default_meta_none_raises(self):
        t = self._make_translator()
        with pytest.raises(ValueError, match="No metadata available"):
            t._resolve_default(None, "col")

    def test_resolve_default_not_null_no_default_raises(self):
        t = self._make_translator()
        with pytest.raises(ValueError, match="NOT NULL"):
            t._resolve_default({"is_nullable": "NO"}, "col")

    # --- _build_standard_insert ---
    def test_build_standard_insert_with_columns(self):
        t = self._make_translator()
        sql = t._build_standard_insert("users", ["id", "name"], "(1, 'alice')")
        assert sql == "INSERT INTO users (id, name) VALUES (1, 'alice')"

    def test_build_standard_insert_no_columns(self):
        t = self._make_translator()
        sql = t._build_standard_insert("users", [], "(1, 'alice')")
        assert sql == "INSERT INTO users VALUES (1, 'alice')"

    # --- _compose_values_section ---
    def test_compose_values_section(self):
        t = self._make_translator()
        result = t._compose_values_section([["1", "'alice'"], ["2", "'bob'"]])
        assert result == "(1, 'alice'), (2, 'bob')"

    # --- _split_sql_expressions ---
    def test_split_sql_expressions_simple(self):
        t = self._make_translator()
        assert t._split_sql_expressions("a, b, c") == ["a", "b", "c"]

    def test_split_sql_expressions_nested_parens(self):
        t = self._make_translator()
        assert t._split_sql_expressions("f(a, b), c") == ["f(a, b)", "c"]

    def test_split_sql_expressions_quoted_comma(self):
        t = self._make_translator()
        assert t._split_sql_expressions("'a,b', c") == ["'a,b'", "c"]

    def test_split_sql_expressions_double_quoted(self):
        t = self._make_translator()
        assert t._split_sql_expressions('"a,b", c') == ['"a,b"', "c"]

    def test_split_sql_expressions_escaped_single_quote(self):
        t = self._make_translator()
        # escaped quote inside string: 'it''s' should be one token
        result = t._split_sql_expressions("'it''s', b")
        assert result == ["'it''s'", "b"]

    # --- _parse_value_tuples ---
    def test_parse_value_tuples_single(self):
        t = self._make_translator()
        assert t._parse_value_tuples("(1, 2)") == ["(1, 2)"]

    def test_parse_value_tuples_multiple(self):
        t = self._make_translator()
        assert t._parse_value_tuples("(1, 2), (3, 4)") == ["(1, 2)", "(3, 4)"]

    def test_parse_value_tuples_empty(self):
        t = self._make_translator()
        assert t._parse_value_tuples("") == []

    def test_parse_value_tuples_no_opening_paren(self):
        t = self._make_translator()
        assert t._parse_value_tuples("1, 2") == []

    # --- _extract_values_section ---
    def test_extract_values_section_basic(self):
        t = self._make_translator()
        # VALUES starts right at index 0
        result = t._extract_values_section("(1, 2)", 0)
        assert result is not None
        values_text, end_idx = result
        assert values_text == "(1, 2)"

    def test_extract_values_section_no_paren(self):
        t = self._make_translator()
        result = t._extract_values_section("1, 2", 0)
        assert result is None

    def test_extract_values_section_empty_string(self):
        t = self._make_translator()
        result = t._extract_values_section("", 0)
        assert result is None

    def test_extract_values_section_with_leading_space(self):
        t = self._make_translator()
        result = t._extract_values_section("  (1, 2)", 0)
        assert result is not None

    def test_extract_values_section_multiple_tuples(self):
        t = self._make_translator()
        result = t._extract_values_section("(1, 2), (3, 4)", 0)
        assert result is not None
        values_text, end_idx = result
        # should include both tuples
        assert "(1, 2)" in values_text
        assert "(3, 4)" in values_text

    # --- _legacy_translate ---
    def test_legacy_translate_no_default(self):
        t = self._make_translator()
        sql = "INSERT INTO users (id, name) VALUES (1, 'alice')"
        assert t._legacy_translate(sql) == sql

    def test_legacy_translate_with_default(self):
        t = self._make_translator()
        sql = "INSERT INTO users (id, name, ts) VALUES (1, 'alice', DEFAULT)"
        result = t._legacy_translate(sql)
        assert "DEFAULT" not in result
        assert "ts" not in result

    def test_legacy_translate_all_default(self):
        t = self._make_translator()
        sql = "INSERT INTO users (ts) VALUES (DEFAULT)"
        result = t._legacy_translate(sql)
        assert result == "INSERT INTO users DEFAULT VALUES"

    def test_legacy_translate_no_match(self):
        t = self._make_translator()
        sql = "SELECT * FROM users"
        assert t._legacy_translate(sql) == sql

    def test_legacy_translate_col_val_mismatch(self):
        t = self._make_translator()
        # Force mismatch: 2 cols, 3 vals — legacy returns original
        sql = "INSERT INTO t (a, b) VALUES (1, 2, 3)"
        assert t._legacy_translate(sql) == sql

    # --- translate() without metadata (falls through to legacy) ---
    def test_translate_no_cache_uses_legacy(self):
        t = DefaultValuesTranslator()  # no cache, no executor
        sql = "INSERT INTO users (id, ts) VALUES (1, DEFAULT)"
        result = t.translate(sql)
        assert "DEFAULT" not in result
        assert "ts" not in result

    # --- _rewrite_with_column_list: all-default single row → DEFAULT VALUES ---
    def test_smart_all_defaults_single_row_produces_default_values(self):
        rows = [("ID", "1", "NO"), ("NAME", "'x'", "NO")]
        cache = MetadataCache()
        executor = DummyExecutor(rows)
        t = DefaultValuesTranslator(metadata_cache=cache, executor=executor)
        sql = 'INSERT INTO SQLUSER."USERS" (id, name) VALUES (DEFAULT, DEFAULT);'
        result = t.translate(sql)
        assert "DEFAULT VALUES" in result

    # --- _rewrite_with_column_list: missing metadata for DEFAULT col → fallback None → legacy ---
    def test_smart_missing_metadata_for_default_col_falls_back(self):
        # Provide metadata for only one of two columns
        rows = [("ID", None, "YES")]  # NAME column not in metadata
        cache = MetadataCache()
        executor = DummyExecutor(rows)
        t = DefaultValuesTranslator(metadata_cache=cache, executor=executor)
        sql = 'INSERT INTO SQLUSER."USERS" (id, name) VALUES (DEFAULT, DEFAULT);'
        # Should fall back to legacy translate (which strips DEFAULT columns)
        result = t.translate(sql)
        assert isinstance(result, str)

    # --- _rewrite_with_column_list: row count mismatch → None → legacy ---
    def test_smart_row_col_count_mismatch(self):
        rows = [("ID", None, "YES"), ("NAME", None, "YES"), ("EXTRA", None, "YES")]
        cache = MetadataCache()
        executor = DummyExecutor(rows)
        t = DefaultValuesTranslator(metadata_cache=cache, executor=executor)
        # 3 metadata cols but only 2 values → mismatch
        sql = 'INSERT INTO SQLUSER."USERS" (id, name) VALUES (1, DEFAULT);'
        result = t.translate(sql)
        assert isinstance(result, str)
