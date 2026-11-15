"""Spec 052 US2: what the executors send to IRIS for a savepoint statement, and what they reply.

The stack's rules are tested in test_savepoint_stack.py; these tests pin the mixin around it: one
stack per session, the statements sent back through execute_query unchanged, the replies'
command tags and SQLSTATEs, and the stack forgotten at every transaction boundary.
"""

from __future__ import annotations

import asyncio

from iris_pgwire._savepoint_mixin import SavepointMixin


class Host(SavepointMixin):
    def __init__(self, fail_on: str | None = None):
        self.sent: list[tuple[str, dict]] = []
        self.fail_on = fail_on

    async def execute_query(self, sql, params=None, session_id=None, **kwargs):
        self.sent.append((sql, kwargs))
        if self.fail_on and self.fail_on in sql:
            return {"success": False, "error": "IRIS said no", "rows": []}
        return {"success": True, "rows": []}


def run(host, sql, session="s", **kwargs):
    return asyncio.run(host._handle_savepoint_statement(sql, session, **kwargs))


def test_savepoint_is_sent_under_pgwires_name_with_its_command_tag():
    host = Host()
    reply = run(host, 'SAVEPOINT "S1"')
    assert reply["success"] and reply["command_tag"] == "SAVEPOINT"
    assert [s for s, _ in host.sent] == ["SAVEPOINT pgw_sp_1"]
    assert host.live_savepoint_depth("s") == 1


def test_sent_statements_skip_the_savepoint_and_isolation_handlers():
    host = Host()
    run(host, "SAVEPOINT a", original_sql="SAVEPOINT a", _skip_isolation=False, other=1)
    _, kwargs = host.sent[0]
    assert kwargs == {"_skip_savepoints": True, "_skip_isolation": True, "other": 1}


def test_rollback_to_re_establishes_and_release_sends_nothing():
    host = Host()
    run(host, "SAVEPOINT a")
    reply = run(host, "ROLLBACK TO SAVEPOINT a")
    assert reply["command_tag"] == "ROLLBACK"
    assert [s for s, _ in host.sent][1:] == [
        "ROLLBACK TO SAVEPOINT pgw_sp_1",
        "SAVEPOINT pgw_sp_1",
    ]
    reply = run(host, "RELEASE SAVEPOINT a")
    assert reply["command_tag"] == "RELEASE"
    assert len(host.sent) == 3
    assert host.live_savepoint_depth("s") == 0


def test_an_unknown_name_is_3b001_and_nothing_is_sent():
    host = Host()
    reply = run(host, "ROLLBACK TO SAVEPOINT nope")
    assert reply["success"] is False
    assert reply["sqlstate"] == "3B001"
    assert reply["error"] == 'savepoint "nope" does not exist'
    assert host.sent == []


def test_sessions_have_their_own_stacks():
    host = Host()
    run(host, "SAVEPOINT a", session="one")
    assert run(host, "RELEASE a", session="two")["sqlstate"] == "3B001"
    assert host.live_savepoint_depth("one") == 1
    assert host.live_savepoint_depth("two") == 0


def test_a_transaction_boundary_forgets_the_stack_and_runs_normally():
    host = Host()
    run(host, "SAVEPOINT a")
    for boundary in ("COMMIT", "ROLLBACK", "BEGIN"):
        assert run(host, boundary) is None
        assert host.live_savepoint_depth("s") == 0
        run(host, "SAVEPOINT a")


def test_other_statements_are_left_alone():
    host = Host()
    run(host, "SAVEPOINT a")
    assert run(host, "SELECT 1") is None
    assert host.live_savepoint_depth("s") == 1


def test_without_a_session_nothing_is_handled():
    host = Host()
    assert run(host, "SAVEPOINT a", session=None) is None
    assert host.live_savepoint_depth(None) == 0
    host.forget_savepoints(None)


def test_iris_refusing_a_statement_returns_its_error_and_drops_the_stack():
    host = Host(fail_on="ROLLBACK TO")
    run(host, "SAVEPOINT a")
    reply = run(host, "ROLLBACK TO a")
    assert reply == {"success": False, "error": "IRIS said no", "rows": []}
    assert host.live_savepoint_depth("s") == 0


def test_forget_on_close():
    host = Host()
    run(host, "SAVEPOINT a")
    host.forget_savepoints("s")
    assert host.live_savepoint_depth("s") == 0
