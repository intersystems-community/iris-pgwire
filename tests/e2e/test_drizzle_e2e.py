"""End-to-end exercises for Drizzle ORM DDL translation via PGWire."""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import Iterable

import pytest

try:
    from iris_devtester import IRISContainer

    IRIS_DEVTESTER_AVAILABLE = True
except ImportError:  # pragma: no cover - skip in environments without iris-devtester
    IRIS_DEVTESTER_AVAILABLE = False

from iris_pgwire.config import DDLTranslationConfig
from iris_pgwire.migrations.executor import MigrationExecutor
from tests.fixtures.drizzle_fixtures import (
    DrizzleMigrationFile,
    drizzle_basic_migration_file,
    drizzle_failure_migration_file,
    drizzle_multi_migration_files,
    drizzle_reserved_words_migration_file,
    drizzle_type_mapping_migration_file,
)

pytestmark = pytest.mark.requires_iris

_DDL_CONFIG = DDLTranslationConfig(
    strict_mode=False,
    auto_quote_reserved_words=True,
    validate_precision=True,
    lock_timeout_seconds=30,
    fail_fast=True,
)


def _create_executor(connection):
    return MigrationExecutor(connection, config=_DDL_CONFIG)


def _ensure_devtester_available() -> None:
    if not IRIS_DEVTESTER_AVAILABLE:
        pytest.skip("iris-devtester is required for Drizzle e2e tests")


@contextlib.contextmanager
def _attach_pgwire_container():
    _ensure_devtester_available()
    try:
        container = IRISContainer.attach("iris-pgwire-test")
    except Exception as exc:  # pragma: no cover - attachment is environment specific
        pytest.skip(f"Unable to attach to iris-pgwire-test: {exc}")

    try:
        connection = container.get_connection()
    except Exception as exc:
        pytest.skip(f"Failed to get IRIS connection from devtester: {exc}")

    try:
        yield container, connection
    finally:
        try:
            connection.close()
        except Exception:
            pass


@pytest.fixture
def attached_iris_resources():
    with _attach_pgwire_container() as resources:
        yield resources


def _execute_embedded_query(connection, sql: str) -> list[dict[str, str | None]]:
    with connection.cursor() as cur:
        cur.execute(sql)
        columns = [d[0].lower() for d in cur.description] if cur.description else []
        rows = cur.fetchall() or []
    return [
        {col: (str(val) if val is not None else None) for col, val in zip(columns, row)}
        for row in rows
    ]


def _embedded_table_exists(connection, table_name: str) -> bool:
    sql = (
        "SELECT 1 AS exists_flag FROM INFORMATION_SCHEMA.TABLES "
        f"WHERE UPPER(TABLE_NAME) = '{table_name.upper()}'"
    )
    rows = _execute_embedded_query(connection, sql)
    return bool(rows)


def _embedded_journal_count(connection, migration_hash: str) -> int:
    sql = (
        "SELECT COUNT(1) AS migration_count FROM __drizzle_migrations "
        f"WHERE hash = '{migration_hash}'"
    )
    rows = _execute_embedded_query(connection, sql)
    if not rows:
        return 0
    value = rows[0].get("migration_count")
    if value is None:
        return 0
    return int(value)


def _drop_table_if_exists(connection, table_name: str | None) -> None:
    if not table_name:
        return
    cursor = connection.cursor()
    try:
        for candidate in {table_name, table_name.upper()}:
            if not candidate:
                continue
            try:
                cursor.execute(f'DROP TABLE IF EXISTS "{candidate}"')
                connection.commit()
            except Exception:
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


def _get_column_map(connection, table_name: str) -> dict[str, str]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
            (table_name.upper(),),
        )
        return {row[0].lower(): row[1].upper() for row in cursor.fetchall()}
    finally:
        cursor.close()


