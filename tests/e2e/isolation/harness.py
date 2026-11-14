"""Play multi-session scripts against a live server, the way Hermitage's terminals do.

Each session gets its own connection and its own worker thread, so a statement that blocks on a
lock does not stop the other sessions. ``play`` walks a script in order. Before sending a step it
waits for that session's previous statement to finish (a terminal cannot type while a statement
runs), then waits ``BLOCK_AFTER`` seconds for the new one. A statement still running then is
recorded as blocked, and the script moves on, which is what lets the other session's COMMIT
release it.

Connections run in autocommit mode, so ``begin`` and ``commit`` are the script's own statements,
sent as written. ``protocol="simple"`` sends every statement as a simple Query message, as psql
does; ``"extended"`` uses Parse/Bind/Execute, as psycopg does by default.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field

import psycopg
import pytest

from .cases import Outcome, Step, StepResult

BLOCK_AFTER = 1.0
# Longer than two IRIS lock timeouts: on the extended protocol PGWire runs a SELECT once for
# Describe and again for Execute, and each run can wait out the 10 s timeout.
STEP_DEADLINE = 35.0


@dataclass
class Target:
    name: str
    dsn: str
    reference: bool  # True for PostgreSQL itself

    def connect(self, protocol: str = "simple", autocommit: bool = True) -> psycopg.Connection:
        factory = psycopg.ClientCursor if protocol == "simple" else psycopg.Cursor
        return psycopg.connect(self.dsn, autocommit=autocommit, cursor_factory=factory)


def run_statement(conn: psycopg.Connection, sql: str, params=None) -> Outcome:
    started = time.perf_counter()
    sent = time.monotonic()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = [tuple(r) for r in cur.fetchall()] if cur.description else None
            return Outcome(
                rows=rows,
                sqlstate=None,
                message=None,
                elapsed=time.perf_counter() - started,
                status=cur.statusmessage.split()[0] if cur.statusmessage else None,
                rowcount=cur.rowcount,
                started=sent,
                finished=time.monotonic(),
                status_after=_status(conn),
            )
    except psycopg.Error as e:
        return Outcome(
            rows=None,
            sqlstate=e.sqlstate or "?????",
            message=str(e).strip().splitlines()[0][:300] if str(e).strip() else type(e).__name__,
            elapsed=time.perf_counter() - started,
            started=sent,
            finished=time.monotonic(),
            status_after=_status(conn),
        )


def _status(conn: psycopg.Connection) -> str:
    """The transaction status the server's last ReadyForQuery reported (UNKNOWN once closed)."""
    return conn.info.transaction_status.name


@dataclass
class Session:
    name: str
    conn: psycopg.Connection
    worker: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(1))
    last: Future | None = None

    def submit(self, sql: str, params=None) -> Future:
        self.last = self.worker.submit(run_statement, self.conn, sql, params)
        return self.last

    def wait_idle(self, deadline: float = STEP_DEADLINE) -> None:
        if self.last is not None:
            self.last.result(timeout=deadline)

    def close(self) -> None:
        try:
            self.wait_idle()
            run_statement(self.conn, "rollback")
        except FutureTimeout:
            pass
        finally:
            try:
                self.conn.close()
            finally:
                self.worker.shutdown(wait=False, cancel_futures=True)


def open_sessions(target: Target, names, protocol: str = "simple") -> dict[str, Session]:
    return {name: Session(name, target.connect(protocol)) for name in names}


@dataclass
class Played:
    step: Step
    result: StepResult


def play(sessions: dict[str, Session], steps) -> list[Played]:
    pending: list[tuple[Step, Future, bool]] = []
    for step in steps:
        session = sessions[step.session]
        session.wait_idle()
        future = session.submit(step.sql)
        try:
            future.result(timeout=BLOCK_AFTER)
            blocked = False
        except FutureTimeout:
            blocked = True
        pending.append((step, future, blocked))
    return [
        Played(step, StepResult(future.result(timeout=STEP_DEADLINE), blocked))
        for step, future, blocked in pending
    ]


def with_table(sql: str, table: str) -> str:
    """Hermitage's scripts name their table ``test``; each target gets its own name."""
    return re.sub(r"\btest\b", table, sql)


# Spec 052 FR-004: the aborted-transaction rule and the savepoint stack must not change under
# PGWIRE_TXN_COMPAT=permissive. Checks decorated with this run once in `make isolation` and again
# in `make isolation-permissive` (the second parameter carries the `permissive` marker).
BOTH_SERVERS = pytest.mark.parametrize(
    "server", ["default", pytest.param("permissive", marks=pytest.mark.permissive)]
)
