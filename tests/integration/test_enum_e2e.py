"""E2E tests for ENUM type handling (Feature 035)."""

import pytest

from iris_pgwire.sql_translator import SQLTranslator, SkipReason


class TestEnumWorkflowE2E:
    """Full ENUM workflow: CREATE TYPE -> table -> column -> DROP."""

    def test_full_enum_workflow(self):
        translator = SQLTranslator()

        create_type = (
            "CREATE TYPE \"public\".\"permission_type\" AS ENUM ('admin', 'write', 'read')"
        )
        result = translator.normalize_sql_with_result(create_type)
        assert result.was_skipped
        assert result.skip_reason == SkipReason.CREATE_TYPE_ENUM
        assert result.command_tag == "CREATE TYPE"

        create_table = """CREATE TABLE "permissions" (
            "id" uuid PRIMARY KEY,
            "permission_type" "permission_type" NOT NULL
        )"""
        result = translator.normalize_sql_with_result(create_table)
        assert not result.was_skipped
        assert "VARCHAR(64)" in result.sql

        drop_type = 'DROP TYPE "permission_type"'
        result = translator.normalize_sql_with_result(drop_type)
        assert result.was_skipped
        assert result.skip_reason == SkipReason.DROP_TYPE_ENUM

    def test_enum_cast_in_default(self):
        translator = SQLTranslator()

        translator.normalize_sql_with_result("CREATE TYPE \"status\" AS ENUM ('pending', 'active')")

        alter_default = '''ALTER TABLE "workspace_invitation" 
            ALTER COLUMN "status" SET DEFAULT 'pending'::"public"."status"'''
        result = translator.normalize_sql_with_result(alter_default)
        assert not result.was_skipped
        assert "'pending'" in result.sql
        assert "::" not in result.sql

    def test_multiple_enum_types_in_session(self):
        translator = SQLTranslator()

        translator.normalize_sql_with_result("CREATE TYPE \"role\" AS ENUM ('admin', 'user')")
        translator.normalize_sql_with_result(
            "CREATE TYPE \"status\" AS ENUM ('active', 'inactive')"
        )

        assert translator.enum_registry.is_registered("role")
        assert translator.enum_registry.is_registered("status")

        table_sql = """CREATE TABLE t (
            role "role",
            status "status"
        )"""
        result = translator.normalize_sql_with_result(table_sql)
        assert result.sql.count("VARCHAR(64)") == 2

    def test_schema_qualified_enum_handling(self):
        translator = SQLTranslator()

        translator.normalize_sql_with_result(
            "CREATE TYPE \"myschema\".\"custom_type\" AS ENUM ('a', 'b')"
        )

        assert translator.enum_registry.is_registered("custom_type")
        assert translator.enum_registry.is_registered('"myschema"."custom_type"')

    def test_enum_registry_isolation_per_translator(self):
        translator1 = SQLTranslator()
        translator2 = SQLTranslator()

        translator1.normalize_sql_with_result("CREATE TYPE \"type1\" AS ENUM ('a')")

        assert translator1.enum_registry.is_registered("type1")
        assert not translator2.enum_registry.is_registered("type1")