def _cleanup_journal_entries(connection, migration_hashes: Iterable[str]) -> None:
    cursor = connection.cursor()
    try:
        for migration_hash in set(migration_hashes):
            if not migration_hash:
                continue
            cursor.execute("DELETE FROM __drizzle_migrations WHERE hash = ?", (migration_hash,))
        connection.commit()
    except Exception:
        connection.rollback()
    finally:
        cursor.close()


def _cleanup_tables(connection, table_names: Iterable[str | None]) -> None:
    for table_name in table_names:
        _drop_table_if_exists(connection, table_name)


def _prepare_migration_environment(connection, migration: DrizzleMigrationFile) -> None:
    _drop_table_if_exists(connection, migration.target_table)
    _cleanup_journal_entries(connection, (migration.hash,))


@pytest.mark.e2e
def test_drizzle_basic_workflow(
    attached_iris_resources,
    drizzle_basic_migration_file: DrizzleMigrationFile,
):
    """Verify the minimal Drizzle CREATE TABLE migration finishes successfully."""
    container, connection = attached_iris_resources
    executor = _create_executor(connection)
    executor.create_journal_table()
    migration = drizzle_basic_migration_file
    _prepare_migration_environment(connection, migration)
    try:
        result = executor.execute_migration(migration)
        assert result.success, f"Migration {migration.filename} should succeed"
        assert result.error is None, "No error should be reported for a clean migration"

        assert _embedded_table_exists(connection, migration.target_table), (
            "Drizzle should create the workflow table before validation"
        )

        column_types = _get_column_map(connection, migration.target_table)
        expected = {
            "id": "VARCHAR",
            "name": "VARCHAR",
            "user_id": "VARCHAR",
            "level": "INTEGER",
            "created_at": "TIMESTAMP",
            "state": "VARCHAR",
        }
        for column_name, expected_type in expected.items():
            actual = column_types.get(column_name)
            assert actual and expected_type in actual, (
                f"Column {column_name} should exist as {expected_type}, got {actual} instead"
            )

        assert _embedded_journal_count(connection, migration.hash) == 1, (
            "Journal should contain exactly one entry for the executed migration"
        )
    finally:
        _cleanup_tables(connection, (migration.target_table,))
        _cleanup_journal_entries(connection, (migration.hash,))


@pytest.mark.e2e
def test_drizzle_reserved_words_workflow(
    attached_iris_resources,
    drizzle_reserved_words_migration_file: DrizzleMigrationFile,
):
    """Ensure reserved keywords in column names are safely quoted."""
    container, connection = attached_iris_resources
    executor = _create_executor(connection)
    executor.create_journal_table()
    migration = drizzle_reserved_words_migration_file
    _prepare_migration_environment(connection, migration)
    try:
        result = executor.execute_migration(migration)
        assert result.success, "Reserved words migration should finish cleanly"

        with connection.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {migration.target_table} ("level", "key", "trigger") VALUES (?, ?, ?)',
                ("1", "value", "event"),
            )
        connection.commit()

        rows = _execute_embedded_query(
            connection,
            f'SELECT "level", "key", "trigger" FROM {migration.target_table}',
        )
        assert rows and rows[0].get("level") == "1" and rows[0].get("key") == "value", (
            "Quoted columns should be readable from embedded IRIS"
        )

        assert _embedded_journal_count(connection, migration.hash) == 1
    finally:
        _cleanup_tables(connection, (migration.target_table,))
        _cleanup_journal_entries(connection, (migration.hash,))


