# Implementation Plan: Unified IRIS Driver Layer

**Branch**: `045-unified-iris-driver` | **Date**: 2026-08-17 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/045-unified-iris-driver/spec.md`
**Evidence**: [`spikes/probe_unified_driver-results.md`](spikes/probe_unified_driver-results.md)

## Summary

Collapse the **three** independent result-materialisation paths — `IRISExecutor`'s embedded and
external materialisers and `DBAPIExecutor._fetch_standard_results` — into **one** decision that both
backends call, so a metadata fix lands once and cannot ship broken on the backend nobody tested.

The spike was run before planning and it changed the plan. The candidate enabler,
`iris-embedded-python-wrapper`, is **not adopted**: measured, its embedded DB-API reports
`type_code=None` for every column, so it cannot be the single source of column metadata, and it does
not normalise error text. Meanwhile the row-count dependence that motivated the feature traces to five
lines of ours — `DBAPIExecutor._map_dbapi_type_to_oid` string-matching a numeric ODBC code and
collapsing every type to varchar. **Route A (consolidate in-house) is the plan.** Route B stays behind
the evidence bar in spec §Alternatives, and point 5 of that bar makes Route A a prerequisite anyway.

## Technical Context

**Language/Version**: Python 3.11 (host) / 3.12 (`irispython` in the container)
**Primary Dependencies**: none new. `intersystems-irispython` 5.4.0 stays the only IRIS dependency
**Storage**: N/A — this feature moves no data; it decides what a result set is described as
**Testing**: pytest against real IRIS 2026.2 (Build 221U); feature 044's probes as the regression
oracle; the raw-wire client in `probe_statement_describe.py` as the client-visible oracle
**Target Platform**: both backends — embedded (`irispython`, inside the container) and DBAPI (pool
over 1972, from the host)
**Project Type**: single project
**Performance Goals**: unified metadata path under 25% of the Principle V 5 ms budget per statement
(SC-009), measured; 044's translation gates already consume a measured 12.4%
**Constraints**: no new runtime dependency (FR-015); no behaviour change outside metadata (FR-013);
the two C-1 unit failures must neither grow nor be "fixed" here (FR-011)
**Scale/Scope**: `iris_executor.py` 4,218 lines, `dbapi_executor.py` 1,454 lines,
`backend_selector.py` 287 lines. Three materialisers to reduce to one; the surrounding transaction,
pooling, `COPY` and vector code is not in scope

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.0.0 before Phase 0. Re-evaluate after
Phase 1 design.*

| # | Principle | Gate | Status |
|---|-----------|------|--------|
| I | Protocol Fidelity | No client-side workaround; unsupported constructs error rather than degrade. **This feature fixes a Principle I violation**: a column declared varchar and encoded as a one-byte bool is a plausible wrong answer that a client cannot decode — the exact failure mode Principle I forbids. FR-004 and FR-007 make it explicit; FR-007 forbids guessing a type, because a confident wrong type is worse than a defined fallback. | ✅ PASS — improves compliance |
| II | Test-First | Real IRIS, real clients, no mocks. The spike ran against live IRIS on both backends before this plan existed. **But the suite does not pass 100%**: two `tests/unit/test_generated_columns.py` tests fail and they are not this feature's — measured baseline 5120 passed / 2 failed / 5 skipped. Two further files do not even collect in this environment. See Complexity Tracking C-1 and C-3. | ⚠️ CONDITIONAL — deviations recorded |
| III | Phased Implementation | The spike that would have changed the design **was run, not assumed**, and it did change it: the third-party route is deferred and the in-house cause was located. Two Phase 0 questions remain open and gate the design (below); Phase 1 must not start until they are measured. | ⚠️ CONDITIONAL — Phase 0 not yet closed |
| IV | IRIS Integration | Both backends must reach the one decision (FR-001) and a test must fail if either stops (FR-003). Backend selection stays configuration — `backend_selector.py` is untouched in shape. FR-009 requires any residual divergence to be documented with its measurement. | ✅ PASS — strengthens parity |
| V | Production Readiness | The metadata decision runs on **every** statement that returns rows, so this is a hot-path change. FR-014 and SC-009 require it measured against the 5 ms budget before merge, in the manner of `tests/unit/test_translation_gate_budget.py`. Not yet measured — that is a Phase 1 exit criterion, not an assumption. | ⚠️ CONDITIONAL — measurement pending |
| VI | Vector Performance | Vector columns carry a literal the translator wrote; the unified path must leave them untouched (spec Edge Cases). No metric, index or operator behaviour changes. `<->` stays rejected. | ✅ PASS — unaffected, asserted by regression |

**Technical Constraints check.** Package import stays `import iris` from
`intersystems-irispython` — and FR-016 exists precisely because the evaluated third-party package
would have made `import iris` ambiguous, which is this constraint under a different name.
**Container restart**: every embedded measurement in the spike was taken by `docker cp` into the
container plus `docker exec`, with no source under test living in the container's Python path, so no
stale-code result was reported; once this feature changes `src/`, embedded results MUST come from a
restarted container or they are invalid and must not be reported.
`public` → IRIS schema mapping is not touched.

### Phase 0 questions that gate the design

Both must be measured before Phase 1. Neither is answered by the spike.

1. **Is `%SQL.Statement` metadata reachable on the embedded backend at all?** Measured: the
   `iris.sql.exec` result object is `iris.%SYS.Python.SQLResultSet` and has **no `_meta` attribute**
   on IRIS 2026.2, so `_materialize_embedded_result`'s primary branch is dead here and metadata comes
   from a discovery query or the row values. Whether `%GetMetadata`, `%SQL.Statement` directly, or
   `%ResultSet` exposes per-column types is unknown. **If yes**, FR-006 applies to the embedded
   backend too and the fallback in FR-007 is rarely reached. **If no**, the embedded backend
   permanently depends on the statement text plus a discovery query, and FR-009 requires that
   asymmetry documented rather than hidden.
2. **Are `_materialize_embedded_result` and `_materialize_external_result` two paths or one path
   wearing two names?** They are near-duplicates by inspection — identical `iris_type == 2` handling,
   identical `CURRENT_TIMESTAMP` special case (with one differing in `type_oid in (25, 1043)` versus
   `== 1043`), identical fallback-to-`_discover_metadata`. Inspection is not measurement: the answer
   decides whether the reduction is 3→1 or 3→2→1, and the divergent `CURRENT_TIMESTAMP` condition may
   be a latent defect or may be deliberate. Must be established by running both against the same
   statements, not by reading.

### Complexity Tracking

| # | Deviation | Why it is accepted | Exit |
|---|---|---|---|
| C-1 | Principle II requires the suite to pass with no quarantined failures. Two fail: `tests/unit/test_generated_columns.py::test_generated_column_skip` and `::test_generated_column_multiple_skip`. | Inherited verbatim from `specs/044-catalog-as-views/plan.md` C-1, where it is diagnosed: `IdentifierNormalizer` deliberately preserves lowercase column names in `CREATE TABLE`, and inconsistently, so these two tests assert pre-fix behaviour. Deciding the correct casing changes what every client sees for `CREATE TABLE`. That is a DDL decision with wide blast radius and it is not a metadata decision. | Owned by `docs/identifier-casing-inconsistency.md`. This feature must not make them worse and **must not** "fix" them by changing DDL casing (FR-011). Re-measured 2026-08-17: still exactly these two. |
| C-2 | The existing "both backends call the shared resolver" guard is a **source-string grep**: `tests/unit/test_column_type_resolution.py` asserts `"resolve_column_type_oids" in inspect.getsource(module)`. That is not a behavioural assertion — a call site could be dead, guarded, or shadowed and the test would still pass. | Accepted as the *starting* state, not the end state. It was the cheapest possible guard at the time and it did catch the class of defect it was written for. | FR-003 replaces it with an assertion that both backends **produce the same declared types for the same statement against real IRIS**. The grep may remain as a cheap tripwire but must not be the only guard when this feature closes. |
| C-3 | `tests/unit` does not fully collect in this environment: `tests/unit/protocol/test_protocol_auth_integration.py` errors with `'benchmark' not found in markers configuration option`, and `tests/unit/test_sql_translator_api.py` with `ModuleNotFoundError: No module named 'fastapi'`. The 5120/2/5 baseline is measured with those two files ignored. | These are environment/config gaps, not failing assertions, and they predate this feature. Principle II forbids skipping a test to reach green; it does not require this feature to fix an unregistered pytest marker and a missing optional dependency. Recording it so the baseline number is honest rather than flattering. | Out of scope here. Named so that a future run cannot mistake "5120 passed" for "the whole unit suite passed". Should be raised as its own small fix. |
| C-4 | A refactor of the query path is, by definition, a change with no user-visible feature. Principle III wants demonstrable exit criteria per phase, which is harder for consolidation than for a new surface. | The exit criteria are borrowed from the defects: 044's probes and the raw-wire Describe client are the oracle, and each phase exits on a *measured* property (identical types across backends; identical types across row counts) rather than on "the code looks unified". SC-008 additionally requires the line count to go **down**, so an abstraction layered over three retained copies fails the criterion. | Each phase below states its measurement. No phase exits on inspection. |

**No unjustified violations.** Three conditional principles (II, III, V) are conditional on work this
plan schedules, not on unresolved doubt: II by C-1/C-3, III by the two Phase 0 questions, V by the
FR-014 measurement that is a Phase 1 exit criterion.

## Project Structure

### Documentation (this feature)

```text
specs/045-unified-iris-driver/
├── spec.md
├── plan.md                              # this file
├── research.md                          # Phase 0 output — the two gating questions, measured
├── contracts/
│   └── result-materialization.md         # Phase 1 — the one interface both backends call
├── tasks.md                             # Phase 2, NOT created by /plan
└── spikes/
    ├── probe_unified_driver.py           # the third-party evaluation, runnable
    └── probe_unified_driver-results.md   # its recorded output
