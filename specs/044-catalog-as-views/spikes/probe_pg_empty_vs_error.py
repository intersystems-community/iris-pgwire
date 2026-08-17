"""CHK045: does PostgreSQL answer a catalog question with empty, or with an error?

FR-008 says a catalog query that "cannot be satisfied" MUST error and MUST NOT
return an empty result. User Story 1 scenario 3 says an empty schema MUST report
an empty database "rather than failing". On the wire those are the same thing, so
the requirements as written point in two directions — and Phase 3 walks into it,
because a constraints query against a table with no constraints is *legitimately*
empty.

"Least surprising" for a PostgreSQL client is not a matter of taste: it is
whatever PostgreSQL does, because that is what set the client's expectations.
So this probe asks PostgreSQL 15 directly rather than arguing from memory.

Run against a throwaway `postgres:15-alpine`; prints, for each shape, whether
real PostgreSQL returns rows, returns zero rows, or raises — and with what
SQLSTATE.
"""

from __future__ import annotations

import subprocess

CONTAINER = "pg-oracle"

# (label, sql, what we are asking about)
CASES = [
    # --- answerable questions whose answer happens to be "nothing" ---
    ("no matching row", "SELECT relname FROM pg_class WHERE relname = 'no_such_table_xyz'"),
    (
        "empty schema, table list",
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r'",
    ),
    (
        "constraints on a table that has none",
        "SELECT conname FROM pg_constraint WHERE conrelid = "
        "(SELECT oid FROM pg_class WHERE relname = 'no_constraints')",
    ),
    (
        "membership against an empty array",
        "SELECT nspname FROM pg_namespace WHERE nspname = ANY('{}')",
    ),
    (
        "a schema that does not exist",
        "SELECT nspname FROM pg_namespace WHERE nspname = 'no_such_schema'",
    ),
    # --- unanswerable questions: the shape itself is wrong ---
    ("catalog table that does not exist", "SELECT * FROM pg_no_such_catalog_table"),
    ("catalog column that does not exist", "SELECT no_such_column FROM pg_class"),
    ("catalog function that does not exist", "SELECT no_such_function(1)"),
    ("syntactically invalid", "SELECT FROM WHERE pg_class"),
    ("wrong argument count", "SELECT obj_description(1, 2, 3)"),
]


def run(sql: str) -> tuple[str, str]:
    """Return (verdict, detail) for one statement against real PostgreSQL."""
    proc = subprocess.run(
        [
            "docker",
            "exec",
            CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            "probe",
            "-v",
            "ON_ERROR_STOP=1",
            "-t",
            "-A",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        first = next((ln for ln in proc.stderr.splitlines() if "ERROR" in ln), proc.stderr.strip())
        return "ERROR", first.strip()[:88]
    rows = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return ("ROWS" if rows else "EMPTY"), f"{len(rows)} row(s)"


def main() -> int:
    # A table with no constraints, so that case is real rather than hypothetical.
    subprocess.run(
        [
            "docker",
            "exec",
            CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            "probe",
            "-q",
            "-c",
            "CREATE TABLE IF NOT EXISTS no_constraints (a int)",
        ],
        capture_output=True,
        text=True,
    )

    print("PostgreSQL 15 — empty result vs error, by question shape\n")
    for label, sql in CASES:
        verdict, detail = run(sql)
        print(f"  {verdict:6} {label:38} {detail}")

    print("\nAlso: what does an entirely empty schema look like to psql's own \\dt?")
    proc = subprocess.run(
        [
            "docker",
            "exec",
            CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            "probe",
            "-c",
            "DROP TABLE IF EXISTS no_constraints; \\dt",
        ],
        capture_output=True,
        text=True,
    )
    print("  stdout:", (proc.stdout.strip() or "(nothing)")[:100])
    print("  stderr:", (proc.stderr.strip() or "(nothing)")[:100])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
