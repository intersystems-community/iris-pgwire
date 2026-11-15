"""`lock_timeout` and `statement_timeout`, parsed and shown as PostgreSQL does (spec 052 US5).

PostgreSQL keeps both in milliseconds. A value without a unit is milliseconds; units are `us ms
s min h d`, lower case, with an optional space; a fraction rounds half to even; `SHOW` prints the
largest unit that divides the value exactly. All measured on PostgreSQL 16, 2026-11-14.

IRIS's lock timeout (`SET OPTION LOCK_TIMEOUT = n`) is whole seconds, so the value IRIS gets is
rounded up, and 0, PostgreSQL's "wait forever", becomes the server's default wait: IRIS has no
unbounded one. `statement_timeout` is accepted and not enforced.

Pure: no I/O.
"""

from __future__ import annotations

import math
import re

_MAX_MS = 2147483647

_UNITS_MS = {"us": 0.001, "ms": 1, "s": 1000, "min": 60000, "h": 3600000, "d": 86400000}
_SHOW_UNITS = (("d", 86400000), ("h", 3600000), ("min", 60000), ("s", 1000))
_VALUE = re.compile(r"^(-?\d+(?:\.\d*)?|-?\.\d+)\s*(us|ms|s|min|h|d)?$")
_STATEMENT = re.compile(
    r"""^\s*(?:
        (?P<set>SET)\s+(?:SESSION\s+|LOCAL\s+)?"?(?P<sname>lock_timeout|statement_timeout)"?
            \s*(?:=|\bTO\b)\s*(?P<value>.+?)
      | (?P<reset>RESET)\s+"?(?P<rname>lock_timeout|statement_timeout)"?
      | (?P<show>SHOW)\s+"?(?P<shname>lock_timeout|statement_timeout)"?
    )\s*;?\s*$""",
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


class TimeoutValueError(ValueError):
    """A value PostgreSQL refuses: 22023 invalid_parameter_value."""

    sqlstate = "22023"
    condition = "invalid_parameter_value"


def parse_timeout_statement(sql: str) -> tuple[str, str, str | None] | None:
    """`("set" | "reset" | "show", parameter, raw value or None)`, or None for anything else."""
    found = _STATEMENT.match(sql)
    if not found:
        return None
    if found.group("set"):
        return "set", found.group("sname").lower(), found.group("value").strip()
    if found.group("reset"):
        return "reset", found.group("rname").lower(), None
    return "show", found.group("shname").lower(), None


def parse_timeout_ms(raw: str, parameter: str) -> int:
    """Milliseconds for a SET value as written (quoted or not); DEFAULT is 0."""
    text = raw.strip()
    if text.upper() == "DEFAULT":
        return 0
    if len(text) >= 2 and text[0] == text[-1] == "'":
        text = text[1:-1].replace("''", "'")
    found = _VALUE.match(text.strip())
    if not found:
        raise TimeoutValueError(f'invalid value for parameter "{parameter}": "{text}"')
    number, unit = found.group(1), found.group(2) or "ms"
    ms = round(float(number) * _UNITS_MS[unit])  # round half to even, as PostgreSQL
    if abs(ms) > _MAX_MS:
        raise TimeoutValueError(f'invalid value for parameter "{parameter}": "{text}"')
    if ms < 0:
        raise TimeoutValueError(
            f'{ms} ms is outside the valid range for parameter "{parameter}" (0 .. {_MAX_MS})'
        )
    return ms


def show_timeout(ms: int) -> str:
    """PostgreSQL's SHOW spelling: the largest unit that divides the value exactly."""
    if ms == 0:
        return "0"
    for unit, size in _SHOW_UNITS:
        if ms % size == 0:
            return f"{ms // size}{unit}"
    return f"{ms}ms"


def iris_lock_timeout_seconds(ms: int) -> int | None:
    """IRIS's whole seconds, rounded up; None for 0, meaning the server's default wait."""
    return None if ms == 0 else math.ceil(ms / 1000)
