---
description: "Tasks for spec 052, PostgreSQL transaction semantics on IRIS"
---

# Tasks: PostgreSQL Transaction Semantics on IRIS

**Input**: `specs/052-postgres-transaction-semantics/` (spec.md, plan.md, research.md, data-model.md,
contracts/wire-behaviour.md, quickstart.md)
**Branch**: `052-postgres-transaction-semantics` (based on `hotfix/2.0.1`)

**Tests**: mandatory and first in every phase. Order inside a phase: unit tests for the pure modules (they must fail
first), then isolation-suite checks in `tests/e2e/isolation/` (run against PGWire and PostgreSQL 16, PostgreSQL's
answer expected; they must fail on PGWire first), then the implementation, then pin removal in
`tests/e2e/isolation/known_differences.py`.

**Phase gate (every phase)**: `make isolation` passes on a fresh server (check first that nothing listens on 5442 and
`pgwire-bench-dbapi` is stopped; `pgwire-release-lab` on 2992 and `iris-pgwire-pgref` on 55433 are up), and
`.venv/bin/python -m pytest tests/unit -q -p no:randomly` passes in its own process, apart from the failures already
at HEAD (`test_sql_metrics.py` ×3 and five collection errors from the missing `toml`, measured 2026-11-14).

**Rules that apply to every task**: format only the files you create (black/prettier churn, see the repo memory);
`ruff check --fix` on touched files; run `markdownlint-cli2 --fix` and `prettier --write` on every edited `.md`; no
commit credits AI tooling.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US8, from spec.md

---

## Phase 1: Setup

**Purpose**: let the suite run against a server with non-default settings, which US3, US4 and US7 need.

- [ ] T001 Add `ISOLATION_SERVER_ENV` and `ISOLATION_MARK` to the `isolation` target in `Makefile`: the env assignments
      are prefixed to the server's command line, the mark is passed as `-m "isolation and $(ISOLATION_MARK)"` when set.
      Add `isolation-permissive` (`PGWIRE_TXN_COMPAT=permissive`, mark `permissive`) and `isolation-read-uncommitted`
      (`PGWIRE_DEFAULT_ISOLATION="read uncommitted"`, mark `default_isolation`) targets that call it. Default
      `make isolation` behaviour unchanged.
- [ ] T002 Register the `permissive` and `default_isolation` markers in `pyproject.toml` (`[tool.pytest.ini_options]
    markers`) and make `tests/e2e/isolation/conftest.py` skip tests carrying either marker unless
      `ISOLATION_MARK` names it, so the default run never needs a second server.
- [ ] T003 Record the ReadyForQuery status per step for the US1/US2 scripts: extend `run_statement` in
      `tests/e2e/isolation/harness.py` to capture `conn.info.transaction_status` after each statement into `Outcome`
      (new field `status_after`, values `IDLE`/`INTRANS`/`INERROR`), keeping every existing caller working.

**Checkpoint**: `make isolation` still 110 passed; `make isolation-permissive` runs zero tests and exits 0.

---

## Phase 2: Foundational

**Purpose**: the two server settings every later story reads, and the SQLSTATEs the stories emit.

- [ ] T004 [P] Unit tests in `tests/unit/test_backend_config_txn_settings.py`: `BackendConfig` gets `default_isolation`
      (env `PGWIRE_DEFAULT_ISOLATION`, default `read committed`, accepts `read committed` / `read uncommitted`, case and
      whitespace normalised) and `txn_compat` (env `PGWIRE_TXN_COMPAT`, default `strict`, accepts `strict` /
      `permissive`); any other value raises a validation error whose message lists the accepted values.
- [ ] T005 [P] Unit tests in `tests/unit/test_sqlstate_classification.py` (append): `classify_iris_error` returns
      `55P03` (`lock_not_available`) for -110/-114 when called with `lock_timeout_set=True` and `40001` otherwise; the
      module exposes constants for `25P02` (`in_failed_sql_transaction`), `25P01` (`no_active_sql_transaction`),
      `54000` (`program_limit_exceeded`), `57014` (`query_canceled`).
- [ ] T006 Implement T004 in `src/iris_pgwire/models/backend_config.py`: two fields, validators, and two rows in the
      env-var table (around line 208). Do not wire them anywhere yet.
