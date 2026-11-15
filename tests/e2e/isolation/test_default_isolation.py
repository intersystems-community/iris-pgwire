"""Spec 052 US7: READ COMMITTED is the default, and PGWIRE_DEFAULT_ISOLATION can change it.

The default run checks a new session against PostgreSQL's default (READ COMMITTED). The run under
`make isolation-read-uncommitted` (marker `default_isolation`) checks a server started with
`PGWIRE_DEFAULT_ISOLATION='read uncommitted'`; the reference server's session is set to READ
UNCOMMITTED explicitly, which PostgreSQL runs as READ COMMITTED (its answer, pinned for IRIS).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .harness import Session, run_statement

ROOT = Path(__file__).resolve().parents[3]


def _table(target, name):
    with target.connect() as conn:
        for sql in (
            f"drop table if exists {name}",
            f"create table {name} (id int primary key, n int)",
            f"insert into {name} values (1, 0)",
        ):
            assert run_statement(conn, sql).ok, sql


def _new_session_view(target, table, set_level=None):
    """What a new session reports and reads while another holds an uncommitted write."""
    holder = target.connect("extended")
    reader = Session("reader", target.connect("extended"))
    try:
        if set_level:
            assert run_statement(
                reader.conn,
                f"set session characteristics as transaction isolation level {set_level}",
            ).ok
        level = run_statement(reader.conn, "show transaction_isolation").rows
        default = run_statement(reader.conn, "show default_transaction_isolation").rows
        assert run_statement(holder, "begin").ok
        assert run_statement(holder, f"update {table} set n = 1 where id = 1").ok
        read = reader.submit(f"select n from {table} where id = 1").result(timeout=30)
        run_statement(holder, "rollback")
        return {
            "level": level,
            "default": default,
            "read": read.rows if read.ok else read.sqlstate,
        }
    finally:
        holder.close()
        reader.close()


def test_a_new_session_runs_at_read_committed(target, expect):
    table = f"di_rc_{os.getpid()}"
    _table(target, table)
    expect.check(
        "default/read_committed",
        _new_session_view(target, table),
        {"level": [("read committed",)], "default": [("read committed",)], "read": [(0,)]},
    )
    expect.done()


@pytest.mark.default_isolation
def test_the_server_default_can_be_read_uncommitted(target, expect):
    table = f"di_ru_{os.getpid()}"
    _table(target, table)
    observed = _new_session_view(
        target, table, set_level="read uncommitted" if target.reference else None
    )
    expect.check(
        "default/read_uncommitted_server",
        observed,
        {"level": [("read uncommitted",)], "default": [("read uncommitted",)], "read": [(0,)]},
    )
    expect.done()


@pytest.mark.parametrize(
    "env, accepted",
    [
        ({"PGWIRE_DEFAULT_ISOLATION": "serializable"}, "read committed"),
        ({"PGWIRE_TXN_COMPAT": "bogus"}, "permissive"),
    ],
    ids=["default_isolation", "txn_compat"],
)
def test_an_invalid_setting_stops_the_server(target, expect, env, accepted):
    """FR-024/FR-025: the server refuses to start, naming the accepted values (PGWire only)."""
    if target.reference:
        pytest.skip("a PGWire server setting; PostgreSQL has no equivalent")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests/e2e/_auth_server.py"), "5499", "trust", "dbapi"],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "IRIS_PORT": "2992", **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    name = next(iter(env))
    expect.check(
        f"startup/{name.lower()}",
        {
            "exited_nonzero": proc.returncode != 0,
            "names_the_values": accepted in proc.stderr + proc.stdout,
        },
        {"exited_nonzero": True, "names_the_values": True},
        returncode=proc.returncode,
        tail=(proc.stderr or proc.stdout)[-300:],
    )
    expect.done()
