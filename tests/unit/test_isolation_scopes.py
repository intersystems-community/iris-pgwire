"""`transaction_isolation` and `default_transaction_isolation` are two settings.

One session had one isolation level, so every spelling of the request wrote the
same slot and both GUCs read it back. That collapses a distinction PostgreSQL
makes and clients rely on: `SET TRANSACTION ISOLATION LEVEL x` lasts until the
transaction ends, `SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL x`
outlives it, and a connection pool that resets the session default cannot tell
the two apart if both write the same place.

Which spelling has which scope is measured, not recalled — against PostgreSQL 16
(`postgres:16-alpine`, read back through `SHOW`):

==================================================  ==========================
Statement                                           Scope
==================================================  ==========================
SET TRANSACTION ISOLATION LEVEL x                   transaction
SET SESSION TRANSACTION ISOLATION LEVEL x           transaction  (not session)
SET LOCAL TRANSACTION ISOLATION LEVEL x             transaction
SET transaction_isolation = x                       transaction
SET SESSION transaction_isolation = x               transaction
SET LOCAL transaction_isolation = x                 transaction
BEGIN / START TRANSACTION ... ISOLATION LEVEL x     transaction
SET SESSION CHARACTERISTICS AS TRANSACTION ISO. x   session
SET default_transaction_isolation = x               session
==================================================  ==========================

`SET SESSION TRANSACTION ISOLATION LEVEL` is the one worth naming: the keyword
says SESSION and the scope is the transaction. Reading it the obvious way would
have left the level in force for the rest of the connection.

Also measured: a transaction-scoped level is gone after COMMIT as well as after
ROLLBACK, and a *session* default set inside a transaction is undone by ROLLBACK
but kept by COMMIT — PostgreSQL rolls back `SET` along with everything else.
"""

from __future__ import annotations

import pytest

from iris_pgwire._isolation import IsolationMixin
from iris_pgwire.sql_translator.isolation import (
    SESSION_SCOPE,
    TRANSACTION_SCOPE,
    parse_begin_isolation,
    parse_set_isolation,
    parse_transaction_boundary,
)

# ---------------------------------------------------------------------------
# Which spelling has which scope
# ---------------------------------------------------------------------------


class TestTheScopeOfEachSpelling:
    @pytest.mark.parametrize(
        "sql",
        [
            "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
            # Says SESSION, scoped to the transaction. Measured, not assumed.
            "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "SET LOCAL TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "SET transaction_isolation = 'read committed'",
            "SET SESSION transaction_isolation = 'read committed'",
            "SET LOCAL transaction_isolation = 'read committed'",
            "SET transaction_isolation TO 'read committed'",
        ],
    )
    def test_transaction_scoped_spellings(self, sql):
        assert parse_set_isolation(sql).scope == TRANSACTION_SCOPE

    @pytest.mark.parametrize(
        "sql",
        [
            "SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "SET default_transaction_isolation = 'read committed'",
            "SET SESSION default_transaction_isolation = 'read committed'",
            "SET default_transaction_isolation TO 'read committed'",
        ],
    )
    def test_session_scoped_spellings(self, sql):
        assert parse_set_isolation(sql).scope == SESSION_SCOPE

    @pytest.mark.parametrize(
        "sql",
        [
            "BEGIN ISOLATION LEVEL READ COMMITTED",
            "START TRANSACTION ISOLATION LEVEL READ COMMITTED",
        ],
    )
    def test_a_level_named_on_the_transaction_start_is_transaction_scoped(self, sql):
        """It cannot outlive the transaction it was named on."""
        assert parse_begin_isolation(sql).scope == TRANSACTION_SCOPE

    def test_the_scope_does_not_depend_on_the_level_being_supported(self):
        """A refused request still carries its scope, so refusing stays uniform."""
        request = parse_set_isolation("SET default_transaction_isolation = 'serializable'")
        assert request.supported is False
        assert request.scope == SESSION_SCOPE


# ---------------------------------------------------------------------------
# Recognising the end of a transaction
# ---------------------------------------------------------------------------


class TestTransactionBoundaries:
    @pytest.mark.parametrize(
        "sql, boundary",
        [
            ("BEGIN", "start"),
            ("begin transaction", "start"),
            ("START TRANSACTION", "start"),
            ("BEGIN ISOLATION LEVEL READ COMMITTED", "start"),
            ("COMMIT", "commit"),
            ("commit work", "commit"),
            # PostgreSQL's END is COMMIT.
            ("END", "commit"),
            ("ROLLBACK", "rollback"),
            ("rollback;", "rollback"),
        ],
    )
    def test_recognised(self, sql, boundary):
        assert parse_transaction_boundary(sql) == boundary

    @pytest.mark.parametrize(
        "sql",
        [
            # Rolling back to a savepoint leaves the transaction open, so the
            # transaction-scoped level is still the one in force.
            "ROLLBACK TO SAVEPOINT sp1",
            "ROLLBACK TO sp1",
            "SAVEPOINT sp1",
            "RELEASE SAVEPOINT sp1",
            "SELECT 1",
            "COMMITTED",
            "",
        ],
    )
    def test_not_a_boundary(self, sql):
        assert parse_transaction_boundary(sql) is None


