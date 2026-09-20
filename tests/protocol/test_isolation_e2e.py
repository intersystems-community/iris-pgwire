"""End-to-end isolation-level behaviour, through the wire, with real psycopg.

These assert what a client observes, which is the part that was wrong. Unit
tests cover the parsing; only a real connection can show that
`SET TRANSACTION ISOLATION LEVEL READ COMMITTED` now reaches IRIS instead of
being answered by a shim, and that a lock conflict arrives as a retryable
SQLSTATE instead of `42000`.

Requires the IRIS container. `docker compose up -d` first; these do not skip
themselves, because a skipped isolation test is indistinguishable from a passing
one in CI and this is exactly the behaviour that went unnoticed.

Run this module in its own pytest process. Appended to a run of tests/unit, the
six tests here that need two independent sessions — the lock-conflict pair,
optimistic locking, the READ COMMITTED pin and TestCrossSessionIsolation — fail:
by then something in that suite has left the process believing every session
shares one IRIS transaction, which is the in-IRIS shape, not the DBAPI one the
fixture asks for. That contamination predates this module and is not diagnosed
here; the single-session tests are unaffected either way.
"""

from __future__ import annotations

import threading
import time

import psycopg
import pytest

# PostgreSQL's spelling of the levels; a client parses the reply against these.
VALID_PG_LEVELS = {"read uncommitted", "read committed", "repeatable read", "serializable"}


def _show(cur, statement: str) -> str:
    cur.execute(statement)
    row = cur.fetchone()
    assert row is not None, f"{statement} returned no row"
    return row[0]


