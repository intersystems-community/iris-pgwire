"""Fetch rows that project a VECTOR value on the embedded backend.

Iterating an `iris.sql.exec` result raises
`<OBJECT DISPATCH>next+9^%SYS.Python.SQLResultSet.1 *Invalid argument type` as soon as a row
contains a VECTOR value, because the embedded Python bridge cannot convert a logical `$vector`.
`%SQL.Statement` fails the same way in logical mode (`Unsupported type`). In ODBC select mode it
returns the vector as text, which is also what the DBAPI adapter sends.

ODBC mode changes the form of three other types too, so `odbc_to_logical` converts those back.
The result is that every non-vector value is exactly what the logical path would have produced.
Measured on IRIS 2026.2.0.221.0com: the types not listed in `_ODBC_DIFFERS` read identically in
both modes, and the three conversions reproduce the logical values. That measurement is in
`specs/051-unified-executor/research.md` §R7.

A statement is only ever re-executed when it cannot write: a fetch failure on anything else is
raised.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

_HOROLOG_EPOCH = dt.date(1840, 12, 31)
_UNIX_EPOCH = dt.datetime(1970, 1, 1)
_POSIXTIME_OFFSET = 1152921504606846976
_ODBC_SELECT_MODE = 1

_LEADING_NOISE = re.compile(r"\A(?:\s+|--[^\n]*(?:\n|\Z)|/\*.*?\*/|\()*", re.DOTALL)


def is_vector_fetch_error(error: BaseException) -> bool:
    """True for the error IRIS raises when an embedded result row holds a VECTOR value."""
    text = str(error)
    return "SQLResultSet" in text and "*Invalid argument type" in text


def is_read_only_statement(sql: str) -> bool:
    """True when re-executing `sql` cannot change data: a SELECT or a WITH query."""
    head = _LEADING_NOISE.sub("", sql or "", count=1).lstrip().upper()
    return head.startswith(("SELECT", "WITH")) and not head.startswith("SELECT INTO")


def odbc_to_logical(value: Any, type_class: str | None) -> Any:
    """Convert an ODBC-mode value to the logical form `iris.sql.exec` returns for its type."""
    if value == "" or not isinstance(value, str):
        return value
    if type_class == "%Library.Date":
        return (dt.date.fromisoformat(value) - _HOROLOG_EPOCH).days
    if type_class == "%Library.Time":
        hours, minutes, seconds = value.split(":")
        total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        return int(total) if total.is_integer() else total
    if type_class == "%Library.PosixTime":
        micros = (dt.datetime.fromisoformat(value) - _UNIX_EPOCH) // dt.timedelta(microseconds=1)
        return _POSIXTIME_OFFSET + micros
    return value


def inline_none_params(sql: str, params: list | None) -> tuple[str, list | None]:
    """Inline every parameter when any is None, as `iris.sql.exec` mishandles bound None.

    Returns the SQL to run and the parameters left to bind.
    """
    if not params or not any(p is None for p in params):
        return sql, params
    for value in params:
        if value is None:
            literal = "NULL"
        elif isinstance(value, bool):
            literal = "1" if value else "0"
        elif isinstance(value, int | float):
            literal = str(value)
        else:
            literal = "'" + str(value).replace("'", "''") + "'"
        sql = sql.replace("?", literal, 1)
    return sql, []


def refetch_in_odbc_mode(iris_module: Any, sql: str, params: list | None) -> list[list[Any]]:
    """Re-execute a read-only statement in ODBC select mode and return its rows.

    Non-vector values are converted back to their logical form, so only vector columns differ
    from what the logical path returns: they arrive as IRIS's ODBC text.
    """
    sql, params = inline_none_params(sql.strip().rstrip(";"), params)
    statement = iris_module.cls("%SQL.Statement")._New()
    statement._SelectMode = _ODBC_SELECT_MODE
    status = statement._Prepare(sql)
    if status != 1:
        raise RuntimeError(f"Re-fetch prepare failed: {status}")
    metadata = statement._Metadata
    count = metadata.columnCount
    type_classes = []
    for index in range(1, count + 1):
        type_class = metadata.columns.GetAt(index).typeClass
        type_classes.append(type_class.Name if type_class is not None else None)

    result = statement._Execute(*(params or []))
    if result._SQLCODE < 0:
        raise RuntimeError(f"Re-fetch failed: SQLCODE {result._SQLCODE} {result._Message}")
    rows = []
    while result._Next():
        rows.append(
            [odbc_to_logical(result._GetData(i), type_classes[i - 1]) for i in range(1, count + 1)]
        )
    return rows