```

### Source Code (repository root)

```text
src/iris_pgwire/
├── result_metadata.py            # NEW (working name) — the one decision, FR-001/FR-002
│                                 #   name normalisation, type OID, size, format
│                                 #   sources in FR-005 precedence: SQL text -> driver -> values
├── sql_translator/
│   ├── column_types.py           # existing row-count-independent resolver; becomes the
│   │                             #   "statement text" source rather than a bolt-on override
│   └── sqlstate.py               # unchanged — FR-008 requires its scores hold, not its rewrite
├── iris_executor.py              # _materialize_embedded_result and _materialize_external_result
│                                 #   reduced to fetching rows; metadata delegated
├── dbapi_executor.py             # _fetch_standard_results likewise;
│                                 #   _map_dbapi_type_to_oid FIXED (FR-006) — it is the upstream
│                                 #   cause of the value-based refinement
└── backend_selector.py           # unchanged in shape; both executors keep their contract

tests/
├── unit/
│   ├── test_result_metadata.py            # NEW — the unified decision, directly
│   ├── test_dbapi_type_code_mapping.py    # NEW — ODBC code -> OID, the FR-006 fix
│   └── test_column_type_resolution.py     # existing; its source-grep guard superseded (C-2)
└── integration/
    └── test_backend_metadata_parity.py    # NEW — same statements, both backends, real IRIS:
                                           #   identical declared types (SC-002) and
                                           #   identical across row counts (SC-003)