@pytest.mark.e2e
def test_drizzle_type_mapping_workflow(
    attached_iris_resources,
    drizzle_type_mapping_migration_file: DrizzleMigrationFile,
):
    """Validate Drizzle type mapping by round-tripping several column types."""
    container, connection = attached_iris_resources
    executor = _create_executor(connection)
    executor.create_journal_table()
    migration = drizzle_type_mapping_migration_file
    _prepare_migration_environment(connection, migration)
    try:
        result = executor.execute_migration(migration)
        assert result.success, "Type mapping migration should succeed"

        test_uuid = str(uuid.UUID("11111111-2222-3333-4444-555555555555"))
        payload = json.dumps({"message": "drizzle-e2e"})
        timestamp = "2026-01-01 12:00:00"

        with connection.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {migration.target_table} ("id", "description", "payload", "is_active", "event_time", "reference_key") VALUES (?, ?, ?, ?, ?, ?)',
                (test_uuid, "Drizzle mission", payload, 1, timestamp, test_uuid),
            )
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT "id", "description", "payload", "is_active", "event_time", "reference_key" FROM {migration.target_table}'
            )
            row = cursor.fetchone()
        assert row is not None, "Inserted row should be retrievable"

        retrieved_payload = json.loads(str(row[2]))
        assert retrieved_payload.get("message") == "drizzle-e2e", "JSON payload should round-trip"
        assert str(row[0]).lower() == test_uuid.lower(), (
            "UUID columns should store canonical strings"
        )
        assert str(row[3]).strip() in {"1", "true"}, "Boolean should map to 1 or TRUE in IRIS"
        assert "2026-01-01" in str(row[4]), "Timestamp should preserve the date portion"

        assert _embedded_journal_count(connection, migration.hash) == 1
    finally:
        _cleanup_tables(connection, (migration.target_table,))
        _cleanup_journal_entries(connection, (migration.hash,))


@pytest.mark.e2e
def test_drizzle_multiple_migrations_workflow(
    attached_iris_resources,
    drizzle_multi_migration_files: tuple[DrizzleMigrationFile, DrizzleMigrationFile],
):
    """Ensure sequential migrations are recorded once and remain idempotent."""
    container, connection = attached_iris_resources
    executor = _create_executor(connection)
    executor.create_journal_table()
    migrations = drizzle_multi_migration_files
    _cleanup_tables(connection, (m.target_table for m in migrations))
    _cleanup_journal_entries(connection, (m.hash for m in migrations))
    try:
        for migration in migrations:
            result = executor.execute_migration(migration)
            assert result.success and not result.already_applied, (
                f"Migration {migration.filename} should run once"
            )

        for migration in migrations:
            assert _embedded_journal_count(connection, migration.hash) == 1, (
                f"Journal should have single entry for {migration.filename}"
            )

        for migration in migrations:
            result = executor.execute_migration(migration)
            assert result.success and result.already_applied, (
                f"Re-applying {migration.filename} should be idempotent"
            )
            assert result.statements_executed == 0, (
                "Already applied migrations execute zero statements"
            )

        assert sum(_embedded_journal_count(connection, m.hash) for m in migrations) == len(
            migrations
        )
    finally:
        _cleanup_tables(connection, (m.target_table for m in migrations))
        _cleanup_journal_entries(connection, (m.hash for m in migrations))


@pytest.mark.e2e
def test_drizzle_migration_failure_workflow(
    attached_iris_resources,
    drizzle_failure_migration_file: DrizzleMigrationFile,
):
    """Verify that an invalid statement aborts and cleans up the entire migration."""
    container, connection = attached_iris_resources
    executor = _create_executor(connection)
    executor.create_journal_table()
    migration = drizzle_failure_migration_file
    _prepare_migration_environment(connection, migration)
    try:
        result = executor.execute_migration(migration)
        assert not result.success, "Migration should fail when invalid SQL is present"
        assert result.error, "Executor should capture the failure reason"

        assert not _table_exists(connection, migration.target_table), (
            "Failed migration should leave no tables behind"
        )
        assert _embedded_journal_count(connection, migration.hash) == 0, (
            "Journal must not record failed migrations"
        )
    finally:
        _cleanup_tables(
            connection,
            (migration.target_table, "broken_statement", "should_not_exist"),
        )
        _cleanup_journal_entries(connection, (migration.hash,))
