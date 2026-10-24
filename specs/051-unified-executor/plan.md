# Implementation Plan: One Executor, Two Connection Adapters

**Feature**: `051-unified-executor`
**Spec**: [spec.md](spec.md)
**Created**: 2026-09-20
**Status**: Phase 0 closed — [research.md](research.md). Five of six questions answered by their own
method; **R6 was not executed by its method** and is deferred to T009 with a named substitute (the
call-site divergence table in `research.md` §R4 supplies the `backend_sensitive` population instead of
a two-adapter suite diff). Constitution Principle III forbids declaring a phase complete on partial
evidence, so this phase is _closed with a recorded gap_, not complete.

---

## Technical Context

**Language**: Python 3.11, running under both `irispython` (embedded) and CPython (DBAPI).
**Existing stack**: `src/iris_pgwire/` — `protocol.py` (wire), `backend_selector.py` (selection),
`iris_executor.py` + `dbapi_executor.py` (the fork this feature removes), `sql_translator/` (51
files, 18,065 lines), `catalog/`, `_isolation.py`, `copy_handler.py`, `bulk_executor.py`,
`integratedml.py`.
**Verification substrate**: `iris-pgwire-db` (IRIS 2026.1 CE, port 2972, **7 concurrent connections
measured**, `DOCKER_CONTEXT=orbstack`) plus a pgvector-enabled PostgreSQL 16 container as the FR-016
reference — measured as `iris-pgwire-pgref`, PostgreSQL 16.14. No mocks (Constitution Principle II).
**New runtime dependencies**: none (FR-028, ADR-0002).

### What already works and must not be disturbed

The 12 rewrite functions in `sql_translator/` are imported identically by both executors and are
already adapter-independent (12 is the module inventory; R4 measured **six** of them applied by the
duplicated inline block and **seven** distinct steps inside `_prepare_sql`). `sql_translator/column_types.py` already serves both and is row-count
independent by construction. `sqlstate.py` already matches both adapters' error wordings. These are
the parts of the existing design that were done right, and the unified core is assembled largely
_from_ them — the feature is mostly about what calls them and from where.

### What is measured and load-bearing

| Fact                                         | Measurement                                                           |
| -------------------------------------------- | --------------------------------------------------------------------- |
| Backend selection is a code fork             | 2 classes, 5,968 lines, one selector                                  |
| One-sided drift                              | last 300 commits touching either: 15 both, 44 IRIS-only, 3 DBAPI-only |
| `optimize_vector_query` call sites in `src/` | exactly 1 — `iris_executor.py:885`                                    |
| Preparation implementations                  | 3 (embedded inline, `_prepare_sql`, DBAPI inline)                     |
| Materialisation implementations              | 3 (`:2366`, `:2959`, `dbapi_executor.py:605`)                         |
| `Executor` Protocol enforcement              | 61 lines, 0 `isinstance`, 0 `abstractmethod` in `src/`                |
| Differential tests today                     | 0                                                                     |
| Wire test files per run                      | 88, one adapter (`conftest.py:691-692`, session-scoped)               |
| Entry-point re-entries                       | 26 call sites across 9 modules                                        |
| Runtime method rebinds                       | 1 (`integratedml.py:372`)                                             |
| Private reach-throughs from outside          | 6 (`bulk_executor.py:358`; `catalog_functions.py` ×5)                 |
| Pool default vs CE licence units             | 10 (`server.py:76`, `:349`) vs **7 measured** (R5)                    |
| Unified preparation cost                     | 0.055 ms worst case = **1.1%** of the 5 ms budget (R4)                |
| Double `SQLRefiner.refine`                   | 0.3047 → 0.6095 ms on a 30-column select = **12.2%** of budget (R4)   |
| Adapters behind the two connection factories | **two**, 29/29 measurements identical (R1)                            |
| Per-column types reachable on embedded       | **yes**, `%SQL.Statement._Metadata`, codes match DBAPI (R2)           |
| Wire tests reaching their first assertion    | 45 of 151; 106 error in setup from a dependency defect (R6)           |

---

## Constitution Check

