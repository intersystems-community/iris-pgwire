"""T011a end-to-end: `= ANY($1)` over the real wire protocol.

Connects to the pgwire server as any PostgreSQL client would and issues the
query shapes that failed. psycopg3 uses the extended query protocol, so this
exercises Parse -> Describe -> Bind -> Execute — the path where the failure
actually lived, which no unit test can reach.

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

CASES = [
    (
        "one value",
        "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname = ANY(%s)",
        (["public"],),
        {"public"},
    ),
    (
        "two values",
        "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname = ANY(%s)",
        (["public", "pg_catalog"],),
        {"public", "pg_catalog"},
    ),
    (
        "no match",
        "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname = ANY(%s)",
        (["nosuchschema"],),
        set(),
    ),
    (
        "empty array",
        "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname = ANY(%s)",
        ([],),
        set(),
    ),
    (
        "negated",
        "SELECT nspname FROM pg_catalog.pg_namespace WHERE NOT (nspname = ANY(%s))",
        (["public"],),
        {"pg_catalog", "information_schema"},
    ),
    (
        "array plus a scalar parameter",
        "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname = ANY(%s) AND oid > %s",
        (["public", "pg_catalog"], 0),
        {"public", "pg_catalog"},
    ),
    (
        "the Prisma introspection shape",
        "SELECT c.relname, n.nspname FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ANY(%s) AND c.relkind = ANY(%s)",
        (["public"], ["r", "v"]),
        None,  # row set depends on the schema; asserted non-empty
    ),
    (
        "array literal, no parameter",
        "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname = ANY('{public}')",
        None,
        {"public"},
    ),
]


def main() -> int:
    failures = 0
    with psycopg.connect(DSN) as conn:
        print(f"connected: {DSN.split('password')[0].strip()}")
        for label, sql, params, expected in CASES:
            with conn.cursor() as cur:
                try:
                    cur.execute(sql, params) if params else cur.execute(sql)
                    rows = cur.fetchall()
                except Exception as exc:  # noqa: BLE001
                    print(f"  FAIL {label}: {type(exc).__name__}: {str(exc)[:200]}")
                    failures += 1
                    conn.rollback()
                    continue

            got = {r[0] for r in rows}
            if expected is None:
                ok = len(rows) > 0
                detail = f"{len(rows)} rows"
            else:
                ok = got == expected
                detail = f"{sorted(got)}"
            print(f"  {'ok  ' if ok else 'FAIL'} {label}: {detail}")
            if not ok:
                failures += 1
                if expected is not None:
                    print(f"        expected {sorted(expected)}")

    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
