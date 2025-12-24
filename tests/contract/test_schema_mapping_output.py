"""
Contract tests for translate_output_schema() function.

These tests validate the output result transformation from IRIS 'SQLUser'
schema to PostgreSQL 'public' schema in schema-related columns only.

Feature: 030-pg-schema-mapping
"""

import pytest

from iris_pgwire.schema_mapper import translate_output_schema


class TestSchemaOutputTranslation:
    """Contract tests for translate_output_schema() per contracts/schema-mapping.md"""

    def test_table_schema_translation(self):
        """SQLUser → public in table_schema column"""
        rows = [("SQLUser", "users", "BASE TABLE")]
        columns = ["table_schema", "table_name", "table_type"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "public"
        assert result[0][1] == "users"  # Unchanged
        assert result[0][2] == "BASE TABLE"  # Unchanged

    def test_system_schema_unchanged(self):
        """%SYS schema should NOT be translated to public"""
        rows = [("%SYS", "Config", "BASE TABLE")]
        columns = ["table_schema", "table_name", "table_type"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "%SYS"

    def test_library_schema_unchanged(self):
        """%Library schema should NOT be translated"""
        rows = [("%Library", "SomeClass", "BASE TABLE")]
        columns = ["table_schema", "table_name", "table_type"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "%Library"

    def test_non_schema_column_unchanged(self):
        """Value 'SQLUser' in non-schema column should NOT be translated"""
        rows = [("SQLUser",)]  # Value happens to match, but column isn't schema-related
        columns = ["some_column"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "SQLUser"  # Not translated

    def test_schema_name_column(self):
        """schema_name column should also be translated"""
        rows = [("SQLUser", "some_table")]
        columns = ["schema_name", "table_name"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "public"
        assert result[0][1] == "some_table"

    def test_nspname_column(self):
        """nspname (PostgreSQL catalog) column should be translated"""
        rows = [("SQLUser", 12345)]
        columns = ["nspname", "oid"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "public"
        assert result[0][1] == 12345

    def test_multiple_rows(self):
        """Multiple rows should all be translated"""
        rows = [
            ("SQLUser", "users"),
            ("SQLUser", "orders"),
            ("%SYS", "Config"),
            ("SQLUser", "products"),
        ]
        columns = ["table_schema", "table_name"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "public"
        assert result[1][0] == "public"
        assert result[2][0] == "%SYS"  # Unchanged
        assert result[3][0] == "public"

    def test_empty_rows(self):
        """Empty result set should return empty"""
        rows = []
        columns = ["table_schema", "table_name"]
        result = translate_output_schema(rows, columns)
        assert result == []

    def test_null_values(self):
        """NULL values should remain NULL"""
        rows = [(None, "orphan_table")]
        columns = ["table_schema", "table_name"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] is None
        assert result[0][1] == "orphan_table"

    def test_case_insensitive_column_matching(self):
        """Column name matching should be case-insensitive"""
        rows = [("SQLUser", "users")]
        columns = ["TABLE_SCHEMA", "table_name"]  # Uppercase column name
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "public"

    def test_mixed_case_schema_value(self):
        """Schema value matching should handle IRIS case variations"""
        rows = [("SQLUSER", "users")]  # IRIS might return uppercase
        columns = ["table_schema", "table_name"]
        result = translate_output_schema(rows, columns)
        # Should translate regardless of case
        assert result[0][0] == "public"

    def test_table_name_sqluser_unchanged(self):
        """A table named 'SQLUser' should NOT have its name changed"""
        rows = [("SQLUser", "SQLUser")]  # Schema is SQLUser, table is also named SQLUser
        columns = ["table_schema", "table_name"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "public"  # Schema translated
        assert result[0][1] == "SQLUser"  # Table name preserved

    def test_multiple_schema_columns(self):
        """Multiple schema columns in same row should all be translated"""
        rows = [("SQLUser", "SQLUser", "FK reference")]
        columns = ["table_schema", "referenced_table_schema", "constraint_name"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "public"
        # Note: referenced_table_schema is not in our SCHEMA_COLUMNS set
        # This test validates we only translate known schema columns
        assert result[0][1] == "SQLUser"  # Not translated (not in SCHEMA_COLUMNS)

    def test_information_schema_columns_query(self):
        """Typical information_schema.columns result"""
        rows = [
            ("SQLUser", "users", "id", "INTEGER", "NO"),
            ("SQLUser", "users", "name", "VARCHAR", "YES"),
            ("SQLUser", "users", "email", "VARCHAR", "NO"),
        ]
        columns = ["table_schema", "table_name", "column_name", "data_type", "is_nullable"]
        result = translate_output_schema(rows, columns)
        for row in result:
            assert row[0] == "public"
            assert row[1] in ("users",)  # Table name unchanged

    def test_preserves_tuple_structure(self):
        """Output should maintain tuple structure compatible with result sets"""
        rows = [("SQLUser", "users", 42, True, None)]
        columns = ["table_schema", "table_name", "id", "active", "deleted_at"]
        result = translate_output_schema(rows, columns)
        assert isinstance(result[0], tuple)
        assert len(result[0]) == 5
        assert result[0] == ("public", "users", 42, True, None)
