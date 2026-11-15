"""Spec 052 US3: what the executor runs for a locking clause, by transaction state and mode.

A fake DBAPI connection records the statements and answers the catalog queries, so these tests
pin the decisions; the isolation suite measures the locks themselves against IRIS.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from iris_pgwire import row_limit
from iris_pgwire._locking_mixin import LockingMixin, StatementRefused

SQL = 'SELECT N FROM SQLUser."LOCK_C" WHERE ID = ? FOR UPDATE'


class FakeCursor:
    def __init__(self, conn):
        self.conn, self._rows = conn, []

    def execute(self, sql, params=None):
        self.conn.sent.append((sql, params))
        if self.conn.fail_touch and sql.startswith("UPDATE"):
            raise RuntimeError(self.conn.fail_touch)
        if "INFORMATION_SCHEMA.TABLES" in sql:
            self._rows = [(self.conn.table_type,)] if self.conn.table_type else []
        elif "INFORMATION_SCHEMA.TRIGGERS" in sql:
            self._rows = [(self.conn.triggers,)]
        elif "INFORMATION_SCHEMA.COLUMNS" in sql:
            self._rows = self.conn.columns
        elif "ProcessLockTimeout" in sql:
            self._rows = [(10,)]
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, table_type="BASE TABLE", triggers=0, columns=None, fail_touch=None):
        self.sent = []
        self.table_type, self.triggers, self.fail_touch = table_type, triggers, fail_touch
        self.columns = columns or [("id", "YES", "NO", "NO", "YES"), ("n", "NO", "NO", "NO", "YES")]

    def cursor(self):
        return FakeCursor(self)

    def statements(self):
        return [s for s, _ in self.sent if "INFORMATION_SCHEMA" not in s]


class Executor(LockingMixin):
    def __init__(self, mode="strict", in_transaction=True):
        self.config = SimpleNamespace(txn_compat=mode)
        self.session_transactions = {"s": True} if in_transaction else {}


def _run(executor, sql=SQL, conn=None, params=(1,)):
    conn = conn or FakeConnection()
    to_run, plan = executor.prepare_locking(sql, "s")
    if plan is not None:
        executor.run_touch_sync(conn, plan, params, sql)
    return to_run, conn


def test_in_a_transaction_the_touch_runs_then_the_select_without_the_clause():
    to_run, conn = _run(Executor())
    assert to_run == 'SELECT N FROM SQLUser."LOCK_C" WHERE ID = ?'
    assert conn.sent[-1] == ('UPDATE SQLUser."LOCK_C" SET "id" = "id" WHERE ID = ?', (1,))


def test_outside_a_transaction_only_the_select_runs():
    to_run, conn = _run(Executor(in_transaction=False))
    assert to_run == 'SELECT N FROM SQLUser."LOCK_C" WHERE ID = ?'
    assert conn.sent == []


def test_a_describe_takes_no_lock():
    with row_limit.at_most(1):
        _, conn = _run(Executor())
    assert conn.sent == []


def test_a_statement_without_a_clause_is_untouched():
    executor = Executor()
    assert executor.prepare_locking("SELECT 1", "s") == ("SELECT 1", None)


def test_without_a_primary_key_the_first_updatable_column_is_touched():
    conn = FakeConnection(columns=[("a", "NO", "NO", "NO", "YES"), ("b", "NO", "NO", "NO", "YES")])
    _run(Executor(), conn=conn)
    assert conn.statements()[-1].startswith('UPDATE SQLUser."LOCK_C" SET "a" = "a"')


def test_an_identity_column_is_not_the_touched_column():
    conn = FakeConnection(
        columns=[("id", "NO", "NO", "YES", "YES"), ("n", "NO", "NO", "NO", "YES")]
    )
    _run(Executor(), conn=conn)
    assert 'SET "n" = "n"' in conn.statements()[-1]


def test_nowait_runs_the_touch_at_lock_timeout_0_and_restores_it():
    _, conn = _run(Executor(), SQL.replace("FOR UPDATE", "FOR UPDATE NOWAIT"))
    assert conn.statements() == [
        "SELECT %SYSTEM_SQL.Util_GetOption('ProcessLockTimeout')",
        "SET OPTION LOCK_TIMEOUT = 0",
        'UPDATE SQLUser."LOCK_C" SET "id" = "id" WHERE ID = ?',
        "SET OPTION LOCK_TIMEOUT = 10",
    ]


def test_nowait_on_a_locked_row_is_55p03_and_the_timeout_is_restored():
    conn = FakeConnection(fail_touch="[SQLCODE: <-110>:<Locking conflict in filing>]")
    with pytest.raises(StatementRefused) as refused:
        _run(Executor(), SQL.replace("FOR UPDATE", "FOR UPDATE NOWAIT"), conn)
    assert refused.value.sqlstate == "55P03"
    assert str(refused.value) == 'could not obtain lock on row in relation "lock_c"'
    assert conn.statements()[-1] == "SET OPTION LOCK_TIMEOUT = 10"


def test_a_touch_that_fails_otherwise_keeps_its_error():
    conn = FakeConnection(fail_touch="[SQLCODE: <-110>:<Locking conflict in filing>]")
    with pytest.raises(RuntimeError):
        _run(Executor(), SQL, conn)  # no NOWAIT: the lock timeout's own error (40001)


@pytest.mark.parametrize(
    "conn, refusal",
    [
        (FakeConnection(table_type="VIEW"), "on a view"),
        (FakeConnection(triggers=1), "UPDATE trigger"),
        (
            FakeConnection(
                columns=[("id", "YES", "NO", "NO", "YES"), ("rv", "NO", "YES", "NO", "YES")]
            ),
            "ROWVERSION",
        ),
    ],
)
def test_catalog_refusals(conn, refusal):
    with pytest.raises(StatementRefused) as refused:
        _run(Executor(), conn=conn)
    assert refused.value.sqlstate == "0A000"
    assert refusal in str(refused.value)
    assert conn.statements() == []


def test_a_missing_table_is_left_to_the_select():
    conn = FakeConnection(table_type=None)
    _run(Executor(), conn=conn)
    assert conn.statements() == []


def test_strict_refuses_a_shape_by_name():
    with pytest.raises(StatementRefused) as refused:
        Executor().prepare_locking("SELECT n FROM t WHERE id = 1 FOR SHARE", "s")
    assert refused.value.sqlstate == "0A000"
    assert str(refused.value).startswith("FOR SHARE is not supported on IRIS")


def test_permissive_runs_a_refused_shape_unchanged():
    sql = "SELECT a.n FROM t a JOIN u b ON a.id = b.id FOR UPDATE"
    executor = Executor("permissive")
    assert executor.prepare_locking(sql, "s") == (sql, None)
    assert executor.prepare_locking(sql, "s") == (sql, None)
    assert len(executor.compat) == 1


def test_permissive_runs_a_catalog_refusal_unlocked():
    conn = FakeConnection(table_type="VIEW")
    to_run, conn = _run(Executor("permissive"), conn=conn)
    assert to_run == 'SELECT N FROM SQLUser."LOCK_C" WHERE ID = ?'
    assert conn.statements() == []


def test_catalog_answers_are_cached_until_ddl():
    executor, conn = Executor(), FakeConnection()
    _run(executor, conn=conn)
    _run(executor, conn=conn)
    lookups = [s for s, _ in conn.sent if "INFORMATION_SCHEMA.TABLES" in s]
    assert len(lookups) == 1
    executor.note_ddl("DROP TABLE lock_c")
    _run(executor, conn=conn)
    assert len([s for s, _ in conn.sent if "INFORMATION_SCHEMA.TABLES" in s]) == 2


def test_a_nowait_describe_takes_the_lock_so_a_held_row_fails_at_once():
    """Found by the slice 3 gate: at READ COMMITTED the Describe's plain SELECT waited out the held
    row's lock twice (20 s) before Execute's NOWAIT touch could refuse it."""
    with row_limit.at_most(1):
        _, conn = _run(Executor(), SQL.replace("FOR UPDATE", "FOR UPDATE NOWAIT"))
    assert "SET OPTION LOCK_TIMEOUT = 0" in conn.statements()
