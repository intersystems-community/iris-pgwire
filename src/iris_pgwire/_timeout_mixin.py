"""SET / RESET / SHOW of `lock_timeout` and `statement_timeout` (spec 052 US5, research R8).

`lock_timeout` becomes IRIS's `SET OPTION LOCK_TIMEOUT = n` on the session's connection, in
whole seconds rounded up; `0` and `RESET` send the server's default wait (measured: the option is
per connection and outlives COMMIT and ROLLBACK, so the pool's reset restores it on close). A
lock timeout in a session whose client set `lock_timeout` is PostgreSQL's 55P03; the server's
default wait stays 40001. `statement_timeout` is recorded for SHOW and not enforced, which is
logged once per session.

The host class must provide ``execute_query``; this mixin's own statements go back through it
with ``_skip_timeouts``, ``_skip_savepoints`` and ``_skip_isolation`` set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from .sql_translator.sqlstate import LOCK_NOT_AVAILABLE
from .sql_translator.timeouts import (
    TimeoutValueError,
    iris_lock_timeout_seconds,
    parse_timeout_ms,
    parse_timeout_statement,
    show_timeout,
)

logger = structlog.get_logger("iris_pgwire.timeouts")

_IRIS_LOCK_TIMEOUT = re.compile(r"SQLCODE:\s*<-11[04]>")
_OWN = {"_skip_timeouts": True, "_skip_savepoints": True, "_skip_isolation": True}


def lock_timeout_sqlstate(
    sqlstate: str, message: str, client_set_lock_timeout: bool
) -> tuple[str, str | None]:
    """55P03 for an IRIS lock timeout the client asked for (FR-019); the state unchanged otherwise."""
    if client_set_lock_timeout and sqlstate == "40001" and _IRIS_LOCK_TIMEOUT.search(message or ""):
        return LOCK_NOT_AVAILABLE
    return sqlstate, None


@dataclass
class _SessionTimeouts:
    values_ms: dict[str, int] = field(default_factory=dict)
    warned_statement_timeout: bool = False


class TimeoutMixin:
    @property
    def _timeout_sessions(self) -> dict[str, _SessionTimeouts]:
        store = getattr(self, "_timeout_sessions_store", None)
        if store is None:
            store = {}
            self._timeout_sessions_store: dict[str, _SessionTimeouts] = store
        return store

    @property
    def statement_timeout_warnings(self) -> int:
        return getattr(self, "_statement_timeout_warnings", 0)

    def lock_timeout_set(self, session_id: str | None) -> bool:
        state = self._timeout_sessions.get(session_id) if session_id else None
        return bool(state and state.values_ms.get("lock_timeout"))

    def session_lock_timeout_seconds(self, session_id: str | None) -> int | None:
        """The IRIS seconds this session's client asked for, or None for the server default."""
        state = self._timeout_sessions.get(session_id) if session_id else None
        return iris_lock_timeout_seconds(state.values_ms.get("lock_timeout", 0)) if state else None

    def forget_timeouts(self, session_id: str | None) -> None:
        if session_id is not None:
            self._timeout_sessions.pop(session_id, None)

    async def server_lock_timeout(self, session_id: str | None, **kwargs) -> int:
        """IRIS's default wait in seconds (`[SQL] LockTimeout`), read once."""
        cached = getattr(self, "_server_lock_timeout", None)
        if cached is None:
            result = await self.execute_query(  # type: ignore[attr-defined]
                "SELECT %SYSTEM_SQL.Util_GetOption('LockTimeout')",
                session_id=session_id,
                **_OWN,
                **kwargs,
            )
            rows = result.get("rows") or []
            cached = int(rows[0][0]) if result.get("success") and rows else 10
            self._server_lock_timeout = cached
        return cached

    async def _handle_timeout_statement(
        self, sql: str, session_id: str | None, **kwargs
    ) -> dict[str, Any] | None:
        parsed = parse_timeout_statement(sql)
        if parsed is None or session_id is None:
            return None
        verb, name, raw = parsed
        state = self._timeout_sessions.setdefault(session_id, _SessionTimeouts())
        if verb == "show":
            return _show_result(name, show_timeout(state.values_ms.get(name, 0)))
        try:
            ms = 0 if verb == "reset" else parse_timeout_ms(raw, name)
        except TimeoutValueError as e:
            return {
                "success": False,
                "error": str(e),
                "sqlstate": e.sqlstate,
                "condition": e.condition,
                "rows": [],
                "columns": [],
                "row_count": 0,
            }
        passthrough = {k: v for k, v in kwargs.items() if k not in _OWN and k != "original_sql"}
        if name == "lock_timeout":
            seconds = iris_lock_timeout_seconds(ms)
            if seconds is None:
                seconds = await self.server_lock_timeout(session_id, **passthrough)
            result = await self.execute_query(  # type: ignore[attr-defined]
                f"SET OPTION LOCK_TIMEOUT = {seconds}", session_id=session_id, **_OWN, **passthrough
            )
            if not result.get("success"):
                return result
        elif not state.warned_statement_timeout:
            state.warned_statement_timeout = True
            self._statement_timeout_warnings = self.statement_timeout_warnings + 1
            logger.warning(
                "statement_timeout is accepted but not enforced on IRIS",
                value=show_timeout(ms),
                session_id=session_id,
            )
        if ms:
            state.values_ms[name] = ms
        else:
            state.values_ms.pop(name, None)
        return {
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "command_tag": "RESET" if verb == "reset" else "SET",
            "execution_time_ms": 0.0,
        }


def _show_result(name: str, value: str) -> dict[str, Any]:
    return {
        "success": True,
        "rows": [[value]],
        "columns": [
            {"name": name, "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0}
        ],
        "row_count": 1,
        "command_tag": "SHOW",
        "execution_time_ms": 0.0,
    }
