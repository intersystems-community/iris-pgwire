"""Transaction isolation level handling, shared by both backends.

This lives in a mixin rather than in either executor because the two backends
have different code paths to IRIS and a client cannot tell which one it is
talking to. Isolation handled in only one of them is isolation handled in none:
the embedded backend serves `iris session`-style execution while DBAPI serves
`intersystems-irispython`, and the pgwire server picks between them by config.

The parsing and the measured IRIS support table are in
sql_translator/isolation.py; this module is only the wiring and the per-session
bookkeeping.

Two settings, not one. `transaction_isolation` is the level the current
transaction runs at and `default_transaction_isolation` is what the next one
starts at, and PostgreSQL's spellings write one or the other — see the measured
table in tests/unit/test_isolation_scopes.py. IRIS has a single level per
session, so the two slots are kept here and IRIS is told whichever one is in
force; `_resync_iris` is what keeps that promise when the level changes because
a transaction ended rather than because a client asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from .sql_translator.isolation import (
    DEFAULT_ISOLATION_LEVEL,
    MID_TRANSACTION_AFTER_QUERY,
    MID_TRANSACTION_CONDITION,
    MID_TRANSACTION_IN_SUBTRANSACTION,
    MID_TRANSACTION_SQLSTATE,
    SESSION_SCOPE,
    counts_as_query,
    parse_begin_isolation,
    parse_isolation_show,
    parse_savepoint_change,
    parse_set_isolation,
    parse_transaction_boundary,
)

logger = structlog.get_logger("iris_pgwire.isolation")


@dataclass
class _SessionIsolation:
    """The per-session state that is not the session default.

    The session default lives in the host class's ``session_isolation`` dict,
    which predates this and is read by name elsewhere. Everything else is here.
    """

    # The transaction-scoped level, in force until the transaction ends.
    override: str | None = None
    # The level IRIS was last told, so a divergence can be noticed and repaired.
    iris_level: str | None = None
    # Whether a transaction is open, which decides whether a session-default
    # change is undoable and whether a resync would land mid-transaction.
    in_transaction: bool = False
    # The session default as it was when this transaction opened, kept only once
    # and only if the transaction changed it — PostgreSQL rolls `SET` back too.
    default_before_transaction: str | None = None
    default_changed_in_transaction: bool = False
    # Whether this transaction has read anything, after which its level can no
    # longer be changed, and how deep it is in savepoints, which is the same rule
    # for a different reason.
    transaction_did_query: bool = False
    savepoint_depth: int = 0


class IsolationMixin:
    """`SET`/`SHOW TRANSACTION ISOLATION LEVEL` against real IRIS state.

    The host class must provide an awaitable
    ``execute_query(sql, params=None, session_id=None, **kwargs)`` and must
    create ``self.session_isolation`` in its ``__init__``.
    """

    session_isolation: dict[str, str]

    # ------------------------------------------------------------------
    # Per-session state
    # ------------------------------------------------------------------

    @property
    def _isolation_sessions(self) -> dict[str, _SessionIsolation]:
        """Created on first use, so a host class only has to know about one dict."""
        store = getattr(self, "_isolation_sessions_store", None)
        if store is None:
            store = {}
            self._isolation_sessions_store: dict[str, _SessionIsolation] = store
        return store

    def _isolation_state(self, session_id: str) -> _SessionIsolation:
        return self._isolation_sessions.setdefault(session_id, _SessionIsolation())

    def get_isolation_level(self, session_id: str | None) -> str:
        """`transaction_isolation`: the level this session is running at now.

        The transaction's own level if it has one, else the session default, else
        READ UNCOMMITTED — which is what IRIS runs at until told otherwise, not
        PostgreSQL's READ COMMITTED default.
        """
        if session_id is None:
            return DEFAULT_ISOLATION_LEVEL
        state = self._isolation_sessions.get(session_id)
        if state is not None and state.override is not None:
            return state.override
        return self.get_default_isolation_level(session_id)

    def get_default_isolation_level(self, session_id: str | None) -> str:
        """`default_transaction_isolation`: what the next transaction starts at.

        Deliberately blind to the current transaction's override. A pool asking
        this is asking what it handed out, and answering with a level that ends
        at the next COMMIT would be the wrong answer to that question.
        """
        if session_id is None:
            return DEFAULT_ISOLATION_LEVEL
        return self.session_isolation.get(session_id, DEFAULT_ISOLATION_LEVEL)

    def forget_isolation_level(self, session_id: str | None) -> None:
        """Drop a closed session's state so the dicts cannot grow without bound.

        Both slots, because session ids are reused: a leftover override would be
        the previous client's, and would be resynced onto IRIS as if asked for.
        """
        if session_id is not None:
            self.session_isolation.pop(session_id, None)
            self._isolation_sessions.pop(session_id, None)

    # ------------------------------------------------------------------
    # Statement handling
    # ------------------------------------------------------------------

    def _isolation_result(self, guc: str, level: str) -> dict[str, Any]:
        """A one-row, one-column SHOW reply carrying `level`."""
        return {
            "success": True,
            "rows": [[level]],
            "columns": [
                {
                    "name": guc,
                    "type_oid": 25,  # TEXT
                    "type_size": -1,
                    "type_modifier": -1,
                    "format_code": 0,
                }
            ],
            "row_count": 1,
            "command_tag": "SHOW",
            "execution_time_ms": 0.0,
        }

    async def _handle_isolation_statement(
        self, sql: str, session_id: str | None = None, **kwargs
    ) -> dict[str, Any] | None:
        """Handle isolation-level SET and SHOW, or return None to pass `sql` on.

        Called before the SQL interceptor in both executors, because the
        interceptor's generic SHOW handler answers anything it does not
        recognise with the literal string "unknown". Being on the path of every
        statement is also what lets the transaction boundary be seen, which is
        where a transaction-scoped level ends.

        A supported SET is executed against IRIS for real and the session's level
        is recorded only once IRIS has accepted it, so `SHOW` can never report a
        level that was not applied. An unsupported one is refused — see
        sql_translator/isolation.py for why it is not downgraded instead.
        """
        guc = parse_isolation_show(sql)
        if guc is not None:
            level = (
                self.get_default_isolation_level(session_id)
                if guc == "default_transaction_isolation"
                else self.get_isolation_level(session_id)
            )
            return self._isolation_result(guc, level)

        request = parse_set_isolation(sql)
        if request is not None:
            if not request.supported:
                # The level is checked before the timing, which is the order
                # PostgreSQL measurably uses: an unusable level is refused on its
                # own terms whether or not it arrived too late.
                return self._refuse(request, session_id)
            too_late = self._too_late_to_change(request, session_id)
            if too_late is not None:
                return too_late
            return await self._apply(request, session_id, **kwargs)

        # `BEGIN ISOLATION LEVEL x` is the same request in the spelling psycopg3
        # sends, and it must be refused and recorded the same way — otherwise a
        # client routes around the refusal by naming the level on BEGIN instead.
        request = parse_begin_isolation(sql)
        if request is not None:
            if not request.supported:
                # Refused before the transaction starts, so the session is left
                # where it was rather than inside a transaction it did not ask for.
                return self._refuse(request, session_id)

            self._note_transaction_boundary("start", session_id)
            # Still one statement, in IRIS's spelling of it — `BEGIN` is not IRIS
            # SQL and this interception happens ahead of the translator that would
            # have rewritten it. The request carries the tag for the verb the
            # client actually used, so the rewrite stays invisible in the reply.
            return await self._apply(request, session_id, **kwargs)

        boundary = parse_transaction_boundary(sql)
        if boundary == "start":
            # Before the transaction opens is the last moment IRIS's level can be
            # corrected, since changing it inside a transaction is what PostgreSQL
            # refuses. A transaction that inherited the wrong level would run at it
            # from its first statement to its last.
            failed = await self._resync_iris(session_id, **kwargs)
            if failed is not None:
                return failed
            self._note_transaction_boundary(boundary, session_id)
            # Not our statement: the BEGIN itself still has to reach IRIS.
            return None

        if boundary is not None:
            self._note_transaction_boundary(boundary, session_id)
            return None

        self._note_ordinary_statement(sql, session_id)
        return await self._resync_iris(session_id, **kwargs)

    def _refuse(self, request, session_id: str | None) -> dict[str, Any]:
        """The error reply for a level IRIS cannot honour."""
        logger.info(
            "Refusing unsupported transaction isolation level",
            requested_level=request.level,
            session_id=session_id,
        )
        return {
            "success": False,
            "error": request.message,
            "sqlstate": request.sqlstate,
            "rows": [],
            "columns": [],
            "row_count": 0,
        }

    async def _apply(self, request, session_id: str | None, **kwargs) -> dict[str, Any]:
        """Send the request's IRIS statement and record the level only if IRIS took it."""
        # `_skip_isolation` stops this from recursing on the statement we send.
        result = await self.execute_query(  # type: ignore[attr-defined]
            request.iris_sql, session_id=session_id, _skip_isolation=True, **kwargs
        )
        if result.get("success") and session_id is not None:
            self._record_applied(request, session_id)
        if request.command_tag is not None:
            result["command_tag"] = request.command_tag
        return result

    def _record_applied(self, request, session_id: str) -> None:
        """Write the accepted level into the slot its spelling names."""
        state = self._isolation_state(session_id)
        state.iris_level = request.level

        if request.scope == SESSION_SCOPE:
            if state.in_transaction and not state.default_changed_in_transaction:
                # Snapshot once: a ROLLBACK restores the value from before the
                # transaction, not from before the most recent SET inside it.
                state.default_before_transaction = self.session_isolation.get(session_id)
                state.default_changed_in_transaction = True
            self.session_isolation[session_id] = request.level
            # The default is what the current transaction runs at too, unless the
            # transaction named its own level — so an override still wins.
        else:
            state.override = request.level

        logger.info(
            "Transaction isolation level applied",
            level=request.level,
            scope=request.scope,
            session_id=session_id,
        )

    def _too_late_to_change(self, request, session_id: str | None) -> dict[str, Any] | None:
        """The 25001 reply if this transaction is past changing its level, else None.

        Only the transaction-scoped spellings can be too late; the session-scoped
        ones describe the next transaction. Re-asserting the level already in
        force is always allowed, measured on PostgreSQL 16 and relied on by every
        client that restates its isolation level defensively.
        """
        if session_id is None or request.scope == SESSION_SCOPE:
            return None
        state = self._isolation_sessions.get(session_id)
        if state is None or not state.in_transaction:
            return None
        if request.level == self.get_isolation_level(session_id):
            return None

        # Savepoints are answered by SavepointMixin before this mixin sees them (spec 052), so
        # its stack is the live depth; the local counter remains for hosts without it.
        live_depth = getattr(self, "live_savepoint_depth", lambda _sid: 0)(session_id)
        if state.savepoint_depth > 0 or live_depth > 0:
            message = MID_TRANSACTION_IN_SUBTRANSACTION
        elif state.transaction_did_query:
            message = MID_TRANSACTION_AFTER_QUERY
        else:
            return None

        logger.info(
            "Refusing a mid-transaction isolation level change",
            requested_level=request.level,
            current_level=self.get_isolation_level(session_id),
            session_id=session_id,
        )
        # Not recorded and not sent: the transaction keeps the level it has, and
        # `SHOW` keeps reporting it.
        return {
            "success": False,
            "error": message,
            "sqlstate": MID_TRANSACTION_SQLSTATE,
            "condition": MID_TRANSACTION_CONDITION,
            "rows": [],
            "columns": [],
            "row_count": 0,
        }

    def _note_ordinary_statement(self, sql: str, session_id: str | None) -> None:
        """Track what an open transaction has done, which decides the 25001 above."""
        if session_id is None:
            return
        savepoint = parse_savepoint_change(sql)
        if savepoint is not None:
            state = self._isolation_state(session_id)
            if not state.in_transaction:
                # A stray savepoint statement outside a transaction; PostgreSQL
                # has nothing to nest and neither have we.
                return
            if savepoint == "enter":
                state.savepoint_depth += 1
            else:
                state.savepoint_depth = max(0, state.savepoint_depth - 1)
            return

        if not counts_as_query(sql):
            return
        state = self._isolation_sessions.get(session_id)
        if state is not None and state.in_transaction:
            state.transaction_did_query = True

    def _note_transaction_boundary(self, boundary: str, session_id: str | None) -> None:
        """Open or close the window a transaction-scoped level lives in."""
        if session_id is None:
            return
        state = self._isolation_state(session_id)

        if boundary == "start":
            state.in_transaction = True
            return

        if boundary == "rollback" and state.default_changed_in_transaction:
            # Measured on PostgreSQL 16: a session default set inside a
            # transaction that rolls back never happened. Savepoints are not
            # modelled — a partial rollback keeps the whole change.
            previous = state.default_before_transaction
            if previous is None:
                self.session_isolation.pop(session_id, None)
            else:
                self.session_isolation[session_id] = previous

        state.override = None
        state.in_transaction = False
        state.default_before_transaction = None
        state.default_changed_in_transaction = False
        state.transaction_did_query = False
        state.savepoint_depth = 0

    async def _resync_iris(self, session_id: str | None, **kwargs) -> dict[str, Any] | None:
        """Put IRIS back on the level we report, or return None to carry on.

        The slots are bookkeeping and IRIS has one level per session, so ending a
        transaction that had its own level changes what we report without any
        statement having said so. Left alone, `SHOW` would go back to naming a
        level the session is not running at, which is the whole defect this
        module exists to fix — arriving by a different route.

        An error here is returned to the client rather than swallowed: carrying on
        would mean running the statement at a level we are about to misreport.
        """
        if session_id is None:
            return None
        state = self._isolation_sessions.get(session_id)
        if state is None or state.iris_level is None or state.in_transaction:
            return None

        wanted = self.get_isolation_level(session_id)
        if wanted == state.iris_level:
            return None

        request = parse_set_isolation(f"SET TRANSACTION ISOLATION LEVEL {wanted}")
        if request is None or not request.supported:  # pragma: no cover - defensive
            return None

        logger.info(
            "Resyncing IRIS to the level now in force",
            was=state.iris_level,
            now=wanted,
            session_id=session_id,
        )
        result = await self.execute_query(  # type: ignore[attr-defined]
            request.iris_sql, session_id=session_id, _skip_isolation=True, **kwargs
        )
        if not result.get("success"):
            return result

        state.iris_level = wanted
        return None
