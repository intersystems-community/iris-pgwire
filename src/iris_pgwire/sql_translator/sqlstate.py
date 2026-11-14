"""Classify an IRIS error into a PostgreSQL SQLSTATE (FR-008e).

Every failure used to reach the client as `42000`
(`syntax_error_or_access_rule_violation`), whatever had actually gone wrong. A
client keys its retry and reporting logic on the SQLSTATE *class*, so an IRIS
internal crash read as "your SQL is wrong", and an ORM could not recognise a
duplicate-key insert at all.

FR-008d permits passing an IRIS failure through to the client. That is only
honest if the error is classified: pass-through must not mean misattributing
blame.

Both halves of the table below were measured, not recalled — the SQLCODEs
against IRIS 2026.2, the SQLSTATEs against PostgreSQL 15:

===========================  ======================================
IRIS SQLCODE                 PostgreSQL SQLSTATE
===========================  ======================================
-1   invalid SQL statement   42601  syntax_error
-4   term expected           42601  syntax_error
-25  input after end         42601  syntax_error
-23  label not listed        42P01  undefined_table
-29  field not found         42703  undefined_column
-30  table/view not found    42P01  undefined_table
-96  feature not supported   0A000  feature_not_supported
-104 field validation        22000  data_exception
-108 required field missing  23502  not_null_violation
-110 writer lock conflict    40001  serialization_failure
-114 reader lock conflict    40001  serialization_failure
-119 UNIQUE/PK failed        23505  unique_violation
-149 error inside a function XX000  internal_error
-359 function not found      42883  undefined_function
-375 savepoint not found     3B001  invalid_savepoint_specification
-400 fatal error             XX000  internal_error
===========================  ======================================

`-375` ("Cannot ROLLBACK to unestablished savepoint") was measured by the
isolation suite in 2.0.1's run, for a savepoint never created and for one already
rolled back to; PostgreSQL answers both with `3B001`.

`08000` (`connection_exception`) is kept for the transport failing, recognised by
its wording. Until 2.0.1 the query paths also used it as their fallback, so -14,
-51, -375 and the DBAPI driver's `<LIST ERROR>` reached clients as a connection
failure, which tells a client-side pool to throw away a connection that was fine.

`-149` is the code IRIS raises when an installed SQL function throws — one of
ours, in practice. IRIS does not surface the inner condition, so there is
nothing to attribute to the client's SQL: `XX000` is the honest answer.

`-110` and `-114` are the two mappings here that cross error *classes* rather than
refining one, so the reasoning is worth stating. Both were measured by forcing
real conflicts against a row a jobbed process held with an uncommitted UPDATE:

    -110  the writer's half. A second UPDATE or DELETE of the row: `Unable to
          acquire lock for UPDATE of table 'X' on row with RowID = '1'`.
    -114  the reader's half. A SELECT of the row at READ COMMITTED: `Unable to
          acquire shared lock on table X for RowID value: 2`, raised at *fetch*
          time with the prepare reporting SQLCODE 0. IRIS 2026.1 words the same
          code "One or more matching rows is locked by another user".

PostgreSQL would call a lock timeout `55P03 lock_not_available`, but that code
means "you asked for NOWAIT and I could not comply". IRIS has no MVCC snapshots,
so a lock timeout is not an edge case — it is the *only* way a conflict is
reported, which is the event PostgreSQL signals as `40001`. Class 40 also tells
the client the correct response: roll back and retry. Every PostgreSQL retry
helper keys on `40001`; none retries `42000`, which is what these used to return,
so a transient conflict reached applications as a bug in their SQL.

`-114`'s 2026.1 wording is a second reason not to pass it through unclassified:
"another user" there means another *connection*, so a client shown that text under
`42000` reads it as a privilege problem with its own query.

Anything unrecognised gets `XX000` (`internal_error`), PostgreSQL's own code for
a failure it cannot classify. A wrong confident classification is worse than no
classification, and the mapping only grows as codes are measured.

This used to be `42000`, defended as the vague answer clients already coped with.
That was not accurate. `42000` is class 42, which tells a client its statement
text is at fault, so every code not yet in the table sent clients off to rewrite
SQL that was fine — the same defect the `-110` and `-114` mappings above fixed,
left in place as the default. Class XX carries no instruction, which is the
honest content of an unmeasured error. ODBC's `HY000` would be the equivalent in
a DB-API layer, but it is not in PostgreSQL's table at all and would reach a
psycopg client as an unknown class with no condition name.

This is client-visible for every unmapped code: anything matching on `42000` to
recognise an IRIS error stops matching. Nothing narrows a query's meaning on it —
the mapped codes above are unaffected, and a call site that supplies its own
`default` still keeps it.
"""