# ---------------------------------------------------------------------------
# The two slots, through the mixin
# ---------------------------------------------------------------------------


class _RecordingExecutor(IsolationMixin):
    """Answers as IRIS would on success, and records what it was sent."""

    def __init__(self):
        self.session_isolation: dict[str, str] = {}
        self.forwarded: list[str] = []

    async def execute_query(self, sql, params=None, session_id=None, **kwargs):
        self.forwarded.append(sql)
        return {"success": True, "rows": [], "columns": [], "row_count": 0}


async def _run(executor, sql, session_id="s1"):
    return await executor._handle_isolation_statement(sql, session_id=session_id)


async def _show(executor, guc, session_id="s1"):
    result = await _run(executor, f"SHOW {guc}", session_id)
    assert result is not None, f"SHOW {guc} was not answered"
    return result["rows"][0][0]


class TestTheTwoSlotsAreDistinct:
    @pytest.mark.asyncio
    async def test_a_transaction_scoped_set_does_not_move_the_session_default(self):
        ex = _RecordingExecutor()

        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        assert await _show(ex, "transaction_isolation") == "read committed"
        assert await _show(ex, "default_transaction_isolation") == "read uncommitted"

    @pytest.mark.asyncio
    async def test_a_session_scoped_set_moves_both(self):
        """The default is what a new transaction starts at, so the current one follows."""
        ex = _RecordingExecutor()

        await _run(ex, "SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED")

        assert await _show(ex, "default_transaction_isolation") == "read committed"
        assert await _show(ex, "transaction_isolation") == "read committed"

    @pytest.mark.asyncio
    async def test_the_override_wins_over_the_session_default(self):
        ex = _RecordingExecutor()

        await _run(ex, "SET default_transaction_isolation = 'read committed'")
        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

        assert await _show(ex, "transaction_isolation") == "read uncommitted"
        assert await _show(ex, "default_transaction_isolation") == "read committed"

    @pytest.mark.asyncio
    async def test_an_untouched_session_reports_the_iris_default_for_both(self):
        ex = _RecordingExecutor()

        assert await _show(ex, "transaction_isolation") == "read uncommitted"
        assert await _show(ex, "default_transaction_isolation") == "read uncommitted"

    @pytest.mark.asyncio
    async def test_the_verbose_show_asks_about_the_current_level(self):
        """`SHOW TRANSACTION ISOLATION LEVEL` is the current one, not the default."""
        ex = _RecordingExecutor()

        await _run(ex, "SET default_transaction_isolation = 'read committed'")
        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

        result = await _run(ex, "SHOW TRANSACTION ISOLATION LEVEL")
        assert result["rows"][0][0] == "read uncommitted"


class TestTheOverrideEndsWithTheTransaction:
    @pytest.mark.parametrize("ending", ["COMMIT", "ROLLBACK", "END"])
    @pytest.mark.asyncio
    async def test_cleared_however_the_transaction_ends(self, ending):
        """Measured on PostgreSQL 16: gone after COMMIT as well as after ROLLBACK."""
        ex = _RecordingExecutor()

        await _run(ex, "BEGIN")
        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        assert await _show(ex, "transaction_isolation") == "read committed"

        await _run(ex, ending)

        assert await _show(ex, "transaction_isolation") == "read uncommitted"

    @pytest.mark.asyncio
    async def test_a_level_named_on_begin_ends_with_that_transaction(self):
        ex = _RecordingExecutor()

        await _run(ex, "BEGIN ISOLATION LEVEL READ COMMITTED")
        assert await _show(ex, "transaction_isolation") == "read committed"

        await _run(ex, "COMMIT")

        assert await _show(ex, "transaction_isolation") == "read uncommitted"

    @pytest.mark.asyncio
    async def test_rolling_back_to_a_savepoint_keeps_it(self):
        ex = _RecordingExecutor()

        await _run(ex, "BEGIN")
        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        await _run(ex, "ROLLBACK TO SAVEPOINT sp1")

        assert await _show(ex, "transaction_isolation") == "read committed"

    @pytest.mark.asyncio
    async def test_the_session_default_survives_the_transaction(self):
        ex = _RecordingExecutor()

        await _run(ex, "BEGIN")
        await _run(ex, "SET default_transaction_isolation = 'read committed'")
        await _run(ex, "COMMIT")

        assert await _show(ex, "default_transaction_isolation") == "read committed"
        assert await _show(ex, "transaction_isolation") == "read committed"


