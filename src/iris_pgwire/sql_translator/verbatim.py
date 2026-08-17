"""Guard for SQL pgwire authored itself, which must not be translated.

The translation pipeline exists to turn *client* SQL into something IRIS
accepts: uppercasing identifiers, mapping schema names, rewriting constructs.
Applied to statements pgwire writes, it is a category error — and a damaging
one for `CREATE FUNCTION … LANGUAGE OBJECTSCRIPT`, where the body is
ObjectScript rather than SQL. Observed on IRIS 2026.2 when the catalog function
installer went through the ordinary path:

* `$SYSTEM.Encryption.SHAHash` became `%SYSTEM.ENCRYPTION`, and class names are
  case-sensitive → `<CLASS DOES NOT EXIST>`;
* the declared parameter and its uses in the body were cased differently →
  `<UNDEFINED> *encoded`.

Both failed at *call* time rather than install time, so the functions installed
"successfully" and then errored on every query that used them.

A ContextVar rather than an argument threaded through `execute_query`, matching
`catalog/_reentrancy.py`: the same call sites are shared by every backend, and
task scoping means one session's verbatim DDL cannot disable translation for a
concurrent client.
"""

from __future__ import annotations

import contextlib
import contextvars

_VERBATIM_SQL: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "iris_pgwire_verbatim_sql", default=False
)


def is_verbatim() -> bool:
    """True when the current task is executing SQL pgwire wrote itself."""
    return _VERBATIM_SQL.get()


@contextlib.contextmanager
def verbatim_sql():
    """Execute SQL exactly as written, with no translation applied."""
    token = _VERBATIM_SQL.set(True)
    try:
        yield
    finally:
        _VERBATIM_SQL.reset(token)


__all__ = ["is_verbatim", "verbatim_sql"]