- [ ] T007 Implement T005 in `src/iris_pgwire/sql_translator/sqlstate.py`: the constants and a keyword-only
      `lock_timeout_set: bool = False` parameter on `classify_iris_error`.

**Checkpoint**: unit tests green; `make isolation` unchanged (110 passed). Gate.

---

## Phase 3: User Story 1 — a failed statement aborts the transaction (P1, slice 1) 🎯 MVP

**Goal**: FR-001 to FR-004. **Independent test**: `failed_transaction/*` give PostgreSQL's answer on both protocols.

### Tests first

- [ ] T008 [P] [US1] Unit tests in `tests/unit/test_transaction_status.py` for a pure status machine
      (`src/iris_pgwire/transaction_status.py`, data-model.md "Transaction status"): every row of the transitions table,
      including `E` + `COMMIT` → `I` with tag `ROLLBACK`, `E` + `ROLLBACK TO` known → `T`, `E` + other → refuse with
      `25P02`, `I` + error → `I`; which statements are "transaction exit" statements (every `_COMMIT_FORMS` /
      `_ROLLBACK_FORMS` spelling in `protocol.py:1207`, `ROLLBACK TO [SAVEPOINT] x`, with comments and a trailing `;`).
- [ ] T009 [US1] Suite checks in `tests/e2e/isolation/test_failed_transaction.py`, both protocols: after a duplicate
      key in a transaction, the next INSERT gets `25P02` with status `INERROR`; `COMMIT` replies `ROLLBACK`, status
      `IDLE`, table empty (replace the expectation of `error_then_commit` with PostgreSQL's steps
      `BEGIN, INSERT, 23505, 25P02, ROLLBACK` and statuses); `ROLLBACK` recovers; `ROLLBACK TO` a savepoint taken before
      the error recovers and keeps the earlier row; in autocommit a failed statement changes nothing (FR-001 scenario 5).
- [ ] T010 [US1] Suite check in `tests/e2e/isolation/test_failed_transaction.py`: a psycopg pipeline
      (`with conn.pipeline():`) inside a transaction sends INSERT 1, a duplicate INSERT 1, INSERT 2, then Sync: the
      third gets no result (discarded), the transaction is aborted, and the table is empty after COMMIT (research R3).
- [ ] T011 [US1] Suite check (SC-002): 100 trials of `BEGIN; INSERT; failing INSERT; INSERT; COMMIT` on each protocol
      commit 0 rows, in `tests/e2e/isolation/test_failed_transaction.py`.
- [ ] T012 [US1] Run `make isolation`; confirm T009–T011 fail on PGWire and pass on PostgreSQL. Record the failing
      output in the task's commit message.

### Implementation

- [ ] T013 [US1] Implement `src/iris_pgwire/transaction_status.py` until T008 passes.
- [ ] T014 [US1] In `src/iris_pgwire/protocol.py`: `send_error_response` (line 891) sets `transaction_status` to
      `STATUS_FAILED_TRANSACTION` when severity is `ERROR` and the status is `STATUS_IN_TRANSACTION` (research R1).