from __future__ import annotations

import re

# Unmapped errors are reported as unclassified rather than as a syntax error.
# Class 42 tells a client to rewrite a statement that was fine; class XX tells it
# nothing, which is the truth when the code has not been measured.
DEFAULT_SQLSTATE = "XX000"
DEFAULT_CONDITION = "internal_error"

# IRIS SQLCODE -> (SQLSTATE, PostgreSQL condition name).
SQLCODE_MAP: dict[int, tuple[str, str]] = {
    -1: ("42601", "syntax_error"),
    -4: ("42601", "syntax_error"),
    -25: ("42601", "syntax_error"),
    -23: ("42P01", "undefined_table"),
    -29: ("42703", "undefined_column"),
    -30: ("42P01", "undefined_table"),
    -96: ("0A000", "feature_not_supported"),
    -104: ("22000", "data_exception"),
    -108: ("23502", "not_null_violation"),
    -110: ("40001", "serialization_failure"),
    -114: ("40001", "serialization_failure"),
    -119: ("23505", "unique_violation"),
    -149: ("XX000", "internal_error"),
    -359: ("42883", "undefined_function"),
    -375: ("3B001", "invalid_savepoint_specification"),
    -400: ("XX000", "internal_error"),
}

# Not every path carries a SQLCODE, and the two backends do not word errors the
# same way. Measured inside the container: the embedded backend (`iris.sql.exec`)
# raises `Table 'SQLUSER.X' not found` and `IDENTIFIER expected, reserved word
# WHERE found` with no SQLCODE anywhere, where DB-API delivers `[SQLCODE: <-30>]`
# and `[SQLCODE: <-1>]`. So both wordings are matched for every family.
#
# Ordered: the first match wins, so the specific patterns precede the general
# ones ("Table or view not found" also contains "not found").
_MESSAGE_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, str]], ...] = (
    (
        # Writer, measured: "Unable to acquire lock for UPDATE of table
        # 'SQLUser.LkProbe' on row with RowID = '1'" (-110). Reader, measured:
        # "Unable to acquire shared lock on table SQLUser.Iso114 for RowID
        # value: 2" (-114). The verb varies (UPDATE, DELETE) and the lock is
        # described as shared, exclusive or table depending on the statement, so
        # only "unable to acquire ... lock" is required.
        re.compile(r"unable to acquire\b[^.]{0,40}?\block\b", re.I),
        ("40001", "serialization_failure"),
    ),
    (
        # IRIS 2026.1 wording for the same reader conflict (-114). "another user"
        # means another connection; left as `42000` a client reads this as a
        # privilege problem with its own SQL.
        re.compile(r"row(?:s)? (?:is|are) locked by another user", re.I),
        ("40001", "serialization_failure"),
    ),
    (
        # Measured: "Specified [level of isolation] is not supported: REPEATABLE
        # READ". The bracketed subject varies by feature.
        re.compile(r"specified \[[^\]]*\] is not supported", re.I),
        ("0A000", "feature_not_supported"),
    ),
    (
        # This one is ours, not IRIS's: a level change that arrived after the
        # transaction had already read something, in PostgreSQL 16's wording —
        # "must be called before any query" or "must not be called in a
        # subtransaction". Matched here as well as carried explicitly, so the
        # paths that only see a string do not make it a syntax error.
        re.compile(r"set transaction isolation level must (?:not\s+)?be called\b", re.I),
        ("25001", "active_sql_transaction"),
    ),
    (
        # DB-API: "Table or view not found". Embedded: "Table 'SQLUSER.X' not found".
        re.compile(r"table (or view )?not found|table '[^']*' not found", re.I),
        ("42P01", "undefined_table"),
    ),
    (
        re.compile(r"label\s+.*is not listed among the applicable tables", re.I),
        ("42P01", "undefined_table"),
    ),
    (
        re.compile(r"not found in the applicable tables", re.I),
        ("42703", "undefined_column"),
    ),
    (
        re.compile(r"(user defined sql function|sql function).*(not found|does not exist)", re.I),
        ("42883", "undefined_function"),
    ),
    (
        # DB-API: "UNIQUE or PRIMARY KEY constraint failed".
        # Embedded: "... Constraint 'T_PKEY2', Field(s) id=1; failed unique check".
        re.compile(
            r"unique\b.*constraint failed|primary key.*constraint failed|failed unique check", re.I
        ),
        ("23505", "unique_violation"),
    ),
    (
        # DB-API: "Required field missing". Embedded: "'id' in table 'T' is a
        # required field".
        re.compile(r"required field missing|is a required field", re.I),
        ("23502", "not_null_violation"),
    ),
    (
        # Both an over-length string and an unparseable number arrive as
        # "failed validation", with nothing to tell them apart. PostgreSQL would
        # say 22001 and 22P02; 22000 is their shared class, so the client learns
        # "bad data" and nothing false.
        re.compile(r"field validation failed|failed validation", re.I),
        ("22000", "data_exception"),
    ),
    (
        re.compile(
            r"a term expected"
            r"|expected, reserved word"
            r"|expected, beginning with"
            r"|input\b.*encountered after end of query"
            r"|closing quote .* missing"
            r"|invalid sql statement",
            re.I,
        ),
        ("42601", "syntax_error"),
    ),
    # ObjectScript escaping into SQL: <UNDEFINED>, <LIST>, a raw %Execute
    # exception. None of these map to a PostgreSQL condition — they are the
    # database breaking, which is exactly what XX000 is for.
    (
        re.compile(
            r"fatal error occurred"
            r"|sql function encountered an error"
            r"|unexpected error occurred"
            r"|exception caught during dsql"
            r"|<(undefined|list|subscript|maxstring|store|framestack|illegal value)>",
            re.I,
        ),
        ("XX000", "internal_error"),
    ),
    (
        # The transport itself, in the wordings the DBAPI executor already treats
        # as a lost connection. Only this is a connection exception.
        re.compile(
            r"communication link failure"
            r"|connection (?:lost|reset|refused|closed)"
            r"|\bnot connected\b"
            r"|socket (?:error|closed)"
            r"|broken pipe",
            re.I,
        ),
        ("08000", "connection_exception"),
    ),
)

_SQLCODE_RE = re.compile(r"SQLCODE:?\s*[<:]?\s*(-\d+)", re.I)


def classify_iris_error(
    message: str | None, default: tuple[str, str] | None = None
) -> tuple[str, str]:
    """Return ``(sqlstate, condition_name)`` for an IRIS error message.

    A negative SQLCODE in the message decides it when the code is mapped;
    otherwise the wording is matched; otherwise the fallback.

    Positive SQLCODEs are not errors — 100 is "no more rows" — so only negative
    codes are read.

    ``default`` lets a call site keep the code it already reported when nothing
    is recognised. That matters where the existing code is *more* specific than
    the unclassified fallback for the non-IRIS case: a genuine transport failure
    on the query path really is `08000`, and only an IRIS error arriving as a
    Python exception should be reclassified.
    """
    fallback = default if default is not None else (DEFAULT_SQLSTATE, DEFAULT_CONDITION)
    if not message:
        return fallback

    match = _SQLCODE_RE.search(message)
    if match:
        mapped = SQLCODE_MAP.get(int(match.group(1)))
        if mapped is not None:
            return mapped

    for pattern, mapped in _MESSAGE_PATTERNS:
        if pattern.search(message):
            return mapped

    return fallback
