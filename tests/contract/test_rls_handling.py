"""Contract tests for Row Level Security statement handling (Feature 035)."""

import pytest

from iris_pgwire.sql_translator.enum_registry import EnumTypeRegistry
from iris_pgwire.sql_translator.statement_filter import SkipReason, StatementFilter


class TestRLSEnableSkip:
    """R-001: ENABLE ROW LEVEL SECURITY skip."""

    def test_enable_rls_detected(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = 'ALTER TABLE "logs" ENABLE ROW LEVEL SECURITY'
        result = filter.check(sql)
        assert result.should_skip is True
        assert result.reason == SkipReason.RLS_ENABLE
        assert result.command_tag == "ALTER TABLE"

    def test_enable_rls_with_schema(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = 'ALTER TABLE "public"."users" ENABLE ROW LEVEL SECURITY'
        result = filter.check(sql)
        assert result.should_skip is True
        assert result.reason == SkipReason.RLS_ENABLE

    def test_enable_rls_case_insensitive(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = "alter table logs enable row level security"
        result = filter.check(sql)
        assert result.should_skip is True


class TestRLSDisableSkip:
    """R-002: DISABLE ROW LEVEL SECURITY skip."""

    def test_disable_rls_detected(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = 'ALTER TABLE "user_environment" DISABLE ROW LEVEL SECURITY'
        result = filter.check(sql)
        assert result.should_skip is True
        assert result.reason == SkipReason.RLS_DISABLE
        assert result.command_tag == "ALTER TABLE"

    def test_disable_rls_with_schema(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = 'ALTER TABLE "public"."settings" DISABLE ROW LEVEL SECURITY'
        result = filter.check(sql)
        assert result.should_skip is True


class TestCreatePolicySkip:
    """R-003: CREATE POLICY skip."""

    def test_create_policy_detected(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = (
            'CREATE POLICY "users_policy" ON "users" FOR SELECT USING (user_id = current_user_id())'
        )
        result = filter.check(sql)
        assert result.should_skip is True
        assert result.reason == SkipReason.CREATE_POLICY
        assert result.command_tag == "CREATE POLICY"

    def test_create_policy_with_all_clauses(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = """CREATE POLICY admin_all ON accounts
                 FOR ALL
                 TO admin_role
                 USING (true)
                 WITH CHECK (true)"""
        result = filter.check(sql)
        assert result.should_skip is True

    def test_create_policy_case_insensitive(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = "create policy my_policy on my_table for select using (true)"
        result = filter.check(sql)
        assert result.should_skip is True


class TestDropPolicySkip:
    """R-004: DROP POLICY skip."""

    def test_drop_policy_detected(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = 'DROP POLICY "users_policy" ON "users"'
        result = filter.check(sql)
        assert result.should_skip is True
        assert result.reason == SkipReason.DROP_POLICY
        assert result.command_tag == "DROP POLICY"

    def test_drop_policy_if_exists(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = 'DROP POLICY IF EXISTS "old_policy" ON "accounts"'
        result = filter.check(sql)
        assert result.should_skip is True


class TestRLSMultiStatement:
    """R-005: Multi-statement batch with RLS."""

    def test_rls_mixed_with_ddl_each_processed(self):
        """Each statement in a batch is processed independently."""
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)

        statements = [
            "CREATE TABLE logs (id INT)",
            "ALTER TABLE logs ENABLE ROW LEVEL SECURITY",
            "CREATE INDEX idx_logs ON logs(id)",
        ]

        results = [filter.check(s) for s in statements]

        assert results[0].should_skip is False
        assert results[1].should_skip is True
        assert results[1].reason == SkipReason.RLS_ENABLE
        assert results[2].should_skip is False


class TestRLSSchemaQualified:
    """R-006: Schema-qualified table in RLS."""

    def test_schema_qualified_enable_rls(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = 'ALTER TABLE "myschema"."mytable" ENABLE ROW LEVEL SECURITY'
        result = filter.check(sql)
        assert result.should_skip is True

    def test_schema_qualified_policy(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = 'CREATE POLICY "pol" ON "myschema"."mytable" FOR SELECT USING (true)'
        result = filter.check(sql)
        assert result.should_skip is True


class TestNonRLSStatementsPassThrough:
    """Verify non-RLS ALTER TABLE statements pass through."""

    def test_alter_table_add_column(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = "ALTER TABLE users ADD COLUMN age INT"
        result = filter.check(sql)
        assert result.should_skip is False

    def test_alter_table_drop_column(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = "ALTER TABLE users DROP COLUMN temp"
        result = filter.check(sql)
        assert result.should_skip is False

    def test_regular_create_statement(self):
        registry = EnumTypeRegistry()
        filter = StatementFilter(registry)
        sql = "CREATE TABLE users (id INT PRIMARY KEY)"
        result = filter.check(sql)
        assert result.should_skip is False
