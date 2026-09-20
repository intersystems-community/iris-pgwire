"""Transaction isolation level handling for the PostgreSQL wire protocol.

Before this module, `SET TRANSACTION ISOLATION LEVEL ...` was caught by the
generic `SET` shim in `protocol.handle_set_command`, which regexes `SET\\s+(\\w+)`,
reads the parameter name as `TRANSACTION`, and replies `CommandComplete("SET")`
without sending anything to IRIS. `SHOW TRANSACTION ISOLATION LEVEL` answered a
hardcoded `"read committed"`. A client asking for READ COMMITTED got success and
no effect, then got told it had what it asked for.

The shim was unnecessary. Measured against IRIS 2026.2 CE:

===============================================  ==================================
Statement                                        IRIS
===============================================  ==================================
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED SQLCODE 0 — accepted
SET TRANSACTION ISOLATION LEVEL READ COMMITTED   SQLCODE 0 — accepted
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ  SQLCODE -96 — "not supported"
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE     SQLCODE -1 — not in the grammar
START TRANSACTION ISOLATION LEVEL READ COMMITTED SQLCODE 0 — accepted
===============================================  ==================================

So the two levels IRIS implements are passed through and take real effect, and
the two it does not are rejected with `0A000 feature_not_supported`.

Rejecting is the deliberate choice, and it follows the precedent already set for
L2 vector distance: this project refuses an operation IRIS cannot perform rather
than pretending. REPEATABLE READ and SERIALIZABLE are not preferences, they are
guarantees about what a transaction will not observe. Answering "SET" to a client
that asked for SERIALIZABLE tells it those guarantees hold. They do not — IRIS
has no MVCC snapshots, so there is nothing to downgrade *to* that would be
honest. An error at SET is recoverable; silent corruption later is not.

What IRIS calls READ COMMITTED is also not what PostgreSQL calls READ COMMITTED
— there are documented exceptions where uncommitted data is still visible. That
difference cannot be fixed here, only disclosed; see KNOWN_LIMITATIONS.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# PostgreSQL's default is "read committed". IRIS's is READ UNCOMMITTED, and that
# is what a session reports until a client successfully changes it. Reporting
# PostgreSQL's default instead would be the same lie the old shim told.
DEFAULT_ISOLATION_LEVEL = "read uncommitted"

# Canonical lowercase level -> the IRIS statement that sets it, or None when IRIS
# cannot honour the level at all.
_IRIS_STATEMENT: dict[str, str | None] = {
    "read uncommitted": "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED",
    "read committed": "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
    "repeatable read": None,
    "serializable": None,
}

# The levels IRIS honours, read off the table above rather than repeated.
_SUPPORTED_LEVELS = frozenset(level for level, sql in _IRIS_STATEMENT.items() if sql is not None)

UNSUPPORTED_SQLSTATE = "0A000"
UNSUPPORTED_CONDITION = "feature_not_supported"

# Changing the level of a transaction that has already read something. Measured
# on PostgreSQL 16: one SQLSTATE, two wordings, and only for the
# transaction-scoped spellings — the session-scoped ones describe the next
# transaction and are accepted whenever they arrive.
MID_TRANSACTION_SQLSTATE = "25001"
MID_TRANSACTION_CONDITION = "active_sql_transaction"
MID_TRANSACTION_AFTER_QUERY = "SET TRANSACTION ISOLATION LEVEL must be called before any query"
MID_TRANSACTION_IN_SUBTRANSACTION = (
    "SET TRANSACTION ISOLATION LEVEL must not be called in a subtransaction"
)

# How long a request lasts. `transaction` is until the transaction ends, which is
# `transaction_isolation`; `session` is the connection's default for transactions
# that do not name one, which is `default_transaction_isolation`. Which spelling
# carries which scope is measured against PostgreSQL 16 — see the table in
# tests/unit/test_isolation_scopes.py, and note that `SET SESSION TRANSACTION
# ISOLATION LEVEL` is transaction-scoped despite the keyword.
TRANSACTION_SCOPE = "transaction"
SESSION_SCOPE = "session"


@dataclass(frozen=True)
class IsolationRequest:
    """A client's request to change the transaction isolation level.

    `supported` is the only field a caller must branch on. When it is True,
    `iris_sql` is the statement to execute, `command_tag` is what the client must
    be told and `scope` is which of the two settings it writes; when False,
    `sqlstate`, `condition` and `message` describe the error to return.
    """

    level: str
    supported: bool
    iris_sql: str | None = None
    command_tag: str | None = None
    scope: str = TRANSACTION_SCOPE
    sqlstate: str | None = None
    condition: str | None = None
    message: str | None = None


# The level itself. Two words for three of them, one for SERIALIZABLE. Named
# because the surrounding patterns have groups of their own.
_LEVEL_RE = r"(?P<level>READ\s+UNCOMMITTED|READ\s+COMMITTED|REPEATABLE\s+READ|SERIALIZABLE)"

# `SET TRANSACTION ISOLATION LEVEL x`, and the SESSION / LOCAL / SESSION
# CHARACTERISTICS AS forms clients also send. The level may be preceded by other
# transaction modes (`SET TRANSACTION READ WRITE, ISOLATION LEVEL x`), so
# anything up to `ISOLATION LEVEL` is skipped rather than matched exactly.
#
# Only `SESSION CHARACTERISTICS AS` makes this the session default; a bare
# `SESSION` does not, which is why it is captured separately.
_SET_TRANSACTION_RE = re.compile(
    r"^\s*SET\s+"
    r"(?P<characteristics>SESSION\s+CHARACTERISTICS\s+AS\s+)?"
    r"(?:SESSION\s+|LOCAL\s+)?"
    r"TRANSACTION\b"
    r".*?\bISOLATION\s+LEVEL\s+" + _LEVEL_RE,
    re.IGNORECASE | re.DOTALL,
)

# The GUC spelling, which is what psycopg and SQLAlchemy actually send:
# `SET transaction_isolation = 'read committed'`. The `default_` prefix is the
# whole difference between the two settings, so it decides the scope.
_SET_GUC_RE = re.compile(
    r"^\s*SET\s+(?:SESSION\s+|LOCAL\s+)?"
    r"(?P<default>default_)?transaction_isolation\s*(?:=|\s+TO\s+)\s*"
    r"'?" + _LEVEL_RE + r"'?",
    re.IGNORECASE | re.DOTALL,
)

# The level named on the statement that starts the transaction, which is how
# psycopg3 asks by default: `BEGIN ISOLATION LEVEL READ COMMITTED`. Anchored at the
# start of the statement so that a `BEGIN` opening a procedure body is not read as a
# transaction start, and otherwise as tolerant of surrounding transaction modes as
# the SET forms above.
_BEGIN_TRANSACTION_RE = re.compile(
    r"^\s*(?:BEGIN(?:\s+TRANSACTION|\s+WORK)?|START\s+TRANSACTION)\b"
    r".*?\bISOLATION\s+LEVEL\s+" + _LEVEL_RE,
    re.IGNORECASE | re.DOTALL,
)

# IRIS has no `BEGIN` statement: measured, `BEGIN ISOLATION LEVEL READ COMMITTED` is
# SQLCODE -51 ("SQL statement expected"), while every `START TRANSACTION ...` spelling
# of the same request is SQLCODE 0 — including `READ WRITE` / `READ ONLY` either side
# of the level. So the verb is replaced and nothing else is: the transaction modes are
# the client's, and IRIS takes them as written.
_BEGIN_VERB_RE = re.compile(r"^\s*BEGIN(?:\s+TRANSACTION|\s+WORK)?", re.IGNORECASE)

# Where a transaction begins and ends, which is where a transaction-scoped level
# begins and ends with it. `ROLLBACK TO [SAVEPOINT] x` is excluded on purpose: it
# leaves the transaction open, so the level it was given is still the one running.
_TRANSACTION_START_RE = re.compile(
    r"^\s*(?:BEGIN|START\s+TRANSACTION)\b",
    re.IGNORECASE,
)
_TRANSACTION_END_RE = re.compile(
    r"^\s*(?:(?P<commit>COMMIT|END)|(?P<rollback>ROLLBACK)(?!\s+TO\b))\b",
    re.IGNORECASE,
)

# Savepoints, which are subtransactions: PostgreSQL refuses to change the
# isolation level inside one. Measured — SAVEPOINT enters, RELEASE leaves, and
# `ROLLBACK TO SAVEPOINT` leaves the savepoint in place, so it is still inside.
_SAVEPOINT_ENTER_RE = re.compile(r"^\s*SAVEPOINT\b", re.IGNORECASE)
_SAVEPOINT_LEAVE_RE = re.compile(r"^\s*RELEASE\b", re.IGNORECASE)

# Statements that do not count as the transaction having read anything. SET and
# SHOW are measured; RESET and DISCARD are not, and are grouped with SET because
# they are parameter statements rather than queries. Savepoint statements are
# here because they are governed by the subtransaction rule instead.
_NOT_A_QUERY_RE = re.compile(
    r"^\s*(?:SET|SHOW|RESET|DISCARD|SAVEPOINT|RELEASE)\b",
    re.IGNORECASE,
)

_SHOW_RE = re.compile(
    r"^\s*SHOW\s+(?:(default_transaction_isolation|transaction_isolation)"
    r"|TRANSACTION\s+ISOLATION\s+LEVEL)\s*;?\s*$",
    re.IGNORECASE,
)


def _canonical(level_text: str) -> str:
    """`'READ   COMMITTED'` -> `'read committed'`."""
    return re.sub(r"\s+", " ", level_text).strip().lower()


def parse_set_isolation(sql: str) -> IsolationRequest | None:
    """Classify `sql` as an isolation-level SET, or return None.

    None means "not an isolation statement" and leaves the caller's existing
    handling untouched — including for `SET TRANSACTION READ ONLY`, which sets an
    access mode and no isolation level, and for an unrecognised level name, which
    should reach IRIS and be refused there rather than guessed at here.
    """
    if not sql:
        return None

    match = _SET_TRANSACTION_RE.match(sql) or _SET_GUC_RE.match(sql)
    if match is None:
        return None

    groups = match.groupdict()
    session_scoped = bool(groups.get("characteristics") or groups.get("default"))
    level = _canonical(match.group("level"))
    return _classify(
        level,
        iris_sql=_IRIS_STATEMENT[level],
        command_tag="SET",
        scope=SESSION_SCOPE if session_scoped else TRANSACTION_SCOPE,
    )


def parse_begin_isolation(sql: str) -> IsolationRequest | None:
    """Classify `sql` as a transaction start that names a level, or return None.

    `BEGIN ISOLATION LEVEL READ COMMITTED` is one statement that both begins the
    transaction and sets the level, and `iris_sql` keeps it that way: it is the same
    statement with only the verb translated, not a `SET` plus a transaction start,
    because splitting it would change when the transaction begins.

    A level IRIS cannot honour is refused here, before the transaction starts, which
    is the only point at which refusing leaves the session where it was.
    """
    if not sql:
        return None

    match = _BEGIN_TRANSACTION_RE.match(sql)
    if match is None:
        return None

    level = _canonical(match.group("level"))
    iris_sql, rewrites = _BEGIN_VERB_RE.subn("START TRANSACTION", sql, count=1)
    # Measured on PostgreSQL 16: `BEGIN` and `BEGIN ISOLATION LEVEL x` are both
    # answered `BEGIN`, while `START TRANSACTION` is answered `START TRANSACTION`.
    # The tag is decided here because the statement sent to IRIS says START
    # TRANSACTION whatever the client wrote, so the verb is no longer recoverable
    # from it downstream.
    return _classify(
        level,
        iris_sql=iris_sql,
        command_tag="BEGIN" if rewrites else "START TRANSACTION",
    )


def _classify(
    level: str, iris_sql: str | None, command_tag: str, scope: str = TRANSACTION_SCOPE
) -> IsolationRequest:
    """Build the request for an already-canonicalised `level`.

    Support is a property of the level alone, so neither `iris_sql` nor
    `command_tag` is consulted: a refused request has an error to return instead
    of a statement to send and a tag to answer with. `scope` is carried through
    either way, because it describes the request and not the answer.
    """
    if level in _SUPPORTED_LEVELS:
        return IsolationRequest(
            level=level,
            supported=True,
            iris_sql=iris_sql,
            command_tag=command_tag,
            scope=scope,
        )

    return IsolationRequest(
        level=level,
        supported=False,
        scope=scope,
        sqlstate=UNSUPPORTED_SQLSTATE,
        condition=UNSUPPORTED_CONDITION,
        # Opens with IRIS's own wording for this refusal so that the message
        # classifies to 0A000 even on the paths that only see an error string —
        # see sqlstate._MESSAGE_PATTERNS.
        message=(
            f"Specified [level of isolation] is not supported: {level.upper()}. "
            f"InterSystems IRIS implements read uncommitted and read committed only, "
            f"and provides no snapshot isolation, so there is no weaker level that "
            f"would preserve the guarantee requested. Rejected rather than silently "
            f"downgraded."
        ),
    )


def parse_transaction_boundary(sql: str) -> str | None:
    """`"start"`, `"commit"`, `"rollback"`, or None for anything else.

    A transaction-scoped isolation level lives exactly as long as the transaction,
    so the level has to be dropped where the transaction ends — and PostgreSQL
    ends it on COMMIT and ROLLBACK alike, `END` being COMMIT's other spelling.
    """
    if not sql:
        return None
    if _TRANSACTION_START_RE.match(sql):
        return "start"
    match = _TRANSACTION_END_RE.match(sql)
    if match is None:
        return None
    return "commit" if match.group("commit") else "rollback"


def parse_savepoint_change(sql: str) -> str | None:
    """`"enter"` for SAVEPOINT, `"leave"` for RELEASE, None for anything else.

    `ROLLBACK TO SAVEPOINT` is neither: the savepoint survives it, so the
    transaction is still inside the subtransaction it names.
    """
    if not sql:
        return None
    if _SAVEPOINT_ENTER_RE.match(sql):
        return "enter"
    if _SAVEPOINT_LEAVE_RE.match(sql):
        return "leave"
    return None


def counts_as_query(sql: str) -> bool:
    """Whether running `sql` makes it too late to change the transaction's level.

    "Any query" in PostgreSQL's wording, which measurably excludes SHOW and SET —
    neither reads a row, so neither commits the transaction to a level.
    """
    if not sql:
        return False
    return _NOT_A_QUERY_RE.match(sql) is None


def parse_isolation_show(sql: str) -> str | None:
    """Return the GUC name a `SHOW` is asking for, or None.

    `SHOW TRANSACTION ISOLATION LEVEL` and `SHOW transaction_isolation` are the
    same query; PostgreSQL labels the result column `transaction_isolation` for
    both, so both map to that name.
    """
    if not sql:
        return None
    match = _SHOW_RE.match(sql)
    if match is None:
        return None
    return (match.group(1) or "transaction_isolation").lower()
