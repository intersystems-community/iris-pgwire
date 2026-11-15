# Research: PostgreSQL Transaction Semantics on IRIS (spec 052)

Phase 0 of `/speckit.plan`. Every decision below rests on a measurement or on the code as it stands at `0451f40`
(`hotfix/2.0.1`). Measurements are from `pgwire-release-lab` (IRIS 2026.2.0.221.0com, port 2992) unless stated.

## R1. Where the abort rule lives

**Decision**: In `protocol.py`, keyed on `self.transaction_status`, which already holds `STATUS_FAILED_TRANSACTION =
b"E"` (line 127) but never sets it. One hook: `send_error_response` with severity `ERROR` while the status is
`STATUS_IN_TRANSACTION` sets it to `E`. One gate: before a statement is translated or sent (`_handle_single_statement`
and the extended path's Parse/Execute), a statement other than `ROLLBACK`, `ROLLBACK TO` or `COMMIT` in state `E` is
answered with `25P02` and never reaches the executor.

**Rationale**: the abort rule is PostgreSQL protocol semantics, not IRIS behaviour, so it belongs in the protocol layer
(constitution IV keeps IRIS specifics in the executor and translator). The status byte is already what ReadyForQuery
sends (`send_ready_for_query`, line 879), so FR-003 follows from the same field. Hooking `send_error_response` catches
every error path at once: there are more than 40 call sites, and a per-site change would miss some. Because it is
protocol-level, it works on both backends, which keeps principle IV.

**Alternatives considered**: tracking the abort in the executor (`session_transactions` in `dbapi_executor.py`) would
need every error path to tell the executor, and the embedded backend has no equivalent dict. Asking IRIS: IRIS has no
aborted-transaction state (it undoes the failed statement only; measured E5), so there is nothing to ask.

## R2. `COMMIT` in an aborted transaction

**Decision**: `_maybe_handle_transaction_command` checks the status first: in state `E`, any `_COMMIT_FORMS` statement
calls `iris_executor.rollback_transaction()` and replies with the tag `ROLLBACK` (status goes to `I`).

**Rationale**: PostgreSQL's documented behaviour (`COMMIT` reference: "If the transaction has been aborted, COMMIT
rolls it back"), and what the suite's E5 reference run shows. `send_transaction_response` already maps tag to status.

## R3. Errors in the extended protocol: discard until Sync

**Decision**: add a `_discard_until_sync` flag. It is set when an error is sent while handling Parse, Bind, Describe,
Execute or Close; the message loop then drops every message except Sync, and Sync clears it and sends ReadyForQuery.

**Rationale**: PostgreSQL protocol, "Extended Query": "When an error is detected while processing any extended-query
message, the backend issues ErrorResponse, then reads and discards messages until a Sync is reached." PGWire does not
do this today (no such state in `message_loop`, line ~925), so a pipeline keeps executing after an error. This
replaces spec 049 FR-005, as the spec says. psycopg's pipeline mode and asyncpg's `executemany` depend on it.

**Alternatives considered**: per-statement isolation (049 FR-005's "should not abort"). Rejected: it is not
PostgreSQL's behaviour, and with an open transaction it would be US1's defect in another form.

## R4. The savepoint stack and IRIS's savepoint semantics

Measured 2026-11-14 with intersystems-irispython 5.3.2 directly against IRIS (no PGWire):

| Probe                                                                                    | Result                                               |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `SAVEPOINT a`, insert 2, `ROLLBACK TO a`, `SAVEPOINT a` again, insert 3, `ROLLBACK TO a` | both succeed; rows 1, 4 survive (re-establish works) |
| `SAVEPOINT a`, insert 1, `SAVEPOINT a`, insert 2, `ROLLBACK TO a`                        | row 1 survives: the most recent `a` is used          |
| `SAVEPOINT a`, `SAVEPOINT b`, `ROLLBACK TO a`, `ROLLBACK TO b`                           | second fails -375: rolling back to `a` drops `b`     |
| 400 `SAVEPOINT`s in one transaction                                                      | `$TLEVEL` 1 → 255; the 255th fails with -400         |
| the same name reused 300 times                                                           | same: -400 at `$TLEVEL` 255                          |
| after the -400, insert and `COMMIT`                                                      | `COMMIT` succeeds, table empty: the work is lost     |

**Decision**: PGWire keeps a per-session stack of client savepoint names, each mapped to an internal IRIS name
(`pgw_sp_<n>`, unique per transaction).

- `SAVEPOINT x`: push `x`, send `SAVEPOINT pgw_sp_<n>`.
- `ROLLBACK TO x`: find the most recent `x`; unknown is `3B001` (not sent, the transaction aborts per R1). Otherwise
  send `ROLLBACK TO SAVEPOINT pgw_sp_<k>`, pop everything above `x`, then send `SAVEPOINT pgw_sp_<k>` again so `x`
  survives, as on PostgreSQL. A successful `ROLLBACK TO` in state `E` returns the status to `T`.
- `RELEASE x`: find the most recent `x`; unknown is `3B001`. Otherwise pop `x` and everything above it. Nothing is
  sent to IRIS; its savepoints stay until the transaction ends, which changes no result, because PGWire never rolls
  back to a popped name.
- The IRIS savepoint count is tracked. A `SAVEPOINT` (or a re-establishment) that would reach `$TLEVEL` 255 is refused
  with `54000` and aborts the transaction (spec FR-008a), before IRIS's -400 can lose the work.
- `COMMIT`, `ROLLBACK`, and session close empty the stack.

**Rationale**: internal names remove every quoting and case question (FR-008 becomes a property of the stack's
lookup, which compares names by PostgreSQL's identifier rules) and make duplicate names exact. Re-establishing after
`ROLLBACK TO` was measured to work. Not sending `RELEASE` is the only option (IRIS has none).

**Alternatives considered**: sending the client's names to IRIS (today's behaviour): duplicates and quoting depend on
IRIS's rules, and a second `ROLLBACK TO` fails. Lazy savepoints (send `SAVEPOINT` only when a `ROLLBACK TO` might
follow): impossible to know in advance. Reusing a released savepoint's IRIS level: measured impossible, every
`SAVEPOINT` raises `$TLEVEL`.

**Where**: a new shared module `src/iris_pgwire/savepoints.py` (a pure stack plus the statement parsing), used from
the executor layer through a mixin like `IsolationMixin` (`_isolation.py`), so both backends get it. It subsumes the
`savepoint_depth` counter in `_isolation.py`'s `_SessionIsolation`, which the 25001 check then reads from the stack.
`rewrite_savepoint_verbs` (2.0.1) stays for the embedded path's translator and becomes unused on DBAPI once the stack
answers these statements itself.

## R5. psycopg's nested blocks, end to end

psycopg 3 sends `SAVEPOINT "_pg3_n"`, then on normal exit `RELEASE "_pg3_n"`, and on an exception `ROLLBACK TO
"_pg3_n"` followed by `RELEASE "_pg3_n"`. Measured on 2.0.1: normal exit raises `XX000` (-51) and the outer
transaction is lost; the exception path works because psycopg ignores errors there. With R4 both paths are exact.
SQLAlchemy (`ROLLBACK TO SAVEPOINT` / `RELEASE SAVEPOINT`, unquoted `sa_savepoint_n`) and Django (quoted
`"s<thread>_x<n>"`) use the same three statements, so the suite adds one check per client spelling.

## R6. Row locking clauses (US3)

**Decision**: a translator step recognises `SELECT ... FROM <one base table> [WHERE ...] FOR UPDATE [OF t] [NOWAIT]`
inside an explicit transaction and runs, before the SELECT, `UPDATE <t> SET <pk> = <pk> WHERE <same predicate>`
(the touch-update), then the SELECT without the clause. `NOWAIT` wraps the touch in `SET OPTION LOCK_TIMEOUT = 0` and
restores the session's timeout afterwards; a -110 from it becomes `55P03`. Shapes refused in strict mode with `0A000`:
joins, a subquery or view in `FROM`, `GROUP BY`/`DISTINCT`/aggregates, `LIMIT`/`OFFSET` (the touch would lock rows the
SELECT does not return), a table with an `UPDATE` trigger or a `ROWVERSION` column, `SKIP LOCKED`, `FOR SHARE`, `FOR NO
KEY UPDATE`, `FOR KEY SHARE`. Outside a transaction the clause is dropped (the statement is its own transaction).

**Rationale**: measured exact for the counter (1000 of 1000) and for exclusion of a second touch and of a writer. The
primary key is found the way `_get_primary_key_columns` (`dbapi_executor.py`) already finds it. The trigger and
`ROWVERSION` refusals follow the spec's edge cases. To confirm in tasks: a `WHERE` with bound parameters is reused with
the same parameters, and a table with no primary key uses `%ID`.

## R7. ON CONFLICT (US4)

The emulation is `_handle_on_conflict_update` (`dbapi_executor.py:784`), reached from the exception handler at line 659. `ReturningPlan` (`sql_translator/returning_plan.py`) parses the clause.

**Decision**:

- A classifier (pure function over `ReturningPlan` plus the table's unique keys from the catalog) labels each
  statement `exact` (FR-013) or names the inexact form.
- `exact` is rewritten to `INSERT OR UPDATE` (without the `INTO` keyword; the 2.0.1 investigation found `INSERT OR
UPDATE INTO t` mis-rewritten to `SQLUser."INTO"`).
- Inexact forms: strict mode refuses with `0A000`; permissive runs the emulation, which now decides on SQLCODE -119
  (the `SQLCODE: <-119>` the driver reports) on the target, honours `DO NOTHING`'s target, and treats `<LIST ERROR>`
  as `XX000` (FR-015 to FR-017).

**Rationale**: the exact form and every inexact form were measured in the spike (E3 table). The unique keys come from
`INFORMATION_SCHEMA.TABLE_CONSTRAINTS`, cached per table with the catalog's existing cache; a `DROP`/`CREATE`
invalidates it.

### R7 implemented: slice 2 (2026-11-14)

- **`INSERT OR UPDATE INTO` (T057)**: not needed. The exact form is rewritten from the statement after translation
  (`INSERT INTO SQLUser."T" ...` becomes `INSERT OR UPDATE SQLUser."T" ...`), so the schema rewrite never sees an
  `INTO` after `UPDATE`. The `SQLUser."INTO"` bug stays, out of scope.
- **Measured on the lab, DBAPI driver alone**: `INSERT OR UPDATE` rejects several rows of VALUES (SQLCODE -25), so
  multi-row upserts are inexact; it accepts no column list. A `CREATE UNIQUE INDEX` is listed in
  `INFORMATION_SCHEMA.TABLE_CONSTRAINTS` as `UNIQUE`, with its columns in `KEY_COLUMN_USAGE`. A -119 names the key's
  fields (`Field(s) u=10`), which is how the permissive emulation tells a conflict on its target from one on another
  key. `<LIST ERROR>` in place of a -119 was also seen on a table created moments before on the same connection, after
  an `INSERT OR UPDATE` on it, not only after a table was recreated.

## R8. `lock_timeout` and `statement_timeout` (US5)

**Decision**: `SET lock_timeout` is handled next to the isolation `SET`s (`_isolation.py`'s statement handling is the
model): parse PostgreSQL's units (`ms` default, `s`, `min`), round up to whole seconds, send `SET OPTION LOCK_TIMEOUT =
n`, record the client's value for `SHOW`. `0` and `RESET` send the server default (the CPF `[SQL] LockTimeout`, 10 on the lab,
read once at startup; which IRIS call reads it is a task to confirm). A -110/-114 in a session whose
`lock_timeout` the client set maps to `55P03`; otherwise `40001` (classifier gets a context flag, `sqlstate.py`).
`statement_timeout` is accepted, recorded for `SHOW`, logged once per session. The value persists across the pool
reset only for the session that set it: `close_session` (2.0.1) adds `SET OPTION LOCK_TIMEOUT = <default>` to the reset.

**Rationale**: measured: `LOCK_TIMEOUT = 0` failed in 0.00 s, `= 2` in 2.00 s. Whether `SET OPTION LOCK_TIMEOUT` is
per process (so per pooled connection) is assumed from the docs; a suite check confirms it before US5 ships
(constitution III).

### R8 measured (T063, 2026-11-14)

`spikes/lock_timeout_scope.py`, plain intersystems-irispython 5.3.2 on the lab:

- **Per connection.** After connection A sent `SET OPTION LOCK_TIMEOUT = 2`, A's write to a held row failed in 2.07 s
  (-110) and connection B's in 10.00 s; `%SYSTEM_SQL.Util_GetOption('ProcessLockTimeout')` read 2 on A, 10 on B.
- **It outlives the transaction.** Still 2 after COMMIT, after a SQL `ROLLBACK` and after the driver's `rollback()`.
  So the design holds: the pool's reset on close restores it (`_reset_connection_sync`'s `lock_timeout_seconds`).
- **The server default** is `%SYSTEM_SQL.Util_GetOption('LockTimeout')` (10 on the lab); a connection's current
  value is `...('ProcessLockTimeout')`. `SET OPTION LOCK_TIMEOUT = 10` restores it.

No change to US5's design.

## R9. Cancel (US6)

Today `handle_cancel_request` (`protocol.py:3601`) calls `iris_executor.cancel_query`, which on DBAPI logs and
returns `False` (`dbapi_executor.py`); the target session is never touched. `server.py` already keeps
`connection_registry` and `find_connection_for_cancellation(pid, secret)`.

**Decision**: the cancel handler looks up the target protocol, and if it has a statement in progress, marks it
cancelled and closes that session's IRIS connection (`conn_wrapper.connection.close()` from another thread, then
`mark_failed`). The statement's worker thread gets a driver error, which the protocol reports as `57014` because of
the mark; the session's state (transaction, savepoints, isolation override) is reset, and its next statement acquires
a fresh pooled connection at the session's isolation level.

**Rationale**: closing the socket is the only way to stop a blocked DBAPI call; IRIS rolls back a transaction whose
process ends. To confirm in tasks: the `irispython` connection's `close()` is safe from another thread while a call is
blocked (if not, close the underlying socket). This is a spike task, run before US6's design is frozen.

### R9 measured (T064, 2026-11-14)

`spikes/close_blocked_connection.py`, plain intersystems-irispython 5.3.2 on the lab. A held a row; B inserted a row
of its own, then blocked updating A's row with a 30 s lock timeout; after 1 s the main thread called B's
`connection.close()`:

- `close()` returned at once (0.00 s), from the other thread.
- B's blocked `execute` returned 1.0 s after it started, i.e. when `close()` ran, with
  `OperationalError: <COMMUNICATION LINK ERROR> Failed to receive message`, not after its 30 s timeout.
- B's transaction was rolled back: its inserted row was gone, seen from a third connection.
- Not measured: whether IRIS lists B's process afterwards (the process-count query in the spike counted 0 before and
  after, so it measured nothing). The rollback shows IRIS ended B's transaction.

No change to US6's design: close the session's connection from the cancel handler, mark it failed, report `57014`.

## R10. Default isolation (US7) and settings

**Decision**: `BackendConfig` (`models/backend_config.py`) gains `default_isolation` (`PGWIRE_DEFAULT_ISOLATION`,
default `read committed`) and `txn_compat` (`PGWIRE_TXN_COMPAT`, `strict` or `permissive`), validated at startup in
the existing env-var table (line ~208). `sql_translator/isolation.py`'s module constant `DEFAULT_ISOLATION_LEVEL`
becomes the fallback for a config value passed to `IsolationMixin`, and to `_reset_connection_sync` (2.0.1). New
pooled connections get the default applied once at creation in `dbapi_connection_pool.py`.

**Rationale**: two places read the constant today (`_isolation.py` and the 2.0.1 reset); a config value keeps them in
step. Applying the level at connection creation means a session that never asks still runs at what it reports.

## R11. Cost (constitution V)

Every addition is a dictionary lookup or a pre-compiled regex on statements that start with a transaction keyword,
except the locking-clause recogniser (one `FOR\s+(UPDATE|SHARE|NO KEY|KEY)` search per SELECT, short-circuited by a
substring check) and the ON CONFLICT classifier (only on INSERTs containing `ON CONFLICT`, with a cached catalog
lookup). The plan's measurement task times the translator on the existing benchmark corpus before and after, against
the 5 ms budget.

### R11 measured: slice 1 (2026-11-14)

- **Cost**: the per-statement additions (the abort gate, the savepoint parse, the transaction-boundary check, the
  status update) cost a median 1.5 to 2.0 µs per statement over a 600-statement corpus in each status (idle, in a
  transaction, aborted), max 2.5 µs: 0.05% of the 5 ms budget.
- **Coverage**: e2e branch coverage of the new modules from `test_failed_transaction.py` and `test_savepoints.py`
  against a server run under `coverage run` (DBAPI, the lab): `transaction_status.py` 93%, `savepoints.py` 95%,
  `_savepoint_mixin.py` 92%, 93% together. Uncovered: the stack's `clear()` (sessions end instead) and the path where
  IRIS refuses a statement the stack issued.
- **Embedded backend**: this tree and HEAD (2.0.1) run as the embedded server in `pgwire-release-lab`.
  `tests/e2e/test_vector_projection.py` 5/5 on both. A single-session transaction smoke test (abort rule, savepoints,
  psycopg nested block): 4/4 on this tree, 1/4 on HEAD. No regression, and slice 1 works on embedded for one session.
  `irispython` execs `/usr/bin/python3`, so an embedded test server is found by the port it listens on (`ss -ltnp`),
  not by an `irispython` command line.

### R11 measured: slice 2 (2026-11-14)

- **Cost (T048)**: `plan_locking` costs 0.6 µs on a SELECT without a locking clause (the regex pre-check), 26 to 29 µs
  to plan one, and 19 µs to pre-check a 4 KB SELECT. `classify_on_conflict` costs 3.4 µs; `statement_shape`, run only
  in permissive mode when a refused statement arrives, 4.1 µs. All well under 1% of the 5 ms budget. The emulation
  costs IRIS round trips, not translation: one extra statement per locked SELECT (the touch-update), four with
  `NOWAIT` (read the lock timeout, set it to 0, touch, restore), and the catalog lookups (three queries for a locked
  table, two for an upsert's table) once per table until the next DDL.

### R11 measured: slice 3 (2026-11-15)

- **Cost (T079c)**: `parse_timeout_statement`, which now sees every statement on the DBAPI backend, costs 0.10 µs on a
  short SELECT and 0.12 µs on a 4 KB one (the anchored regex fails on the first word), 0.54 µs on a `SET lock_timeout`.
  The emulations cost IRIS round trips, not translation: `SET lock_timeout` sends one `SET OPTION` (plus one read of
  the server default, once per server), and a cancel one `close()` from a worker thread.
- **Coverage (T079a)**: `make isolation-coverage` (default, permissive and read-uncommitted runs, server under
  coverage): spec 052's modules 90% together, the floor; `make coverage-052` (unit tests) 97%.
- **Found by the gate**:
  - The pool's connections ran in the DBAPI driver's autocommit mode, in which a write whose client closed the
    connection still commits once its lock wait ends (measured with the driver alone: `n = 5`; autocommit off:
    `n = 0`). So a cancelled write landed, 10 of 10. The pool now turns the driver's autocommit off; PGWire commits
    after each statement of an autocommit session, as it already did.
  - A cancel could release the statement's connection back to the pool before it was marked failed, so the next
    session got a closed connection (`08000`). It is now marked failed before the first `await`.
  - Describe runs a statement to learn its columns, once for the statement and once for the portal. At READ COMMITTED
    a plain SELECT of a held row waits out the lock, so `FOR UPDATE NOWAIT` waited 20 s before refusing. A NOWAIT
    Describe now takes the lock (fails at once). Not fixed, and true of every extended-protocol read of a held row at
    READ COMMITTED: it waits twice, 20 s, before `40001`.

### R11 measured: release (T081, 2026-11-15)

SC-008 on a throwaway Enterprise IRIS 2026.1.6 (`pgwire-bench-ent`, arm64 key, 127.0.0.1:2993), not the Community lab.
`benchmarks/spec052_statement_overhead.py` starts one DBAPI server from a given tree and runs, over psycopg's extended
protocol in autocommit, a SELECT by primary key, a one-row INSERT and an UPDATE by primary key, plus a BEGIN / SELECT /
2 UPDATEs / COMMIT block: none of spec 052's features. 500 iterations after 50 warm-up; three rounds alternating 2.0.1
(`hotfix/2.0.1` worktree), 2.1.0 and 2.1.0 with `PGWIRE_DEFAULT_ISOLATION=read uncommitted`. Median of the three round
medians, in ms (raw: `build/sc008-results.jsonl`):

| Tree                     | SELECT | INSERT | UPDATE | Block |
| ------------------------ | -----: | -----: | -----: | ----: |
| 2.0.1                    |   3.16 |   1.27 |   0.95 |  5.26 |
| 2.1.0 (read committed)   |   1.79 |   0.93 |   0.81 |  3.55 |
| 2.1.0 (read uncommitted) |   1.65 |   0.86 |   0.76 |  3.25 |

The first run failed SC-008: 2.1.0 was 0.3 ms slower on SELECT, 1.4 ms on UPDATE and 3.2 ms on the block. Not spec
052's own code: called directly, `DBAPIExecutor.execute_query` was faster on 2.1.0 (UPDATE 0.39 ms against 0.46,
SELECT 0.45 against 0.85). A cProfile of the server and a timer around the Execute path found two costs that 2.0.1
already had, which 2.1.0 hit more often once UPDATE and DELETE left the fast-batch path (for correct row counts, the
SQLAlchemy fix):

- `send_query_result` slept 1 ms (`asyncio.sleep(0.001)`) after every extended-protocol result, "for Sync to arrive".
  The message loop reads a buffered stream, so nothing can be missed. On macOS the sleep takes about 1.3 ms.
- `send_no_data`, sent for every INSERT, UPDATE and DELETE, formatted the whole call stack for a debug log line:
  0.9 ms in 2.0.1, 2.1 ms in 2.1.0's deeper stack.

Both removed, each with a budget test (`tests/unit/test_protocol_message_budget.py`). The isolation level makes no
measurable difference here: READ COMMITTED costs about 0.1 ms over READ UNCOMMITTED on these uncontended statements.

### R9 revised: end the IRIS process, don't close the connection (2026-11-15)

Closing the session's DBAPI connection from another thread, as R9 measured, makes the blocked call fail at once, but
it also crashes the process now and then: the PGWire server died with SIGSEGV (exit 139) in one of three runs of 12
cancels (`intersystems-irispython` 5.3.2, macOS arm64). The isolation gate had caught it only as a flaky
`cancel/ten_trials`. The cancel now ends the session's IRIS process instead, with `%SYSTEM.Process.Terminate` through the
Native API on a control connection of its own, and never touches the session's connection from the cancelling thread.
Measured with the driver alone: 40 of 40 blocked calls failed at once with `<COMMUNICATION LINK ERROR>`, none of the
writes landed, and the row lock was free afterwards. Through PGWire, 150 cancels on one server: 150 `57014`, no write
landed, the row free within 1 s every time, the server up throughout (the old cancel: one SIGSEGV in 36). The pool records each
connection's process (`SELECT $JOB`) when it opens it. If IRIS refuses the terminate, the statement runs to completion
and is not committed, because PGWire commits only after a statement it has not cancelled.