| Principle                           | Status                      | Note                                                                                                                                                                                                             |
| ----------------------------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **I. Protocol Fidelity**            | ✅ strengthened             | FR-012 makes refusal-over-degradation structural rather than per-case. Empty-string/NULL (FR-017) and type-OID correctness (FR-009) are fidelity fixes.                                                          |
| **II. Test-First (NON-NEGOTIABLE)** | ✅ literally satisfied      | US1 _is_ the test infrastructure, built before any code moves, against behaviour that must not change. Every later story is gated on it.                                                                         |
| **III. Phased Implementation**      | ✅                          | Six stories, each independently testable, each gated by the corpus. US6 is the only irreversible one and it is last.                                                                                             |
| **IV. IRIS Integration**            | ✅ the point of the feature | _"Backend selection MUST be configuration, never a code fork"_ is currently violated. FR-001…FR-005 make it true. ADR-0001 keeps both adapters peers.                                                            |
| **V. Production Readiness**         | ✅ measured                 | R4 costs the unified path at **1.1% of the 5 ms budget**, so FR-027's gate is met before design freeze. R5 measured the licence ceiling at **7** against a pool default of 10, making FR-013 a confirmed defect. |
| **VI. Vector Performance**          | ✅                          | L2 `<->` refusal becomes adapter-independent (US2 scenario 2); today it is only refused on one path. HNSW behaviour unchanged.                                                                                   |

No principle requires dilution, and no gate is outstanding. V was a measurement obligation rather than
a waiver, and Phase 0 discharged it: the number is 1.1% of budget.

---

## Phase 0: Research — five of six answered

All six questions are resolved in [research.md](research.md), each with the command that produced it.
Summary, and what each one changed:

| #      | Answer                                                                                                                                                                  | Changed the design?                                                                                                                                                                      |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R1** | **Two** adapters. 29/29 measurements identical between `iris.connect` and `iris.dbapi.connect`                                                                          | Yes — no third capability column; `_execute_external_async` is deleted, not ported. And DBAPI is **unreachable under `irispython`**, which FR-012 must refuse                            |
| **R2** | Embedded **does** report per-column types, via `%SQL.Statement._Prepare` → `._Metadata` → `.columns.GetAt(i).ODBCType`, with codes identical to DBAPI's `description`   | Yes — reverses a recorded negative. FR-009 applies to both adapters; FR-010's fallback narrows to the `iris.sql.exec` route                                                              |
| **R3** | PostgreSQL 16.14 captured as `iris-pgwire-pgref`. Six IRIS-dialect statements have **no** reference answer                                                              | Yes — the ledger needs a third disposition; T002 needs a pgvector image                                                                                                                  |
| **R4** | Unified preparation costs **1.1% of the 5 ms budget** at worst. The double `SQLRefiner.refine` costs **12.2%**                                                          | No objection to unification; one new task for the double refine                                                                                                                          |
| **R5** | DBAPI has per-session transaction **ownership** but not isolation; dirty reads on both. **Licence ceiling 7** against a pool default of 10                              | Yes — two new capability fields; FR-013 confirmed as a live defect                                                                                                                       |
| **R6** | **Not executed.** Its method could not run: 106/151 wire tests error in session setup from an `iris-devtester` fixture-loader defect. This is a blockage, not an answer | The blockage itself confirms the Q7/Q10 design — corpus below the wire, per-adapter diff nightly and container-only, marker set seeded from static analysis. But the question stays open |

R6 is the one open item, and it is open for a reason outside this repository. The consequence is
bounded: the `backend_sensitive` population is derived from the call-site divergence table in
research.md R4 rather than from a diff, and three new tasks capture the blockers.

### The questions as originally posed

- **R1. How many adapters are there — two or three?** `IRISExecutor` contains both
  `_execute_embedded_async` (`:2663`) and `_execute_external_async` (`:3278`), the latter using the
  external `irispython` driver. 045 asked whether that path and `DBAPIExecutor` are "the same path
  wearing two names" and never answered. **Method**: run the corpus scaffold against all three paths
  and compare raw results. If external and DBAPI agree on every row, they are one adapter with two
  connection strategies, and the adapter count is two. If they diverge, it is three and the
  capability set needs a third column.
- **R2. Is per-column metadata reachable on the embedded adapter at all?** Measured: the
  `iris.sql.exec` result object has no `_meta` on 2026.2 and every type code is `None`. 045 left
  `%SQL.Statement.%GetMetadata` unverified. **Method**: `docker exec` + `irispython`, execute a
  statement with a boolean, an integer and a varchar column, and attempt metadata retrieval through
  `%SQL.Statement` directly. This decides whether FR-010's fallback is the common case on embedded or
  the rare one.
- **R3. What does PostgreSQL actually answer for each corpus statement?** FR-016 makes it the
  reference; the reference has to be captured before it can arbitrate. **Method**: stand up
  PostgreSQL 15 (and 16, to catch version drift), run the corpus, record OIDs, `RowDescription`
  shapes, command tags and row counts as fixtures. Statements PostgreSQL cannot run at all are the
  set where incumbent embedded behaviour becomes the reference, and that set must be enumerated, not
  discovered later.
