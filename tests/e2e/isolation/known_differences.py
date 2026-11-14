"""IRIS's measured outcomes where they differ from PostgreSQL's, pinned.

Pinned, not endorsed. Each entry is what PGWire on IRIS did, measured by this suite on
pgwire-release-lab (IRIS 2026.2.0.221.0com, DBAPI backend) on 2026-11-14, and re-measured for
2.0.1 the same day, which removed the pins its fixes made match PostgreSQL. The expected answer
for every case is PostgreSQL's (Hermitage's postgres.md and README, or the reference server);
an entry here only records how IRIS departs from it. A run whose verdicts differ from the pin
fails, which means either the behaviour changed or the pin was wrong, and
docs/investigations/mvcc-apps-on-iris-pgwire.md is stale either way.

Hermitage keys are ``(case, level)``; values are the set of verdicts seen across the runs, so a
case that went both ways is pinned as both.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnyOf:
    """A pin for an outcome that varied across runs: any one of ``options`` is the known shape."""

    options: tuple


HERMITAGE: dict[tuple[str, str], set[str]] = {
    # READ UNCOMMITTED is IRIS's default and PGWire's: readers see uncommitted writes. Same row as
    # MySQL and SQL Server "read uncommitted" in Hermitage's README, except PMP-write below.
    ("G1a", "read uncommitted"): {"anomaly"},
    ("G1b", "read uncommitted"): {"anomaly"},
    ("G1c", "read uncommitted"): {"anomaly"},
    ("OTV", "read uncommitted"): {"anomaly"},
    # READ COMMITTED: a read of a locked row waits for the writer. G1c and OTV make a session wait
    # on a row whose writer is itself waiting on that session, so one read fails with 40001 after
    # the 10 s lock timeout instead of reading the committed version.
    ("G1c", "read committed"): {"prevented-by-timeout"},
    ("OTV", "read committed"): {"prevented-by-timeout"},
    # Stronger than PostgreSQL: IRIS's blocked DELETE re-evaluates `value = 20` against the row T1
    # committed and deletes it, which is the serial order T1 then T2. PostgreSQL deletes nothing.
    ("PMP-write", "read uncommitted"): {"prevented"},
    ("PMP-write", "read committed"): {"prevented"},
}

# Every other check: ``(suite, key) -> observed``, where suite is the test module's name without
# its ``test_`` prefix.
PINS: dict[tuple[str, str], object] = {
    # E5. Statement-level atomicity: the failed INSERT is undone, the transaction carries on, and
    # COMMIT commits the work before and after it. ReadyForQuery never reports a failed state.
    **{
        ("failed_transaction", f"error_then_commit/{protocol}"): {
            "steps": ["BEGIN", "INSERT", "error", "INSERT", "COMMIT"],
            "ready_for_query": ["INTRANS", "INTRANS", "INTRANS", "INTRANS", "IDLE"],
            "ids": [1, 2],
        }
        for protocol in ("simple", "extended")
    },
    # A unique violation on a recreated table: the DBAPI driver reports "<LIST ERROR> Incorrect
    # list format" (XX000) instead of SQLCODE -119 on any connection that already had a -119 on
    # the table before it was recreated; a fresh connection gets -119 (23505). Reproduced with
    # intersystems-irispython 5.3.2 alone, so the cause is below PGWire. Since 2.0.1 PGWire
    # discards a connection that gave this error, so about half the trials get a fresh one.
    ("failed_transaction", "unique_violation_new_table"): AnyOf((["XX000"], ["23505", "XX000"])),
    # E4. psycopg's nested `transaction()` matches PostgreSQL since 2.0.1 (the DBAPI backend now
    # rewrites `ROLLBACK TO "_pg3_1"`): no pin. Its `RELEASE "_pg3_1"` still fails (-51), and
    # psycopg ignores that failure on the rollback path.
    # SQLCODE -375 is 3B001, as on PostgreSQL. For a name never created IRIS rolls back the whole
    # transaction, as its ROLLBACK reference says, but the transaction stays open and COMMIT
    # succeeds, where PostgreSQL's aborted transaction turns COMMIT into ROLLBACK.
    ("savepoints", "rollback_to_unknown"): {
        "steps": ["BEGIN", "INSERT", "3B001", "COMMIT"],
        "ids": [],
    },
    ("savepoints", "rollback_to_unknown_with_savepoint"): {
        "steps": ["BEGIN", "INSERT", "SAVEPOINT", "INSERT", "3B001", "COMMIT"],
        "ids": [],
    },
    # ROLLBACK TO deletes the savepoint, so the second ROLLBACK TO is an unknown name: -375, and
    # the whole transaction is rolled back, rows 1 and 3 with it. (Before 2.0.1 PGWire took the
    # first ROLLBACK TO for the end of the transaction and auto-committed the next INSERT, which
    # is why this used to leave rows 1 and 3 committed.)
    ("savepoints", "rollback_to_twice"): {
        "steps": [
            "BEGIN",
            "INSERT",
            "SAVEPOINT",
            "INSERT",
            "ROLLBACK",
            "INSERT",
            "3B001",
            "COMMIT",
        ],
        "ids": [],
    },
    # IRIS has no RELEASE SAVEPOINT (SQLCODE -51, unmapped, so XX000); nothing rolls back.
    ("savepoints", "release/existing"): {
        "steps": ["BEGIN", "INSERT", "SAVEPOINT", "XX000", "COMMIT"],
        "ids": [1],
    },
    ("savepoints", "release/after_rollback_to"): {
        "steps": ["BEGIN", "INSERT", "SAVEPOINT", "INSERT", "ROLLBACK", "XX000", "COMMIT"],
        "ids": [1],
    },
    ("savepoints", "release/unknown"): {
        "steps": ["BEGIN", "INSERT", "XX000", "COMMIT"],
        "ids": [1],
    },
    # E3. The emulation swallows any error whose text says "constraint": a foreign-key violation
    # under DO NOTHING, and a conflict on a key that is not the ON CONFLICT target.
    ("on_conflict", "do_nothing_fk_violation"): {"error": None, "rows": []},
    ("on_conflict", "do_nothing_other_key"): {"error": None, "rows": [[1, 10, 1]]},
    # Racing a DELETE, the emulation never reported 0 rows but sometimes failed with the DBAPI
    # driver's "<LIST ERROR> Incorrect list format" (XX000); native INSERT OR UPDATE sometimes hit
    # a -110 lock timeout (40001). Both varied from run to run.
    ("on_conflict", "upsert_vs_delete/on_conflict"): AnyOf(
        (
            {"zero_row_upserts": False, "errors": []},
            {"zero_row_upserts": False, "errors": ["XX000"]},
        )
    ),
    ("on_conflict", "upsert_vs_delete/insert_or_update"): AnyOf(
        (
            {"zero_row_upserts": False, "errors": []},
            {"zero_row_upserts": False, "errors": ["40001"]},
        )
    ),
    # INSERT OR UPDATE matches on any unique key and writes every supplied column, so it differs
    # from ON CONFLICT whenever the SET list is not "every inserted column from EXCLUDED", the
    # update has a WHERE or reads the existing row, or the table has a second unique key.
    ("on_conflict", "insert_or_update/pk_only_set_subset"): {"rows": [[1, 9, 9]], "error": None},
    ("on_conflict", "insert_or_update/set_uses_existing_row"): {"rows": [[1, 9, 9]], "error": None},
    ("on_conflict", "insert_or_update/do_update_where_false"): {"rows": [[1, 9, 9]], "error": None},
    # Matched on v and rewrote the primary key, where PostgreSQL raises a unique violation.
    ("on_conflict", "insert_or_update/second_unique_key_conflicts"): {
        "rows": [[2, 1, 9]],
        "error": None,
    },
    ("on_conflict", "insert_or_update/target_is_secondary_key_new_pk"): {
        "rows": [[5, 1, 9]],
        "error": None,
    },
    # E2. SELECT ... FOR UPDATE takes no lock on IRIS: a second FOR UPDATE and a writer both go
    # straight through, and the read-then-write counter loses about half its increments.
    **{
        ("locking", f"{name}@{level}"): {"waited_for_commit": False, "result": "ok"}
        for name in ("for_update_vs_for_update", "for_update_vs_update")
        for level in ("read committed", "read uncommitted")
    },
    **{
        ("locking", f"counter_for_update@{level}"): {"lost_updates": True, "all_committed": True}
        for level in ("read committed", "read uncommitted")
    },
    # The touch-update (`SET id = id`, or `SET n = n`) excludes like PostgreSQL's UPDATE: no pin.
    # Gotcha row 4, H1. At READ COMMITTED a read of a row another session holds waits out the
    # 10 s lock timeout and fails (40001) instead of reading the committed version, every time.
    # GROUP BY and aggregates read the uncommitted value at once, as IRIS documents. DISTINCT,
    # which IRIS also documents as an exception, waits like a plain read.
    **{
        ("read_committed", f"h1/{shape}/{protocol}"): [outcome]
        for protocol in ("simple", "extended")
        for shape, outcome in (
            ("plain_pk", "timeout"),
            ("plain_scan", "timeout"),
            ("derived_table", "timeout"),
            ("distinct", "timeout"),
            ("group_by", "dirty"),
            ("aggregate", "dirty"),
            ("count_where", "dirty"),
        )
    },
    # H2. Every way of asking for READ COMMITTED, on both protocols, is honoured.
    **{
        ("read_committed", f"h2/{mode}/{protocol}"): ["timeout"]
        for protocol in ("simple", "extended")
        for mode in (
            "begin_then_set_transaction",
            "begin_isolation_level",
            "set_transaction_without_begin",
            "session_characteristics",
            "default_then_begin",
        )
    },
    # H3 matches PostgreSQL since 2.0.1: DBAPIExecutor.close_session rolls back a disconnected
    # client's transaction and resets the isolation level before the connection is reused, and
    # discards a connection whose reset fails. No pins.
    # Rows 10 to 12: the other locking clauses reach IRIS raw (42601), and so do the advisory-lock
    # functions (SQLCODE -359, 42883).
    **{
        ("unsupported_clauses", f"answer/{name}"): "42601"
        for name in (
            "for_share",
            "for_no_key_update",
            "for_key_share",
            "for_update_nowait",
            "for_update_skip_locked",
        )
    },
    **{
        ("unsupported_clauses", f"answer/{name}"): "42883"
        for name in (
            "pg_advisory_lock",
            "pg_try_advisory_lock",
            "pg_advisory_xact_lock",
            "pg_advisory_unlock",
        )
    },
    # The CancelRequest is acknowledged, never reaches IRIS (DBAPIExecutor.cancel_query returns
    # False), and the "cancelled" UPDATE is applied once the lock is released.
    ("cancel", "cancel_lock_wait"): {
        "sqlstate": None,
        "answered_before_the_lock_was_released": False,
        "update_applied": True,
    },
}