- [ ] T015 [US1] In `src/iris_pgwire/protocol.py`: gate in `_handle_single_statement` (line 1062) before
      `_maybe_handle_transaction_command`, and in `handle_parse_message` / `handle_execute_message`: in state `E`, a
      statement that is not a transaction exit is answered with `25P02` ("current transaction is aborted, commands
      ignored until end of transaction block") and never reaches the executor.
- [ ] T016 [US1] In `src/iris_pgwire/protocol.py` `_maybe_handle_transaction_command` (line 1217) and the extended
      path's transaction handling (around line 3148): `COMMIT` forms in state `E` call
      `iris_executor.rollback_transaction()` and reply `ROLLBACK` (research R2).
- [ ] T017 [US1] In `src/iris_pgwire/protocol.py`: `_discard_until_sync` (data-model.md): set on an error sent while
      handling Parse/Bind/Describe/Execute/Close; `message_loop` drops every message but Sync while set;
      `handle_sync_message` (line 3239) clears it. Flush any buffered batch (`flush_batch`) is skipped while discarding.
- [ ] T018 [US1] Amend `specs/049-pipeline-mode-executemany/spec.md` FR-005: replaced by spec 052 research R3
      (discard until Sync, as PostgreSQL); leave the old text struck through with the reason.
- [ ] T019 [US1] Remove the `failed_transaction/error_then_commit/*` pins from
      `tests/e2e/isolation/known_differences.py` and update the E5 subsection of
      `docs/investigations/mvcc-apps-on-iris-pgwire.md` ("fixed in 2.1, spec 052 US1").

**Checkpoint (gate)**: `make isolation` passes with US1's checks at PostgreSQL's answer; unit suite green.

---

## Phase 4: User Story 2 — savepoints behave as on PostgreSQL (P1, slice 1) 🎯 MVP

**Goal**: FR-005 to FR-008a. **Independent test**: `savepoints/*` give PostgreSQL's answer, three client spellings.

### Tests first

- [ ] T020 [P] [US2] Unit tests in `tests/unit/test_savepoint_stack.py` for `src/iris_pgwire/savepoints.py`
      (data-model.md "Savepoint stack"): push/rollback-to/release return the IRIS statements to send; most recent
      duplicate wins; rolling back to `a` drops `b`; release drops the named and later entries and sends nothing;
      unknown name → `3B001`; the 255th IRIS level (including re-establishments and released savepoints) → `54000`;
      identifier rules (`"S1"` ≠ `s1`, `S1` = `s1`, doubled quotes); parsing of every spelling (`ROLLBACK TO x`,
      `ROLLBACK TO SAVEPOINT x`, `ROLLBACK WORK TO`, `RELEASE x`, `RELEASE SAVEPOINT x`, quoted, trailing `;`).
- [ ] T021 [US2] Suite checks in `tests/e2e/isolation/test_savepoints.py`: rollback-to twice keeps the savepoint (PG:
      rows [1]); rollback to `a` drops `b` (second gets `3B001`); `RELEASE` of an existing / after-rollback savepoint
      succeeds; unknown name → `3B001`, then `COMMIT` replies `ROLLBACK`, table empty; savepoint outside a transaction →
      `25P01`; duplicate names; a savepoint established, then a failure, then `ROLLBACK TO` it recovers.
- [ ] T022 [US2] Suite checks in `tests/e2e/isolation/test_savepoints.py` (SC-004): psycopg nested `transaction()`
      blocks three deep, every combination of normal exit and exception at each level (8 cases), rows equal to
      PostgreSQL's; SQLAlchemy `Session.begin_nested()` normal exit and rollback (psycopg dialect); Django-style quoted
      `SAVEPOINT "s1_x1"` / `RELEASE SAVEPOINT "s1_x1"` / `ROLLBACK TO SAVEPOINT "s1_x1"` scripts.
- [ ] T023 [US2] Suite check in `tests/e2e/isolation/test_savepoints.py`: 300 `SAVEPOINT`/`RELEASE` pairs in one
      transaction. PostgreSQL: all succeed. PGWire: the 255th `SAVEPOINT` gets `54000`, status `INERROR`, `COMMIT`
      replies `ROLLBACK`, table empty. Pin that outcome with the reason (IRIS limit, research R4, spec FR-008a).
- [ ] T024 [US2] Run `make isolation`; confirm T021–T022 fail on PGWire and pass on PostgreSQL.

### Implementation

- [ ] T025 [US2] Implement `src/iris_pgwire/savepoints.py` until T020 passes.
- [ ] T026 [US2] Create `src/iris_pgwire/_savepoint_mixin.py`: a mixin like `IsolationMixin` (`_isolation.py`) that
      intercepts `SAVEPOINT` / `ROLLBACK TO` / `RELEASE` in `execute_query`, keeps one stack per session, sends the
      statements the stack returns (with `_skip_isolation=True`), and returns the command tag (`SAVEPOINT`,
      `ROLLBACK`, `RELEASE`) or the error with its SQLSTATE; `25P01` outside a transaction. Clear the stack on
      transaction end (hook the same boundary `_note_transaction_boundary` sees) and in `forget_isolation_level`'s
      caller on session close.
- [ ] T027 [US2] Wire the mixin into `src/iris_pgwire/dbapi_executor.py` (`class DBAPIExecutor(SavepointMixin,
    IsolationMixin)`, intercept before `rewrite_savepoint_verbs`) and `src/iris_pgwire/iris_executor.py` (same
      order), so both backends share it (constitution IV).
- [ ] T028 [US2] Replace `_SessionIsolation.savepoint_depth` in `src/iris_pgwire/_isolation.py` with the stack's
      depth; delete `parse_savepoint_change`'s now-unused callers in `sql_translator/isolation.py` only if
      `tests/unit/test_isolation_mid_transaction.py` still passes unchanged.
- [ ] T029 [US2] In `src/iris_pgwire/protocol.py`: a successful `ROLLBACK TO` in state `E` sets the status back to
      `STATUS_IN_TRANSACTION` (data-model.md transitions).
- [ ] T030 [US2] Remove the `savepoints/*` pins (rollback_to_unknown, rollback_to_unknown_with_savepoint,
      rollback_to_twice, release/\*) from `tests/e2e/isolation/known_differences.py`; keep only T023's limit pin. Update
      the E4 table and "2.0.1 re-measurement" notes in `docs/investigations/mvcc-apps-on-iris-pgwire.md`.

**Checkpoint (gate)**: `make isolation` passes; `failed_transaction/*` and `savepoints/*` at PostgreSQL's answer
except the pinned limit; SC-002 and SC-004 recorded. **Slice 1 done (MVP).**

---

## Phase 5: User Story 8 — the suite gates releases, users can see what works (P2, alongside every slice)

**Goal**: FR-027 to FR-029. **Independent test**: the checklist step exists; every compatibility-page claim names a
check.

- [ ] T031 [P] [US8] Unit test in `tests/unit/test_compatibility_doc.py`: every row of the "works / refused" tables in
      `docs/POSTGRES_APP_COMPATIBILITY.md` names a check key (`suite/key`) that appears in
      `tests/e2e/isolation/` source (assert the answer: grep the key in the test modules); `KNOWN_LIMITATIONS.md`
      links the page.
- [ ] T032 [P] [US8] Unit test in `tests/unit/test_release_checklist.py`: `docs/RELEASE_CHECKLIST.md` contains a step
      running `make isolation` on a fresh server and regenerating the Hermitage table.
- [ ] T033 [US8] Write `docs/POSTGRES_APP_COMPATIBILITY.md` with slice 1's rows (aborted transactions, savepoints,
      the 254-savepoint limit and its workaround), the ORM/driver table (psycopg, SQLAlchemy, Django, Prisma, Rails,
      Hibernate: what each sends and what works), the Hermitage row, and a placeholder section per later story marked
      "not yet (spec 052 US3–US7)". Link it from `KNOWN_LIMITATIONS.md`.
