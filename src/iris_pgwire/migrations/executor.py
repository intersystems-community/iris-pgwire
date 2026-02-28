"""Migration executor helpers for Drizzle migrations."""

from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..config import DDLTranslationConfig
from ..sql_translator.ddl_parser import DDLParser
from ..sql_translator.ddl_translator import DDLTranslator

MigrationFile = Any


@dataclass(frozen=True)
class MigrationResult:
    """Outcome for a single migration execution attempt."""

    migration_file: MigrationFile
    success: bool
    statements_executed: int = 0
    already_applied: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)
    execution_time_ms: float = 0.0
    error: str | None = None


class MigrationExecutor:
    """Executes pending Drizzle migrations against IRIS."""

    def __init__(self, connection: Any, config: DDLTranslationConfig | None = None) -> None:
        """Initialize executor state with an IRIS DBAPI connection."""
        self._connection = connection
        self._transaction_active = False
        self._config = config or DDLTranslationConfig()

    def create_journal_table(self) -> None:
        """Ensure the migration journal table exists before applying migrations."""

        if self._journal_table_exists():
            return

        create_table_sql = """
        CREATE TABLE __drizzle_migrations (
            id INTEGER NOT NULL IDENTITY(1,1) PRIMARY KEY,
            hash VARCHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        with self._cursor() as cursor:
            cursor.execute(create_table_sql)

    def is_migration_applied(self, migration_hash: str) -> bool:
        """Return True if the journal already contains the supplied migration hash."""

        lookup_sql = "SELECT 1 FROM __drizzle_migrations WHERE hash = ?"
        with self._cursor() as cursor:
            cursor.execute(lookup_sql, (migration_hash,))
            return cursor.fetchone() is not None

    def record_migration(self, migration_file: "MigrationFile") -> None:
        """Record a successfully applied migration in the journal."""

        migration_hash = self._get_migration_hash(migration_file)
        insert_sql = (
            "INSERT INTO __drizzle_migrations (hash, created_at) VALUES (?, CURRENT_TIMESTAMP)"
        )

        with self._cursor() as cursor:
            cursor.execute(insert_sql, (migration_hash,))

    def _begin_transaction(self) -> None:
        """Begin an IRIS transaction if one is not already active."""

        if self._transaction_active:
            return

        # IRIS requires explicit START TRANSACTION for rollback to work
        with self._cursor() as cursor:
            cursor.execute("START TRANSACTION")

        self._transaction_active = True

    def _commit_transaction(self) -> None:
        """Commit the active transaction, if any."""

        if not self._transaction_active:
            return

        # Use DBAPI commit method
        self._connection.commit()
        self._transaction_active = False

    def _rollback_transaction(self) -> None:
        """Rollback the active transaction, if any."""

        if not self._transaction_active:
            return

        # Use DBAPI rollback method
        self._connection.rollback()
        self._transaction_active = False

    def _journal_table_exists(self) -> bool:
        """Return True when the journal table is already present in the catalog."""

        check_sql = "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?"
        with self._cursor() as cursor:
            cursor.execute(check_sql, ("__DRIZZLE_MIGRATIONS",))
            return cursor.fetchone() is not None

    def _get_migration_hash(self, migration_file: "MigrationFile") -> str:
        """Retrieve the hash/ checksum used for journal bookkeeping."""

        for attribute in ("hash", "checksum"):
            value = getattr(migration_file, attribute, None)
            if value:
                return str(value)

        content = getattr(migration_file, "content", None)
        if isinstance(content, bytes):
            payload = content
        elif isinstance(content, str):
            payload = content.encode("utf-8")
        else:
            payload = None

        if payload:
            return hashlib.sha256(payload).hexdigest()

        raise AttributeError(
            "MigrationFile must expose a 'hash', 'checksum', or 'content' attribute"
        )

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        """Yield a database cursor and ensure it is closed."""

        cursor = self._connection.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def _acquire_lock(self, timeout_seconds: int = 30) -> None:
        """Acquire an exclusive lock on the migration journal table."""

        with self._cursor() as cursor:
            # Try to set lock timeout (PostgreSQL syntax - IRIS doesn't support this)
            try:
                cursor.execute(f"SET SESSION LOCK_TIMEOUT = {timeout_seconds}")
            except Exception:
                # IRIS doesn't support SET SESSION, skip it
                pass
            cursor.execute("LOCK TABLE __drizzle_migrations IN EXCLUSIVE MODE")

    def _release_lock(self) -> None:
        """Release lock placeholder - lock releases at transaction end."""

        # IRIS releases table locks automatically on COMMIT/ROLLBACK
        return

    def execute_migration(self, migration_file: "MigrationFile") -> MigrationResult:
        """Run a single migration file within an exclusive lock and transaction."""

        start_time = time.perf_counter()
        warnings: list[str] = []
        statements_executed = 0
        migration_hash = self._get_migration_hash(migration_file)
        lock_acquired = False

        try:
            self._acquire_lock(self._config.lock_timeout_seconds)
            lock_acquired = True

            if self.is_migration_applied(migration_hash):
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return MigrationResult(
                    migration_file=migration_file,
                    success=True,
                    already_applied=True,
                    statements_executed=0,
                    warnings=tuple(warnings),
                    execution_time_ms=elapsed_ms,
                )

            self._begin_transaction()
            parser = DDLParser()
            translator = DDLTranslator(self._config)

            statements = getattr(migration_file, "statements", None)
            if statements is None:
                content = getattr(migration_file, "content", "")
                statements = [content] if content else []

            for sql_statement in statements:
                if not sql_statement:
                    continue
                parsed_statements = parser.parse(sql_statement)
                if not parsed_statements:
                    # The DDL parser couldn't recognize the statement — strip
                    # comments and execute it raw so the database can reject it
                    # if it is invalid (e.g. CREATE TAABLE typos).
                    import re

                    raw_sql = re.sub(r"--[^\n]*", "", sql_statement).strip().rstrip(";").strip()
                    if raw_sql:
                        with self._cursor() as cursor:
                            cursor.execute(raw_sql)
                        statements_executed += 1
                    continue
                for parsed in parsed_statements:
                    translated = translator.translate_statement(parsed)
                    warnings.extend(translated.translation_warnings)
                    if not translated.is_translatable:
                        reason = translated.skip_reason or "Statement not translatable"
                        raise RuntimeError(reason)

                    translated_sql = translated.translated_sql
                    if not translated_sql:
                        continue

                    with self._cursor() as cursor:
                        cursor.execute(translated_sql)

                    statements_executed += 1

            self.record_migration(migration_file)
            self._commit_transaction()

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return MigrationResult(
                migration_file=migration_file,
                success=True,
                statements_executed=statements_executed,
                warnings=tuple(warnings),
                execution_time_ms=elapsed_ms,
            )

        except Exception as error:
            if self._transaction_active:
                self._rollback_transaction()

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return MigrationResult(
                migration_file=migration_file,
                success=False,
                statements_executed=statements_executed,
                warnings=tuple(warnings),
                execution_time_ms=elapsed_ms,
                error=str(error),
            )

        finally:
            if lock_acquired:
                self._release_lock()


__all__ = ["MigrationExecutor", "MigrationResult"]
