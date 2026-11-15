"""INSERT ... ON CONFLICT on IRIS: exactly, or refused (spec 052 US4, research R7).

``sql_translator/on_conflict.py`` decides whether IRIS's INSERT OR UPDATE expresses the statement,
given the table's unique keys, which this mixin reads from the catalog and caches until DDL.

- The exact form runs as INSERT OR UPDATE, atomically, in one statement.
- Every other form, DO NOTHING included, is refused with 0A000 in strict mode.
- In permissive mode it runs PGWire's 2.0 emulation (insert, catch the unique violation, update or
  do nothing), now deciding "was it the conflict?" by SQLCODE -119 on the target's columns, read
  from IRIS's message (`Field(s) k=1`), never by the message's wording (FR-015, FR-017). Any other
  error reaches the client, and so does the DBAPI driver's "<LIST ERROR>", which carries no SQLCODE
  (FR-016).

The host class must provide ``config`` (a ``BackendConfig``).
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from ._locking_mixin import FEATURE_NOT_SUPPORTED, StatementRefused, closing_cursor
from .compat_mode import CompatMixin
from .sql_translator.on_conflict import TableKeys, classify_on_conflict
from .sql_translator.returning_plan import ReturningPlan

_INSERT_TABLE = re.compile(
    r'^\s*INSERT\s+INTO\s+(?:("?)(?P<schema>\w+)\1\s*\.\s*)?"?(?P<table>\w+)"?', re.IGNORECASE
)
_UNIQUE_119 = re.compile(r"SQLCODE:\s*<-119>")
_FIELDS = re.compile(r"Field\(s\)\s+(?P<fields>[^;>\]]*)")


def conflict_fields(error: Exception) -> set[str] | None:
    """The columns of the unique key an IRIS -119 names, lower case; None if it is not a -119.

    An empty set means a -119 whose message lists no fields: a unique violation on an unknown key.
    """
    message = str(error)
    if not _UNIQUE_119.search(message):
        return None
    found = _FIELDS.search(message)
    if not found:
        return set()
    return {
        part.split("=", 1)[0].strip().strip('"').lower()
        for part in found.group("fields").split(",")
        if "=" in part
    }


class OnConflictMixin(CompatMixin):
    def plan_on_conflict_sync(
        self, connection: Any, plan: ReturningPlan, sql: str
    ) -> ReturningPlan:
        """The plan to execute for an INSERT ... ON CONFLICT; raises StatementRefused in strict mode."""
        keys = self._table_keys_sync(connection, sql)
        if keys is None:
            return plan  # no such table: the INSERT fails with IRIS's own error
        decision = classify_on_conflict(plan, keys)
        if decision is None:
            return plan
        if decision.form == "exact":
            return dataclasses.replace(
                plan,
                stripped_sql=decision.sql,
                on_conflict_clause=None,
                conflict_action=None,
                conflict_set_clause=None,
                conflict_where_clause=None,
            )
        if self.compat.permissive:
            self.permissive_warning(sql, decision.message)
            return plan
        raise StatementRefused(FEATURE_NOT_SUPPORTED, decision.message)

    @staticmethod
    def is_target_conflict(plan: ReturningPlan, fields: set[str] | None) -> bool:
        """Whether a failed insert's error is the conflict the clause names (FR-015, FR-017)."""
        if fields is None:
            return False  # not a unique violation: a foreign key, the driver's <LIST ERROR>, ...
        if not plan.conflict_target_columns:
            return True  # `ON CONFLICT DO NOTHING`: any unique violation
        return bool(fields) and fields == set(plan.conflict_target_columns)

    def _table_keys_sync(self, connection: Any, sql: str) -> TableKeys | None:
        found = _INSERT_TABLE.match(sql)
        if not found:
            return None
        return self.cached_table_fact(
            "on_conflict",
            found.group("schema"),
            found.group("table"),
            lambda schema, table: self._read_table_keys(connection, schema, table),
        )

    @staticmethod
    def _read_table_keys(connection: Any, schema: str, table: str) -> TableKeys | None:
        with closing_cursor(connection) as cursor:
            cursor.execute(
                "SELECT t.CONSTRAINT_NAME, k.COLUMN_NAME "
                "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS t "
                "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k ON k.CONSTRAINT_NAME = t.CONSTRAINT_NAME "
                "AND k.TABLE_SCHEMA = t.TABLE_SCHEMA AND k.TABLE_NAME = t.TABLE_NAME "
                "WHERE LOWER(t.TABLE_SCHEMA) = ? AND LOWER(t.TABLE_NAME) = ? "
                "AND t.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'UNIQUE')",
                (schema, table),
            )
            constraints: dict[str, set[str]] = {}
            for name, column in cursor.fetchall():
                constraints.setdefault(name, set()).add(str(column).lower())
            cursor.execute(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE LOWER(TABLE_SCHEMA) = ? AND LOWER(TABLE_NAME) = ? ORDER BY ORDINAL_POSITION",
                (schema, table),
            )
            columns = tuple(str(row[0]).lower() for row in cursor.fetchall())
        if not columns:
            return None
        unique = tuple(dict.fromkeys(frozenset(c) for c in constraints.values()))
        return TableKeys(unique_keys=unique, columns=columns)