- [ ] T034 [US8] Add the release-gate step to `docs/RELEASE_CHECKLIST.md`: preconditions (one server, the two
      containers), `make isolation`, `make isolation-permissive`, `make isolation-read-uncommitted`,
      `make isolation-table`, and "a pin change needs its reason in known_differences.py and the investigation doc".
- [ ] T035 [US8] After each later slice, add its rows to `docs/POSTGRES_APP_COMPATIBILITY.md` (repeat in T046, T058,
      T074; T031 keeps the page honest).

**Checkpoint**: T031–T032 pass.

---

## Phase 6: User Story 3 — row locking clauses lock, or are refused (P2, slice 2)

**Goal**: FR-009 to FR-012, FR-025/026 for these shapes. **Independent test**: `locking/*` at PostgreSQL's answer;
SC-003.

### Tests first

- [ ] T036 [P] [US3] Unit tests in `tests/unit/test_locking_clauses.py` for `src/iris_pgwire/sql_translator/
    locking_clauses.py` (research R6): recognise `FOR UPDATE`, `FOR UPDATE OF t`, `NOWAIT`, `SKIP LOCKED`,
      `FOR SHARE`, `FOR NO KEY UPDATE`, `FOR KEY SHARE`; classify a statement as `emulate` (one base table, `WHERE`
      reusable) or a named refusal (join, subquery or view in FROM, GROUP BY/DISTINCT/aggregate, LIMIT/OFFSET, several
      tables in `OF`); for `emulate`, produce the touch-update (`UPDATE t SET pk = pk WHERE <same predicate>`, `%ID`
      when there is no primary key) and the SELECT without the clause; parameter markers keep their positions; no
      match inside string literals or comments; the cheap pre-check skips SELECTs without `FOR`.
