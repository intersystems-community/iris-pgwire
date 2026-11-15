"""A transaction's isolation level cannot be changed once it has read anything.

Accepting one would be the original defect in a new place: the client is told the
transaction runs at a level that cannot apply to the rows it has already read, so
whatever it concluded from those rows was concluded under the old level. There is
nothing to reread them under, IRIS having no snapshot to go back to.

PostgreSQL 16, measured (`postgres:16-alpine`), for the four spellings after a
transaction has already done something:

============================  ==================  ================================
After                         Transaction-scoped  Session-scoped
============================  ==================  ================================
nothing                       accepted            accepted
SHOW                          accepted            accepted
another SET                   accepted            accepted
SELECT                        25001               accepted
SAVEPOINT                     25001               accepted
============================  ==================  ================================

Two wordings, one SQLSTATE: after a query it is "must be called before any
query", inside a subtransaction "must not be called in a subtransaction". Three
further measured details drive the rest of this file:

* Re-asserting the level already in force is accepted even after a query — it
  changes nothing, and clients and pools re-assert constantly.
* An invalid level is rejected on its own terms (`22023` there, `0A000` here)
  rather than by the timing rule, so the level is checked first.
* `SAVEPOINT` enters a subtransaction and `RELEASE` leaves one;
  `ROLLBACK TO SAVEPOINT` leaves it open, so it is still a subtransaction.
"""

from __future__ import annotations

import pytest

from iris_pgwire._isolation import IsolationMixin


class _RecordingExecutor(IsolationMixin):
    # These tests pin the override mechanics against IRIS's own default, READ UNCOMMITTED: the
    # server run with PGWIRE_DEFAULT_ISOLATION=read uncommitted. The READ COMMITTED default of spec
    # 052 US7 is tested in test_default_isolation_config.py.
    default_isolation_level = "read uncommitted"

    def __init__(self):
        self.session_isolation: dict[str, str] = {}
        self.forwarded: list[str] = []

    async def execute_query(self, sql, params=None, session_id=None, **kwargs):
        self.forwarded.append(sql)
        return {"success": True, "rows": [], "columns": [], "row_count": 0}


async def _run(executor, sql, session_id="s1"):
    return await executor._handle_isolation_statement(sql, session_id=session_id)


async def _level(executor, session_id="s1") -> str:
    result = await _run(executor, "SHOW transaction_isolation", session_id)
    return result["rows"][0][0]


def _assert_refused(result, wording: str) -> None:
    assert result is not None and result["success"] is False
    assert result["sqlstate"] == "25001"
    assert wording in result["error"], result["error"]


TRANSACTION_SCOPED = [
    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
    "SET transaction_isolation = 'read committed'",
]
SESSION_SCOPED = [
    "SET default_transaction_isolation = 'read committed'",
    "SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED",
]


class TestBeforeTheTransactionHasDoneAnything:
    @pytest.mark.parametrize("sql", TRANSACTION_SCOPED + SESSION_SCOPED)
    @pytest.mark.asyncio
    async def test_accepted(self, sql):
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")

        result = await _run(ex, sql)

        assert result["success"] is True

    @pytest.mark.parametrize("first", ["SHOW transaction_isolation", "SET search_path = public"])
    @pytest.mark.asyncio
    async def test_a_show_or_a_plain_set_is_not_doing_anything(self, first):
        """Measured: neither trips the rule. Neither reads a row."""
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, first)

        result = await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        assert result["success"] is True


class TestAfterTheTransactionHasReadSomething:
    @pytest.mark.parametrize("sql", TRANSACTION_SCOPED)
    @pytest.mark.asyncio
    async def test_the_transaction_scoped_spellings_are_refused(self, sql):
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SELECT 1")

        _assert_refused(await _run(ex, sql), "before any query")

    @pytest.mark.asyncio
    async def test_the_refused_level_is_not_recorded(self):
        """Recording it would make SHOW report a level the transaction is not at."""
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SELECT 1")
        ex.forwarded.clear()

        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        assert await _level(ex) == "read uncommitted"
        assert ex.forwarded == [], "a refused level must not reach IRIS either"

    @pytest.mark.parametrize("sql", SESSION_SCOPED)
    @pytest.mark.asyncio
    async def test_the_session_scoped_spellings_are_still_accepted(self, sql):
        """They describe the next transaction, so this one having read is irrelevant."""
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SELECT 1")

        result = await _run(ex, sql)

        assert result["success"] is True
        assert ex.get_default_isolation_level("s1") == "read committed"

    @pytest.mark.asyncio
    async def test_re_asserting_the_level_in_force_is_accepted(self):
        """Measured on PostgreSQL 16, and clients and pools do this constantly."""
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        await _run(ex, "SELECT 1")

        result = await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        assert result["success"] is True
        assert await _level(ex) == "read committed"

    @pytest.mark.asyncio
    async def test_an_unsupported_level_is_refused_as_unsupported(self):
        """Measured precedence: the level is checked before the timing."""
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SELECT 1")

        result = await _run(ex, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")

        assert result["sqlstate"] == "0A000"

    @pytest.mark.asyncio
    async def test_outside_a_transaction_there_is_nothing_to_be_too_late_for(self):
        ex = _RecordingExecutor()
        await _run(ex, "SELECT 1")

        result = await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        assert result["success"] is True

    @pytest.mark.parametrize("ending", ["COMMIT", "ROLLBACK"])
    @pytest.mark.asyncio
    async def test_the_next_transaction_starts_clean(self, ending):
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SELECT 1")
        await _run(ex, ending)
        await _run(ex, "BEGIN")

        result = await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        assert result["success"] is True


class TestInsideASubtransaction:
    @pytest.mark.asyncio
    async def test_refused_with_the_subtransaction_wording(self):
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SAVEPOINT sp1")

        _assert_refused(
            await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"),
            "in a subtransaction",
        )

    @pytest.mark.asyncio
    async def test_releasing_the_savepoint_leaves_the_subtransaction(self):
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SAVEPOINT sp1")
        await _run(ex, "RELEASE SAVEPOINT sp1")

        result = await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_rolling_back_to_the_savepoint_does_not_leave_it(self):
        """The savepoint is still there to be rolled back to again."""
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SAVEPOINT sp1")
        await _run(ex, "ROLLBACK TO SAVEPOINT sp1")

        _assert_refused(
            await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"),
            "in a subtransaction",
        )

    @pytest.mark.asyncio
    async def test_nesting_is_counted(self):
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SAVEPOINT sp1")
        await _run(ex, "SAVEPOINT sp2")
        await _run(ex, "RELEASE SAVEPOINT sp2")

        _assert_refused(
            await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"),
            "in a subtransaction",
        )

    @pytest.mark.asyncio
    async def test_the_count_ends_with_the_transaction(self):
        ex = _RecordingExecutor()
        await _run(ex, "BEGIN")
        await _run(ex, "SAVEPOINT sp1")
        await _run(ex, "COMMIT")
        await _run(ex, "BEGIN")

        result = await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_a_savepoint_outside_a_transaction_is_ignored(self):
        """Clients send these; one arriving out of order must not wedge the session."""
        ex = _RecordingExecutor()
        await _run(ex, "SAVEPOINT sp1")

        result = await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        assert result["success"] is True