class TestShowReportsRealState:
    def test_guc_spelling_is_answered(self, pgwire_client):
        """`SHOW transaction_isolation` is what psycopg and SQLAlchemy send.

        It used to miss the SHOW lookup table entirely and fall through to the
        unknown-parameter branch, which returns an empty string.
        """
        with pgwire_client.cursor() as cur:
            value = _show(cur, "SHOW transaction_isolation")
        assert value != "", "the GUC spelling returned an empty setting"
        assert value in VALID_PG_LEVELS

    def test_verbose_spelling_is_answered(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            value = _show(cur, "SHOW TRANSACTION ISOLATION LEVEL")
        assert value in VALID_PG_LEVELS

    def test_both_spellings_agree(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            guc = _show(cur, "SHOW transaction_isolation")
            verbose = _show(cur, "SHOW TRANSACTION ISOLATION LEVEL")
        assert guc == verbose

    def test_untouched_session_reports_iris_default(self, pgwire_client):
        """IRIS runs READ UNCOMMITTED until told otherwise.

        This used to report "read committed" unconditionally — a claim no session
        had earned, since the SET that would earn it was being discarded.
        """
        with pgwire_client.cursor() as cur:
            assert _show(cur, "SHOW transaction_isolation") == "read uncommitted"


class TestSetTakesEffect:
    @pytest.mark.parametrize("level", ["READ COMMITTED", "READ UNCOMMITTED"])
    def test_supported_level_is_reflected_by_show(self, pgwire_client, level):
        with pgwire_client.cursor() as cur:
            cur.execute(f"SET TRANSACTION ISOLATION LEVEL {level}")
            assert _show(cur, "SHOW transaction_isolation") == level.lower()

    def test_guc_form_also_takes_effect(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            cur.execute("SET transaction_isolation = 'read committed'")
            assert _show(cur, "SHOW transaction_isolation") == "read committed"

    def test_level_does_not_leak_between_sessions(self, pgwire_server, pgwire_connection_params):
        """Per-session state, not server-global."""
        with psycopg.connect(**pgwire_connection_params) as a:
            with a.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                assert _show(cur, "SHOW transaction_isolation") == "read committed"

            with psycopg.connect(**pgwire_connection_params) as b, b.cursor() as cur_b:
                assert _show(cur_b, "SHOW transaction_isolation") == "read uncommitted"


class TestUnsupportedLevelsAreRefused:
    @pytest.mark.parametrize("level", ["SERIALIZABLE", "REPEATABLE READ"])
    def test_refused_with_feature_not_supported(self, pgwire_client, level):
        """IRIS has no snapshot isolation, so these cannot be honoured.

        Answering success would tell the client guarantees hold that do not. The
        error is `0A000`, which is how PostgreSQL says "this server cannot do
        that" — distinguishable from a syntax error in the client's SQL.
        """
        with pgwire_client.cursor() as cur:
            with pytest.raises(psycopg.Error) as excinfo:
                cur.execute(f"SET TRANSACTION ISOLATION LEVEL {level}")
        assert (
            excinfo.value.sqlstate == "0A000"
        ), f"expected feature_not_supported, got {excinfo.value.sqlstate}"
        pgwire_client.rollback()

    def test_refusal_does_not_change_the_reported_level(
        self, pgwire_server, pgwire_connection_params
    ):
        """Autocommit, because the refusal has to be survived without a rollback.

        A rollback would end the transaction the level belongs to and clear it for
        a reason that has nothing to do with the refusal — see
        TestTheTwoSettingsAreDistinct.
        """
        with psycopg.connect(**pgwire_connection_params) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                with pytest.raises(psycopg.Error):
                    cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                assert _show(cur, "SHOW transaction_isolation") == "read committed"


class TestTheLevelNamedOnBegin:
    """`BEGIN ISOLATION LEVEL x` is what psycopg3 sends when given isolation_level.

    Handling only `SET` left the same request unrecorded and unrefused in the
    spelling clients reach for first, which is the original defect wearing a
    different statement.
    """

    def test_show_reflects_a_level_set_on_begin(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            cur.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
            assert _show(cur, "SHOW transaction_isolation") == "read committed"
        pgwire_client.rollback()

    def test_show_reflects_a_level_set_on_start_transaction(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            cur.execute("START TRANSACTION ISOLATION LEVEL READ COMMITTED")
            assert _show(cur, "SHOW transaction_isolation") == "read committed"
        pgwire_client.rollback()

    @pytest.mark.parametrize("level", ["SERIALIZABLE", "REPEATABLE READ"])
    def test_an_unsupported_level_on_begin_is_refused(self, pgwire_client, level):
        """Same answer as on SET, or the refusal is one keyword away from bypassed."""
        with pgwire_client.cursor() as cur:
            with pytest.raises(psycopg.Error) as excinfo:
                cur.execute(f"BEGIN ISOLATION LEVEL {level}")
        assert (
            excinfo.value.sqlstate == "0A000"
        ), f"expected feature_not_supported on BEGIN, got {excinfo.value.sqlstate}"
        pgwire_client.rollback()

    @pytest.mark.parametrize(
        "sql, tag",
        [
            # IRIS has no BEGIN statement, so BEGIN is sent on as START TRANSACTION.
            # The reply must not show that: measured on PostgreSQL 16, BEGIN is
            # answered `BEGIN` and START TRANSACTION is answered `START TRANSACTION`.
            ("BEGIN ISOLATION LEVEL READ COMMITTED", "BEGIN"),
            ("START TRANSACTION ISOLATION LEVEL READ COMMITTED", "START TRANSACTION"),
        ],
    )
    def test_the_command_tag_is_the_clients_own_verb(self, pgwire_client, sql, tag):
        with pgwire_client.cursor() as cur:
            cur.execute(sql)
            assert cur.statusmessage == tag
        pgwire_client.rollback()

    def test_a_plain_begin_still_works(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
        pgwire_client.rollback()


class TestTheTwoSettingsAreDistinct:
    """`transaction_isolation` ends with the transaction; the default does not.

    Both used to be one slot, so `SET TRANSACTION ISOLATION LEVEL x` silently
    became the connection's default and a pooled connection handed on a level
    nobody asked for. Which spelling has which scope is measured against
    PostgreSQL 16 — see tests/unit/test_isolation_scopes.py.

    These go through a real psycopg connection in its default non-autocommit mode,
    which is what makes them worth running through the wire: psycopg sends its own
    BEGIN and COMMIT around the statements, and those boundaries are exactly what
    the scoping depends on.
    """

    def test_the_default_is_answered_in_its_own_right(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            assert _show(cur, "SHOW default_transaction_isolation") in VALID_PG_LEVELS

    def test_a_transaction_scoped_set_leaves_the_default_alone(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            assert _show(cur, "SHOW transaction_isolation") == "read committed"
            assert _show(cur, "SHOW default_transaction_isolation") == "read uncommitted"
        pgwire_client.rollback()

    def test_the_override_ends_with_the_transaction(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            assert _show(cur, "SHOW transaction_isolation") == "read committed"
        pgwire_client.commit()

        with pgwire_client.cursor() as cur:
            assert _show(cur, "SHOW transaction_isolation") == "read uncommitted"
        pgwire_client.rollback()

    def test_a_level_named_on_begin_ends_with_that_transaction(self, pgwire_client):
        pgwire_client.rollback()  # psycopg has not opened one yet; make it explicit
        with pgwire_client.cursor() as cur:
            cur.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
            assert _show(cur, "SHOW transaction_isolation") == "read committed"
            cur.execute("COMMIT")
            assert _show(cur, "SHOW transaction_isolation") == "read uncommitted"
        pgwire_client.rollback()

    def test_the_session_default_outlives_the_transaction(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED")
        pgwire_client.commit()

        with pgwire_client.cursor() as cur:
            assert _show(cur, "SHOW default_transaction_isolation") == "read committed"
            # And a transaction that names no level of its own starts at it.
            assert _show(cur, "SHOW transaction_isolation") == "read committed"
        pgwire_client.rollback()

    def test_the_guc_spelling_of_the_default_also_sets_it(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            cur.execute("SET default_transaction_isolation = 'read committed'")
        pgwire_client.commit()

        with pgwire_client.cursor() as cur:
            assert _show(cur, "SHOW default_transaction_isolation") == "read committed"
        pgwire_client.rollback()

    def test_the_session_is_usable_after_the_override_ends(self, pgwire_client):
        """The end of the override re-sends a level to IRIS; it must not break the session.

        IRIS has one isolation level per session, so when the reported level
        changes because a transaction ended, IRIS is told before the next
        transaction opens. That statement is invisible to the client — unless it
        fails, which is what this would catch.
        """
        with pgwire_client.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        pgwire_client.commit()

        with pgwire_client.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
            assert _show(cur, "SHOW transaction_isolation") == "read uncommitted"
        pgwire_client.rollback()

    def test_the_default_does_not_leak_between_sessions(
        self, pgwire_server, pgwire_connection_params
    ):
        with psycopg.connect(**pgwire_connection_params) as a:
            with a.cursor() as cur:
                cur.execute("SET default_transaction_isolation = 'read committed'")
            a.commit()

            with psycopg.connect(**pgwire_connection_params) as b, b.cursor() as cur_b:
                assert _show(cur_b, "SHOW default_transaction_isolation") == "read uncommitted"


class TestTheLevelCannotChangeMidTransaction:
    """Once the transaction has read something, its level is settled.

    Accepting the change would be the original defect in a new place: the client
    is told the transaction runs at a level that cannot apply to rows it has
    already read. IRIS has no snapshot to reread them under, so there is nothing
    the acceptance could mean. PostgreSQL 16 answers `25001`; measured, along with
    the two wordings it uses — see tests/unit/test_isolation_mid_transaction.py.
    """

    def test_refused_after_a_query_with_25001(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            cur.execute("SELECT 1")
            with pytest.raises(psycopg.Error) as excinfo:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        assert (
            excinfo.value.sqlstate == "25001"
        ), f"expected active_sql_transaction, got {excinfo.value.sqlstate}"
        assert "before any query" in str(excinfo.value)
        pgwire_client.rollback()

    def test_the_refused_level_is_not_reported(self, pgwire_client):
        """The transaction keeps the level it actually ran the SELECT at."""
        with pgwire_client.cursor() as cur:
            cur.execute("SELECT 1")
            with pytest.raises(psycopg.Error):
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            assert _show(cur, "SHOW transaction_isolation") == "read uncommitted"
        pgwire_client.rollback()

    def test_the_session_default_is_still_settable(self, pgwire_client):
        """It describes the next transaction, so this one having read is irrelevant."""
        with pgwire_client.cursor() as cur:
            cur.execute("SELECT 1")
            cur.execute("SET default_transaction_isolation = 'read committed'")
            assert _show(cur, "SHOW default_transaction_isolation") == "read committed"
        pgwire_client.rollback()

    def test_the_next_transaction_may_set_its_own_level(self, pgwire_client):
        with pgwire_client.cursor() as cur:
            cur.execute("SELECT 1")
            with pytest.raises(psycopg.Error):
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        pgwire_client.rollback()

        with pgwire_client.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            assert _show(cur, "SHOW transaction_isolation") == "read committed"
        pgwire_client.rollback()

    def test_before_any_query_it_is_accepted(self, pgwire_client):
        """The boundary itself: a SET as the transaction's first statement is fine."""
        pgwire_client.rollback()
        with pgwire_client.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            assert _show(cur, "SHOW transaction_isolation") == "read committed"
            cur.execute("COMMIT")
        pgwire_client.rollback()


class TestLockConflictIsRetryable:
    """A write-write conflict must not reach the client as broken SQL.

    IRIS reports a lock timeout (`SQLCODE -110`); with no MVCC that is the only
    way a conflict surfaces. It used to arrive as `42000`
    (`syntax_error_or_access_rule_violation`), which no retry helper retries.
    """

    def test_conflicting_update_reports_serialization_failure(
        self, pgwire_server, pgwire_connection_params
    ):
        table = f"iso_lock_{int(time.time())}"

        with psycopg.connect(**pgwire_connection_params) as setup:
            setup.autocommit = True
            with setup.cursor() as cur:
                cur.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, v INT)")
                cur.execute(f"INSERT INTO {table} (id, v) VALUES (1, 1)")

        holder_ready = threading.Event()
        release_holder = threading.Event()
        holder_error: list[Exception] = []

        def hold_the_row():
            try:
                with psycopg.connect(**pgwire_connection_params) as holder:
                    with holder.cursor() as cur:
                        # No commit: the row stays locked by an open transaction.
                        cur.execute(f"UPDATE {table} SET v = 2 WHERE id = 1")
                    holder_ready.set()
                    release_holder.wait(timeout=60)
                    holder.rollback()
            except Exception as e:  # surfaced in the assertion below
                holder_error.append(e)
                holder_ready.set()

        thread = threading.Thread(target=hold_the_row, daemon=True)
        thread.start()
        assert holder_ready.wait(timeout=30), "holder never acquired the row lock"
        assert not holder_error, f"holder failed instead of locking: {holder_error}"

        try:
            with psycopg.connect(**pgwire_connection_params) as contender:
                with contender.cursor() as cur:
                    with pytest.raises(psycopg.Error) as excinfo:
                        cur.execute(f"UPDATE {table} SET v = 3 WHERE id = 1")
        finally:
            release_holder.set()
            thread.join(timeout=30)

        assert excinfo.value.sqlstate == "40001", (
            f"a lock conflict must be retryable; got {excinfo.value.sqlstate} "
            f"for {excinfo.value}"
        )

        with psycopg.connect(**pgwire_connection_params) as cleanup:
            cleanup.autocommit = True
            with cleanup.cursor() as cur:
                cur.execute(f"DROP TABLE {table}")


class TestReaderConflictIsRetryable:
    """The reader's half of a conflict, which reports a different SQLCODE.

    A writer meeting a held row gets `-110`; a reader at READ COMMITTED meeting
    one gets `-114`, and gets it while fetching rather than while preparing. Both
    must reach the client as `40001`, because both are the same event — IRIS has
    no snapshot to read instead — and both are retryable.
    """

    def test_read_committed_reader_reports_serialization_failure(
        self, pgwire_server, pgwire_connection_params
    ):
        table = f"iso_read_{int(time.time())}"

        with psycopg.connect(**pgwire_connection_params) as setup:
            setup.autocommit = True
            with setup.cursor() as cur:
                cur.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, n INT)")
                cur.execute(f"INSERT INTO {table} (id, n) VALUES (1, 100)")

        holder_ready = threading.Event()
        release_holder = threading.Event()
        holder_error: list[Exception] = []

        def hold_the_row():
            try:
                with psycopg.connect(**pgwire_connection_params) as holder:
                    with holder.cursor() as cur:
                        cur.execute(f"UPDATE {table} SET n = 999 WHERE id = 1")
                    holder_ready.set()
                    release_holder.wait(timeout=60)
                    holder.rollback()
            except Exception as e:
                holder_error.append(e)
                holder_ready.set()

        thread = threading.Thread(target=hold_the_row, daemon=True)
        thread.start()
        assert holder_ready.wait(timeout=30), "holder never acquired the row lock"
        assert not holder_error, f"holder failed instead of locking: {holder_error}"

        try:
            with psycopg.connect(**pgwire_connection_params) as reader:
                with reader.cursor() as cur:
                    cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                    with pytest.raises(psycopg.Error) as excinfo:
                        cur.execute(f"SELECT n FROM {table} WHERE id = 1")
                        cur.fetchall()
        finally:
            release_holder.set()
            thread.join(timeout=30)

        assert excinfo.value.sqlstate == "40001", (
            f"a reader's lock conflict must be retryable; got "
            f"{excinfo.value.sqlstate} for {excinfo.value}"
        )

        with psycopg.connect(**pgwire_connection_params) as cleanup:
            cleanup.autocommit = True
            with cleanup.cursor() as cur:
                cur.execute(f"DROP TABLE {table}")


@pytest.mark.pinned_limitation
class TestOptimisticLockingReportsFalseConflicts:
    """Codifies a known limitation so a change in it cannot pass unnoticed.

    This asserts behaviour that is *wrong* by PostgreSQL's standards and cannot be
    fixed at the wire layer — it is pinned, not endorsed. See KNOWN_LIMITATIONS.md,
    "Optimistic Locking Reports False Conflicts". If this test starts failing, the
    limitation has changed and the documentation needs updating.

    `UPDATE t SET ver = 2 WHERE id = ? AND ver = 1` is how SQLAlchemy
    `version_id_col`, JPA `@Version`, ActiveRecord `lock_version` and Django's
    equivalent detect concurrent modification. While another session holds the new
    version uncommitted, the predicate matches nothing, so nothing contends and the
    second session is told zero rows — which every one of those frameworks reads as
    "someone else changed this row" even though nothing was ever committed.
    """

    def test_version_guarded_update_sees_zero_rows_without_a_commit(
        self, pgwire_server, pgwire_connection_params
    ):
        table = f"iso_optlock_{int(time.time())}"

        with psycopg.connect(**pgwire_connection_params) as setup:
            setup.autocommit = True
            with setup.cursor() as cur:
                cur.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, ver INT)")
                cur.execute(f"INSERT INTO {table} (id, ver) VALUES (3, 1)")

        guarded = f"UPDATE {table} SET ver = 2 WHERE id = 3 AND ver = 1"
        try:
            with psycopg.connect(**pgwire_connection_params) as a:
                with a.cursor() as ca:
                    ca.execute(guarded)
                    assert ca.rowcount == 1, "the first session should win the row"

                # Not committed. On PostgreSQL the second session would block here
                # and then report rowcount 1 once the first rolled back.
                with psycopg.connect(**pgwire_connection_params) as b, b.cursor() as cb:
                    cb.execute(guarded)
                    assert cb.rowcount == 0, (
                        "KNOWN_LIMITATIONS records rowcount 0 here; a different "
                        "answer means the limitation changed"
                    )

                a.rollback()

            with psycopg.connect(**pgwire_connection_params) as check:
                check.autocommit = True
                with check.cursor() as cur:
                    cur.execute(f"SELECT ver FROM {table} WHERE id = 3")
                    assert cur.fetchone()[0] == 1, (
                        "nothing was ever committed — which is what makes the "
                        "zero row count a false conflict rather than a real one"
                    )
        finally:
            with psycopg.connect(**pgwire_connection_params) as cleanup:
                cleanup.autocommit = True
                with cleanup.cursor() as cur:
                    cur.execute(f"DROP TABLE {table}")


@pytest.mark.pinned_limitation
@pytest.mark.slow
class TestAnAcceptedReadCommittedIsNotAGuarantee:
    """IRIS accepting READ COMMITTED does not mean READ COMMITTED is in force.

    Pinned, not endorsed. Measured against `iris-pgwire-db` (IRIS 2026.1 CE) with a
    writer holding one row uncommitted, a reader that has just had
    `SET TRANSACTION ISOLATION LEVEL READ COMMITTED` accepted with SQLCODE 0 does
    one of two things:

        waits a flat 10.0s lock timeout and fails, SQLCODE -114 -> `40001`
        returns the uncommitted value immediately, no wait and no error

    The disjunction *is* the limitation: a client cannot tell which it will get, and
    the trigger for the second shape was not isolated — not statement text, not
    reader index, not whether the SET preceded or followed the first read, not
    whether a transaction was explicitly open. (An earlier "isolation is sticky per
    statement text" model was measured, published and then retracted; it does not
    reproduce.) So this asserts the set of outcomes rather than one of them. A
    result outside the set means the behaviour changed and KNOWN_LIMITATIONS.md is
    stale.

    The 10s lock timeout is why this is marked slow: anything that waits on a
    contended read needs a budget above 10 seconds, not the usual few.
    """

    def test_the_reader_either_times_out_or_reads_dirty(
        self, pgwire_server, pgwire_connection_params
    ):
        table = f"iso_unreliable_{int(time.time())}"

        with psycopg.connect(**pgwire_connection_params) as setup:
            setup.autocommit = True
            with setup.cursor() as cur:
                cur.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, n INT)")
                cur.execute(f"INSERT INTO {table} (id, n) VALUES (1, 100)")

        holder_ready = threading.Event()
        release_holder = threading.Event()
        holder_error: list[Exception] = []

        def hold_the_row():
            try:
                with psycopg.connect(**pgwire_connection_params) as holder:
                    with holder.cursor() as cur:
                        cur.execute(f"UPDATE {table} SET n = 999 WHERE id = 1")
                    holder_ready.set()
                    release_holder.wait(timeout=90)
                    holder.rollback()
            except Exception as e:
                holder_error.append(e)
                holder_ready.set()

        thread = threading.Thread(target=hold_the_row, daemon=True)
        thread.start()
        assert holder_ready.wait(timeout=30), "holder never acquired the row lock"
        assert not holder_error, f"holder failed instead of locking: {holder_error}"

        waited = 0.0
        value: int | None = None
        sqlstate: str | None = None
        try:
            with psycopg.connect(**pgwire_connection_params) as reader:
                with reader.cursor() as cur:
                    cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                    assert _show(cur, "SHOW transaction_isolation") == "read committed", (
                        "the level was not even accepted; this test is about an "
                        "accepted level not holding"
                    )
                    started = time.perf_counter()
                    try:
                        cur.execute(f"SELECT n FROM {table} WHERE id = 1")
                        value = cur.fetchone()[0]
                    except psycopg.Error as e:
                        sqlstate = e.sqlstate
                    waited = time.perf_counter() - started
        finally:
            release_holder.set()
            thread.join(timeout=60)

        if sqlstate is not None:
            assert sqlstate == "40001", (
                f"a lock conflict must still arrive retryable; got {sqlstate}. "
                f"KNOWN_LIMITATIONS records -114 -> 40001 here"
            )
            assert waited > 5.0, (
                f"the honoured shape waits out the 10s IRIS lock timeout; this "
                f"failed after {waited:.2f}s, so something else refused the read"
            )
        else:
            assert value == 999, (
                f"the other measured shape is an immediate dirty read of the "
                f"uncommitted 999; got {value} after {waited:.2f}s, which is "
                f"neither outcome KNOWN_LIMITATIONS records"
            )

        with psycopg.connect(**pgwire_connection_params) as cleanup:
            cleanup.autocommit = True
            with cleanup.cursor() as cur:
                cur.execute(f"DROP TABLE {table}")


class TestCrossSessionIsolation:
    """Fills the stub that used to be `pass` — two clients must not share state.

    A single shared IRIS connection behind several wire sessions would make one
    client's uncommitted write another client's committed data, and one client's
    ROLLBACK discard another's work.
    """

    def test_sessions_do_not_share_a_transaction(self, pgwire_server, pgwire_connection_params):
        table = f"iso_xsession_{int(time.time())}"

        with psycopg.connect(**pgwire_connection_params) as setup:
            setup.autocommit = True
            with setup.cursor() as cur:
                cur.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, val TEXT)")

        try:
            with psycopg.connect(**pgwire_connection_params) as writer:
                with writer.cursor() as wcur:
                    wcur.execute(f"INSERT INTO {table} (id, val) VALUES (1, 'uncommitted')")

                    # The writer sees its own work.
                    wcur.execute(f"SELECT val FROM {table} WHERE id = 1")
                    assert wcur.fetchone()[0] == "uncommitted"

                    with psycopg.connect(**pgwire_connection_params) as reader:
                        reader.autocommit = True
                        with reader.cursor() as rcur:
                            rcur.execute(f"SELECT COUNT(*) FROM {table}")
                            seen = rcur.fetchone()[0]

                    writer.rollback()

                    # IRIS is READ UNCOMMITTED by default, so `seen` may legitimately
                    # be 1 here. What must hold is that the reader had its own
                    # transaction: the writer's rollback still undoes the row.
                    assert seen in (0, 1)

                with writer.cursor() as wcur:
                    wcur.execute(f"SELECT COUNT(*) FROM {table}")
                    assert wcur.fetchone()[0] == 0, (
                        "the writer's ROLLBACK did not take effect — sessions are "
                        "sharing a transaction"
                    )
        finally:
            with psycopg.connect(**pgwire_connection_params) as cleanup:
                cleanup.autocommit = True
                with cleanup.cursor() as cur:
                    cur.execute(f"DROP TABLE {table}")

    def test_a_readers_rollback_does_not_discard_a_writers_commit(
        self, pgwire_server, pgwire_connection_params
    ):
        table = f"iso_xcommit_{int(time.time())}"

        with psycopg.connect(**pgwire_connection_params) as setup:
            setup.autocommit = True
            with setup.cursor() as cur:
                cur.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, val TEXT)")

        try:
            with psycopg.connect(**pgwire_connection_params) as a:
                with a.cursor() as cur:
                    cur.execute(f"INSERT INTO {table} (id, val) VALUES (1, 'kept')")
                a.commit()

                with psycopg.connect(**pgwire_connection_params) as b:
                    with b.cursor() as cur:
                        cur.execute(f"SELECT val FROM {table} WHERE id = 1")
                        assert cur.fetchone()[0] == "kept"
                    b.rollback()

                with a.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    assert (
                        cur.fetchone()[0] == 1
                    ), "another session's ROLLBACK discarded this session's commit"
        finally:
            with psycopg.connect(**pgwire_connection_params) as cleanup:
                cleanup.autocommit = True
                with cleanup.cursor() as cur:
                    cur.execute(f"DROP TABLE {table}")
