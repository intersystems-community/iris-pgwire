"""E2E tests for Drizzle-style migration patterns (Feature 035)."""

import pytest

from iris_pgwire.sql_translator import SkipReason, SQLTranslator


class TestDrizzleMigrationPatterns:
    """Test patterns from actual Drizzle ORM migrations."""

    def test_drizzle_enum_migration(self):
        """Drizzle creates enum types before tables that use them."""
        translator = SQLTranslator()

        drizzle_statements = [
            "CREATE TYPE \"public\".\"permission_type\" AS ENUM('admin', 'write', 'read')",
            "CREATE TYPE \"public\".\"notification_type\" AS ENUM('email', 'sms', 'webhook')",
            """CREATE TABLE "permissions" (
                "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                "permission_type" "permission_type" NOT NULL
            )""",
            """CREATE TABLE "notifications" (
                "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                "type" "notification_type" NOT NULL,
                "enabled" boolean DEFAULT true NOT NULL
            )""",
        ]

        results = [translator.normalize_sql_with_result(s) for s in drizzle_statements]

        assert results[0].was_skipped
        assert results[1].was_skipped
        assert not results[2].was_skipped
        assert "VARCHAR(64)" in results[2].sql
        assert not results[3].was_skipped
        assert "VARCHAR(64)" in results[3].sql
        assert "DEFAULT 1" in results[3].sql

    def test_drizzle_rls_migration(self):
        """Drizzle disables RLS on tables during migrations."""
        translator = SQLTranslator()

        drizzle_statements = [
            'ALTER TABLE "logs" DISABLE ROW LEVEL SECURITY',
            'ALTER TABLE "user_environment" DISABLE ROW LEVEL SECURITY',
            'ALTER TABLE "settings" DISABLE ROW LEVEL SECURITY',
        ]

        for stmt in drizzle_statements:
            result = translator.normalize_sql_with_result(stmt)
            assert result.was_skipped
            assert result.skip_reason == SkipReason.RLS_DISABLE
            assert result.command_tag == "ALTER TABLE"

    def test_drizzle_boolean_columns(self):
        """Drizzle uses boolean DEFAULT true/false in column definitions."""
        translator = SQLTranslator()

        drizzle_statements = [
            'ALTER TABLE "settings" ADD COLUMN "debug_mode" boolean DEFAULT false NOT NULL',
            'ALTER TABLE "settings" ADD COLUMN "auto_connect" boolean DEFAULT true NOT NULL',
            'ALTER TABLE "users" ADD COLUMN "is_active" boolean DEFAULT true NOT NULL',
            'ALTER TABLE "users" ADD COLUMN "is_deleted" boolean DEFAULT false NOT NULL',
        ]

        for stmt in drizzle_statements:
            result = translator.normalize_sql_with_result(stmt)
            assert not result.was_skipped
            assert "DEFAULT true" not in result.sql
            assert "DEFAULT false" not in result.sql
            assert "DEFAULT 1" in result.sql or "DEFAULT 0" in result.sql

    def test_drizzle_enum_with_default_cast(self):
        """Drizzle uses enum casts in default values."""
        translator = SQLTranslator()

        translator.normalize_sql_with_result(
            "CREATE TYPE \"public\".\"workspace_invitation_status\" AS ENUM('pending', 'accepted', 'rejected')"
        )

        alter_stmt = '''ALTER TABLE "workspace_invitation"
            ALTER COLUMN "status" SET DEFAULT 'pending'::"public"."workspace_invitation_status"'''

        result = translator.normalize_sql_with_result(alter_stmt)
        assert not result.was_skipped
        assert "'pending'" in result.sql
        assert "::" not in result.sql

    def test_full_drizzle_migration_sequence(self):
        """Simulate a complete Drizzle migration with all Feature 035 patterns."""
        translator = SQLTranslator()

        migration = [
            "CREATE TYPE \"public\".\"status\" AS ENUM('active', 'inactive', 'pending')",
            """CREATE TABLE "workspaces" (
                "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                "name" varchar(255) NOT NULL,
                "status" "status" DEFAULT 'active'::"public"."status" NOT NULL,
                "is_public" boolean DEFAULT false NOT NULL,
                "auto_join" boolean DEFAULT true NOT NULL
            )""",
            'ALTER TABLE "workspaces" DISABLE ROW LEVEL SECURITY',
            'CREATE INDEX "idx_workspaces_name" ON "workspaces"("name")',
        ]

        results = []
        for stmt in migration:
            result = translator.normalize_sql_with_result(stmt)
            results.append(result)

        assert results[0].was_skipped
        assert results[0].skip_reason == SkipReason.CREATE_TYPE_ENUM

        assert not results[1].was_skipped
        assert "VARCHAR(64)" in results[1].sql
        assert "'active'" in results[1].sql
        assert "::" not in results[1].sql
        assert "DEFAULT 0" in results[1].sql
        assert "DEFAULT 1" in results[1].sql

        assert results[2].was_skipped
        assert results[2].skip_reason == SkipReason.RLS_DISABLE

        assert not results[3].was_skipped


class TestDrizzleMigrationCount:
    """Verify we handle the expected number of problematic statements."""

    def test_handles_enum_statement_patterns(self):
        """13 ENUM statements identified in problem analysis."""
        translator = SQLTranslator()

        enum_patterns = [
            "CREATE TYPE \"status\" AS ENUM ('a')",
            "CREATE TYPE \"public\".\"role\" AS ENUM ('admin', 'user')",
            "CREATE TYPE permission AS ENUM ('read', 'write')",
        ]

        for pattern in enum_patterns:
            result = translator.normalize_sql_with_result(pattern)
            assert result.was_skipped, f"Should skip: {pattern}"

    def test_handles_rls_statement_patterns(self):
        """3 RLS statements identified in problem analysis."""
        translator = SQLTranslator()

        rls_patterns = [
            "ALTER TABLE t ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE t DISABLE ROW LEVEL SECURITY",
            "CREATE POLICY p ON t FOR SELECT USING (true)",
        ]

        for pattern in rls_patterns:
            result = translator.normalize_sql_with_result(pattern)
            assert result.was_skipped, f"Should skip: {pattern}"

    def test_handles_boolean_default_patterns(self):
        """48 boolean default statements identified in problem analysis."""
        translator = SQLTranslator()

        bool_patterns = [
            "ALTER TABLE t ADD COLUMN c boolean DEFAULT true",
            "ALTER TABLE t ADD COLUMN c boolean DEFAULT false",
            "ALTER TABLE t ADD COLUMN c boolean DEFAULT TRUE NOT NULL",
            "ALTER TABLE t ADD COLUMN c boolean DEFAULT FALSE NOT NULL",
        ]

        for pattern in bool_patterns:
            result = translator.normalize_sql_with_result(pattern)
            assert not result.was_skipped
            assert "DEFAULT true" not in result.sql
            assert "DEFAULT false" not in result.sql
            assert "DEFAULT TRUE" not in result.sql
            assert "DEFAULT FALSE" not in result.sql
