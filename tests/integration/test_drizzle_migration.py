"""E2E tests for Drizzle-style migration patterns (Feature 035)."""

from decimal import Decimal
import contextlib
from dataclasses import dataclass
import uuid

import pytest
from iris_devtester import IRISContainer

from iris_pgwire.migrations.executor import MigrationExecutor
from iris_pgwire.sql_translator import SkipReason, SQLTranslator
from iris_pgwire.sql_translator.ddl_parser import DDLParser
from iris_pgwire.sql_translator.ddl_translator import DDLTranslator


def _translate_postgres_create_table(sql: str) -> str:
    parser = DDLParser()
    translator = DDLTranslator()
    statements = parser.parse(sql)
    if not statements:
        raise AssertionError("DDL parser did not return any statements")
    result = translator.translate_statement(statements[0])
    assert result.is_translatable, "CREATE TABLE translation failed"
    assert result.translated_sql, "Translated SQL is empty"
    return result.translated_sql


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
        assert "VARCHAR(64)" in results[2].translated_sql
        assert not results[3].was_skipped
        assert "VARCHAR(64)" in results[3].translated_sql
        assert "DEFAULT 1" in results[3].translated_sql

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
            assert "DEFAULT true" not in result.translated_sql
            assert "DEFAULT false" not in result.translated_sql
            assert "DEFAULT 1" in result.translated_sql or "DEFAULT 0" in result.translated_sql

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
        assert "'pending'" in result.translated_sql
        assert "::" not in result.translated_sql

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
        assert "VARCHAR(64)" in results[1].translated_sql
        assert "'active'" in results[1].translated_sql
        assert "::" not in results[1].translated_sql
        assert "DEFAULT 0" in results[1].translated_sql
        assert "DEFAULT 1" in results[1].translated_sql

        assert results[2].was_skipped
        assert results[2].skip_reason == SkipReason.RLS_DISABLE

        assert not results[3].was_skipped

    def test_common_type_mappings(self):
        create_sql = """CREATE TABLE "type_map" (
            "id" text PRIMARY KEY,
            "active" boolean NOT NULL DEFAULT true,
            "payload" jsonb
        )"""
        translated_sql = _translate_postgres_create_table(create_sql)
        upper_sql = translated_sql.upper()
        assert (
            "VARCHAR(32767)" in upper_sql
        )  # VARCHAR(*) fails in IRIS - must use explicit max length
        assert "BIT" in upper_sql
        # IRIS requires native type %Library.DynamicObject for JSON in DDL
        assert "%LIBRARY.DYNAMICOBJECT" in upper_sql

    def test_timestamp_timezone_mapping(self):
        create_sql = """CREATE TABLE "time_map" (
            "event_time" timestamp with time zone NOT NULL
        )"""
        translated_sql = _translate_postgres_create_table(create_sql)
        upper_sql = translated_sql.upper()
        assert "TIMESTAMP" in upper_sql
        assert "WITH TIME ZONE" not in upper_sql

    def test_uuid_type_and_default(self):
        create_sql = """CREATE TABLE "uuid_map" (
            "id" uuid PRIMARY KEY DEFAULT gen_random_uuid()
        )"""
        translated_sql = _translate_postgres_create_table(create_sql)
        upper_sql = translated_sql.upper()
        # IRIS requires native type %Library.UniqueIdentifier for UUID in DDL
        assert "%LIBRARY.UNIQUEIDENTIFIER" in upper_sql
        # IRIS doesn't support function calls in DEFAULT, so DEFAULT is skipped
        assert "DEFAULT" not in upper_sql

    @pytest.mark.requires_iris
    def test_type_semantics_validation(self, iris_connection):
        create_table_sql = """CREATE TABLE "type_semantics_validation" (
            "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            "payload" jsonb NOT NULL,
            "is_active" boolean NOT NULL DEFAULT true,
            "created_at" timestamp with time zone DEFAULT now(),
            "score" numeric(10,2) NOT NULL DEFAULT 0.0
        )"""
        translated_sql = _translate_postgres_create_table(create_table_sql)
        table_identifier = '"type_semantics_validation"'
        drop_sql = f"DROP TABLE IF EXISTS {table_identifier}"
        row_uuid = "11111111-2222-3333-4444-555555555555"
        payload = '{"feature":"drizzle"}'
        try:
            with iris_connection.cursor() as cursor:
                cursor.execute(drop_sql)
                cursor.execute(translated_sql)
            iris_connection.commit()
            insert_sql = f'INSERT INTO {table_identifier} ("id", "payload", "is_active", "score") VALUES (?, ?, ?, ?)'
            with iris_connection.cursor() as cursor:
                cursor.execute(insert_sql, (row_uuid, payload, 1, Decimal("42.42")))
            iris_connection.commit()
            with iris_connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT "id", "payload", "is_active", "score" FROM {table_identifier}'
                )
                row = cursor.fetchone()
            assert row is not None
            assert str(row[0]).lower() == row_uuid.lower()
            assert "drizzle" in str(row[1]).lower()
            assert str(row[2]).strip() == "1"
            assert Decimal(str(row[3])) == Decimal("42.42")
        finally:
            with iris_connection.cursor() as cursor:
                cursor.execute(drop_sql)
            iris_connection.commit()


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
            assert "DEFAULT true" not in result.translated_sql
            assert "DEFAULT false" not in result.translated_sql
            assert "DEFAULT TRUE" not in result.translated_sql
            assert "DEFAULT FALSE" not in result.translated_sql


