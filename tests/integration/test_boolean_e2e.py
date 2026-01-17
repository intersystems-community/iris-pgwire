"""E2E tests for boolean default translation (Feature 035)."""

import pytest

from iris_pgwire.sql_translator import SQLTranslator


class TestBooleanDefaultsE2E:
    """Boolean defaults in CREATE TABLE and ALTER TABLE."""

    def test_create_table_with_boolean_defaults(self):
        translator = SQLTranslator()

        sql = """CREATE TABLE "user_settings" (
            "id" uuid PRIMARY KEY,
            "email_notifications" boolean DEFAULT true NOT NULL,
            "sms_notifications" boolean DEFAULT false NOT NULL,
            "push_notifications" boolean DEFAULT true NOT NULL,
            "dark_mode" boolean DEFAULT false NOT NULL
        )"""

        result = translator.normalize_sql_with_result(sql)
        assert not result.was_skipped
        assert result.sql.count("DEFAULT 1") == 2
        assert result.sql.count("DEFAULT 0") == 2

    def test_alter_table_add_boolean_column(self):
        translator = SQLTranslator()

        sql = 'ALTER TABLE "settings" ADD COLUMN "debug_mode" boolean DEFAULT false NOT NULL'

        result = translator.normalize_sql_with_result(sql)
        assert "DEFAULT 0" in result.sql
        assert "DEFAULT false" not in result.sql

    def test_alter_column_set_default(self):
        translator = SQLTranslator()

        sql = 'ALTER TABLE "users" ALTER COLUMN "active" SET DEFAULT true'

        result = translator.normalize_sql_with_result(sql)
        assert "DEFAULT 1" in result.sql

    def test_boolean_in_complex_create_table(self):
        translator = SQLTranslator()

        sql = """CREATE TABLE "features" (
            "id" serial PRIMARY KEY,
            "name" varchar(100) NOT NULL,
            "enabled" boolean DEFAULT false,
            "beta" boolean DEFAULT true,
            "description" text DEFAULT 'This is a feature',
            "created_at" timestamp DEFAULT now()
        )"""

        result = translator.normalize_sql_with_result(sql)
        assert "DEFAULT 0" in result.sql
        assert "DEFAULT 1" in result.sql
        assert "'This is a feature'" in result.sql


class TestBooleanWithOtherTranslations:
    """Boolean translation combined with other Feature 035 translations."""

    def test_boolean_and_enum_together(self):
        translator = SQLTranslator()

        translator.normalize_sql_with_result(
            "CREATE TYPE \"status\" AS ENUM ('active', 'inactive')"
        )

        sql = """CREATE TABLE "accounts" (
            "id" uuid PRIMARY KEY,
            "status" "status" NOT NULL,
            "is_verified" boolean DEFAULT false NOT NULL,
            "is_premium" boolean DEFAULT true NOT NULL
        )"""

        result = translator.normalize_sql_with_result(sql)
        assert "VARCHAR(64)" in result.sql
        assert "DEFAULT 0" in result.sql
        assert "DEFAULT 1" in result.sql

    def test_boolean_after_rls_in_batch(self):
        translator = SQLTranslator()

        rls_result = translator.normalize_sql_with_result("ALTER TABLE t ENABLE ROW LEVEL SECURITY")
        assert rls_result.was_skipped

        bool_result = translator.normalize_sql_with_result(
            "ALTER TABLE t ADD COLUMN active boolean DEFAULT true"
        )
        assert not bool_result.was_skipped
        assert "DEFAULT 1" in bool_result.sql


class TestBooleanPreservesOriginalStructure:
    """Verify boolean translation preserves SQL structure."""

    def test_whitespace_preserved(self):
        translator = SQLTranslator()

        sql = "CREATE TABLE t (\n    col boolean DEFAULT true\n)"
        result = translator.normalize_sql_with_result(sql)
        assert "\n" in result.sql

    def test_other_defaults_unchanged(self):
        translator = SQLTranslator()

        sql = "CREATE TABLE t (n INT DEFAULT 42, s VARCHAR DEFAULT 'hello', b boolean DEFAULT true)"
        result = translator.normalize_sql_with_result(sql)
        assert "DEFAULT 42" in result.sql
        assert "'hello'" in result.sql
        assert "DEFAULT 1" in result.sql
