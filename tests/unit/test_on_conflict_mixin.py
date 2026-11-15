"""Spec 052 US4: what the executor does with an ON CONFLICT statement, by form and mode.

A fake DBAPI connection answers the catalog queries. The isolation suite measures the rows.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from iris_pgwire._locking_mixin import StatementRefused
from iris_pgwire._on_conflict_mixin import OnConflictMixin, conflict_fields
from iris_pgwire.sql_translator.returning_plan import ReturningPlan

T = 'SQLUser."OC_M"'
EXACT = f"INSERT INTO {T} (K, V, W) VALUES (?, ?, ?) ON CONFLICT (K) DO UPDATE SET V = EXCLUDED.V, W = EXCLUDED.W"
SUBSET = f"INSERT INTO {T} (K, V, W) VALUES (?, ?, ?) ON CONFLICT (K) DO UPDATE SET V = EXCLUDED.V"
NOTHING = f"INSERT INTO {T} (K, V, W) VALUES (?, ?, ?) ON CONFLICT (K) DO NOTHING"

UNIQUE_119 = (
    "<SQL ERROR>; Details: [SQLCODE: <-119>:<UNIQUE or PRIMARY KEY constraint failed uniqueness "
    "check upon INSERT>] [Location: <ServerLoop>] [%msg: <Table 'SQLUser.oc_m', Constraint "
    "'{c}', Field(s) {f}; failed unique check>]"
)


class FakeCursor:
    def __init__(self, conn):
        self.conn, self._rows = conn, []

    def execute(self, sql, params=None):
        self.conn.sent.append(sql)
        if "TABLE_CONSTRAINTS" in sql:
            self._rows = self.conn.keys
        elif "INFORMATION_SCHEMA.COLUMNS" in sql:
            self._rows = [(c,) for c in self.conn.columns]
        else:
            self._rows = []

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, keys=None, columns=("k", "v", "w")):
        self.keys = keys if keys is not None else [("OC_M_PKEY1", "k")]
        self.columns, self.sent = columns, []

    def cursor(self):
        return FakeCursor(self)


class Executor(OnConflictMixin):
    def __init__(self, mode="strict"):
        self.config = SimpleNamespace(txn_compat=mode)


def test_the_exact_form_runs_as_insert_or_update():
    plan = Executor().plan_on_conflict_sync(FakeConnection(), ReturningPlan.from_sql(EXACT), EXACT)
    assert plan.stripped_sql == f"INSERT OR UPDATE {T} (K, V, W) VALUES (?, ?, ?)"
    assert plan.on_conflict_clause is None and plan.conflict_action is None


def test_strict_refuses_an_inexact_form_by_name():
    with pytest.raises(StatementRefused) as refused:
        Executor().plan_on_conflict_sync(FakeConnection(), ReturningPlan.from_sql(SUBSET), SUBSET)
    assert refused.value.sqlstate == "0A000"
    assert "sets only some of the inserted columns" in str(refused.value)


def test_strict_refuses_do_nothing():
    with pytest.raises(StatementRefused):
        Executor().plan_on_conflict_sync(FakeConnection(), ReturningPlan.from_sql(NOTHING), NOTHING)


def test_a_second_unique_key_makes_the_exact_spelling_inexact():
    conn = FakeConnection(keys=[("OC_M_PKEY1", "k"), ("OC_M_V", "v")])
    with pytest.raises(StatementRefused) as refused:
        Executor().plan_on_conflict_sync(conn, ReturningPlan.from_sql(EXACT), EXACT)
    assert "more than one unique key" in str(refused.value)


def test_permissive_keeps_the_emulation_and_warns_once():
    executor = Executor("permissive")
    plan = ReturningPlan.from_sql(SUBSET)
    assert executor.plan_on_conflict_sync(FakeConnection(), plan, SUBSET) is plan
    executor.plan_on_conflict_sync(FakeConnection(), plan, SUBSET)
    assert len(executor.compat) == 1


def test_a_missing_table_runs_as_written():
    plan = ReturningPlan.from_sql(EXACT)
    conn = FakeConnection(keys=[], columns=())
    assert Executor().plan_on_conflict_sync(conn, plan, EXACT) is plan


def test_catalog_answers_are_cached_until_ddl():
    executor, conn = Executor(), FakeConnection()
    for _ in range(2):
        executor.plan_on_conflict_sync(conn, ReturningPlan.from_sql(EXACT), EXACT)
    assert sum("TABLE_CONSTRAINTS" in s for s in conn.sent) == 1
    executor.note_ddl("ALTER TABLE oc_m ADD CONSTRAINT u UNIQUE (v)")
    executor.plan_on_conflict_sync(conn, ReturningPlan.from_sql(EXACT), EXACT)
    assert sum("TABLE_CONSTRAINTS" in s for s in conn.sent) == 2


def test_a_composite_key_is_one_key():
    conn = FakeConnection(keys=[("PK", "a"), ("PK", "b")], columns=("a", "b", "v"))
    sql = "INSERT INTO t (A, B, V) VALUES (?, ?, ?) ON CONFLICT (A, B) DO UPDATE SET V = EXCLUDED.V"
    plan = Executor().plan_on_conflict_sync(conn, ReturningPlan.from_sql(sql), sql)
    assert plan.stripped_sql.startswith("INSERT OR UPDATE t")


@pytest.mark.parametrize(
    "message, fields",
    [
        (UNIQUE_119.format(c="spk_ui_u", f="u=10"), {"u"}),
        (UNIQUE_119.format(c="PK", f="a=1,b=2"), {"a", "b"}),
        (UNIQUE_119.format(c="PK", f="K=1"), {"k"}),
        ("[SQLCODE: <-121>:<FOREIGN KEY constraint failed referential check upon INSERT>]", None),
        ("<LIST ERROR> Incorrect list format, unsupported type for IRISList", None),
        ("[SQLCODE: <-119>:<UNIQUE or PRIMARY KEY constraint failed>] no field list", set()),
    ],
)
def test_conflict_fields_come_from_sqlcode_119_only(message, fields):
    assert conflict_fields(Exception(message)) == fields


@pytest.mark.parametrize(
    "sql, fields, is_conflict",
    [
        (NOTHING, {"k"}, True),
        (NOTHING, {"u"}, False),
        (NOTHING, None, False),
        (NOTHING, set(), False),
        (f"INSERT INTO {T} (K, V, W) VALUES (?, ?, ?) ON CONFLICT DO NOTHING", {"u"}, True),
        (f"INSERT INTO {T} (K, V, W) VALUES (?, ?, ?) ON CONFLICT DO NOTHING", None, False),
        (SUBSET, {"k"}, True),
        (SUBSET, {"v"}, False),
    ],
)
def test_only_a_unique_violation_on_the_target_is_the_conflict(sql, fields, is_conflict):
    assert OnConflictMixin.is_target_conflict(ReturningPlan.from_sql(sql), fields) is is_conflict