@dataclass(frozen=True)
class SimpleMigration:
    """Minimal model used to exercise MigrationExecutor."""

    statements: tuple[str, ...]
    hash: str


# Removed custom _attached_iris_connection() - use standard iris_connection fixture instead


def _execute_sql(connection, sql: str, params: tuple | None = None) -> None:
    cursor = connection.cursor()
    try:
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
    finally:
        cursor.close()


def drop_table_if_exists(connection, table_name: str) -> None:
    cursor = connection.cursor()
    try:
        for identifier in (table_name, table_name.upper()):
            for stmt in (f'DROP TABLE "{identifier}"', f"DROP TABLE {identifier}"):
                try:
                    cursor.execute(stmt)
                    connection.commit()
                    return
                except Exception:  # pragma: no cover - drop might fail
                    connection.rollback()
    finally:
        cursor.close()


def _table_exists(connection, table_name: str) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?",
            (table_name.upper(),),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def _get_table_columns(connection, table_name: str) -> list[tuple[str, str]]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?",
            (table_name.upper(),),
        )
        return cursor.fetchall()
    finally:
        cursor.close()


def _has_primary_key_constraint(connection, table_name: str) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
            "WHERE TABLE_NAME = ? AND CONSTRAINT_TYPE = ?",
            (table_name.upper(), "PRIMARY KEY"),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def _count_migration_hash(connection, migration_hash: str) -> int:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(1) FROM __drizzle_migrations WHERE hash = ?", (migration_hash,)
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    finally:
        cursor.close()


def _delete_migration_hash(connection, migration_hash: str) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM __drizzle_migrations WHERE hash = ?", (migration_hash,))
        connection.commit()
    finally:
        cursor.close()


def _parse_first_create_statement(sql: str):
    parser = DDLParser()
    statements = parser.parse(sql)
    for statement in statements:
        if statement.statement_type == "CREATE_TABLE":
            return statement
    raise AssertionError("No CREATE TABLE statement found in DDL payload")


def _parse_first_alter_statement(sql: str):
    parser = DDLParser()
    statements = parser.parse(sql)
    for statement in statements:
        if statement.statement_type == "ALTER_TABLE":
            return statement
    raise AssertionError("No ALTER TABLE statement found in DDL payload")


def _apply_parsed_statement(connection, parsed_statement) -> None:
    translator = DDLTranslator()
    translated = translator.translate_statement(parsed_statement)
    assert translated.is_translatable
    assert translated.translated_sql
    _execute_sql(connection, translated.translated_sql)
    connection.commit()


@pytest.mark.integration
def test_basic_table_creation(sample_drizzle_migration, iris_connection):
    connection = iris_connection
    drop_table_if_exists(connection, "workflow")
    try:
        parser = DDLParser()
        statements = parser.parse(sample_drizzle_migration)
        create_stmt = next(
            (stmt for stmt in statements if stmt.statement_type == "CREATE_TABLE"),
            None,
        )
        assert create_stmt is not None, "Expected CREATE TABLE statement in fixture"
        _apply_parsed_statement(connection, create_stmt)
        column_map = {
            name.lower(): dtype.upper()
            for name, dtype in _get_table_columns(connection, "workflow")
        }
        expected_types = {
            "id": "VARCHAR",
            "name": "VARCHAR",
            "user_id": "VARCHAR",
            "level": "INTEGER",
            "created_at": "TIMESTAMP",
            "state": "VARCHAR",
        }
        for column_name, expected_type in expected_types.items():
            actual = column_map.get(column_name)
            assert actual and expected_type in actual
    finally:
        drop_table_if_exists(connection, "workflow")


