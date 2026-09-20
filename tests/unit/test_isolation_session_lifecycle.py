"""The per-session isolation level must not outlive the session.

`IsolationMixin.forget_isolation_level` existed from the start and was called by
nobody, so `session_isolation` grew by one entry for every client that ever set a
level and never shrank. A pgwire server is long-lived and its sessions are not, so
that is a leak in the only dictionary keyed by something as short-lived as a TCP
connection.

Both executors are covered because a client cannot tell which backend it reached:
a leak fixed in one of them is a leak.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from iris_pgwire.dbapi_executor import DBAPIExecutor
from iris_pgwire.iris_executor import IRISExecutor


def _bare_dbapi_executor() -> DBAPIExecutor:
    """A DBAPIExecutor with only what `close_session` touches.

    Built with ``__new__`` rather than the constructor so the test exercises the
    real ``close_session`` body without a pool, a container or a config: the thing
    under test is which dictionaries that method empties.
    """
    ex = object.__new__(DBAPIExecutor)
    ex.session_connections = {}
    ex.session_namespaces = {}
    ex.session_transactions = {}
    ex.session_isolation = {}
    return ex


def _bare_iris_executor() -> IRISExecutor:
    ex = object.__new__(IRISExecutor)
    ex._connection_lock = threading.RLock()
    ex.session_executors = {}
    ex.session_connections = {}
    ex.session_namespaces = {}
    ex.session_isolation = {}
    return ex


@pytest.fixture(params=[_bare_dbapi_executor, _bare_iris_executor], ids=["dbapi", "embedded"])
def executor(request):
    return request.param()


class TestCloseSessionForgetsTheLevel:
    def test_the_entry_is_gone(self, executor):
        executor.session_isolation["session-1"] = "read committed"

        asyncio.run(executor.close_session("session-1"))

        assert "session-1" not in executor.session_isolation

    def test_the_level_reverts_to_the_iris_default(self, executor):
        """A reused session id must not inherit the last client's level."""
        executor.session_isolation["session-1"] = "read committed"

        asyncio.run(executor.close_session("session-1"))

        assert executor.get_isolation_level("session-1") == "read uncommitted"

    def test_other_sessions_are_untouched(self, executor):
        executor.session_isolation["session-1"] = "read committed"
        executor.session_isolation["session-2"] = "read committed"

        asyncio.run(executor.close_session("session-1"))

        assert executor.session_isolation == {"session-2": "read committed"}

    def test_closing_a_session_that_never_set_a_level_is_quiet(self, executor):
        asyncio.run(executor.close_session("session-never-seen"))

        assert executor.session_isolation == {}

    def test_the_dict_does_not_grow_across_many_sessions(self, executor):
        """The leak itself: one entry per connection, none of them ever removed."""
        for i in range(50):
            session_id = f"session-{i}"
            executor.session_isolation[session_id] = "read committed"
            asyncio.run(executor.close_session(session_id))

        assert executor.session_isolation == {}


class TestForgetIsolationLevel:
    def test_none_is_accepted(self, executor):
        """`close_session` is typed for a str, but the mixin is called with None elsewhere."""
        executor.session_isolation["session-1"] = "read committed"

        executor.forget_isolation_level(None)

        assert executor.session_isolation == {"session-1": "read committed"}
