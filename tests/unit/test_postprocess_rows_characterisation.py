"""What `_postprocess_rows` does to each kind of value, pinned before it was made to skip columns
that need nothing (2026-11-14: it called `_serialize_value` on all 1.2 million values of a
100,000-row read, 0.48 s of a 0.92 s fetch).
"""

from __future__ import annotations

import datetime as dt

from iris_pgwire.iris_executor import POSIXTIME_OFFSET, IRISExecutor


def _cols(*oids):
    return [{"name": f"c{i}", "type_oid": oid} for i, oid in enumerate(oids)]


def _run(rows, columns):
    IRISExecutor.__new__(IRISExecutor)._postprocess_rows(rows, columns)
    return rows, columns


def test_text_float_and_numeric_columns_are_left_alone():
    rows = [["a", 1.5, "1.25", None], ["", 2.5, "x", "y"]]
    out, cols = _run([list(r) for r in rows], _cols(25, 701, 1700, 1043))
    assert out == rows
    assert [c["type_oid"] for c in cols] == [25, 701, 1700, 1043]


def test_an_integer_column_holding_posixtime_becomes_a_timestamp():
    us = POSIXTIME_OFFSET + 1_000_000  # 1970-01-01 00:00:01
    out, cols = _run([[us, 7], [5, 8]], _cols(20, 23))
    assert out == [["1970-01-01 00:00:01.000000", 7], [5, 8]]
    assert cols[0]["type_oid"] == 1114
    assert cols[1]["type_oid"] == 23


def test_posixtime_in_a_later_row_is_converted_but_does_not_retype_the_column():
    us = POSIXTIME_OFFSET + 1_000_000
    out, cols = _run([[5], [us]], _cols(20))
    assert out == [[5], ["1970-01-01 00:00:01.000000"]]
    assert cols[0]["type_oid"] == 20


def test_timestamp_values_of_each_kind():
    us = POSIXTIME_OFFSET + 2_000_000
    rows = [[us], [dt.datetime(2026, 1, 2, 3, 4, 5, 6)], ["2026-01-02T03:04:05"], [str(us)], [None]]
    out, _ = _run(rows, _cols(1114))
    assert out == [
        ["1970-01-01 00:00:02.000000"],
        ["2026-01-02 03:04:05.000006"],
        ["2026-01-02 03:04:05.000000"],
        ["1970-01-01 00:00:02.000000"],
        [None],
    ]


def test_date_values_of_each_kind():
    out, _ = _run([["2000-01-11"], [58_074 + 10], [None], ["not a date"]], _cols(1082))
    assert out == [[10], [10], [None], ["not a date"]]


def test_a_row_longer_than_the_columns_keeps_its_extra_values():
    out, _ = _run([[1, "extra"]], _cols(23))
    assert out == [[1, "extra"]]
