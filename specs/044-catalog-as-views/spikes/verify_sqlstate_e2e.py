"""T027 end-to-end: does the client receive a SQLSTATE that names the fault?

Every failure used to arrive as `42000` — an IRIS internal crash and the
client's own typo were indistinguishable. This asks over the real wire, with a
real client, what SQLSTATE each failure shape now carries.

The `pgcode` psycopg exposes is exactly the `C` field of the ErrorResponse, so
this measures what any PostgreSQL client sees, not what our code intended.

Set PGWIRE_HOST / PGWIRE_PORT to point at either backend.
"""

from __future__ import annotations

import os
import sys

import psycopg

DSN = (
    f"host={os.environ.get('PGWIRE_HOST', 'localhost')} "
    f"port={os.environ.get('PGWIRE_PORT', '5432')} "
    f"dbname={os.environ.get('PGWIRE_DB', 'USER')} "
    f"user={os.environ.get('PGWIRE_USER', '_SYSTEM')} "
    f"password={os.environ.get('PGWIRE_PASSWORD', 'SYS')}"
)

# (label, sql, expected SQLSTATE) — the expectations are what PostgreSQL 15
# returns for the same shape, measured in spikes/probe_pg_empty_vs_error.py and
# alongside it.
TABLE = "t027_wire_probe"

# Created so the DML failures below are real. These are the ones an ORM keys on:
# a duplicate insert it must recognise as a conflict rather than a crash.
SETUP = [
    f"DROP TABLE IF EXISTS {TABLE}",
    f"CREATE TABLE {TABLE} (id INT NOT NULL PRIMARY KEY, name VARCHAR(10))",
    f"INSERT INTO {TABLE} (id, name) VALUES (1, 'a')",
]

CASES = [
    ("undefined table", "SELECT * FROM no_such_table_xyz", "42P01"),
    ("undefined column", "SELECT no_such_col FROM pg_catalog.pg_class", "42703"),
    ("undefined function", "SELECT no_such_function_xyz(1)", "42883"),
    ("syntax error", "SELECT FROM WHERE", "42601"),
    ("trailing input", "SELECT 1 FROM pg_catalog.pg_class ) extra", "42601"),
    ("unique violation", f"INSERT INTO {TABLE} (id, name) VALUES (1, 'b')", "23505"),
    ("not null violation", f"INSERT INTO {TABLE} (name) VALUES ('c')", "23502"),
    ("value too long", f"INSERT INTO {TABLE} (id, name) VALUES (2, 'way too long')", "22000"),
]


def run(label: str, sql: str, expected: str) -> bool:
    with psycopg.connect(DSN, autocommit=True) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                if cur.description:
                    cur.fetchall()
        except psycopg.Error as exc:
            actual = exc.sqlstate or "(none)"
            ok = actual == expected
            detail = str(exc).splitlines()[0][:78]
            print(f"  {'PASS' if ok else 'FAIL'} {label:20} {actual:6} (want {expected})  {detail}")
            return ok
        print(f"  FAIL {label:20} no error raised at all")
        return False


def setup() -> None:
    with psycopg.connect(DSN, autocommit=True) as conn:
        for sql in SETUP:
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
            except psycopg.Error as exc:
                print(f"  setup: {sql[:44]:46} {str(exc).splitlines()[0][:50]}")


def main() -> int:
    print(f"SQLSTATE classification over the wire — {DSN.split()[1]}\n")
    setup()
    results = [run(*case) for case in CASES]

    print("\nAnd the case that motivated FR-008e: an IRIS internal failure must")
    print("not be reported as the client's syntax error.")
    crash_ok = False
    with psycopg.connect(DSN, autocommit=True) as conn:
        try:
            with conn.cursor() as cur:
                # Measured: $LISTGET over a non-list raises <LIST> inside IRIS,
                # which surfaces as SQLCODE -400 with ObjectScript detail in
                # %msg. Nothing about it is the client's SQL being malformed.
                cur.execute("SELECT $LISTGET('not a list', 1)")
                cur.fetchall()
        except psycopg.Error as exc:
            state = exc.sqlstate or "(none)"
            crash_ok = state == "XX000"
            print(
                f"  {'PASS' if crash_ok else 'FAIL'} internal failure    {state:6} (want XX000)"
                f"  {str(exc).splitlines()[0][:52]}"
            )
        else:
            print("  FAIL internal failure    IRIS accepted it; probe no longer reproduces -400")

    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {TABLE}")

    passed = sum(results) + (1 if crash_ok else 0)
    total = len(results) + 1
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