@pytest.mark.integration
def test_reserved_word_auto_quoting(iris_connection):
    table_name = "reserved_words_demo"
    create_sql = f"""CREATE TABLE {table_name} (
        level text,
        key text,
        trigger text
    )"""

    connection = iris_connection
    drop_table_if_exists(connection, table_name)
    try:
        statement = _parse_first_create_statement(create_sql)
        _apply_parsed_statement(connection, statement)
        insert_sql = f'INSERT INTO {table_name} ("level", "key", "trigger") VALUES (?, ?, ?)'
        _execute_sql(connection, insert_sql, ("1", "value", "event"))
        connection.commit()
        select_sql = f'SELECT "level", "key", "trigger" FROM {table_name}'
        cursor = connection.cursor()
        try:
            cursor.execute(select_sql)
            row = cursor.fetchone()
        finally:
            cursor.close()
        assert row == ("1", "value", "event")
    finally:
        drop_table_if_exists(connection, table_name)


@pytest.mark.integration
def test_alter_table_add_column(iris_connection):
    table_name = "alter_table_add_reserved"
    create_sql = f"CREATE TABLE {table_name} (id text)"
    alter_sql = f"ALTER TABLE {table_name} ADD COLUMN level text NOT NULL"

    connection = iris_connection
    drop_table_if_exists(connection, table_name)
    try:
        statement = _parse_first_create_statement(create_sql)
        _apply_parsed_statement(connection, statement)

        alter_statement = _parse_first_alter_statement(alter_sql)
        translator = DDLTranslator()
        result = translator.translate_statement(alter_statement)
        assert result.is_translatable
        assert '"level"' in result.translated_sql

        _execute_sql(connection, result.translated_sql)
        connection.commit()

        columns = _get_table_columns(connection, table_name)
        assert any(
            name.lower() == "level" and "VARCHAR" in dtype.upper() for name, dtype in columns
        )
    finally:
        drop_table_if_exists(connection, table_name)


@pytest.mark.integration
def test_alter_table_reserved_words(iris_connection):
    table_name = "alter_table_reserved_words"
    create_sql = f"CREATE TABLE {table_name} (id text, level text, key text, state text)"

    drop_sql = f"ALTER TABLE {table_name} DROP COLUMN state"
    rename_sql = f'ALTER TABLE {table_name} RENAME COLUMN "key" TO "value"'

    connection = iris_connection
    drop_table_if_exists(connection, table_name)
    try:
        statement = _parse_first_create_statement(create_sql)
        _apply_parsed_statement(connection, statement)

        drop_statement = _parse_first_alter_statement(drop_sql)
        drop_result = DDLTranslator().translate_statement(drop_statement)
        assert drop_result.is_translatable
        # state is not a reserved word, so it won't be quoted
        assert "state" in drop_result.translated_sql.lower()
        _execute_sql(connection, drop_result.translated_sql)
        connection.commit()

        rename_statement = _parse_first_alter_statement(rename_sql)
        rename_result = DDLTranslator().translate_statement(rename_statement)
        # IRIS doesn't support RENAME COLUMN
        assert not rename_result.is_translatable
        assert any("does not support" in w.lower() for w in rename_result.translation_warnings)

        # Since RENAME isn't supported, manually verify the columns exist
        column_names = {name.upper() for name, _ in _get_table_columns(connection, table_name)}
        assert "STATE" not in column_names  # Was dropped
        assert "KEY" in column_names  # Still exists (rename not executed)
        assert "VALUE" not in column_names  # Rename not executed
    finally:
        drop_table_if_exists(connection, table_name)


@pytest.mark.integration
def test_alter_table_type_translation(iris_connection):
    table_name = "alter_table_type_translation"
    create_sql = f"CREATE TABLE {table_name} (id text)"
    # (pg_type, expected_in_sql_or_workaround, expected_db_type)
    columns_to_add = [
        ("jsonb", "%LIBRARY.DYNAMICOBJECT", "VARCHAR"),  # JSON mapped to VARCHAR in IRIS
        ("uuid", "%LIBRARY.UNIQUEIDENTIFIER", "GUID"),  # UUID reported as GUID in IRIS
        ("text", "%LIBRARY.STRING", "VARCHAR"),  # text uses workaround for ALTER TABLE
    ]

    connection = iris_connection
    drop_table_if_exists(connection, table_name)
    try:
        statement = _parse_first_create_statement(create_sql)
        _apply_parsed_statement(connection, statement)

        for i, (pg_type, expected_sql, expected_db_type) in enumerate(columns_to_add):
            column_name = f"col{i}"
            alter_sql = f'ALTER TABLE {table_name} ADD COLUMN "{column_name}" {pg_type}'
            alter_statement = _parse_first_alter_statement(alter_sql)
            result = DDLTranslator().translate_statement(alter_statement)
            assert result.is_translatable
            # Check workaround is applied in translated SQL
            assert expected_sql in result.translated_sql.upper(), (
                f"Expected {expected_sql} in SQL: {result.translated_sql}"
            )
            _execute_sql(connection, result.translated_sql)
            connection.commit()

        # Verify columns were created with correct types
        columns = {
            name.upper(): dtype.upper()
            for name, dtype in _get_table_columns(connection, table_name)
        }
        for i, (_, _, expected_db_type) in enumerate(columns_to_add):
            column_name = f"COL{i}"
            dtype = columns.get(column_name)
            assert dtype and expected_db_type in dtype, (
                f"Expected {expected_db_type} in db type {dtype} for {column_name}"
            )
    finally:
        drop_table_if_exists(connection, table_name)


