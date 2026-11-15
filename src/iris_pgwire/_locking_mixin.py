"""`SELECT ... FOR UPDATE` that locks on IRIS, or is refused (spec 052 US3, research R6).

The plan comes from ``sql_translator/locking_clauses.py``: either a touch-update that locks
exactly the rows the SELECT returns, or the name of the shape it cannot lock. This mixin decides
what runs, by the transaction state and ``PGWIRE_TXN_COMPAT``:

- Inside an explicit transaction, an emulated shape runs the touch-update, then the SELECT
  without the clause. `NOWAIT` runs the touch with IRIS's lock timeout at 0 (measured: a locked
  row then fails at once with SQLCODE -110) and reports 55P03, as PostgreSQL does.
- Outside one, the statement is its own transaction and the lock would end with it: the SELECT
  runs without the clause.
- A refused shape gets 0A000 in strict mode. In permissive mode it runs as 2.0 ran it (the
  statement unchanged; IRIS ignores `FOR UPDATE`, rejects the rest), warned once per shape.

The touch is an UPDATE, so its side effects decide whether it is exact: a table with an UPDATE
trigger, or a ROWVERSION or other generated column, is refused, and so is a view. The catalog
answers are cached per table and dropped on any DDL.

The host class must provide ``config`` (a ``BackendConfig``) and ``session_transactions``.
The mode, its warnings and the catalog cache are ``compat_mode.CompatMixin``'s.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import structlog

from . import row_limit
from .compat_mode import CompatMixin
from .sql_translator.locking_clauses import LockPlan, plan_locking, refusal_message
from .sql_translator.sqlstate import LOCK_NOT_AVAILABLE

logger = structlog.get_logger("iris_pgwire.locking")

FEATURE_NOT_SUPPORTED = ("0A000", "feature_not_supported")


@contextmanager
def closing_cursor(connection: Any) -> Iterator[Any]:
    """A cursor on ``connection``, closed afterwards; a failure to close it is ignored."""
    cursor = connection.cursor()
    try:
        yield cursor
    finally:
        try:
            cursor.close()
        except Exception:
            pass


class StatementRefused(Exception):
    """A statement answered with a PostgreSQL SQLSTATE instead of being run as written."""

    def __init__(self, state: tuple[str, str], message: str):
        super().__init__(message)
        self.sqlstate, self.condition = state

    def result(self) -> dict[str, Any]:
        return {
            "success": False,
            "error": str(self),
            "sqlstate": self.sqlstate,
            "condition": self.condition,
            "rows": [],
            "columns": [],
            "row_count": 0,
        }


@dataclass(frozen=True)
class _TableFacts:
    refusal: str | None  # "view", "update_trigger", "generated_column", "no_lockable_column"
    column: str | None  # the column the touch sets to itself, quoted


class LockingMixin(CompatMixin):
    def prepare_locking(self, sql: str, session_id: str | None) -> tuple[str, LockPlan | None]:
        """What to run for ``sql``, and the touch to run first (None for no touch).

        Raises ``StatementRefused`` for a shape strict mode refuses.
        """
        plan = plan_locking(sql)
        if plan is None:
            return sql, None
        if plan.refusal is not None:
            if self.compat.permissive:
                self.permissive_warning(sql, plan.message)
                return sql, None
            raise StatementRefused(FEATURE_NOT_SUPPORTED, plan.message)
        in_transaction = bool(session_id and self.session_transactions.get(session_id))  # type: ignore[attr-defined]
        if not in_transaction or plan.table is None or row_limit.current() is not None:
            # No lock to take: autocommit (the statement's own lock ends with it), no table, or a
            # Describe, which runs the statement for its columns only; its Execute takes the lock.
            return plan.select_sql, None
        return plan.select_sql, plan

    def run_touch_sync(self, connection: Any, plan: LockPlan, params: Any, sql: str) -> None:
        """Lock the plan's rows, in the caller's transaction, on ``connection``."""
        facts = self._table_facts_sync(connection, plan)
        if facts is None:
            return  # no such table: the SELECT fails with IRIS's own error
        if facts.refusal is not None:
            message = refusal_message(facts.refusal, plan.clause_head)
            if self.compat.permissive:
                self.permissive_warning(sql, message)
                return
            raise StatementRefused(FEATURE_NOT_SUPPORTED, message)

        touch = plan.touch_sql(facts.column)
        touch_params = plan.touch_params(params)
        touch_args = (touch, touch_params) if touch_params else (touch,)
        with closing_cursor(connection) as cursor:
            if not plan.nowait:
                cursor.execute(*touch_args)
                return
            cursor.execute("SELECT %SYSTEM_SQL.Util_GetOption('ProcessLockTimeout')")
            previous = int(cursor.fetchone()[0])
            cursor.execute("SET OPTION LOCK_TIMEOUT = 0")
            try:
                cursor.execute(*touch_args)
            except Exception as e:
                text = str(e)
                if "-110" in text or "-114" in text:
                    raise StatementRefused(
                        LOCK_NOT_AVAILABLE,
                        f'could not obtain lock on row in relation "{plan.table.name.lower()}"',
                    ) from e
                raise
            finally:
                cursor.execute(f"SET OPTION LOCK_TIMEOUT = {previous}")

    def _table_facts_sync(self, connection: Any, plan: LockPlan) -> _TableFacts | None:
        table = plan.table
        return self.cached_table_fact(
            "lock",
            table.schema,
            table.name,
            lambda schema, name: self._read_table_facts(connection, schema, name),
        )

    @staticmethod
    def _read_table_facts(connection: Any, schema: str, name: str) -> _TableFacts | None:
        where = "LOWER(TABLE_SCHEMA) = ? AND LOWER(TABLE_NAME) = ?"
        with closing_cursor(connection) as cursor:
            cursor.execute(
                f"SELECT TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES WHERE {where}", (schema, name)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            if str(row[0]).upper() != "BASE TABLE":
                return _TableFacts("view", None)
            cursor.execute(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TRIGGERS "
                f"WHERE {where} AND EVENT_MANIPULATION LIKE '%UPDATE%'",
                (schema, name),
            )
            if int(cursor.fetchone()[0]):
                return _TableFacts("update_trigger", None)
            cursor.execute(
                "SELECT COLUMN_NAME, PRIMARY_KEY, IS_GENERATED, IS_IDENTITY, IS_UPDATABLE "
                f"FROM INFORMATION_SCHEMA.COLUMNS WHERE {where} ORDER BY ORDINAL_POSITION",
                (schema, name),
            )
            columns = cursor.fetchall()
        # ROWVERSION reports IS_GENERATED = 'YES' (measured); so do computed columns.
        if any(str(c[2]).upper() == "YES" for c in columns):
            return _TableFacts("generated_column", None)
        keys = [c[0] for c in columns if str(c[1]).upper() == "YES"]
        plain = [c[0] for c in columns if str(c[3]).upper() != "YES" and str(c[4]).upper() != "NO"]
        candidates = keys or plain
        if not candidates:
            return _TableFacts("no_lockable_column", None)
        return _TableFacts(None, '"' + candidates[0].replace('"', '""') + '"')
