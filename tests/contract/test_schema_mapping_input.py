"""
Contract tests for translate_input_schema() function.

These tests validate the input SQL translation from PostgreSQL 'public'
schema references to IRIS 'SQLUser' schema.

Feature: 030-pg-schema-mapping
"""

import pytest

from iris_pgwire.schema_mapper import translate_input_schema


class TestSchemaInputTranslation:
    """Contract tests for translate_input_schema() per contracts/schema-mapping.md"""

    def test_where_clause_public(self):
        """WHERE table_schema = 'public' → 'SQLUser'"""
        sql = "SELECT * FROM information_schema.tables WHERE table_schema = 'public'"
        result = translate_input_schema(sql)
        assert "table_schema = 'SQLUser'" in result
        assert "'public'" not in result

    def test_schema_qualified_name(self):
        """FROM public.tablename → SQLUser.tablename"""
        sql = "SELECT * FROM public.users"
        result = translate_input_schema(sql)
        assert "SQLUser.users" in result
        assert "public.users" not in result

    def test_case_insensitive_uppercase(self):
        """Case-insensitive: 'PUBLIC' → 'SQLUser'"""
        sql = "WHERE table_schema = 'PUBLIC'"
        result = translate_input_schema(sql)
        assert "SQLUser" in result
        assert "'PUBLIC'" not in result

    def test_case_insensitive_mixed(self):
        """Case-insensitive: 'Public' → 'SQLUser'"""
        sql = "WHERE table_schema = 'Public'"
        result = translate_input_schema(sql)
        assert "SQLUser" in result
        assert "'Public'" not in result

    def test_sqluser_unchanged(self):
        """Explicit SQLUser references should not be double-mapped"""
        sql = "WHERE table_schema = 'SQLUser'"
        result = translate_input_schema(sql)
        # Should have exactly one SQLUser, not double-mapped
        assert result.count("SQLUser") == 1
        assert "table_schema = 'SQLUser'" in result

    def test_system_schema_unchanged(self):
        """IRIS system schemas (%SYS, etc.) should not be modified"""
        sql = "WHERE table_schema = '%SYS'"
        result = translate_input_schema(sql)
        assert "%SYS" in result
        assert "'%SYS'" in result

    def test_other_system_schema_unchanged(self):
        """IRIS %Library schema should not be modified"""
        sql = "WHERE table_schema = '%Library'"
        result = translate_input_schema(sql)
        assert "%Library" in result

    def test_schema_in_select_list(self):
        """Schema reference in SELECT should be translated"""
        sql = "SELECT * FROM public.orders WHERE public.orders.id = 1"
        result = translate_input_schema(sql)
        assert "SQLUser.orders" in result
        assert "public.orders" not in result

    def test_multiple_public_references(self):
        """Multiple public references in one query"""
        sql = """
            SELECT t.table_name, c.column_name
            FROM public.tables t
            JOIN public.columns c ON t.id = c.table_id
            WHERE t.schema = 'public'
        """
        result = translate_input_schema(sql)
        assert "public" not in result.lower() or "'SQLUser'" in result
        assert "SQLUser.tables" in result
        assert "SQLUser.columns" in result

    def test_public_in_subquery(self):
        """Schema reference in subquery"""
        sql = """
            SELECT * FROM (
                SELECT * FROM public.users WHERE active = true
            ) AS active_users
        """
        result = translate_input_schema(sql)
        assert "SQLUser.users" in result
        assert "public.users" not in result

    def test_information_schema_query(self):
        """Typical Prisma/SQLAlchemy introspection query"""
        sql = """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """
        result = translate_input_schema(sql)
        assert "table_schema = 'SQLUser'" in result
        # information_schema itself should NOT be modified
        assert "information_schema.tables" in result

    def test_double_quoted_schema_unaffected(self):
        """Double-quoted identifiers should also be handled"""
        sql = 'SELECT * FROM "public".users'
        result = translate_input_schema(sql)
        # Should translate double-quoted schema reference
        assert "SQLUser" in result or '"SQLUser"' in result

    def test_no_false_positives_in_strings(self):
        """The word 'public' in string literals (not schema refs) should be preserved"""
        sql = "SELECT 'This is public data' AS label"
        result = translate_input_schema(sql)
        # Should NOT modify 'public' inside a string value
        assert "'This is public data'" in result

    def test_insert_with_schema(self):
        """INSERT INTO public.tablename should be translated"""
        sql = "INSERT INTO public.users (name, email) VALUES ('John', 'john@example.com')"
        result = translate_input_schema(sql)
        assert "SQLUser.users" in result
        assert "public.users" not in result

    def test_update_with_schema(self):
        """UPDATE public.tablename should be translated"""
        sql = "UPDATE public.users SET name = 'Jane' WHERE id = 1"
        result = translate_input_schema(sql)
        assert "SQLUser.users" in result
        assert "public.users" not in result

    def test_delete_with_schema(self):
        """DELETE FROM public.tablename should be translated"""
        sql = "DELETE FROM public.users WHERE id = 1"
        result = translate_input_schema(sql)
        assert "SQLUser.users" in result
        assert "public.users" not in result
