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
-104 field validation        22000  data_exception
-108 required field missing  23502  not_null_violation
-119 UNIQUE/PK failed        23505  unique_violation
-149 error inside a function XX000  internal_error
-359 function not found      42883  undefined_function
-400 fatal error             XX000  internal_error
===========================  ======================================

`-149` is the code IRIS raises when an installed SQL function throws — one of
ours, in practice. IRIS does not surface the inner condition, so there is
nothing to attribute to the client's SQL: `XX000` is the honest answer.

Anything unrecognised keeps the historical `42000`. That is deliberate: a wrong
confident classification is worse than the vague one clients already cope with,
and the mapping only grows as codes are measured.
"""

from __future__ import annotations

import re

# What shipped before this module existed. Unmapped errors keep it, so no client
# relying on the old behaviour regresses.
DEFAULT_SQLSTATE = "42000"
DEFAULT_CONDITION = "syntax_error_or_access_rule_violation"

# IRIS SQLCODE -> (SQLSTATE, PostgreSQL condition name).
SQLCODE_MAP: dict[int, tuple[str, str]] = {
    -1: ("42601", "syntax_error"),
    -4: ("42601", "syntax_error"),
    -25: ("42601", "syntax_error"),
    -23: ("42P01", "undefined_table"),
    -29: ("42703", "undefined_column"),
    -30: ("42P01", "undefined_table"),
    -104: ("22000", "data_exception"),
    -108: ("23502", "not_null_violation"),
    -119: ("23505", "unique_violation"),
    -149: ("XX000", "internal_error"),
    -359: ("42883", "undefined_function"),
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
    `42000` for the non-IRIS case: a genuine transport failure on the query path
    really is `08000`, and only an IRIS error arriving as a Python exception
    should be reclassified.
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