```

**Structure Decision**: single project, existing layout. One new module beside
`sql_translator/column_types.py` rather than inside either executor — for the same reason 044 put
`column_types.py` there: the defect being fixed *is* that the logic lived in one of two executors. The
new integration test directory is the one that already exists (`tests/integration/`), and it drives
real IRIS the way `test_pg_array_against_iris.py` does.

## Design

### 1. One decision, three sources, defined precedence

`result_metadata.py` answers one question — *given the statement text and whatever the driver reported,
what is each output column?* — and answers it identically for both backends. Sources, in the
FR-005 order:

| Source | Available with zero rows? | What it settles |
|---|---|---|
| Statement text (`column_types.py`) | **yes** | explicit casts, known catalog columns, boolean expressions |
| Driver description | **yes** on the native path (measured: `12`/`-7`/`4`); **no** on the embedded path (measured: `None`) | the declared IRIS/ODBC type |
| Row values | no | last resort only |

The ordering is not a preference, it is the requirement: anything that consults row values above a
source available without rows reintroduces T011h by construction.

### 2. Fix `_map_dbapi_type_to_oid` first

This is the smallest, highest-value change in the feature and it is independently shippable:

```python
# dbapi_executor.py:1241 — today
type_str = str(dbapi_type).upper()
if "INT" in type_str: return 23
...
return 1043
```

Measured against real IRIS, the argument is a numeric ODBC code, and every code tested maps to 1043:
`12 → 1043`, `-7 → 1043`, `4 → 1043`, `-5 → 1043`, `8 → 1043`, `93 → 1043`. A real ODBC-code table
makes the driver's own answer usable and removes the *reason* the value-based refinement was written.
It must handle a non-numeric `type_code` too, because PEP 249 permits a type object there and the
current string matching is presumably why it was written that way — that is a compatibility question
to settle by measurement, not by deletion.

### 3. Rows and metadata separate

Each materialiser today interleaves three jobs: fetch rows, decide metadata, coerce values. Splitting
metadata out leaves the value coercion where it is (it differs legitimately per backend — the external
path casts ints and floats by OID, the embedded path normalises IRIS NULLs) and makes FR-009 checkable:
any *remaining* difference is in value handling, is visible, and either gets documented or gets
unified on evidence.

### 4. Error classification is not touched

`sqlstate.py` stays as it is. FR-008 is a requirement to **re-verify**, not to rewrite: the spike
showed classification surviving even the raw `%Status` blob a third-party embedded facade raises, and
that resilience came from matching wording as well as SQLCODE. The risk in this feature is a value or
exception passing through a different code path and reaching the generic handler again — which is
exactly the defect T027 found (an IRIS error arriving as a Python exception was reported as `08000`).
So the two probes are a gate on every phase, not a final check.

### 5. Empty string versus NULL (FR-010)

Measured: the native driver already returns `''` and `None` correctly. `iris.sql.exec` returns
`'\x00'` for the empty string and `''` for NULL — inverted relative to Python — and
`_normalize_iris_null` handles only the NULL half. Whether that reaches a client wrongly was **not**
verified over the wire, because pgwire's embedded backend only runs inside the container and the
running server was not to be restarted. So the first task is the wire-level measurement, and the fix
is conditional on it. If the wire path is already correct, the finding is recorded as an absorbed
driver quirk and FR-010 closes without a code change.

## Phases

**Phase 0 — Research (gates everything)**. Answer the two questions above by measurement, against
real IRIS, and record them in `research.md`. **Exit**: it is known whether the embedded backend can
report per-column types, and whether the two `IRISExecutor` materialisers are one path or two —
including whether their differing `CURRENT_TIMESTAMP` condition is a defect. Also: the wire-level
empty-string measurement of §5, since it decides whether FR-010 has a code change in it.

**Phase 1 — The narrow fix and the parity harness**. Fix `_map_dbapi_type_to_oid` (FR-006) and build
`tests/integration/test_backend_metadata_parity.py` — the ≥20-shape corpus, run on both backends,
asserting identical declared types (SC-002) and row-count independence (SC-003). The harness comes
*before* the consolidation, because it is the only thing that can prove the consolidation changed
nothing. **Exit**: the corpus passes on both backends with the three materialisers still in place, and
its current divergences are enumerated; plus the FR-014 budget measurement for the metadata path
(Principle V gate closes here).

**Phase 2 — One decision**. Introduce `result_metadata.py`, route all three materialisers through it,
and delete what it replaces. **Exit**: the parity corpus unchanged, `probe_statement_describe.py`
PASS on both backends (SC-004), 044's SQLSTATE probes at 9/9 and 13/13 (SC-005), `tests/unit` at the
C-1 baseline (SC-006), and result-materialisation line count **down** (SC-008).

**Phase 3 — Residual divergence**. Whatever the parity corpus still shows as backend-specific is
either unified or documented with its measurement (FR-009), and FR-010 is closed on the Phase 0
evidence. **Exit**: zero undocumented divergences; the empty-string matrix at 4/4 or a recorded,
measured gap (SC-007).

**Phase 4 — Re-qualify 044**. Re-run every 044 probe and confirm every defect in
`docs/orm-introspection-findings.md` is still fixed (FR-012). **Exit**: all 044 probes at their
recorded scores. This phase exists because 044's verification was performed against the current
materialisers; consolidating them invalidates it as evidence even when it does not break it.

## Risks

| Risk | Mitigation |
|---|---|
| Consolidation changes a declared type nobody was watching, and an ORM breaks weeks later | The Phase 1 parity corpus is built **before** the consolidation and is the only accepted proof that Phase 2 changed nothing. ≥20 shapes, both backends, real IRIS. |
| The embedded backend cannot report per-column types, so "one decision" is one decision with two very different input sets | Phase 0 question 1 settles it by measurement. If it holds, FR-009 forces the asymmetry into the open rather than into an `if backend ==` buried in a materialiser. |
| A metadata pass per column per statement blows the 5 ms budget | FR-014 + SC-009, measured in Phase 1 before the code that would consume it is written. 044's gates already take a measured 12.4%. |
| An IRIS error starts reaching the generic handler again through the new path, and is reported as `08000` | Exactly the T027 defect. Both SQLSTATE probes are a per-phase gate, not a final check. |
| The two C-1 failures get "fixed" opportunistically while touching adjacent code | FR-011 forbids it explicitly; C-1's exit condition lives in another feature. |
| A future maintainer adopts the third-party wrapper without the evidence bar, because the spike shows it working | The bar is written into spec §Alternatives with five measured conditions, and point 5 requires this feature to be complete first so a driver swap is bisectable against a known-good layer. |
| Embedded results reported without restarting the container after a source change | Constitution Technical Constraint. Every embedded measurement in this feature states whether a restart preceded it; results without one are invalid and must be discarded, not caveated. |
| `_map_dbapi_type_to_oid`'s string matching exists for a non-numeric `type_code` on some driver version | Treated as a compatibility question to measure, not a bug to delete: the fix must handle both a numeric ODBC code and a type object. |
