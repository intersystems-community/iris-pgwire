# Feature Specification: PostgreSQL Transaction Semantics on IRIS

**Feature Branch**: `052-postgres-transaction-semantics`
**Created**: 2026-11-14
**Status**: Draft
**Ships as**: 2.1.0, with a "behaviour changes" section in the changelog
**Builds on**: the 2.0.1 hotfix (`hotfix/2.0.1`, `3424acb`): pool reset on session close, `XX000` as the default
SQLSTATE, `3B001` for SQLCODE -375, the savepoint rewrite on the DBAPI backend
**Amends**: spec 049 FR-002 (ON CONFLICT in batches) and FR-005 (errors in pipeline mode)
**Input**: Track 4 of `docs/plans/2026-11-14-work-tracks.md` ("Track 4 decisions" and "Track 4 spike results and
decisions"), measured by the isolation suite (`tests/e2e/isolation/`, `make isolation`); results in
`docs/investigations/mvcc-apps-on-iris-pgwire.md` section 5, including "2.0.1 re-measurement".

## Why

Applications written for PostgreSQL rely on transaction behaviour that IRIS does not have, and today PGWire passes
most of the difference through without a word. The isolation suite measured what that costs, on IRIS 2026.2 through
PGWire's DBAPI backend, against PostgreSQL 16 as the authority:

- After a failed statement, `COMMIT` commits the work before and after it. PostgreSQL rolls the transaction back.
- `SELECT ... FOR UPDATE` takes no lock. Four workers incrementing a counter that way lost about half their updates,
  with no error.
- ON CONFLICT is emulated by insert-then-catch, which swallows any error whose text says "constraint" (a foreign-key
  violation under `DO NOTHING`, a conflict on a key that is not the target). IRIS's own `INSERT OR UPDATE` matches on
  any unique key and can rewrite a row's primary key.
- IRIS has no `RELEASE SAVEPOINT`, so a psycopg nested `transaction()` block that exits normally raises an error and
  loses the whole outer transaction.
- A CancelRequest is acknowledged and never reaches IRIS; the "cancelled" statement runs later.

### The rule

For each difference: **emulate it in PGWire when the emulation gives PostgreSQL's answer exactly; otherwise refuse
loudly with a PostgreSQL SQLSTATE.** A Critical or High difference is never passed through silently. The one forced
exception is gotcha row 3 (aggregates, `GROUP BY` and full-scan `DISTINCT` read uncommitted rows at READ COMMITTED),
which cannot be detected cheaply and stays documented.

### Strict by default

A server-wide setting, `PGWIRE_TXN_COMPAT=permissive`, brings back the old behaviour **for the refusals only** (locking
clauses, ON CONFLICT forms with no exact mapping), logging a warning once per statement shape. The exact emulations
(aborted transactions, the savepoint stack, `3B001`) are always on: permissive mode never brings back
commit-after-error.

## User Scenarios & Testing _(mandatory)_

The users are developers running a PostgreSQL application, ORM or migration tool against IRIS through PGWire, and the
operators who run the server. Every scenario below is a check in the isolation suite, run against PGWire and against
the reference PostgreSQL 16 with PostgreSQL's answer as the expected one.

### User Story 1 - A failed statement aborts the transaction (Priority: P1)

A developer's code runs several statements in a transaction; one fails (a duplicate key, say). As on PostgreSQL, the
transaction is then aborted: every later statement is refused until the transaction ends, and `COMMIT` rolls it back.
Today the failed statement is undone on its own and `COMMIT` commits the rest, so an application that relies on
"all or nothing" writes half its work.

**Why this priority**: silent partial commits corrupt application data, and nearly every PostgreSQL application relies
on this rule without knowing it. Measured: `BEGIN; INSERT 1; INSERT 1 (duplicate); INSERT 2; COMMIT` committed rows 1
and 2 on both protocols.

**Independent Test**: the suite's `failed_transaction/*` checks give PostgreSQL's answer on both protocols.

**Acceptance Scenarios**:

1. **Given** an open transaction in which a statement has failed, **When** the client sends any statement other than
   `ROLLBACK`, `ROLLBACK TO SAVEPOINT` or `COMMIT`, **Then** it is refused with `25P02` (`in_failed_sql_transaction`)
   and not sent to IRIS.
2. **Given** an aborted transaction, **When** the client sends `COMMIT`, **Then** the transaction is rolled back and
   the reply's command tag is `ROLLBACK`, as on PostgreSQL.
3. **Given** an aborted transaction, **When** the server sends ReadyForQuery, **Then** its status is `E` (failed
   transaction), on the simple and the extended protocol.
4. **Given** an aborted transaction with a savepoint established before the failure, **When** the client sends
   `ROLLBACK TO SAVEPOINT` that savepoint, **Then** the transaction is usable again and the work before the savepoint
   is kept.
5. **Given** no explicit transaction (autocommit), **When** a statement fails, **Then** nothing else changes: the next
   statement runs normally.

---

### User Story 2 - Savepoints behave as on PostgreSQL (Priority: P1)

A developer uses nested transactions: psycopg's `with conn.transaction():` inside another, SQLAlchemy's
`begin_nested()`, Django's `atomic()`, or raw `SAVEPOINT` / `ROLLBACK TO` / `RELEASE`. Each behaves as on PostgreSQL.
PGWire keeps track of the savepoints itself, because IRIS has no `RELEASE` and deletes a savepoint when it is rolled
back to.

**Why this priority**: since 2.0.1 a nested block that rolls back works, but one that exits normally raises an error
(`RELEASE`, SQLCODE -51) and the whole outer transaction is lost. That is the common path of every nested block.

**Independent Test**: the suite's `savepoints/*` checks give PostgreSQL's answer, including psycopg nested blocks that
exit normally, raise, and nest three deep.

**Acceptance Scenarios**:

1. **Given** a savepoint `s`, **When** the client sends `RELEASE SAVEPOINT s` (or `RELEASE s`), **Then** it succeeds,
   `s` and every savepoint established after it are forgotten, and their work stays in the transaction.
2. **Given** a savepoint `s`, **When** the client rolls back to `s` twice with work between, **Then** both succeed and
   only the work before `s` survives (the savepoint survives a rollback to it, as on PostgreSQL).
3. **Given** savepoints `a` then `b`, **When** the client rolls back to `a`, **Then** `b` is gone and `a` remains.
4. **Given** an open transaction, **When** the client rolls back to or releases a name that is not established, **Then**
   it is refused with `3B001` and the transaction is aborted (User Story 1), as on PostgreSQL.
5. **Given** a psycopg nested `transaction()` block that exits normally, **When** the outer block commits, **Then**
   every row from both blocks is committed and no error is raised.
6. **Given** the same savepoint name established twice, **When** the client rolls back to it, **Then** the most
   recent one is used, as on PostgreSQL.

---

### User Story 3 - Row locking clauses lock, or are refused (Priority: P2)

A developer writes `SELECT ... FOR UPDATE` to serialise read-then-write (job queues, counters, balance transfers).
Where PGWire can make that lock exactly, it does; where it cannot, the statement is refused instead of running
unlocked.

**Why this priority**: IRIS documents `FOR UPDATE` as doing nothing, and the suite measured lost updates with no error.
The touch-update (`UPDATE t SET pk = pk WHERE ...`) was measured to lock exactly as PostgreSQL's `FOR UPDATE` does
(1000 of 1000 increments), so an exact emulation exists for the common shape.

**Independent Test**: the suite's `locking/*` checks: a second `FOR UPDATE` and a writer wait for COMMIT, the counter
reaches 1000 of 1000, and refused shapes get the specified SQLSTATE.

**Acceptance Scenarios**:

1. **Given** a single-table `SELECT ... FOR UPDATE` whose `WHERE` PGWire can reuse in an `UPDATE`, **When** it runs
   inside a transaction, **Then** the selected rows are locked until the transaction ends and the rows returned are the
   same as without the clause.
2. **Given** such a statement with `NOWAIT`, **When** a selected row is locked by another session, **Then** it fails at
   once with `55P03` (`lock_not_available`).
3. **Given** `FOR UPDATE` on a shape PGWire cannot lock exactly (a join, a subquery in `FROM`, `GROUP BY`, a `LIMIT` or `OFFSET`, a view), **When** strict mode is on, **Then** it is refused with `0A000` and a message
   naming the shape and the workaround.
4. **Given** `SKIP LOCKED`, `FOR SHARE`, `FOR NO KEY UPDATE` or `FOR KEY SHARE`, **When** strict mode is on, **Then**
   it is refused with `0A000` (today `42601`, a syntax error).
5. **Given** permissive mode, **When** a refused shape arrives, **Then** it runs as before 2.1 (the clause stripped or
   passed through) and a warning is logged once for that statement shape.
6. **Given** `FOR UPDATE` outside an explicit transaction, **When** it runs, **Then** it behaves as on PostgreSQL in
   autocommit: the lock lasts only for the statement.

---

### User Story 4 - ON CONFLICT does exactly what it says, or is refused (Priority: P2)

A developer uses `INSERT ... ON CONFLICT` (upserts, idempotent inserts, ORM `get_or_create`). PGWire sends IRIS's
native `INSERT OR UPDATE` only for the one form it expresses exactly, and refuses the rest in strict mode. In
permissive mode the existing emulation stays, with its known bugs fixed.

**Why this priority**: the emulation today is not atomic and swallows unrelated errors; `INSERT OR UPDATE` used
loosely rewrites primary keys. Both lose or corrupt data silently.

**Independent Test**: the suite's `on_conflict/*` checks: the exact form gives PostgreSQL's rows, every inexact form is
refused with `0A000` in strict mode, and the permissive emulation no longer swallows a foreign-key violation or a
conflict on another key.

**Acceptance Scenarios**:

1. **Given** a table whose only unique key is the conflict target, **When** `ON CONFLICT (target) DO UPDATE` sets every
   inserted column from `EXCLUDED` with no `WHERE`, **Then** PGWire sends IRIS's `INSERT OR UPDATE` and the rows
   match PostgreSQL's, on both the insert and the update path.
2. **Given** any other ON CONFLICT form (a `SET` of a subset of columns, a `SET` that reads the existing row, a
   `DO UPDATE ... WHERE`, a table with a second unique key, a target that is not the only unique key, `DO NOTHING`),
   **When** strict mode is on, **Then** it is refused with `0A000`, naming the form.
3. **Given** permissive mode and `ON CONFLICT ... DO NOTHING`, **When** the insert fails with a foreign-key violation or
   a unique violation on a key that is not the target, **Then** the error reaches the client (`23503` / `23505`).
4. **Given** permissive mode, **When** the emulation decides whether an error was the conflict, **Then** it decides by
   IRIS's unique-violation code (SQLCODE -119) on the target key, never by the wording of the message.
5. **Given** permissive mode on a connection where the IRIS driver reports `<LIST ERROR>` in place of the unique
   violation (measured after a table is recreated), **When** the emulation meets it, **Then** it does not guess: the
   statement fails with `XX000` and the connection is not reused (as 2.0.1 already does).

---

### User Story 5 - `lock_timeout` works (Priority: P3)

A developer or a migration tool sets `lock_timeout` so a statement gives up rather than waiting on a lock. PGWire maps
it to IRIS's lock timeout.

**Why this priority**: IRIS's default 10-second wait makes contended statements slow and health checks report hangs;
migration tools set `lock_timeout` routinely. Measured on IRIS: a lock timeout of 0 failed a contended write in 0.00 s,
and of 2 in 2.00 s.

**Independent Test**: the suite times a contended write after `SET lock_timeout` to several values.

**Acceptance Scenarios**:

1. **Given** `SET lock_timeout = '2s'` (or `2000`, `2000ms`), **When** a statement meets a lock held by another session,
   **Then** it fails after about 2 seconds with `55P03`, the SQLSTATE PostgreSQL uses for a lock timeout.
2. **Given** a value that is not a whole number of seconds, **When** it is applied, **Then** it is rounded up to the
   next whole second, and `SHOW lock_timeout` reports the value the client set.
3. **Given** `SET lock_timeout = 0` or `RESET lock_timeout`, **When** it is applied, **Then** the server's default wait
   is restored (PostgreSQL's 0 means "wait forever"; IRIS has no unbounded wait, which is documented).
4. **Given** `SET statement_timeout`, **When** it is applied, **Then** it is accepted, has no effect, is logged once per
   session, and is listed in the documentation as not enforced.

---

### User Story 6 - A cancel is never silently ignored (Priority: P3)

A client cancels a long or waiting statement (psql's Ctrl-C, a driver's timeout). Today PGWire acknowledges the
cancel, IRIS never hears of it, and the statement completes later. In 2.1 a cancel ends the statement: PGWire closes
that session's IRIS connection, so the statement fails with `57014` (`query_canceled`) and its transaction is rolled
back.

**Why this priority**: a cancelled write that lands later is data the user believes was not written. Closing the
connection is louder than PostgreSQL (which keeps the transaction open but aborted), but never wrong.

**Independent Test**: the suite's `cancel/*` check: a statement waiting on a lock is cancelled, fails with `57014`
before the lock is released, and its write is not applied.

**Acceptance Scenarios**:

1. **Given** a statement running or waiting on a lock, **When** a valid CancelRequest for that session arrives, **Then**
   the statement fails with `57014`, its transaction is rolled back, and its writes are not applied.
2. **Given** a cancelled session, **When** the client sends its next statement, **Then** the session still works, on a
   fresh IRIS connection, outside any transaction, at the session's isolation level.
3. **Given** a CancelRequest for a session with no statement running, **When** it arrives, **Then** nothing happens, as
   on PostgreSQL.
4. **Given** a CancelRequest with a wrong secret key, **When** it arrives, **Then** it is ignored.
5. **Given** a statement cancelled inside an explicit transaction, **When** the client sends its next statement,
   **Then** the session is outside any transaction (ReadyForQuery `I`). PostgreSQL would report `E` and keep the
   transaction open; this deviation is pinned in the suite with its reason (see Assumptions).

---

### User Story 7 - READ COMMITTED is the default (Priority: P3)

An operator upgrades to 2.1. New sessions start at READ COMMITTED, PostgreSQL's default, instead of IRIS's READ
UNCOMMITTED. An operator who needs the old behaviour sets `PGWIRE_DEFAULT_ISOLATION=read uncommitted`.

**Why this priority**: READ UNCOMMITTED reads uncommitted data silently; READ COMMITTED on IRIS fails loudly (a
`40001` after the lock wait), and User Story 5 bounds that wait. Since 2.0.1 an accepted level is reliably in force.

**Independent Test**: on a fresh server, `SHOW transaction_isolation` reports `read committed` and a read of a row
another session holds does not return the uncommitted value; with the setting, both report and behave as READ
UNCOMMITTED.

**Acceptance Scenarios**:

1. **Given** a 2.1 server with no setting, **When** a session starts, **Then** it reports and runs at READ COMMITTED,
   including on a reused pooled connection.
2. **Given** `PGWIRE_DEFAULT_ISOLATION=read uncommitted`, **When** a session starts, **Then** it reports and runs at
   READ UNCOMMITTED.
3. **Given** an unsupported value (`repeatable read`, `serializable`, anything unknown), **When** the server starts,
   **Then** it refuses to start and says which values are accepted.
4. **Given** the change, **When** an operator reads the 2.1 changelog, **Then** it is listed under behaviour changes,
   with gotcha row 3 (aggregates still read uncommitted rows at READ COMMITTED) and the escape hatch.

---

### User Story 8 - The suite gates releases, and users can see what works (Priority: P2)

A maintainer cannot release 2.1 (or any later version) without the isolation suite passing, and a user can read, in
one page, which PostgreSQL transaction behaviours work, which are refused, and what to do instead.

**Why this priority**: every finding in this spec came from the suite, and two earlier conclusions about IRIS turned
out to be PGWire bugs. Without the gate, the next regression is found by a user.

**Independent Test**: the release checklist contains the step; `docs/POSTGRES_APP_COMPATIBILITY.md` exists, is linked
from `KNOWN_LIMITATIONS.md`, and every claim in it is backed by a suite check.

**Acceptance Scenarios**:

1. **Given** a release candidate, **When** a maintainer follows `docs/RELEASE_CHECKLIST.md`, **Then** it requires
   `make isolation` to pass on a fresh server and the Hermitage table to be regenerated.
2. **Given** the compatibility page, **When** a user reads it, **Then** it covers what works, what needs redesign, an
   ORM and driver table (psycopg, SQLAlchemy, Django, Prisma, Rails, Hibernate), permissive mode, and the Hermitage
   row for IRIS through PGWire.
3. **Given** a behaviour this spec changes, **When** its pin in `tests/e2e/isolation/known_differences.py` no longer
   matches, **Then** the pin is removed (PostgreSQL's answer) or updated with the reason, in the same change.

### Edge Cases

- **Errors inside a pipeline** (extended protocol, several statements before one Sync): after an error PostgreSQL
  discards messages until Sync, and if a transaction is open it is aborted. PGWire does the same. This replaces spec
  049 FR-005 ("an error SHOULD NOT abort subsequent statements").
- **Batched ON CONFLICT** (spec 049 FR-002, executemany): the strict and permissive rules of User Story 4 apply per
  statement shape. The embedded backend's executemany dropping `DO UPDATE` belongs to spec 051, not here.
- **An error in `COMMIT` itself** (a deferred constraint, a lost connection): the transaction is reported as rolled
  back, never as committed.
- **A failed statement in a transaction the client began with `BEGIN ISOLATION LEVEL ...`**: the abort rule applies the
  same way; the level is not changed by the abort.
- **`ROLLBACK TO SAVEPOINT` in a transaction aborted before any savepoint existed**: refused with `3B001`; the
  transaction stays aborted.
- **Many savepoints in one transaction**: an ORM that opens and releases a savepoint per row reaches IRIS's limit of
  254 savepoints per transaction (released ones still count). The 255th is refused loudly (FR-008a); the
  compatibility page names the limit and the workaround (commit in batches).
- **Savepoint names**: case and quoting follow PostgreSQL (`"S1"` and `s1` are different; `S1` and `s1` are the same).
- **A cancel that races the statement's completion**: either the statement's result or `57014` is delivered, never
  both, and never a write the client was told was cancelled.
- **`FOR UPDATE OF table`** on a single-table query: treated as `FOR UPDATE`; with several tables, refused like a join.
- **Lock escalation**: a touch-update of more than IRIS's lock-escalation threshold (1000 rows by default) escalates to
  a table lock. Documented, not prevented; measuring it needs an enterprise-key lab (out of scope).
- **The touch-update's side effects**: it fires `UPDATE` triggers and bumps a `ROWVERSION` column. A table with an `UPDATE` trigger or a
  `ROWVERSION` column is therefore a shape the emulation refuses in strict mode, because the emulation would not be
  exact there.
- **Embedded backend**: none of this applies. It stays documented as single-client; its guard against concurrent
  transactions is spec 051 task T088.

## Requirements _(mandatory)_

### Functional Requirements

#### Aborted transactions (US1)

- **FR-001**: After a statement fails inside an explicit transaction, the server MUST refuse every later statement
  except `ROLLBACK`, `ROLLBACK TO SAVEPOINT` (to an established savepoint) and `COMMIT`, with `25P02`, without sending
  it to IRIS.
- **FR-002**: `COMMIT` in an aborted transaction MUST roll it back and reply with the command tag `ROLLBACK`.
- **FR-003**: ReadyForQuery MUST report `E` while a transaction is aborted, on both protocols.
- **FR-003a**: After an error while handling an extended-protocol message (Parse, Bind, Describe, Execute, Close),
  the server MUST discard every message up to the next Sync, then answer Sync with ReadyForQuery, as PostgreSQL does.
  This replaces spec 049 FR-005.
- **FR-004**: The abort rule MUST be always on; `PGWIRE_TXN_COMPAT=permissive` MUST NOT disable it.

#### Savepoints (US2)

- **FR-005**: The server MUST keep each session's savepoint stack itself and answer `SAVEPOINT`, `ROLLBACK TO
[SAVEPOINT]` and `RELEASE [SAVEPOINT]` as PostgreSQL does, including a savepoint surviving a rollback to it and
  `RELEASE` forgetting the named savepoint and every later one.
- **FR-006**: `RELEASE` MUST succeed without being sent to IRIS (which has no `RELEASE`).
- **FR-007**: Rolling back to or releasing a name not on the stack MUST be refused with `3B001` and MUST abort the
  transaction.
- **FR-007a**: `SAVEPOINT`, `ROLLBACK TO` and `RELEASE` outside an explicit transaction MUST be refused with `25P01`
  (`no_active_sql_transaction`), as PostgreSQL does.
- **FR-008**: Savepoint names MUST follow PostgreSQL's identifier rules for case and quoting.
- **FR-008a**: IRIS allows 254 savepoints per transaction, counting released ones (each raises `$TLEVEL`; the 255th
  fails with SQLCODE -400, after which the transaction's work is lost and `COMMIT` still succeeds; measured
  2026-11-14). The server MUST refuse the savepoint that would exceed the limit with `54000`
  (`program_limit_exceeded`) and MUST abort the transaction (FR-001), so the loss is never silent.

#### Row locking clauses (US3)

- **FR-009**: Inside an explicit transaction, `SELECT ... FOR UPDATE` on a shape the emulation covers MUST lock the
  selected rows until the transaction ends, and MUST return the same rows as the statement without the clause.
- **FR-010**: The emulation MUST cover a single base table in `FROM` with a `WHERE` the server can reuse unchanged, and
  MUST refuse every other shape in strict mode with `0A000` and a message that names the shape.
- **FR-011**: `NOWAIT` MUST fail at once with `55P03` when a selected row is locked by another session.
- **FR-012**: `SKIP LOCKED`, `FOR SHARE`, `FOR NO KEY UPDATE` and `FOR KEY SHARE` MUST be refused with `0A000` in
  strict mode.

#### ON CONFLICT (US4)

- **FR-013**: The server MUST map `ON CONFLICT (target) DO UPDATE` to IRIS's `INSERT OR UPDATE` only when the target is
  the table's only unique key (primary key included) and the update sets every inserted column from `EXCLUDED`, with
  no `WHERE`.
- **FR-014**: In strict mode every other ON CONFLICT form, `DO NOTHING` included, MUST be refused with `0A000` naming
  the form.
- **FR-015**: In permissive mode the insert-then-catch emulation MUST treat as a conflict only a unique violation
  (SQLCODE -119) on the conflict target; every other error MUST reach the client.
- **FR-016**: In permissive mode, an error the IRIS driver reports as `<LIST ERROR>` MUST fail the statement with
  `XX000`, not be treated as a conflict.
- **FR-017**: The `DO NOTHING` emulation MUST honour its conflict target (today it ignores it).

#### Timeouts and cancel (US5, US6)

- **FR-018**: `SET lock_timeout` MUST set IRIS's lock timeout for the session, in whole seconds rounded up; `0` and
  `RESET` MUST restore the server default; `SHOW lock_timeout` MUST report the value set.
- **FR-019**: A statement that times out waiting for a lock after `lock_timeout` was set MUST fail with `55P03`. One
  that waits out the server's default timeout keeps `40001` (unchanged since 1.x).
- **FR-020**: `statement_timeout` MUST be accepted and MUST NOT be enforced; the server MUST log once per session that
  it is not enforced.
- **FR-021**: A valid CancelRequest for a session with a statement in progress MUST end that statement with `57014`,
  roll back its transaction, and leave the session usable on a fresh IRIS connection.
- **FR-022**: A cancelled statement's writes MUST NOT be applied.

#### Default isolation (US7)

- **FR-023**: New sessions MUST start at READ COMMITTED unless `PGWIRE_DEFAULT_ISOLATION` says otherwise; this default
  MUST hold on a reused pooled connection.
- **FR-024**: `PGWIRE_DEFAULT_ISOLATION` MUST accept `read committed` and `read uncommitted`; any other value MUST stop
  the server at startup with a message listing the accepted values.

#### Compatibility mode (all refusals)

- **FR-025**: `PGWIRE_TXN_COMPAT` MUST accept `strict` (the default) and `permissive`; any other value MUST stop the
  server at startup.
- **FR-026**: In permissive mode a statement that strict mode would refuse MUST run as it did in 2.0, and the server
  MUST log one warning per distinct statement shape.

#### Measurement and documentation (US8)

- **FR-027**: Every acceptance scenario in this spec MUST be a check in the isolation suite, run against PGWire and the
  reference PostgreSQL 16, with PostgreSQL's answer as the expectation and any remaining IRIS difference pinned with
  its reason.
- **FR-028**: `docs/RELEASE_CHECKLIST.md` MUST require `make isolation` to pass on a fresh server before a release.
- **FR-029**: `docs/POSTGRES_APP_COMPATIBILITY.md` MUST exist, MUST be linked from `KNOWN_LIMITATIONS.md`, and MUST be
  consistent with the suite's results.
- **FR-030**: The 2.1.0 changelog MUST list under "behaviour changes": the abort rule, the READ COMMITTED default, the
  refusals and permissive mode, the cancel behaviour, and the SQLSTATE changes (`42601` to `0A000` for locking
  clauses, `55P03` for lock timeouts set by the client).

### Key Entities

- **Session transaction state**: whether a transaction is open, whether it is aborted, its isolation level, and its
  savepoint stack. Owned by PGWire per client session; reset when the session ends or its IRIS connection is replaced.
- **Savepoint stack**: the ordered names a session has established in the current transaction, each standing for an
  IRIS savepoint PGWire re-establishes as needed.
- **Compatibility mode**: a server-wide setting, strict or permissive, that decides only whether shapes without an
  exact emulation are refused.
- **Statement shape**: the form of a statement with its literals removed, used to log one permissive-mode warning per
  shape.
- **Known difference (pin)**: an IRIS outcome the suite records where it still differs from PostgreSQL, with its reason.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: In the isolation suite, every check this spec adds or changes gives PostgreSQL's answer, and no pin that
  this spec makes obsolete remains.
- **SC-002**: A transaction containing a failed statement never commits any of its work: 0 rows committed in 100 of 100
  trials, on both protocols.
- **SC-003**: Four workers incrementing one counter 250 times each through `SELECT ... FOR UPDATE` then `UPDATE` end at
  1000 of 1000, with no lost update, in 5 of 5 runs.
- **SC-004**: A psycopg nested `transaction()` block, exiting normally or by an exception, three deep, leaves exactly
  the rows PostgreSQL leaves in every combination the suite tries.
- **SC-005**: No ON CONFLICT form the suite tries silently gives a different result from PostgreSQL in strict mode: it
  either matches PostgreSQL's rows or is refused.
- **SC-006**: After `SET lock_timeout = '2s'`, a contended write fails within 2 to 3 seconds; with no setting it still
  fails after the server's default (10 s).
- **SC-007**: A cancelled statement waiting on a lock fails within 1 second of the cancel, and its write is never
  applied, in 10 of 10 trials.
- **SC-008**: The added work stays within the constitution's budget: translation and bookkeeping add no more than 5 ms
  per statement, and a session that uses none of these features sees no measurable change in the existing benchmark.
- **SC-009**: Every statement in `docs/POSTGRES_APP_COMPATIBILITY.md` about what works or is refused is backed by a
  named check in the suite.

## Assumptions

- **DBAPI backend only.** The embedded backend shares one IRIS process across sessions, so per-session transactions do
  not exist there; it stays documented as single-client (spec 051 T088).
- **IRIS 2026.2, Community Edition**, on `pgwire-release-lab`, is the measurement target, as for the spike. Lock
  escalation (E6) and pgbench (E7) need an enterprise-key lab and are not part of this spec's gate.
- **The emulations are measured, not argued.** The touch-update's exclusion, `LOCK_TIMEOUT` behaviour and the single
  exact `INSERT OR UPDATE` form were all measured in the spike; anything this spec emulates beyond those must be
  measured in the suite before it ships.
- **`55P03` for a client-set lock timeout, `40001` for the default wait.** PostgreSQL reports a `lock_timeout` expiry as
  `55P03`. The default wait stays `40001` because, without MVCC, it is how IRIS reports every conflict, and retry
  helpers key on it (see `sql_translator/sqlstate.py`).
- **Cancel by closing the connection** is accepted as louder than PostgreSQL: the whole transaction ends, where
  PostgreSQL leaves it open and aborted. A true cancel through IRIS's own API is later work.
- **No GitHub issues** are filed from this spec; tickets are `tasks.md` through `/speckit.tasks`, tests first.

## Out of Scope

- The embedded backend (spec 051 T088), and the embedded executemany dropping `DO UPDATE` (spec 051).
- Advisory locks (`pg_advisory_lock` and friends; they stay `42883`). A later spec may emulate them for migration
  tools.
- Emulating `SKIP LOCKED` (no exact mapping exists).
- Gotcha row 3: aggregates, `GROUP BY` and full-scan `DISTINCT` reading uncommitted rows at READ COMMITTED. Documented.
- REPEATABLE READ and SERIALIZABLE (still refused with `0A000`).
- Enforcing `statement_timeout`; a true IRIS-side cancel; running the suite in CI.
- The `<LIST ERROR>` itself, which comes from below PGWire (intersystems-irispython 5.3.2 reproduces it alone).
- Translating `%` (modulo), and the `INSERT OR UPDATE INTO` rewrite bug: separate fixes, not transaction semantics.