- [ ] T037 [US3] Suite checks in `tests/e2e/isolation/test_locking.py`: the existing `for_update_vs_*` and
      `counter_for_update` checks at both levels expect PostgreSQL's answer (SC-003: 1000 of 1000, 5 runs); add
      `NOWAIT` against a held row → `55P03` within 1 s; a join `FOR UPDATE` → `0A000` (strict); `FOR UPDATE` in
      autocommit returns the rows; rows returned equal the rows without the clause.
- [ ] T038 [US3] Update `tests/e2e/isolation/test_unsupported_clauses.py`: expectation stays PostgreSQL's (`ok`); the
      pins for `for_share`, `for_no_key_update`, `for_key_share`, `for_update_skip_locked` change from `42601` to
      `0A000`; `for_update_nowait` loses its pin (now emulated).
- [ ] T039 [US3] Permissive checks, marker `permissive`, in `tests/e2e/isolation/test_locking.py`: a refused shape
      runs (rows returned) and the server log contains one warning for two identical statements (read
      `build/isolation-server.log`).
- [ ] T040 [US3] Run `make isolation` and `make isolation-permissive`; confirm the new checks fail first.

### Implementation

- [ ] T041 [US3] Implement `src/iris_pgwire/sql_translator/locking_clauses.py` until T036 passes.
- [ ] T042 [US3] Call it from `src/iris_pgwire/dbapi_executor.py` `execute_query` after the interceptor: inside an
      explicit transaction run the touch-update, then the SELECT; `NOWAIT` wraps the touch in `SET OPTION
    LOCK_TIMEOUT = 0` and restores the session's value after, mapping -110 to `55P03`; outside a transaction run the
      SELECT only; refusals return `0A000` in strict mode. Primary key from `_get_primary_key_columns`. Refuse tables
      with an UPDATE trigger or a ROWVERSION column (catalog lookup, cached per table).
- [ ] T043 [US3] Add the permissive-mode warning registry (data-model.md "Statement shape", bounded at 1000) in
      `src/iris_pgwire/compat_mode.py`, read `BackendConfig.txn_compat`, and use it for US3's refusals.
- [ ] T044 [US3] Remove the `locking/*` pins and update the `unsupported_clauses/*` pins in
      `tests/e2e/isolation/known_differences.py`; update gotcha rows for `FOR UPDATE` in
      `docs/investigations/mvcc-apps-on-iris-pgwire.md` and the `FOR UPDATE` paragraph in `KNOWN_LIMITATIONS.md`.
- [ ] T045 [US3] Measure the translator cost on SELECTs with and without `FOR` (existing benchmark corpus,
      `benchmarks/`), record in `specs/052-postgres-transaction-semantics/research.md` R11; must stay under 5 ms.
- [ ] T046 [US3] Add US3's rows to `docs/POSTGRES_APP_COMPATIBILITY.md` (touch-update side effects: triggers,
      ROWVERSION, lock escalation past 1000 rows).

**Checkpoint (gate)**: `make isolation` and `make isolation-permissive` pass.

---

## Phase 7: User Story 4 — ON CONFLICT does exactly what it says, or is refused (P2, slice 2)

**Goal**: FR-013 to FR-017. **Independent test**: `on_conflict/*`; SC-005.

### Tests first

- [ ] T047 [P] [US4] Unit tests in `tests/unit/test_on_conflict_classifier.py` for
      `src/iris_pgwire/sql_translator/on_conflict.py` (research R7): given a `ReturningPlan` and the table's unique
      keys, label `exact` only when the target is the only unique key and `DO UPDATE SET` assigns every inserted
      non-key column from `EXCLUDED` with no `WHERE`; name each inexact form (subset SET, SET reading the row,
      `DO UPDATE ... WHERE`, second unique key, target not the only key, `DO NOTHING`); produce
      `INSERT OR UPDATE t (...) VALUES (...)` without `INTO` for `exact`.
- [ ] T048 [US4] Suite checks in `tests/e2e/isolation/test_on_conflict.py` (strict, default run): the exact form
      matches PostgreSQL on the insert and the update path; each inexact form (the `insert_or_update/*` table's ON
      CONFLICT spellings) gets `0A000` (pin: PostgreSQL accepts them); `do_nothing_*` get `0A000` (pin);
      `upsert_vs_delete/on_conflict` now runs as `INSERT OR UPDATE` (pin `AnyOf` of no errors / `40001`).
