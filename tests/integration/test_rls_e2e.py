"""E2E tests for RLS statement handling (Feature 035)."""

import pytest

from iris_pgwire.sql_translator import SQLTranslator, SkipReason


class TestRLSMigrationBatchE2E:
    """RLS statements in migration batch."""

    def test_rls_in_migration_sequence(self):
        translator = SQLTranslator()

        migration_statements = [
            'CREATE TABLE "logs" (id INT PRIMARY KEY, data TEXT)',
            'ALTER TABLE "logs" ENABLE ROW LEVEL SECURITY',
            'CREATE POLICY "logs_policy" ON "logs" FOR SELECT USING (true)',
            'CREATE INDEX "idx_logs_id" ON "logs"(id)',
            'ALTER TABLE "logs" DISABLE ROW LEVEL SECURITY',
            'DROP POLICY "logs_policy" ON "logs"',
        ]

        results = [translator.normalize_sql_with_result(s) for s in migration_statements]

        assert not results[0].was_skipped
        assert results[1].was_skipped and results[1].skip_reason == SkipReason.RLS_ENABLE
        assert results[2].was_skipped and results[2].skip_reason == SkipReason.CREATE_POLICY
        assert not results[3].was_skipped
        assert results[4].was_skipped and results[4].skip_reason == SkipReason.RLS_DISABLE
        assert results[5].was_skipped and results[5].skip_reason == SkipReason.DROP_POLICY

    def test_rls_command_tags(self):
        translator = SQLTranslator()

        result = translator.normalize_sql_with_result("ALTER TABLE t ENABLE ROW LEVEL SECURITY")
        assert result.command_tag == "ALTER TABLE"

        result = translator.normalize_sql_with_result(
            "CREATE POLICY p ON t FOR SELECT USING (true)"
        )
        assert result.command_tag == "CREATE POLICY"

        result = translator.normalize_sql_with_result("DROP POLICY p ON t")
        assert result.command_tag == "DROP POLICY"

    def test_rls_with_complex_policy(self):
        translator = SQLTranslator()

        complex_policy = """CREATE POLICY "tenant_isolation" ON "data"
            FOR ALL
            TO authenticated_users
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)"""

        result = translator.normalize_sql_with_result(complex_policy)
        assert result.was_skipped
        assert result.skip_reason == SkipReason.CREATE_POLICY


class TestRLSDoesNotAffectOtherStatements:
    """Verify RLS detection doesn't interfere with other ALTER TABLE statements."""

    def test_alter_table_add_column_not_skipped(self):
        translator = SQLTranslator()

        result = translator.normalize_sql_with_result(
            "ALTER TABLE users ADD COLUMN security_level INT"
        )
        assert not result.was_skipped

    def test_alter_table_with_security_in_name(self):
        translator = SQLTranslator()

        result = translator.normalize_sql_with_result(
            "ALTER TABLE security_settings ADD COLUMN level INT"
        )
        assert not result.was_skipped

    def test_regular_ddl_unaffected(self):
        translator = SQLTranslator()

        statements = [
            "CREATE TABLE users (id INT)",
            "ALTER TABLE users ADD COLUMN name VARCHAR(100)",
            "DROP TABLE users",
            "CREATE INDEX idx ON users(id)",
        ]

        for stmt in statements:
            result = translator.normalize_sql_with_result(stmt)
            assert not result.was_skipped, f"Statement should not be skipped: {stmt}"