@pytest.mark.integration
def test_primary_key_constraint(iris_connection):
    table_name = f"PRIMARY_KEY_TEST_{uuid.uuid4().hex[:8].upper()}"
    create_sql = f"CREATE TABLE {table_name} (id text PRIMARY KEY NOT NULL, value text)"

    connection = iris_connection
    drop_table_if_exists(connection, table_name)
    try:
        statement = _parse_first_create_statement(create_sql)
        _apply_parsed_statement(connection, statement)
        assert _has_primary_key_constraint(connection, table_name)
        cursor = connection.cursor()
        try:
            cursor.execute(f"INSERT INTO {table_name} (id, value) VALUES (?, ?)", ("a", "first"))
        finally:
            cursor.close()
        connection.commit()
        with pytest.raises(Exception):
            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"INSERT INTO {table_name} (id, value) VALUES (?, ?)", ("a", "second")
                )
            finally:
                cursor.close()
        connection.rollback()
    finally:
        drop_table_if_exists(connection, table_name)


@pytest.mark.integration
def test_transaction_rollback_on_failure(iris_connection):
    table_name = f"ROLLBACK_TEST_{uuid.uuid4().hex[:8].upper()}"
    migration_hash = f"rollback-{uuid.uuid4().hex}"
    statements = (
        f"CREATE TABLE {table_name} (id text PRIMARY KEY NOT NULL)",
        f"CREATE INDEX idx_{table_name} ON {table_name} (id)",
    )
    migration = SimpleMigration(statements=statements, hash=migration_hash)

    connection = iris_connection
    drop_table_if_exists(connection, table_name)
    executor = MigrationExecutor(connection)
    executor.create_journal_table()
    result = executor.execute_migration(migration)
    assert not result.success
    assert not _table_exists(connection, table_name)
    assert _count_migration_hash(connection, migration_hash) == 0
    drop_table_if_exists(connection, table_name)


@pytest.mark.integration
def test_unsupported_index_feature():
    parser = DDLParser()
    translator = DDLTranslator()
    scenarios = (
        (
            'CREATE INDEX "active_users" ON "users" ("email") WHERE "active" = true;',
            "IRIS does not support partial indexes",
            "Remove WHERE clause or create index on full table.",
        ),
        (
            'CREATE INDEX "include_idx" ON "users" ("email") INCLUDE ("name");',
            "IRIS does not support INCLUDE columns",
            "Create separate index or remove INCLUDE clause.",
        ),
        (
            'CREATE INDEX "expr_idx" ON "users" (LOWER("email"));',
            "IRIS does not support expression indexes",
            "Create index on column directly.",
        ),
    )

    for sql, expected_message, expected_fix in scenarios:
        statements = parser.parse(sql)
        assert statements, f"Parser returned no statements for SQL: {sql}"
        translated = translator.translate_statement(statements[0])
        assert not translated.is_translatable
        warning_text = " ".join(translated.translation_warnings)
        assert "UNSUPPORTED_INDEX_FEATURE" in warning_text
        assert expected_message in warning_text
        assert expected_fix in warning_text


@pytest.mark.integration
def test_migration_journal_tracking(iris_connection):
    table_name = f"JOURNAL_TEST_{uuid.uuid4().hex[:8].upper()}"
    migration_hash = f"journal-{uuid.uuid4().hex}"
    migration = SimpleMigration(
        statements=(f"CREATE TABLE {table_name} (id text PRIMARY KEY NOT NULL)",),
        hash=migration_hash,
    )

    connection = iris_connection
    drop_table_if_exists(connection, table_name)
    executor = MigrationExecutor(connection)
    executor.create_journal_table()
    first_result = executor.execute_migration(migration)
    assert first_result.success and not first_result.already_applied
    second_result = executor.execute_migration(migration)
    assert second_result.success and second_result.already_applied
    assert second_result.statements_executed == 0
    assert _count_migration_hash(connection, migration_hash) == 1
    _delete_migration_hash(connection, migration_hash)
    drop_table_if_exists(connection, table_name)