- [ ] T049 [US4] Permissive checks, marker `permissive`, in `tests/e2e/isolation/test_on_conflict.py`: `DO NOTHING`
      with a foreign-key violation → `23503`; a collision on a non-target key → `23505`; `DO NOTHING` honours its
      target; a `<LIST ERROR>` conflict (recreate the table on the same connection after a -119, as in
      `test_unique_violation_on_a_new_table`) → `XX000`, not treated as the conflict.
- [ ] T050 [US4] Run both suites; confirm the new checks fail first.

### Implementation

- [ ] T051 [US4] Implement `src/iris_pgwire/sql_translator/on_conflict.py` until T047 passes; unique keys from
      `INFORMATION_SCHEMA.TABLE_CONSTRAINTS` / `KEY_COLUMN_USAGE`, cached per table and invalidated by DDL on it.
- [ ] T052 [US4] In `src/iris_pgwire/dbapi_executor.py`: route `exact` to the rewritten `INSERT OR UPDATE`; refuse
      inexact forms in strict mode (`0A000`, through `compat_mode.py`); in permissive mode keep
      `_handle_on_conflict_update` (line 784) and the handler at line 659, now deciding on `SQLCODE: <-119>` for the
      target only, honouring `DO NOTHING`'s target, and failing `<LIST ERROR>` with `XX000`.
- [ ] T053 [US4] Apply the same strict/permissive rule to batched ON CONFLICT (spec 049 FR-002, `protocol.py`
      `flush_batch` path); amend `specs/049-pipeline-mode-executemany/spec.md` FR-002 to point here.
- [ ] T054 [US4] Fix the `INSERT OR UPDATE INTO t` rewrite to `SQLUser."INTO"` only if T051's rewrite needs it; else
      leave it (out of scope) and note it in research R7.
- [ ] T055 [US4] Update `on_conflict/*` pins in `tests/e2e/isolation/known_differences.py` (remove what now matches,
      re-pin refusals with the reason); keep the `insert_or_update/*` pins (they measure IRIS's native statement).
- [ ] T056 [US4] Move "executemany drops DO UPDATE" (embedded) to spec 051: add a task to
      `specs/051-unified-executor/tasks.md` referencing the spike's E3 row.
- [ ] T057 [US4] Update the ON CONFLICT rows of the gotcha table in `docs/investigations/mvcc-apps-on-iris-pgwire.md`.
- [ ] T058 [US4] Add US4's rows to `docs/POSTGRES_APP_COMPATIBILITY.md` (the exact form, how to rewrite the rest, the
      ORM upsert table).

**Checkpoint (gate)**: `make isolation` and `make isolation-permissive` pass. **Slice 2 done.**

---

## Phase 8: Spikes for slice 3 (constitution III)

**Purpose**: run the two measurements research R8 and R9 depend on, before any US5/US6 code.

- [ ] T059 Spike R8 in `specs/052-postgres-transaction-semantics/spikes/lock_timeout_scope.py` (plain
      intersystems-irispython on 2992, no PGWire): does `SET OPTION LOCK_TIMEOUT = n` on one connection affect another
      connection? Survive COMMIT/ROLLBACK? How is the server default read (which call, value on the lab)? Write results
      into research.md R8, revise US5's design if any assumption fails.
- [ ] T060 Spike R9 in `specs/052-postgres-transaction-semantics/spikes/close_blocked_connection.py`: a thread blocked
      in `cursor.execute` on a locked row; another thread calls `connection.close()`. Does the blocked call return
      promptly with an error? Does IRIS roll back that connection's transaction (check from a third connection)? Is
      the process left clean? If `close()` blocks, try closing the socket. Write results into research.md R9 and
      revise US6's design if needed.

**Checkpoint**: research.md R8 and R9 carry measured results; Thomas told of any design change before Phase 9.

---

## Phase 9: User Story 5 — `lock_timeout` works (P3, slice 3)

**Goal**: FR-018 to FR-020. **Independent test**: `timeouts/*`; SC-006.

- [ ] T061 [P] [US5] Unit tests in `tests/unit/test_lock_timeout_parsing.py`: PostgreSQL units (`2000`, `2000ms`,
      `2s`, `1min`, `'1500ms'`) → whole seconds rounded up; `0` / `RESET` → default; `SHOW` echoes the client's
      spelling as PostgreSQL normalises it (`2s`, `1500ms`); invalid values → `22023` as PostgreSQL.
