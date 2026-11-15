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
    # E5 matches PostgreSQL since spec 052 US1 (an error aborts the transaction, COMMIT rolls back,
    # ReadyForQuery reports E): no pins.
    # A unique violation on a recreated table: the DBAPI driver reports "<LIST ERROR> Incorrect
    # list format" (XX000) instead of SQLCODE -119 on any connection that already had a -119 on
    # the table before it was recreated; a fresh connection gets -119 (23505). Reproduced with
    # intersystems-irispython 5.3.2 alone, so the cause is below PGWire. Since 2.0.1 PGWire
    # discards a connection that gave this error, so about half the trials get a fresh one.
    ("failed_transaction", "unique_violation_new_table"): AnyOf((["XX000"], ["23505", "XX000"])),
    # E4 matches PostgreSQL since spec 052 US2 (PGWire keeps the savepoint stack itself): no pins,
    # except IRIS's limit. IRIS keeps every savepoint alive until the transaction ends (it has no
    # RELEASE) and fails the 255th with SQLCODE -400, losing the work while COMMIT still succeeds.
    # PGWire refuses the 255th with 54000 and aborts the transaction, so the loss is loud
    # (research.md R4, spec FR-008a). PostgreSQL has no such limit.
    # SQLAlchemy's begin_nested() matches PostgreSQL since PGWire answers current_schema() and the
    # rest of the dialect's connect-time questions (test_sqlalchemy.py): no pin.
    ("savepoints", "savepoint_limit"): {
        "first_failure": [255, "54000", "INERROR"],
        "commit": "ROLLBACK",
        "ids": [],
    },
    # E3 since spec 052 US4. Strict mode sends IRIS's INSERT OR UPDATE for the one form it expresses
    # exactly (the target is the table's only unique key, DO UPDATE sets every inserted column from
    # EXCLUDED, no WHERE) and refuses every other form with 0A000, DO NOTHING included, where
    # PostgreSQL runs them (research.md R7). Before 2.1 the emulation swallowed any error whose text
    # said "constraint": a foreign-key violation, a conflict on another key.
    ("on_conflict", "do_nothing_fk_violation"): {"error": "0A000", "rows": []},
    ("on_conflict", "do_nothing_other_key"): {"error": "0A000", "rows": [[1, 10, 1]]},
    **{
        ("on_conflict", f"strict/{name}"): {"rows": [[1, 1, 1]], "error": "0A000"}
        for name in (
            "pk_only_set_subset",
            "set_uses_existing_row",
            "do_update_where_false",
            "second_unique_key_conflicts",
            "target_is_secondary_unique_key",
            "target_is_secondary_key_new_pk",
        )
    },
    ("on_conflict", "strict/executemany_set_subset"): {"rows": [[1, 1, 1]], "error": "0A000"},
    **{
        ("on_conflict", f"strict/other/{name}"): {"rows": [[1, 1, 1]], "error": "0A000"}
        for name in ("multi_row", "insert_select", "on_constraint", "set_constant")
    },
    # Racing a DELETE, the upsert is now IRIS's INSERT OR UPDATE, which never affected 0 rows but
    # sometimes waited out a lock and failed with -110 (40001), or, on a pooled connection that had
    # an error on the table before it was recreated, with the DBAPI driver's "<LIST ERROR>" (XX000).
    ("on_conflict", "upsert_vs_delete/on_conflict"): AnyOf(
        (
            {"zero_row_upserts": False, "errors": []},
            {"zero_row_upserts": False, "errors": ["40001"]},
            {"zero_row_upserts": False, "errors": ["XX000"]},
            {"zero_row_upserts": False, "errors": ["40001", "XX000"]},
        )
    ),
    # Permissive mode, on a connection where the DBAPI driver reports "<LIST ERROR>" in place of
    # the unique violation (a table recreated after a -119 on it): the emulation cannot tell it is
    # the conflict, so the statement fails with XX000 instead of doing nothing (FR-016). When the
    # driver reports the -119 itself, it matches PostgreSQL.
    ("on_conflict", "permissive/list_error"): AnyOf(
        (
            {"first": None, "after_recreate": None, "next_session": "23505"},
            {"first": None, "after_recreate": "XX000", "next_session": "23505"},
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
    # E2 matches PostgreSQL since spec 052 US3: PGWire locks a single-table FOR UPDATE with a
    # touch-update (`UPDATE t SET pk = pk WHERE <same predicate>`). The shapes a touch cannot lock
    # exactly are refused with 0A000 where PostgreSQL runs them (research.md R6): a join or a
    # subquery in FROM, LIMIT (the touch would lock rows the SELECT does not return), a view, and
    # a table with a ROWVERSION column (the touch would bump it).
    **{
        ("locking", f"refused/{name}"): "0A000"
        for name in (
            "join",
            "subquery_in_from",
            "limit",
            "view",
            "rowversion",
            "update_trigger",
            "with",
            "several_locking_clauses",
            "of_unknown_table",
        )
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
    # Rows 10 to 12. FOR UPDATE NOWAIT is emulated since spec 052 US3 (no pin). FOR SHARE, FOR NO
    # KEY UPDATE, FOR KEY SHARE and SKIP LOCKED have no IRIS equivalent and are refused with 0A000
    # (before 2.1 they reached IRIS raw, 42601). The advisory-lock functions reach IRIS raw
    # (SQLCODE -359, 42883).
    **{
        ("unsupported_clauses", f"answer/{name}"): "0A000"
        for name in ("for_share", "for_no_key_update", "for_key_share", "for_update_skip_locked")
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
    # GROUP BY 3 on a two-column select: PostgreSQL refuses it (42P10). PGWire has no column to
    # substitute, so IRIS reads 3 as a constant and returns one row over all ten, status arbitrary.
    **{
        ("positional_clauses", f"group_by_position_out_of_range/{protocol}"): AnyOf(
            ([["new", 10]], [["paid", 10]], [["void", 10]])
        )
        for protocol in ("simple", "extended")
    },
    # The CancelRequest is acknowledged, never reaches IRIS (DBAPIExecutor.cancel_query returns
    # False), and the "cancelled" UPDATE is applied once the lock is released.
    ("cancel", "cancel_lock_wait"): {
        "sqlstate": None,
        "answered_before_the_lock_was_released": False,
        "update_applied": True,
    },
}
