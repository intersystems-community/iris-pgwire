"""The end of a transaction must reach the isolation bookkeeping on both backends.

A transaction-scoped level is dropped when the transaction ends, and the mixin
sees that by reading the SQL of every statement. That works for the DBAPI backend
because its `commit_transaction` sends `COMMIT` through `execute_query`, and it
does not work for the embedded backend, whose transaction methods call
`iris.sql.exec` directly and are never seen by the mixin at all.

Which means the same client, asking the same thing, would get a level that ends
on one backend and one that never ends on the other — and the backend is a server
config a client cannot see. Both are pinned here.
"""

from __future__ import annotations

import threading

import pytest

from iris_pgwire.dbapi_executor import DBAPIExecutor
from iris_pgwire.iris_executor import IRISExecutor


def _bare_iris_executor() -> IRISExecutor:
    """An embedded executor with only what the transaction methods touch.

    `embedded_mode` is False so the methods do their bookkeeping and skip the
    `iris.sql.exec` that needs a real IRIS behind it.
    """
    ex = object.__new__(IRISExecutor)
    ex._connection_lock = threading.RLock()
    ex.embedded_mode = False
    # None is asyncio's default executor, which is what these methods need when
    # there is no session to have its own thread.
    ex.thread_pool = None
    ex.session_executors = {}
    ex.session_connections = {}
    ex.session_namespaces = {}
    ex.session_isolation = {}
    return ex


def _open_transaction_at(executor, level: str, session_id: str = "s1") -> None:
    """Put the session in the state `BEGIN; SET TRANSACTION ISOLATION LEVEL x` leaves."""
    executor._note_transaction_boundary("start", session_id)
    state = executor._isolation_state(session_id)
    state.override = level
    state.iris_level = level


class TestTheEmbeddedBackendsTransactionMethods:
    @pytest.mark.asyncio
    async def test_commit_ends_the_transaction_scoped_level(self):
        ex = _bare_iris_executor()
        _open_transaction_at(ex, "read committed")

        await ex.commit_transaction(session_id="s1")

        assert ex.get_isolation_level("s1") == "read uncommitted"

    @pytest.mark.asyncio
    async def test_rollback_ends_the_transaction_scoped_level(self):
        ex = _bare_iris_executor()
        _open_transaction_at(ex, "read committed")

        await ex.rollback_transaction(session_id="s1")

        assert ex.get_isolation_level("s1") == "read uncommitted"

    @pytest.mark.asyncio
    async def test_rollback_undoes_a_session_default_set_inside_the_transaction(self):
        ex = _bare_iris_executor()
        ex.session_isolation["s1"] = "read committed"
        ex._note_transaction_boundary("start", "s1")
        state = ex._isolation_state("s1")
        state.default_before_transaction = "read committed"
        state.default_changed_in_transaction = True
        ex.session_isolation["s1"] = "read uncommitted"

        await ex.rollback_transaction(session_id="s1")

        assert ex.get_default_isolation_level("s1") == "read committed"

    @pytest.mark.asyncio
    async def test_begin_opens_the_window(self):
        """Without this, a level set inside the transaction would never be cleared."""
        ex = _bare_iris_executor()

        await ex.begin_transaction(session_id="s1")

        assert ex._isolation_state("s1").in_transaction is True

    @pytest.mark.asyncio
    async def test_begin_resyncs_iris_to_the_level_now_in_force(self):
        """The last moment the level can be corrected is before the transaction opens."""
        ex = _bare_iris_executor()
        sent: list[str] = []

        async def fake_execute_query(sql, params=None, session_id=None, **kwargs):
            sent.append(sql)
            return {"success": True, "rows": [], "columns": [], "row_count": 0}

        ex.execute_query = fake_execute_query  # type: ignore[method-assign]
        # A previous transaction left IRIS at READ COMMITTED while the session
        # default, which is what we now report, is READ UNCOMMITTED.
        ex._isolation_state("s1").iris_level = "read committed"

        await ex.begin_transaction(session_id="s1")

        assert sent == ["SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"]

    @pytest.mark.asyncio
    async def test_a_session_id_is_not_required(self):
        """These are called without one on paths that have no session."""
        ex = _bare_iris_executor()

        await ex.begin_transaction()
        await ex.commit_transaction()
        await ex.rollback_transaction()


class TestTheDbapiBackendGoesThroughTheSqlPath:
    """Pins the coupling the DBAPI backend relies on instead of its own hook.

    If these stop going through `execute_query`, the mixin stops seeing the
    boundary and the transaction-scoped level stops ending — silently.
    """

    @pytest.mark.parametrize(
        "method, expected",
        [
            ("begin_transaction", "START TRANSACTION"),
            ("commit_transaction", "COMMIT"),
            ("rollback_transaction", "ROLLBACK"),
        ],
    )
    @pytest.mark.asyncio
    async def test_the_statement_reaches_execute_query(self, method, expected):
        ex = object.__new__(DBAPIExecutor)
        sent: list[str] = []

        async def fake_execute_query(sql, params=None, session_id=None, **kwargs):
            sent.append(sql)
            return {"success": True, "rows": [], "columns": [], "row_count": 0}

        ex.execute_query = fake_execute_query  # type: ignore[method-assign]

        await getattr(ex, method)(session_id="s1")

        assert sent == [expected]