class TestRollbackUndoesASessionDefaultSetInsideIt:
    """Measured on PostgreSQL 16, and easy to miss: `SET` is transactional too.

    A `SET default_transaction_isolation` inside a transaction that then rolls
    back leaves the session at the value it had before the transaction. A pool
    that resets the session default in a transaction it later abandons would
    otherwise hand out a connection whose reported default never happened.
    """

    @pytest.mark.asyncio
    async def test_rollback_restores_the_previous_default(self):
        ex = _RecordingExecutor()

        await _run(ex, "SET default_transaction_isolation = 'read committed'")
        await _run(ex, "BEGIN")
        await _run(ex, "SET default_transaction_isolation = 'read uncommitted'")
        await _run(ex, "ROLLBACK")

        assert await _show(ex, "default_transaction_isolation") == "read committed"

    @pytest.mark.asyncio
    async def test_commit_keeps_the_new_default(self):
        ex = _RecordingExecutor()

        await _run(ex, "BEGIN")
        await _run(ex, "SET default_transaction_isolation = 'read committed'")
        await _run(ex, "COMMIT")

        assert await _show(ex, "default_transaction_isolation") == "read committed"

    @pytest.mark.asyncio
    async def test_only_the_value_from_before_the_transaction_is_restored(self):
        """Two changes in one transaction restore to before the first, not the second."""
        ex = _RecordingExecutor()

        await _run(ex, "BEGIN")
        await _run(ex, "SET default_transaction_isolation = 'read committed'")
        await _run(ex, "SET default_transaction_isolation = 'read uncommitted'")
        await _run(ex, "ROLLBACK")

        assert await _show(ex, "default_transaction_isolation") == "read uncommitted"


class TestIrisIsToldWhatWeReport:
    """The slots are bookkeeping; IRIS has one isolation level per session.

    So when the effective level changes without a statement of its own — which is
    what clearing the override at the end of a transaction does — IRIS has to be
    told, or `SHOW` goes back to reporting a level the session is not running at.
    That is the original defect, and it would return by this route.
    """

    @pytest.mark.asyncio
    async def test_the_next_statement_resyncs_iris_after_the_override_ends(self):
        ex = _RecordingExecutor()

        await _run(ex, "BEGIN ISOLATION LEVEL READ COMMITTED")
        await _run(ex, "COMMIT")
        ex.forwarded.clear()

        await _run(ex, "SELECT 1")

        assert ex.forwarded == ["SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"]

    @pytest.mark.asyncio
    async def test_nothing_is_resent_when_the_level_has_not_moved(self):
        ex = _RecordingExecutor()

        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        ex.forwarded.clear()

        await _run(ex, "SELECT 1")
        await _run(ex, "SELECT 2")

        assert ex.forwarded == []

    @pytest.mark.asyncio
    async def test_an_untouched_session_never_sends_a_set(self):
        """A session that asked for nothing is left at whatever IRIS starts at."""
        ex = _RecordingExecutor()

        await _run(ex, "SELECT 1")

        assert ex.forwarded == []

    @pytest.mark.asyncio
    async def test_the_resync_happens_on_the_begin_and_not_inside_the_transaction(self):
        """Changing the level mid-transaction is exactly what PostgreSQL refuses.

        So the correction goes just before the transaction opens, which is also
        the only place it is any use: a transaction that inherited the level of
        the one before it would run at it from its first statement to its last.
        """
        ex = _RecordingExecutor()

        await _run(ex, "BEGIN ISOLATION LEVEL READ COMMITTED")
        await _run(ex, "COMMIT")
        ex.forwarded.clear()

        await _run(ex, "BEGIN")
        assert ex.forwarded == ["SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"]

        ex.forwarded.clear()
        await _run(ex, "SELECT 1")
        assert ex.forwarded == []


class TestForgettingASession:
    @pytest.mark.asyncio
    async def test_both_slots_are_dropped(self):
        ex = _RecordingExecutor()

        await _run(ex, "SET default_transaction_isolation = 'read committed'")
        await _run(ex, "BEGIN")
        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

        ex.forget_isolation_level("s1")

        assert await _show(ex, "transaction_isolation") == "read uncommitted"
        assert await _show(ex, "default_transaction_isolation") == "read uncommitted"
        assert ex.session_isolation == {}

    @pytest.mark.asyncio
    async def test_a_reused_session_id_starts_clean(self):
        """Session ids are reused, so leftover state would be another client's."""
        ex = _RecordingExecutor()

        await _run(ex, "BEGIN")
        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        ex.forget_isolation_level("s1")
        ex.forwarded.clear()

        # Nothing to resync: the new session inherits no expectation.
        await _run(ex, "SELECT 1")

        assert ex.forwarded == []


class TestSessionsDoNotShareSlots:
    @pytest.mark.asyncio
    async def test_the_override_is_per_session(self):
        ex = _RecordingExecutor()

        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED", session_id="a")

        assert await _show(ex, "transaction_isolation", session_id="b") == "read uncommitted"

    @pytest.mark.asyncio
    async def test_one_sessions_commit_does_not_clear_anothers_override(self):
        ex = _RecordingExecutor()

        await _run(ex, "BEGIN", session_id="a")
        await _run(ex, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED", session_id="a")
        await _run(ex, "COMMIT", session_id="b")

        assert await _show(ex, "transaction_isolation", session_id="a") == "read committed"