- [ ] T062 [US5] Suite checks in new `tests/e2e/isolation/test_timeouts.py`: contended write after `lock_timeout`
      `2s` fails in 2–3 s with `55P03`; `1500ms` rounds to 2 s; `0` and `RESET` restore the default (`40001` after
      ~10 s); `statement_timeout` accepted and not enforced (pin: PostgreSQL enforces it, `57014`); a new session on a
      reused connection has the default lock timeout.
- [ ] T063 [US5] Implement parsing in `src/iris_pgwire/sql_translator/timeouts.py` and the SET/SHOW handling in
      `src/iris_pgwire/_isolation.py` (next to the isolation SETs), per research R8 as revised by T059; log
      `statement_timeout` once per session.
- [ ] T064 [US5] Pass `lock_timeout_set` to `classify_iris_error` from the error paths in `protocol.py` (the sites
      changed in 2.0.1) via a session flag; extend `DBAPIExecutor._reset_connection_sync` to restore the default lock
      timeout.
- [ ] T065 [US5] Pin `timeouts/statement_timeout` with its reason in `tests/e2e/isolation/known_differences.py`.

**Checkpoint (gate)**: `make isolation` passes.

---

## Phase 10: User Story 6 — a cancel is never silently ignored (P3, slice 3)

**Goal**: FR-021, FR-022. **Independent test**: `cancel/*`; SC-007.

- [ ] T066 [P] [US6] Unit tests in `tests/unit/test_cancel_routing.py`: `server.find_connection_for_cancellation`
      rejects a wrong secret; a protocol with no statement in progress ignores the cancel; one with a statement in
      progress is marked cancelled and asks its executor to close the session's IRIS connection (a real
      `DBAPIExecutor` object built as in `tests/unit/test_isolation_session_lifecycle.py`, no IRIS needed).
- [ ] T067 [US6] Suite checks in `tests/e2e/isolation/test_cancel.py`: `cancel_lock_wait` expects PostgreSQL's
      answer (`57014` before the lock is released, write not applied; 10 trials, SC-007: within 1 s); the next
      statement in the cancelled session works, status `IDLE`, at the session's isolation level; cancel with no
      statement running changes nothing; cancel with a wrong secret changes nothing.
- [ ] T068 [US6] Implement in `src/iris_pgwire/protocol.py` `handle_cancel_request` (line 3601) via
      `server.find_connection_for_cancellation`, a per-protocol "statement in progress" flag and a cancelled mark;
      `DBAPIExecutor.cancel_session(session_id)` in `src/iris_pgwire/dbapi_executor.py` closes the connection per
      research R9 (as revised by T060), marks it failed, and drops the session's transaction, savepoint and
      isolation-override state. The cancelled statement reports `57014`.
- [ ] T069 [US6] Remove the `cancel/cancel_lock_wait` pin from `tests/e2e/isolation/known_differences.py`; update
      gotcha table and headline 4 in `docs/investigations/mvcc-apps-on-iris-pgwire.md`.

**Checkpoint (gate)**: `make isolation` passes.

---

## Phase 11: User Story 7 — READ COMMITTED is the default (P3, slice 3)

**Goal**: FR-023, FR-024. **Independent test**: `default_isolation/*` on both server settings.

- [ ] T070 [P] [US7] Unit tests in `tests/unit/test_default_isolation_config.py`: `IsolationMixin` reports the
      configured default; `DBAPIExecutor._reset_connection_sync` resets to it; the pool applies it to a new connection
      (statement list returned, no IRIS).
- [ ] T071 [US7] Suite checks in new `tests/e2e/isolation/test_default_isolation.py`: default run — a new session
      reports `read committed` and does not read a held row's uncommitted value (times out `40001`, or reads the
      committed value on PostgreSQL); marker `default_isolation` run — reports and runs at `read uncommitted`; the
      2.0.1 check `h3/reused_connection_runs_at_the_default_level` passes on both runs. Startup with
      `PGWIRE_DEFAULT_ISOLATION=serializable` exits non-zero with the accepted values in its message (subprocess).
