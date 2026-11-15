"""Spec 052 US5: what the DBAPI executor does with SET/RESET/SHOW lock_timeout and statement_timeout.

A fake host records the statements sent to IRIS. The isolation suite measures the waits.
"""

from __future__ import annotations

import asyncio

import pytest

from iris_pgwire._timeout_mixin import TimeoutMixin


class Host(TimeoutMixin):
    def __init__(self, server_default=10):
        self.sent: list[str] = []
        self.server_default = server_default

    async def execute_query(self, sql, params=None, session_id=None, **kwargs):
        self.sent.append(sql)
        assert kwargs.get("_skip_timeouts"), "own statements must bypass the timeout handler"
        if "Util_GetOption" in sql:
            return {"success": True, "rows": [[self.server_default]], "columns": []}
        return {"success": True, "rows": [], "columns": []}


def run(host, sql, session="s"):
    return asyncio.run(host._handle_timeout_statement(sql, session))


def test_set_sends_whole_seconds_rounded_up_and_show_keeps_postgresqls_spelling():
    host = Host()
    reply = run(host, "SET lock_timeout = '1500ms'")
    assert reply["success"] and reply["command_tag"] == "SET"
    assert host.sent[-1] == "SET OPTION LOCK_TIMEOUT = 2"
    assert run(host, "SHOW lock_timeout")["rows"] == [["1500ms"]]
    assert host.lock_timeout_set("s")


def test_zero_and_reset_restore_the_server_default_and_clear_the_flag():
    for statement in ("SET lock_timeout = 0", "RESET lock_timeout", "SET lock_timeout = DEFAULT"):
        host = Host(server_default=10)
        run(host, "SET lock_timeout = '2s'")
        reply = run(host, statement)
        assert reply["success"]
        assert host.sent[-1] == "SET OPTION LOCK_TIMEOUT = 10"
        assert not host.lock_timeout_set("s")
        assert run(host, "SHOW lock_timeout")["rows"] == [["0"]]


def test_the_server_default_is_read_once():
    host = Host()
    run(host, "SET lock_timeout = '2s'")
    run(host, "RESET lock_timeout")
    run(host, "RESET lock_timeout")
    assert sum("Util_GetOption" in s for s in host.sent) == 1


def test_show_before_any_set_is_postgresqls_default():
    host = Host()
    assert run(host, "SHOW lock_timeout")["rows"] == [["0"]]
    assert run(host, "SHOW statement_timeout")["rows"] == [["0"]]
    assert host.sent == []


def test_an_invalid_value_is_22023_and_changes_nothing():
    host = Host()
    reply = run(host, "SET lock_timeout = 'abc'")
    assert reply["success"] is False
    assert reply["sqlstate"] == "22023"
    assert reply["error"] == 'invalid value for parameter "lock_timeout": "abc"'
    assert host.sent == []


def test_statement_timeout_is_recorded_not_sent_and_warned_once_per_session(caplog):
    host = Host()
    assert run(host, "SET statement_timeout = '5s'")["success"]
    assert run(host, "SET statement_timeout = '6s'")["success"]
    assert host.sent == []
    assert run(host, "SHOW statement_timeout")["rows"] == [["6s"]]
    assert host.statement_timeout_warnings == 1
    run(host, "SET statement_timeout = '7s'", session="other")
    assert host.statement_timeout_warnings == 2


def test_sessions_are_separate_and_forgotten_on_close():
    host = Host()
    run(host, "SET lock_timeout = '2s'", session="a")
    assert host.lock_timeout_set("a") and not host.lock_timeout_set("b")
    assert host.session_lock_timeout_seconds("a") == 2
    host.forget_timeouts("a")
    assert not host.lock_timeout_set("a")
    assert host.session_lock_timeout_seconds("a") is None


def test_other_statements_are_not_handled():
    host = Host()
    assert run(host, "SELECT 1") is None
    assert run(host, "SET search_path = public") is None


@pytest.mark.parametrize(
    "sqlstate, message, flagged, expected",
    [
        ("40001", "[SQLCODE: <-110>:<Locking conflict in filing>]", True, "55P03"),
        ("40001", "[SQLCODE: <-114>:<shared lock>]", True, "55P03"),
        ("40001", "[SQLCODE: <-110>:<Locking conflict in filing>]", False, "40001"),
        ("40001", "serialization failure without a SQLCODE", True, "40001"),
        ("23505", "[SQLCODE: <-119>]", True, "23505"),
    ],
)
def test_a_lock_timeout_the_client_set_is_55p03(sqlstate, message, flagged, expected):
    from iris_pgwire._timeout_mixin import lock_timeout_sqlstate

    assert lock_timeout_sqlstate(sqlstate, message, flagged)[0] == expected
