"""Contract tests for ENUM type translation (Feature 035)."""

import pytest

from iris_pgwire.sql_translator.enum_registry import EnumTypeRegistry
from iris_pgwire.sql_translator.statement_filter import StatementFilter, SkipReason
from iris_pgwire.sql_translator.enum_translator import EnumTranslator


class TestEnumRegistry:
    """Tests for EnumTypeRegistry."""

    def test_register_simple_type(self):
        registry = EnumTypeRegistry()
        registry.register("status")
        assert registry.is_registered("status")
        assert "status" in registry

    def test_register_quoted_type(self):
        registry = EnumTypeRegistry()
        registry.register('"MyEnum"')
        assert registry.is_registered("myenum")
        assert registry.is_registered('"MyEnum"')

    def test_register_schema_qualified(self):
        registry = EnumTypeRegistry()
        registry.register('"public"."permission_type"')
        assert registry.is_registered("permission_type")
        assert registry.is_registered('"permission_type"')

    def test_case_insensitive_lookup(self):
        registry = EnumTypeRegistry()
        registry.register("Status")
        assert registry.is_registered("STATUS")
        assert registry.is_registered("status")
        assert registry.is_registered("Status")

    def test_clear_registry(self):
        registry = EnumTypeRegistry()
        registry.register("type1")
        registry.register("type2")
        assert len(registry) == 2
        registry.clear()
        assert len(registry) == 0
        assert not registry.is_registered("type1")

    def test_get_registered_types(self):
        registry = EnumTypeRegistry()
        registry.register('"public"."status"')
        registry.register("permission")
        types = registry.get_registered_types()
        assert types == {"status", "permission"}


class TestStatementFilterEnumSkip:
    """E-001: CREATE TYPE AS ENUM skip tests."""

    def test_create_type_enum_detected(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = "CREATE TYPE \"public\".\"status\" AS ENUM ('active', 'inactive')"
        result = filter.check(sql)
        assert result.should_skip is True
        assert result.reason == SkipReason.CREATE_TYPE_ENUM
        assert result.command_tag == "CREATE TYPE"
        assert result.extracted_type_name == '"status"'

    def test_create_type_enum_simple(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = "CREATE TYPE status AS ENUM ('a', 'b', 'c')"
        result = filter.check(sql)
        assert result.should_skip is True
        assert result.reason == SkipReason.CREATE_TYPE_ENUM

    def test_create_type_enum_with_whitespace(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = "  CREATE   TYPE  my_enum   AS   ENUM  ('val1')"
        result = filter.check(sql)
        assert result.should_skip is True

    def test_non_enum_create_type_passes_through(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = "CREATE TYPE mytype AS (x int, y int)"
        result = filter.check(sql)
        assert result.should_skip is False


class TestStatementFilterDropType:
    """E-004: DROP TYPE skip for registered enums."""

    def test_drop_type_registered_enum_skipped(self):
        registry = EnumTypeRegistry()
        registry.register("status")
        filter = StatementFilter(registry)
        sql = 'DROP TYPE "status"'
        result = filter.check(sql)
        assert result.should_skip is True
        assert result.reason == SkipReason.DROP_TYPE_ENUM
        assert result.command_tag == "DROP TYPE"

    def test_drop_type_if_exists_registered(self):
        registry = EnumTypeRegistry()
        registry.register("status")
        filter = StatementFilter(registry)
        sql = 'DROP TYPE IF EXISTS "public"."status"'
        result = filter.check(sql)
        assert result.should_skip is True

    def test_drop_type_unregistered_passes_through(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = 'DROP TYPE "unknown_type"'
        result = filter.check(sql)
        assert result.should_skip is False


class TestEnumTranslatorColumnTypes:
    """E-002: Column type translation to VARCHAR(64)."""

    def test_translate_column_type_simple(self):
        registry = EnumTypeRegistry()
        registry.register("status")
        translator = EnumTranslator(registry)
        sql = 'CREATE TABLE t ("col" "status" NOT NULL)'
        result, count = translator.translate_column_types(sql)
        assert "VARCHAR(64)" in result
        assert count >= 1

    def test_translate_set_data_type(self):
        registry = EnumTypeRegistry()
        registry.register("workspace_invitation_status")
        translator = EnumTranslator(registry)
        sql = 'ALTER TABLE "t" ALTER COLUMN "status" SET DATA TYPE "public"."workspace_invitation_status"'
        result, count = translator.translate_column_types(sql)
        assert "VARCHAR(64)" in result
        assert "workspace_invitation_status" not in result.lower() or "varchar" in result.lower()

    def test_no_translation_when_no_enums(self):
        registry = EnumTypeRegistry()
        translator = EnumTranslator(registry)
        sql = "CREATE TABLE t (id INT, name VARCHAR(100))"
        result, count = translator.translate(sql)
        assert result == sql
        assert count == 0


class TestEnumTranslatorCastStripping:
    """E-003: Enum cast stripping."""

    def test_strip_simple_cast(self):
        registry = EnumTypeRegistry()
        registry.register("status")
        translator = EnumTranslator(registry)
        sql = "'active'::\"status\""
        result, count = translator.strip_enum_casts(sql)
        assert result == "'active'"
        assert count == 1

    def test_strip_schema_qualified_cast(self):
        registry = EnumTypeRegistry()
        registry.register("workspace_invitation_status")
        translator = EnumTranslator(registry)
        sql = '\'pending\'::"public"."workspace_invitation_status"'
        result, count = translator.strip_enum_casts(sql)
        assert result == "'pending'"
        assert count == 1

    def test_strip_cast_in_alter_statement(self):
        registry = EnumTypeRegistry()
        registry.register("status")
        translator = EnumTranslator(registry)
        sql = 'ALTER TABLE t ALTER COLUMN c SET DEFAULT \'active\'::"public"."status"'
        result, count = translator.strip_enum_casts(sql)
        assert "'active'" in result
        assert "::" not in result
        assert count == 1

    def test_no_strip_for_unregistered_type(self):
        registry = EnumTypeRegistry()
        translator = EnumTranslator(registry)
        sql = "'value'::\"unknown_type\""
        result, count = translator.strip_enum_casts(sql)
        assert result == sql
        assert count == 0


class TestEnumTranslatorSchemaQualified:
    """E-005: Schema-qualified enum handling."""

    def test_schema_qualified_type_in_column(self):
        registry = EnumTypeRegistry()
        registry.register('"public"."permission_type"')
        translator = EnumTranslator(registry)
        sql = 'SET DATA TYPE "public"."permission_type"'
        result, count = translator.translate_column_types(sql)
        assert "VARCHAR(64)" in result

    def test_quoted_identifier_enum(self):
        registry = EnumTypeRegistry()
        registry.register('"MyCustomEnum"')
        translator = EnumTranslator(registry)
        sql = "'val'::\"MyCustomEnum\""
        result, count = translator.strip_enum_casts(sql)
        assert result == "'val'"