- [ ] T072 [US7] Implement: pass `BackendConfig.default_isolation` into `IsolationMixin` and
      `_reset_connection_sync` (`src/iris_pgwire/_isolation.py`, `src/iris_pgwire/dbapi_executor.py`), with
      `sql_translator/isolation.py`'s `DEFAULT_ISOLATION_LEVEL` as the fallback; apply it on connection creation in
      `src/iris_pgwire/dbapi_connection_pool.py`.
- [ ] T073 [US7] Re-run the Hermitage section; the table's levels are explicit so no pin should change. Any that does
      is investigated, not re-pinned.
- [ ] T074 [US7] Add US5–US7 rows to `docs/POSTGRES_APP_COMPATIBILITY.md`; update `KNOWN_LIMITATIONS.md`'s isolation
      section for the new default.

**Checkpoint (gate)**: `make isolation`, `make isolation-permissive`, `make isolation-read-uncommitted` pass.
**Slice 3 done.**

---

## Phase 12: Release prep for 2.1.0

- [ ] T075 Changelog: `CHANGELOG.md` `[2.1.0]` with a "Behaviour changes" section (FR-030): the abort rule, READ
      COMMITTED default and `PGWIRE_DEFAULT_ISOLATION`, the refusals and `PGWIRE_TXN_COMPAT=permissive`, cancel,
      SQLSTATE changes (`42601`→`0A000` for locking clauses, `55P03` for client-set lock timeouts, `54000` at the
      savepoint limit).
- [ ] T076 SC-008: run the existing benchmark before (2.0.1) and after on the lab; record per-statement overhead in
      research.md R11 and in the changelog entry; fail the release if over 5 ms or measurably slower for sessions using
      none of the features.
- [ ] T077 Regenerate the Hermitage table (`make isolation-table`) into section 5 of
      `docs/investigations/mvcc-apps-on-iris-pgwire.md`; mark every gotcha row spec 052 fixed with "fixed in 2.1.0".
- [ ] T078 Bump `__version__` in `src/iris_pgwire/__init__.py` and `<Version>` in `ipm/module.xml` to 2.1.0; follow
      `docs/RELEASE_CHECKLIST.md` up to, not including, push/tag/publish (Thomas's word required).
- [ ] T079 Update `docs/plans/2026-11-14-work-tracks.md`: track 4 done, what moved to "later" (E6/E7, advisory locks,
      true cancel, CI).

---

## Dependencies & Execution Order

- Phase 1 → Phase 2 → everything else.
- **Slice 1**: US1 (Phase 3) before US2 (Phase 4): US2's `3B001` and `54000` abort the transaction through US1's
  status machine, and T029 changes US1's transitions.
- **US8** (Phase 5) starts with slice 1 and is extended by every later slice (T035).
- **Slice 2**: US3 (Phase 6) and US4 (Phase 7) are independent of each other once T043 (`compat_mode.py`) exists; do
  T043 first if they run in parallel.
- **Spikes** (Phase 8) before US5 and US6; US7 does not depend on them.
- **Slice 3**: US5, US6, US7 independent; US6 reuses US2's state reset.
- Release prep last.

Only one PGWire server may run at a time on the CE lab, so suite runs never overlap, whatever runs in parallel
otherwise.

## Parallel opportunities

- T004 and T005 (different files).
- Unit-test tasks at the start of each story phase are `[P]` with each other across stories once Phase 2 is done:
  T008, T020, T036, T047, T061, T066, T070.
- T031 and T032.
- Within slice 2: Phase 6 and Phase 7 implementation, after T043.

```text
# Example: start slice 2 in two worktrees after T043
worker A: T036 → T037 → T038 → T039 → T041 → T042 → T044 …
worker B: T047 → T048 → T049 → T051 → T052 → T053 …
# then one person runs make isolation and make isolation-permissive, sequentially
```

## Implementation Strategy

1. **MVP = slice 1 (US1 + US2) plus US8's gate.** It removes the two silent-data-loss paths every PostgreSQL app hits
   (commit after error, nested blocks), and the 254-savepoint loss. It could ship alone as 2.1.0-beta if Thomas wants
   it earlier.
2. Slice 2 (US3, US4) adds the refusals and permissive mode.
3. Spikes, then slice 3 (US5–US7), then the 2.1.0 release prep.
4. Every slice ends at a gate: both suites green, pins updated with reasons, compatibility page extended.