- **R4. What does preparation cost today, per adapter?** FR-027 needs a before number.
  **Method**: extend `tests/unit/test_translation_gate_budget.py`'s approach to time the full
  sequence on each path. Also settles whether running `SQLRefiner.refine` once instead of twice
  (`normalizer.py:258` + `pipeline.py:61`) is a measurable saving or a rounding error.
- **R5. What is the embedded adapter's real concurrency limit?** `KNOWN_LIMITATIONS.md:366-391`
  records a two-thread transaction visibility leak. FR-011 turns that into a declared number.
  **Method**: re-run the recorded reproducer, then extend it — two sessions, one transaction, with
  and without an explicit `BEGIN` — and derive `max_concurrent_sessions` and
  `isolation_levels_in_force` from what is observed, not from what is documented.
- **R6. Which of the 88 wire test files are genuinely adapter-sensitive?** FR-003 and the
  `backend_sensitive` marker need a population. **Method**: run the wire suite under each adapter
  separately and diff the results. Files that pass on one and fail on the other are sensitive by
  demonstration. Files that pass on both are the candidate single-run set — but the ones that pass
  for _different reasons_ will not show up this way, which is a known limit of the method and goes in
  the ledger as a coverage caveat.

**Output**: [research.md](research.md) — written, one section per question, each ending in a decision
and the command that produced it.

---

## Phase 1: Design

**No `data-model.md`, `contracts/` or `quickstart.md`, deliberately.** This feature adds no entity and
no external surface: it consolidates two implementations behind one seam that already has callers. The
three seam types below _are_ the data model, and the contract they satisfy is the PostgreSQL v3 wire
protocol, which is specified elsewhere and not ours to restate. A `contracts/` directory here would
hold a copy of something authoritative, and copies drift. The absence is a decision; `AVAILABLE_DOCS`
listing only `research.md` and `tasks.md` is the expected shape for a refactor.

### The seam types

Three types carry the whole design. They are deliberately small; depth lives behind them.

**`PreparedStatement`** — the outcome of preparation, and the type that kills the re-entrancy:

- either _answered locally_ (rows and column metadata the core produced itself — a catalog view, a
  canned reply, a refusal), or _sent to the adapter_ (IRIS-executable SQL plus ordered parameters).
- carries the column metadata the statement text settles, so materialisation never has to re-derive
  it, and Describe and Execute cannot disagree (FR-007).
- carries the original frontend statement for error messages and logging. _(Today
  `dbapi_executor.py:219` assigns `original_sql = sql` as a local that shadows the caller's kwarg and
  is then discarded.)_

**`RawResult`** — what an adapter returns, in the driver's terms only:

- rows; driver-reported per-column types **or `None` meaning the driver reported nothing**;
  affected-row count; unparsed error.
- `None` is a declared case, not a failure. This is the reason a PEP-249 cursor was rejected as the
  seam: the embedded adapter would have had to manufacture a `description` it does not have, which is
  the exact shape of the T011h defect.
- R2 narrows when `None` actually occurs: both adapters _can_ report types, so `None` is the
  `iris.sql.exec` route and error paths, not the embedded steady state. The case stays declared —
  the seam should not depend on a preparation route staying chosen.

**`Capabilities`** — declared per adapter, read by the core at startup. R5 and R2 supplied the values
and added three fields that were not in this sketch:

| Field                        | embedded                    | dbapi                                       |
| ---------------------------- | --------------------------- | ------------------------------------------- |
| `per_session_transactions`   | `False`                     | `True`                                      |
| `cross_session_dirty_reads`  | `True`                      | `True`                                      |
| `max_concurrent_sessions`    | `1`                         | `min(pool_size, licence_units)`, 7 measured |
| `isolation_levels_accepted`  | unmeasured, non-blocking    | `{READ UNCOMMITTED, READ COMMITTED}`        |
| `isolation_levels_in_force`  | `frozenset()`               | `frozenset()`                               |
| `reports_column_types`       | `True` via `%SQL.Statement` | `True` via `description`                    |
| `describe_without_execute`   | `True`                      | `False`                                     |
| `available_under_irispython` | `True`                      | `False`                                     |

- Declared as data. The core never asks an adapter what it is; it reads what the adapter says it can
  do.
- `isolation_levels_in_force` is empty on **both** adapters. Naming it separately from
  `..._accepted` is the whole point: acceptance without enforcement is what produced the retracted
  text-stickiness model, and a single "supports isolation" boolean would recreate it.

### Module shape

