# Implementation Plan: PostgreSQL Transaction Semantics on IRIS

**Branch**: `052-postgres-transaction-semantics` | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/052-postgres-transaction-semantics/spec.md`
**Base**: `hotfix/2.0.1` at `0451f40` (2.0.1 ships from `main` with the ADBC work, Thomas 2026-11-14)

## Summary

Make PGWire's DBAPI backend give PostgreSQL's transaction answers, or refuse loudly. The protocol layer gets the abort
rule (`25P02`, `COMMIT` becomes `ROLLBACK`, ReadyForQuery `E`, discard-until-Sync), which it can do for both backends
because the status byte already exists and is simply never set to `E`. The executor layer gets a savepoint stack that
maps client names to internal IRIS savepoints, re-establishes after `ROLLBACK TO`, answers `RELEASE` itself, and refuses
the 255th savepoint before IRIS's -400 loses the transaction (measured, research R4). Later slices add the
`FOR UPDATE` touch-update emulation, the ON CONFLICT classifier, `lock_timeout`, a loud cancel, the READ COMMITTED
default and two server settings. The isolation suite is the gate throughout.

**First slice: US1 + US2** (both P1), then US8's gate and docs alongside every slice, then US3/US4 (P2), then
US5/US6/US7 (P3).

## Technical Context

**Language/Version**: Python 3.11+ (CPython for the DBAPI backend; `irispython` for embedded)
**Primary Dependencies**: intersystems-irispython 5.3.2 (`import iris`), structlog, pydantic (BackendConfig); psycopg 3
in tests
**Storage**: IRIS 2026.2 (no schema changes; all new state is per session, in memory)
**Testing**: pytest. Unit tests for the pure pieces (status machine, savepoint stack, clause classifiers) in
`tests/unit/`; behaviour in `tests/e2e/isolation/` against PGWire and PostgreSQL 16 (`make isolation`)
**Target Platform**: the PGWire server beside IRIS (DBAPI); the embedded backend gets the protocol-level and shared
pieces for free but is not measured
**Project Type**: single project (`src/iris_pgwire`, `tests/`)
**Performance Goals**: translation and bookkeeping within the constitution's 5 ms per statement; no measurable change
for sessions that use none of the features (SC-008)
**Constraints**: one PGWire server at a time on the CE lab; IRIS allows 254 savepoints per transaction; IRIS has no
`RELEASE`, no aborted-transaction state, no lock for `FOR UPDATE`
**Scale/Scope**: 8 user stories, 31 functional requirements; about 6 source modules touched, 2 new

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

Evaluated against `.specify/memory/constitution.md` v1.0.0.

| #   | Principle              | Gate                                                                                                                         | Status                                                                                                                                                                                                                                                        |
| --- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| I   | Protocol Fidelity      | No client-side workaround is required; unsupported constructs return a protocol error rather than a degraded or wrong result | **PASS**: this spec is principle I applied to transactions. Every inexact shape is refused with a SQLSTATE. Permissive mode is an operator opt-in, logged per shape, and never covers the abort rule.                                                         |
| II  | Test-First Development | Tests run against real IRIS and real PostgreSQL clients; no mocks, no fakes, no skipped tests to reach green                 | **PASS**: every acceptance scenario is a suite check run with psycopg against real IRIS and PostgreSQL 16. Unit tests cover pure state machines and parsers only, which need no IRIS and stand in for nothing.                                                |
| III | Phased Implementation  | Phases have demonstrable exit criteria; any spike that would change the design has actually been run                         | **PASS with two spikes scheduled**: the savepoint design rested on a spike and it was run (research R4). Cancel (R9: closing a blocked connection from another thread) and the scope of `SET OPTION LOCK_TIMEOUT` (R8) are spike tasks that gate US6 and US5. |
| IV  | IRIS Integration       | Works on both embedded Python and DBAPI backends; backend choice stays configuration                                         | **JUSTIFIED** (Complexity Tracking): measured on DBAPI only. The abort rule and the savepoint stack are backend-independent code; the embedded backend shares one IRIS process across sessions, so it stays documented single-client.                         |
| V   | Production Readiness   | Query-path latency measured against the 5 ms budget; monitoring and tracing present                                          | **PASS, measured in tasks**: R11 lists every addition's cost; a task times the translator before and after on the benchmark corpus. New refusals and permissive warnings log through structlog.                                                               |
| VI  | Vector Performance     | HNSW where applicable; L2 (`<->`) rejected, never emulated                                                                   | **N/A**: no vector paths change.                                                                                                                                                                                                                              |

Technical Constraints: `import iris` throughout; every reported suite result comes from `make isolation`, which
starts a fresh server from this checkout (no container to restart); no schema mapping changes.

**Post-design re-check (after Phase 1)**: unchanged. The design adds no client-visible deviation outside the refusals
the spec lists, and the one new limit found during design (254 savepoints) became a loud refusal (spec FR-008a)
rather than a silent loss.

## Project Structure

### Documentation (this feature)

```text
specs/052-postgres-transaction-semantics/
├── spec.md               # the specification (FR-008a added during planning)
├── plan.md               # this file
├── research.md           # Phase 0: decisions R1–R11 with the measurements behind them
├── data-model.md         # Phase 1: status machine, savepoint stack, settings
├── quickstart.md         # Phase 1: the gate and a by-hand check
├── contracts/
│   └── wire-behaviour.md # Phase 1: what a client receives, per story
├── checklists/
│   └── requirements.md
└── tasks.md              # Phase 2 (/speckit.tasks)
```

### Source Code (repository root)

```text
src/iris_pgwire/
├── protocol.py                    # US1: status E, 25P02 gate, COMMIT→ROLLBACK, discard-until-Sync (R1–R3);
│                                  # US6: cancel handler targets the session (R9)
├── server.py                      # US6: find_connection_for_cancellation already exists
├── savepoints.py                  # NEW, US2: pure savepoint stack + statement parsing (R4)
├── _savepoint_mixin.py            # NEW, US2: executor wiring, shared by both executors (R4)
├── _isolation.py                  # US2: savepoint_depth read from the stack; US5: lock_timeout SET/SHOW (R8)
├── dbapi_executor.py              # US2 wiring; US3/US4 call sites; US6 cancel; 2.0.1 reset extended (R8, R10)
├── dbapi_connection_pool.py       # US7: default level applied to new connections (R10)
├── models/backend_config.py       # US7 + strict/permissive: two settings, validated at startup (R10)
└── sql_translator/
    ├── isolation.py               # US7: DEFAULT_ISOLATION_LEVEL becomes the config fallback
    ├── locking_clauses.py         # NEW, US3: FOR UPDATE recogniser and shape classifier (R6)
    ├── on_conflict.py             # NEW, US4: exact-form classifier (R7)
    ├── returning_plan.py          # US4: parse result reused by the classifier
    └── sqlstate.py                # 25P02, 54000, 55P03, 57014 entries; lock-timeout context (R8)

