"""SAVEPOINT, ROLLBACK TO and RELEASE answered as PostgreSQL does (spec 052 US2).

Shared by both executors, like ``IsolationMixin``: a client cannot tell which backend it reached,
so savepoints handled in one of them are savepoints handled in neither. The stack and its rules
are in ``savepoints.py``; this module keeps one stack per session, sends the IRIS statements the
stack returns, and turns the stack's refusals into results carrying their SQLSTATE.

The host class must provide ``execute_query(sql, params=None, session_id=None, **kwargs)``.
Statements this mixin sends go back through it with ``_skip_savepoints`` and ``_skip_isolation``
set, so they are executed as written.

Outside a transaction block these statements never get here: the protocol layer refuses them
with 25P01 (``transaction_status.refusal``), because it owns the transaction status.
"""

from __future__ import annotations

from typing import Any

import structlog

from .savepoints import SavepointError, SavepointStack, parse_savepoint_statement
from .sql_translator.isolation import parse_transaction_boundary

logger = structlog.get_logger("iris_pgwire.savepoints")

_OWN_FLAGS = ("_skip_savepoints", "_skip_isolation", "original_sql")
_COMMAND_TAGS = {"savepoint": "SAVEPOINT", "rollback_to": "ROLLBACK", "release": "RELEASE"}


class SavepointMixin:
    @property
    def _savepoint_stacks(self) -> dict[str, SavepointStack]:
        """Created on first use, so a host class needs no constructor change."""
        stacks = getattr(self, "_savepoint_stacks_store", None)
        if stacks is None:
            stacks = {}
            self._savepoint_stacks_store: dict[str, SavepointStack] = stacks
        return stacks

    def live_savepoint_depth(self, session_id: str | None) -> int:
        """How many savepoints the client can still name; the 25001 rule reads this."""
        stack = self._savepoint_stacks.get(session_id) if session_id else None
        return stack.depth if stack is not None else 0

    def forget_savepoints(self, session_id: str | None) -> None:
        if session_id is not None:
            self._savepoint_stacks.pop(session_id, None)

    async def _handle_savepoint_statement(
        self, sql: str, session_id: str | None, **kwargs
    ) -> dict[str, Any] | None:
        """The reply for a savepoint statement, or None to let ``sql`` run normally.

        Also watches transaction boundaries, because every savepoint ends with its transaction.
        """
        if session_id is None:
            return None
        parsed = parse_savepoint_statement(sql)
        if parsed is None:
            if parse_transaction_boundary(sql) is not None:
                self.forget_savepoints(session_id)
            return None

        verb, name = parsed
        stack = self._savepoint_stacks.setdefault(session_id, SavepointStack())
        try:
            statements = getattr(stack, verb)(name)
        except SavepointError as e:
            logger.info(
                "Savepoint statement refused",
                verb=verb,
                sqlstate=e.sqlstate,
                error=str(e),
                session_id=session_id,
            )
            return {
                "success": False,
                "error": str(e),
                "sqlstate": e.sqlstate,
                "condition": e.condition,
                "rows": [],
                "columns": [],
                "row_count": 0,
            }

        passthrough = {k: v for k, v in kwargs.items() if k not in _OWN_FLAGS}
        for statement in statements:
            result = await self.execute_query(  # type: ignore[attr-defined]
                statement,
                session_id=session_id,
                _skip_savepoints=True,
                _skip_isolation=True,
                **passthrough,
            )
            if not result.get("success"):
                # IRIS refused what the stack expected it to accept; the stack can no longer
                # be trusted for this transaction, and the error aborts it anyway.
                logger.warning(
                    "IRIS refused a savepoint statement the stack issued",
                    statement=statement,
                    error=result.get("error"),
                    session_id=session_id,
                )
                self.forget_savepoints(session_id)
                return result

        return {
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "command_tag": _COMMAND_TAGS[verb],
            "execution_time_ms": 0.0,
        }