```text
core (owns the statement lifecycle)
├── preparation      → PreparedStatement          # one sequence, from sql_translator/
├── local answers    → catalog views, refusals     # a preparation outcome, not a callback
├── execution        → adapter.execute(...)        # the only place an adapter is touched
├── materialisation  → rows + column metadata      # 045's scope, one implementation
├── isolation        → no re-entry, no flag
└── errors           → one mode (FR-006)

adapters (driver knowledge and nothing else)
├── embedded   — %SQL.Statement in-process (R2: it reports types; iris.sql.exec does not)
└── dbapi      — pooled DBAPI over 1972
                 (R1: _execute_external_async is this same adapter; US6 deletes it)

callers (outside the core, by design)
└── copy_handler, bulk_executor, integratedml, catalog installers
```

**The deletion test, applied to what this feature removes**: delete `SQLPipeline` and complexity
vanishes — it is 63 lines that both executors construct and neither uses, and four tests mock away
its construction so nothing can observe that. Delete the duplicated 37-line rewrite sequence and
complexity _concentrates_ — which is why it earns a home rather than a deletion.

### Test architecture

- **Differential corpus** (US1) — below the wire, no server. For each statement, for each adapter:
  raw result captured, compared, divergences classified against the ledger. Runs in seconds.
- **Divergence ledger** — a data file, not prose, so the corpus can read it. Each entry: statement
  shape, observed values per adapter, `pin` with measurement or `fix` with owner. FR-015.
- **`backend_sensitive` marker** — tests whose outcome depends on the adapter run against all of
  them. Population from R6. Everything else runs once, as today.
- **Reference fixtures** — PostgreSQL's answers from R3, checked in, so FR-016 arbitration does not
  need a live PostgreSQL on every run.
- **Deleted**: `TestBothExecutorsUseIt`'s `inspect.getsource` assertion, replaced by executed parity
  (FR-003).

### Migration mechanics

Build the core alongside, selectable by a `PGWIRE_BACKEND_TYPE` value (FR-022). The old pair stays as
the oracle: every corpus statement runs through old and new, and _both_ comparisons must hold — new
versus old, and new versus PostgreSQL. Where they conflict, PostgreSQL wins and the old behaviour
becomes a ledger `fix` (FR-016). Rollback is the environment variable, until US6 removes it.

---

## Complexity Tracking

| Deliberate complexity                                           | Why it is accepted                                                                                                                                                                                                                                                                                                                                               | Exit condition                                                                                                                                                                          |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Two implementations coexist during US2-US5                      | The old pair is the only available oracle; a big-bang rewrite has no bisectable failure                                                                                                                                                                                                                                                                          | US6 deletes both and the flag (FR-023)                                                                                                                                                  |
| A ledger of permitted differences                               | Constitution IV allows divergence only with a recorded reason; without a ledger the reason lives in nobody's head                                                                                                                                                                                                                                                | Never — the ledger is permanent, but every entry is reviewable                                                                                                                          |
| Corpus needs a live IRIS, so it cannot be the pre-merge CI gate | There is no mock (Principle II) and introducing one would measure our fiction, not IRIS                                                                                                                                                                                                                                                                          | Local gate plus nightly container job; container-free CI keeps the static checks                                                                                                        |
| ~~Adapter count unknown until R1~~                              | ~~guessing would bake the wrong seam~~                                                                                                                                                                                                                                                                                                                           | **Closed.** R1: two adapters, 29/29 identical                                                                                                                                           |
| `backend_sensitive` population derived, not demonstrated        | R6's diff cannot run: an `iris-devtester` fixture-loader defect errors 106/151 wire tests in setup, upstream of any adapter behaviour                                                                                                                                                                                                                            | T075 reports the defect upstream; the nightly per-adapter job replaces the diff                                                                                                         |
| FR-024 accepts a baseline below Principle II's required 100%    | **Principle II deviation, recorded not diluted.** The 106 errors + 5 skips R6 measured are a fixture-loader defect upstream of any adapter behaviour, present before this feature and not caused by it. Restoring 100% inside 051 would couple a consolidation to an unrelated upstream fix and destroy bisectability — the same argument ADR-0002 point 5 makes | T075-T077 restore the container suites; when they pass, FR-024's baseline is restated as 100% and this row closes. Until then no new failure is permitted, only the existing floor held |

---

## Sequencing and release interaction

**1.8.0 does not wait for this feature.** It ships with a surgical fix for the vector gap — the
missing translation call on the DBAPI path plus the parameter-renumbering defect in
`optimize_vector_query` — because published 1.7.3 has a broken console script (`62d5b85` fixes it)
and the README's own example currently fails on the default backend.

The condition on that fix: it lands **with its assertion written as the first rows of the differential
corpus**, same statement, both adapters, equality asserted by execution. So the surgical fix seeds
US1 instead of adding a 45th one-sided commit, and 051 inherits a test file that already fails the
moment either adapter stops routing through the shared path.

051 then targets **1.9.0**.