tests/
├── unit/test_transaction_status.py      # US1 status machine
├── unit/test_savepoint_stack.py         # US2
├── unit/test_locking_clauses.py         # US3
├── unit/test_on_conflict_classifier.py  # US4
└── e2e/isolation/
    ├── test_failed_transaction.py       # US1 (exists): add both protocols, pipelines, ROLLBACK TO recovery
    ├── test_savepoints.py               # US2 (exists): RELEASE, psycopg/SQLAlchemy/Django spellings, the limit
    ├── test_locking.py, test_on_conflict.py, test_cancel.py, test_unsupported_clauses.py  # US3, US4, US6
    ├── test_timeouts.py, test_default_isolation.py   # NEW, US5, US7
    └── known_differences.py             # pins removed or updated per story
```

**Structure Decision**: single project. Protocol semantics (US1) stay in `protocol.py`; everything IRIS-specific
(savepoint mapping, touch-update, `INSERT OR UPDATE`, `LOCK_TIMEOUT`) stays behind the executor and translator, per
constitution IV. The savepoint stack and the classifiers are pure modules so their rules are unit-tested without IRIS.

## Phases and exit criteria

Each phase ends with `make isolation` passing on a fresh server and the unit suite green in its own process.

1. **Slice 1, US1 + US2 (P1)**. Tests first: unit tests for the status machine and the savepoint stack; suite checks
   for every US1/US2 acceptance scenario, both protocols, three client spellings, a pipeline with an error, and the
   255th savepoint. Then R1–R4. **Exit**: `failed_transaction/*` and `savepoints/*` give PostgreSQL's answer; their
   pins in `known_differences.py` are gone; SC-002 and SC-004 measured.
2. **US8 alongside**: `docs/RELEASE_CHECKLIST.md` gets the `make isolation` step; `docs/POSTGRES_APP_COMPATIBILITY.md`
   starts with slice 1's rows and grows per slice. **Exit**: page linked from `KNOWN_LIMITATIONS.md`, each claim
   naming its check.
3. **Slice 2, US3 + US4 (P2)**, plus the `PGWIRE_TXN_COMPAT` setting they need. **Exit**: SC-003 and SC-005; strict
   refusals and permissive warnings both checked.
4. **Spikes for slice 3**: R8 (`SET OPTION LOCK_TIMEOUT` scope on a pooled connection) and R9 (closing a blocked
   connection from another thread). **Exit**: written results in `research.md`; the US5/US6 design confirmed or changed
   before code.
5. **Slice 3, US5 + US6 + US7 (P3)**. **Exit**: SC-006, SC-007; the default-isolation checks on a fresh server.
6. **Release prep for 2.1.0**: changelog "behaviour changes" (FR-030), the Hermitage table regenerated with READ
   COMMITTED as the default, SC-008's measurement recorded.

## Complexity Tracking

| Violation                                        | Why Needed                                                                                                                                                        | Simpler Alternative Rejected Because                                                                                                                                                              |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Principle IV: measured on the DBAPI backend only | The embedded backend serves every session from threads of one IRIS process, and IRIS transactions belong to the process, so two-session checks cannot pass there. | Measuring embedded would test a configuration that is documented as single-client (spec 051 T088 adds its guard). The shared code still runs there; only the multi-session claims are DBAPI-only. |
