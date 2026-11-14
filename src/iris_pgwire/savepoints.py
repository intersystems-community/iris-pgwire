"""PGWire's own savepoint stack (spec 052 US2), mapped onto IRIS savepoints.

PostgreSQL's savepoints and IRIS's differ in three ways, all measured against IRIS 2026.2
(specs/052-postgres-transaction-semantics/research.md R4):

- IRIS has no RELEASE (SQLCODE -51). PostgreSQL clients release every savepoint they do not roll
  back to; psycopg's nested ``transaction()`` does it on every normal exit.
- IRIS deletes a savepoint when it is rolled back to. PostgreSQL keeps it, so a second
  ``ROLLBACK TO`` the same name works there and fails (-375) on IRIS.
- IRIS allows 254 savepoints alive in one transaction. Each raises ``$TLEVEL``; at 255 the next
  one fails with -400, after which the transaction's work is lost and COMMIT still succeeds.
  ROLLBACK TO frees the savepoint and everything after it; nothing else does.

So the stack keeps the client's names itself, gives each savepoint an internal IRIS name, sends
no RELEASE, re-establishes a savepoint after rolling back to it, and refuses the savepoint that
would pass IRIS's limit. Internal names also settle quoting, case and duplicates: the client's
name is only ever compared here, by PostgreSQL's identifier rules.

Pure: nothing here talks to IRIS. ``_savepoint_mixin.py`` sends what this returns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .sql_translator.sqlstate import INVALID_SAVEPOINT, PROGRAM_LIMIT_EXCEEDED

# $TLEVEL is 1 inside a transaction and IRIS fails at 255, so 254 savepoints can be alive.
MAX_IRIS_SAVEPOINTS = 254

_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_NAME = r'("(?:[^"]|"")+"|[^\s";]+)'
_STATEMENTS = (
    ("savepoint", re.compile(r"SAVEPOINT\s+" + _NAME, re.I)),
    (
        "rollback_to",
        re.compile(r"ROLLBACK(?:\s+(?:WORK|TRANSACTION))?\s+TO\s+(?:SAVEPOINT\s+)?" + _NAME, re.I),
    ),
    ("release", re.compile(r"RELEASE\s+(?:SAVEPOINT\s+)?" + _NAME, re.I)),
)


def parse_savepoint_statement(sql: str) -> tuple[str, str] | None:
    """``(verb, raw name)`` for SAVEPOINT, ROLLBACK TO or RELEASE; None for anything else."""
    text = _COMMENTS.sub(" ", sql or "").strip().rstrip(";").strip()
    for verb, pattern in _STATEMENTS:
        match = pattern.fullmatch(text)
        if match and match.group(1).upper() != "SAVEPOINT":
            return verb, match.group(1)
    return None


def normalise_name(raw: str) -> str:
    """PostgreSQL's identifier rule: unquoted folds to lower case, quoted is exact."""
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('""', '"')
    return raw.lower()


class SavepointError(Exception):
    """A savepoint statement PostgreSQL would refuse; the transaction is then aborted."""

    def __init__(self, state: tuple[str, str], message: str):
        super().__init__(message)
        self.sqlstate, self.condition = state


@dataclass
class _Entry:
    name: str  # the client's name, normalised
    iris_name: str


@dataclass
class SavepointStack:
    """One session's savepoints in the current transaction."""

    # Savepoints the client can still name, oldest first.
    _entries: list[_Entry] = field(default_factory=list)
    # Every IRIS savepoint alive in this transaction, oldest first: the client's, plus released
    # ones, which IRIS keeps because it has no RELEASE.
    _alive: list[str] = field(default_factory=list)
    _next_id: int = 1

    @property
    def depth(self) -> int:
        return len(self._entries)

    @property
    def iris_alive(self) -> int:
        return len(self._alive)

    def savepoint(self, raw_name: str) -> list[str]:
        if len(self._alive) >= MAX_IRIS_SAVEPOINTS:
            raise SavepointError(
                PROGRAM_LIMIT_EXCEEDED,
                f"too many savepoints in one transaction: IRIS allows {MAX_IRIS_SAVEPOINTS}, "
                "including released ones; commit in smaller batches",
            )
        iris_name = f"pgw_sp_{self._next_id}"
        self._next_id += 1
        self._entries.append(_Entry(normalise_name(raw_name), iris_name))
        self._alive.append(iris_name)
        return [f"SAVEPOINT {iris_name}"]

    def rollback_to(self, raw_name: str) -> list[str]:
        index = self._find(raw_name)
        entry = self._entries[index]
        del self._entries[index + 1 :]
        # IRIS frees the savepoint and everything after it, released ones included, then the
        # savepoint is established again so it survives, as on PostgreSQL.
        del self._alive[self._alive.index(entry.iris_name) + 1 :]
        return [f"ROLLBACK TO SAVEPOINT {entry.iris_name}", f"SAVEPOINT {entry.iris_name}"]

    def release(self, raw_name: str) -> list[str]:
        index = self._find(raw_name)
        del self._entries[index:]
        return []  # IRIS keeps its savepoints; PGWire never rolls back to a released one

    def clear(self) -> None:
        self._entries.clear()
        self._alive.clear()
        self._next_id = 1

    def _find(self, raw_name: str) -> int:
        name = normalise_name(raw_name)
        for index in range(len(self._entries) - 1, -1, -1):
            if self._entries[index].name == name:
                return index
        raise SavepointError(INVALID_SAVEPOINT, f'savepoint "{name}" does not exist')
