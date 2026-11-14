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
