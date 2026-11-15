"""Spec 052 US5: `lock_timeout` and `statement_timeout`, parsed and shown as PostgreSQL does.

Every expectation here is PostgreSQL 16's answer, measured on the reference server (2026-11-14):
values without a unit are milliseconds; units are `us ms s min h d`, lower case, with an optional
space; fractions round half to even; `SHOW` uses the largest unit that divides the value exactly;
invalid values are 22023 with PostgreSQL's wording. IRIS's lock timeout is whole seconds, so a
value is rounded up for IRIS while `SHOW` keeps PostgreSQL's spelling.
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.timeouts import (
    TimeoutValueError,
    iris_lock_timeout_seconds,
    parse_timeout_ms,
    parse_timeout_statement,
    show_timeout,
)


@pytest.mark.parametrize(
    "raw, ms",
    [
        ("2000", 2000),
        ("'2000'", 2000),
        ("'2000ms'", 2000),
        ("'2s'", 2000),
        ("'1500ms'", 1500),
        ("'1.5s'", 1500),
        ("'1min'", 60000),
        ("'90s'", 90000),
        ("'1h'", 3600000),
        ("'1d'", 86400000),
        ("0", 0),
        ("'0'", 0),
        ("'500us'", 0),
        ("'1500us'", 2),
        ("1.5", 2),
        ("'2 s'", 2000),
        ("DEFAULT", 0),
    ],
)
def test_postgresql_units(raw, ms):
    assert parse_timeout_ms(raw, "lock_timeout") == ms


@pytest.mark.parametrize(
    "ms, shown",
    [
        (2000, "2s"),
        (1500, "1500ms"),
        (60000, "1min"),
        (90000, "90s"),
        (3600000, "1h"),
        (86400000, "1d"),
        (0, "0"),
        (2, "2ms"),
    ],
)
def test_show_uses_the_largest_exact_unit(ms, shown):
    assert show_timeout(ms) == shown


@pytest.mark.parametrize(
    "raw, message",
    [
        ("'abc'", 'invalid value for parameter "lock_timeout": "abc"'),
        ("'2S'", 'invalid value for parameter "lock_timeout": "2S"'),
        ("'10000000000'", 'invalid value for parameter "lock_timeout": "10000000000"'),
        (
            "-1",
            '-1 ms is outside the valid range for parameter "lock_timeout" (0 .. 2147483647)',
        ),
    ],
)
def test_invalid_values_are_22023_with_postgresqls_message(raw, message):
    with pytest.raises(TimeoutValueError) as refused:
        parse_timeout_ms(raw, "lock_timeout")
    assert refused.value.sqlstate == "22023"
    assert str(refused.value) == message


@pytest.mark.parametrize(
    "ms, seconds",
    [(2000, 2), (1500, 2), (1, 1), (999, 1), (60000, 60), (0, None)],
)
def test_iris_gets_whole_seconds_rounded_up_and_0_means_the_default(ms, seconds):
    assert iris_lock_timeout_seconds(ms) == seconds


@pytest.mark.parametrize(
    "sql, parsed",
    [
        ("SET lock_timeout = '2s'", ("set", "lock_timeout", "'2s'")),
        ("set lock_timeout to 2000", ("set", "lock_timeout", "2000")),
        ("SET SESSION lock_timeout = '4s';", ("set", "lock_timeout", "'4s'")),
        ("SET LOCAL lock_timeout = '4s'", ("set", "lock_timeout", "'4s'")),
        ("SET statement_timeout = 0", ("set", "statement_timeout", "0")),
        ("RESET lock_timeout", ("reset", "lock_timeout", None)),
        ("SHOW lock_timeout", ("show", "lock_timeout", None)),
        ("show statement_timeout;", ("show", "statement_timeout", None)),
        ("SET lock_timeout = DEFAULT", ("set", "lock_timeout", "DEFAULT")),
        ('SET "lock_timeout" = 5', ("set", "lock_timeout", "5")),
    ],
)
def test_statements_are_recognised(sql, parsed):
    assert parse_timeout_statement(sql) == parsed


@pytest.mark.parametrize(
    "sql",
    [
        "SET idle_in_transaction_session_timeout = 0",
        "SELECT 'SET lock_timeout = 1'",
        "SET search_path = public",
        "SHOW transaction_isolation",
    ],
)
def test_other_statements_are_not(sql):
    assert parse_timeout_statement(sql) is None
