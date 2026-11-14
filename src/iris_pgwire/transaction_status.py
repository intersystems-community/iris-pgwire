"""The aborted-transaction rule (spec 052 US1), as a pure state machine.

PostgreSQL aborts a transaction block on any error. Until the block ends, ReadyForQuery reports
``E``, every statement except one that ends or repairs the transaction is refused with 25P02,
and COMMIT rolls the transaction back. IRIS has no such state: it undoes the failed statement
alone and carries on, so before 2.1 a COMMIT after an error committed the work around it.

The protocol layer owns the status byte (it is what ReadyForQuery sends) and asks this module
what each event does to it. Nothing here touches IRIS, so the rule is the same on both backends.
The transitions are specs/052-postgres-transaction-semantics/data-model.md "Transaction status".
"""

from __future__ import annotations

import re

from .savepoints import parse_savepoint_statement
from .sql_translator.sqlstate import IN_FAILED_SQL_TRANSACTION, NO_ACTIVE_SQL_TRANSACTION

IDLE = b"I"
IN_TRANSACTION = b"T"
FAILED = b"E"

# PostgreSQL's message for 25P02, verbatim: clients log it and people search for it.
ABORTED_MESSAGE = "current transaction is aborted, commands ignored until end of transaction block"

_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_BEGIN = re.compile(r"(?:BEGIN|START\s+TRANSACTION)\b.*", re.I | re.S)
_END = re.compile(r"(?:COMMIT|END|ROLLBACK|ABORT)(?:\s+(?:WORK|TRANSACTION))?", re.I)
_ROLLBACK_TO = re.compile(r"ROLLBACK(?:\s+(?:WORK|TRANSACTION))?\s+TO\b", re.I)
_SAVEPOINT_VERBS = {
    "savepoint": "SAVEPOINT",
    "rollback_to": "ROLLBACK TO SAVEPOINT",
    "release": "RELEASE SAVEPOINT",
}


def _normalise(sql: str) -> str:
    return _COMMENTS.sub(" ", sql or "").strip().rstrip(";").strip()


def is_exit_statement(sql: str) -> bool:
    """COMMIT, ROLLBACK or ROLLBACK TO, in any spelling: the statements an aborted block takes."""
    text = _normalise(sql)
    return _END.fullmatch(text) is not None or _ROLLBACK_TO.match(text) is not None


def refusal(status: bytes, sql: str) -> tuple[str, str, str] | None:
    """``(sqlstate, condition, message)`` if ``sql`` must be refused in this state, else None."""
    if status == FAILED and not is_exit_statement(sql):
        return (*IN_FAILED_SQL_TRANSACTION, ABORTED_MESSAGE)
    if status == IDLE:
        parsed = parse_savepoint_statement(sql)
        if parsed is not None:
            verb = _SAVEPOINT_VERBS[parsed[0]]
            return (*NO_ACTIVE_SQL_TRANSACTION, f"{verb} can only be used in transaction blocks")
    return None


def after_success(status: bytes, sql: str) -> bytes:
    """The status after ``sql`` succeeded, for statements that reach the executor.

    The plain BEGIN/COMMIT/ROLLBACK spellings are answered by the protocol layer itself, but
    `BEGIN ISOLATION LEVEL ...` and `ROLLBACK TO` go through the executor, and before 2.1 a
    transaction opened that way left ReadyForQuery at idle.
    """
    text = _normalise(sql)
    if _ROLLBACK_TO.match(text):
        return after_rollback_to(status, True)
    if _BEGIN.fullmatch(text):
        return IN_TRANSACTION
    if _END.fullmatch(text):
        return IDLE
    return status


def after_error(status: bytes) -> bytes:
    """Any ERROR inside a transaction block aborts it; outside one it changes nothing."""
    return FAILED if status == IN_TRANSACTION else status


def commit_rolls_back(status: bytes) -> bool:
    """COMMIT of an aborted transaction is a ROLLBACK, and is reported as one."""
    return status == FAILED


def after_rollback_to(status: bytes, succeeded: bool) -> bytes:
    """A successful ROLLBACK TO an established savepoint makes an aborted block usable again."""
    if status == FAILED and succeeded:
        return IN_TRANSACTION
    return status
