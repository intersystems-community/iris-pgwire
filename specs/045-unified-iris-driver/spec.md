# Feature Specification: Unified IRIS Driver Layer

**Feature Branch**: `045-unified-iris-driver`
**Created**: 2026-08-17
**Status**: Draft — spike complete, awaiting plan review. No open clarifications.

**Running spec-kit commands on this feature**: the scripts resolve the feature from a `NNN-` branch
prefix. If development happens on a branch without that prefix, every invocation needs the override:

```bash
SPECIFY_FEATURE=045-unified-iris-driver bash .specify/scripts/bash/check-prerequisites.sh --json
```

**Input**: There are three independent places that decide what a result set looks like. Collapse them
into one, so a fix lands once and holds on both backends.

**Evidence**: [`spikes/probe_unified_driver-results.md`](spikes/probe_unified_driver-results.md) —
every claim in this document that says "measured" traces to a line of that file, produced against
real IRIS 2026.2. Prior defects: `specs/044-catalog-as-views/tasks.md` T011g, T011h, T027.

---

## Why

`backend_selector.py` builds one of two executors, and each carries its own result-materialisation
code. Counting the paths that independently decide **column metadata**:

1. `IRISExecutor._materialize_embedded_result` — `iris_executor.py:2366`, embedded `iris.sql.exec`
2. `IRISExecutor._materialize_external_result` — `iris_executor.py:2959`, `iris.connect` cursor
3. `DBAPIExecutor._fetch_standard_results` — `dbapi_executor.py:605`, DBAPI pool cursor

Three copies of the same decision, in two classes, ~5,700 lines between them. That duplication has
already produced two recorded defects, and both were found by a real client failing rather than by
review:

- **T011g / T011h.** A catalog boolean went out as the wrong PostgreSQL type. The fix landed in
  `IRISExecutor` only, so the `dbapi` backend kept declaring varchar. Worse, `DBAPIExecutor` inferred
  types from the **first row's value**, so a statement Describe — which runs with dummy parameters
  that match nothing — declared different types than Execute did, and a client that read the Describe
  could not decode the DataRow it was then sent. `prisma db pull` died on
  `Getting is_partition from ResultRow { types: [Text, …] } as bool failed`.
  Reproducer: `specs/044-catalog-as-views/spikes/probe_statement_describe.py`.
- **T027.** The two backends word IRIS errors completely differently. DBAPI delivers
  `[SQLCODE: <-30>:<Table or view not found>]`; embedded raises `Table 'SQLUSER.X' not found` with
  **no SQLCODE at all**, so a SQLCODE-only classifier scored 2/5 on the default backend.
  `sql_translator/sqlstate.py` now matches both wordings for every family.

Both fixes work. Both had to be written *twice*, or written outside the executors precisely because
they would otherwise be written twice — the header comment in
`sql_translator/column_types.py` says so explicitly. **The prize in this feature is collapsing three
materialisation paths into one**, so the next fix of this kind lands once.

### What the spike changes about the diagnosis

Guillaume Rongier's `iris-embedded-python-wrapper` (PyPI, MIT) was the candidate enabler: it claims a
DB-API facade over both embedded and native backends and normalisation of "SQL NULL handling, empty
strings". It was measured, not assumed. Three results reshape this spec:

1. **The T011h property already holds on the native driver, and it always did.** Measured:
   `cursor.description` is byte-for-byte identical for 10 rows and 0 rows, and reports *distinct*
   ODBC codes — `12` varchar, `-7` bit, `4` integer. The facade contributes nothing here; the bare
   official driver gives the same answer.
2. **We discard that metadata ourselves, in five lines.** `DBAPIExecutor._map_dbapi_type_to_oid`
   (`dbapi_executor.py:1241`) does `str(dbapi_type).upper()` on a **numeric** ODBC code and searches
   it for the words `INT`/`CHAR`/`DATE`/`TIME`. Measured: `12 → 1043`, `-7 → 1043`, `4 → 1043`,
   and so on for every code tried. The value-based refinement that made the declared type depend on
   the row count existed to repair metadata that had arrived correct and been thrown away one function
   earlier.
3. **The facade cannot be the single source of column metadata.** Measured on the embedded backend:
   every `cursor.description` type code is `None`. Stable across row counts, but vacuously so.

So the third-party package is a **possible enabler, not the fix**. The fix is ours.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — A metadata fix lands once and holds on both backends (Priority: P1)

A maintainer corrects how a column's PostgreSQL type is decided. They change one function. Both
backends change together, and a test fails if either stops using it.

**Why this priority**: This is the feature. T011g is the counter-example — a correct fix that shipped
broken on the default backend because a second copy existed and nobody knew.

**Independent Test**: Change the resolved type for one construct; assert both backends report the new
type for the same statement, against real IRIS, without touching either executor.

**Acceptance Scenarios**:

1. **Given** a statement whose column type is settled by its own text, **When** it is executed on the
   embedded backend and on the DBAPI backend, **Then** the declared type is identical.
2. **Given** the metadata decision is changed in one place, **When** the suite runs, **Then** no
   second implementation of that decision remains for a test to find.
3. **Given** a backend-specific quirk that genuinely cannot be unified, **When** it is handled,
   **Then** the difference is recorded with the measurement that justifies it (FR-009).

---

### User Story 2 — A client can decode what the server told it to expect (Priority: P1)

A client sends Parse → Describe(statement) → Bind → Execute. The types in the RowDescription match the
encoding of the DataRow, whatever the query happens to return.

**Why this priority**: Equal to US1 because it is the user-visible failure. It is separately testable
and it is the property that broke `prisma db pull`.

**Independent Test**: `specs/044-catalog-as-views/spikes/probe_statement_describe.py` unchanged, on
both backends: statement Describe declarations versus DataRow widths.

**Acceptance Scenarios**:

1. **Given** a query whose parameters match nothing, **When** its statement Describe is read,
   **Then** the declared types equal those declared when the same query matches many rows.
2. **Given** a binary-format result request, **When** a column is declared `bool`, **Then** the
   DataRow carries exactly one byte for it.
3. **Given** the query has no rows and the SQL settles nothing, **When** the Describe is answered,
   **Then** the type reported is the one the *driver* reported — never a guess from an absent value.

---

### User Story 3 — An error tells the client whose fault it is, on either backend (Priority: P2)

A failing statement produces the same SQLSTATE class regardless of which backend served it.

**Why this priority**: T027 already delivered this; it must not regress when the driver layer moves.
Measured: classification survives even the raw `%Status` blob the third-party embedded facade raises
— but only because the classifier matches wording, and that property has to be protected
deliberately.

**Independent Test**: `specs/044-catalog-as-views/spikes/verify_sqlstate_e2e.py` over the wire and
`spikes/probe_embedded_error_wording.py` on the embedded backend; both must keep their current scores.

**Acceptance Scenarios**:

1. **Given** a missing table, a missing column and an internal failure, **When** each is run on each
   backend, **Then** each yields `42P01`, `42703`, `XX000` respectively.
2. **Given** a driver whose message text changes shape, **When** the classifier runs, **Then** it
   still classifies, or a test fails naming the wording that stopped matching.

---

### User Story 4 — An empty string is an empty string (Priority: P3)

A client writes `''` and reads back `''`, not NULL and not a one-byte NUL.

**Why this priority**: Real, measured, and narrower than the others. Measured on the embedded API:
`iris.sql.exec` returns `'\x00'` for a non-NULL empty string and `''` for SQL NULL — the *inverse* of
Python's convention. `IRISExecutor._normalize_iris_null` maps `''` to `None` (right for NULL) and
leaves `'\x00'` alone, so a genuine empty string appears to a client as one NUL character. This was
measured at the driver level and **not** verified end-to-end over the wire, so it is a
suspicion-with-evidence, not yet a confirmed wire defect (see FR-010).

**Independent Test**: write `''` and NULL, as literals and as bound parameters, read them back on both
backends, and compare against real PostgreSQL 15 for the same four cases.

**Acceptance Scenarios**:

1. **Given** a non-NULL empty string in a column, **When** it is read on either backend, **Then** the
   client receives a zero-length value.
2. **Given** SQL NULL in a column, **When** it is read on either backend, **Then** the client receives
   NULL.
3. **Given** the two cases, **When** they are read, **Then** they are distinguishable — the failure to
   avoid is the two collapsing into one value.

---

### Edge Cases

- **A query returns zero rows** — the declared types must be identical to the non-empty case. This is
  the T011h shape and it must be a test, not a hope.
- **`SELECT *` expansion**, where the select-list item count does not match the column count: an
  override must be declined rather than applied to the wrong column (the existing guard).
- **A column the SQL settles nothing about** and the driver reports nothing about either — the
  embedded backend reports no type codes at all (measured). What is declared then must be defined, not
  incidental.
- **A statement executed for its side effect** (DDL, `INSERT` without `RETURNING`) — no
  RowDescription; the unified path must not invent one.
- **`RETURNING` emulation**, which builds rows without a driver cursor at all.
- **Vector columns**, where the value is a literal the translator wrote — must be untouched.
- **A parameter bound as `None` on the embedded backend**, where the raw API is already worked around
  by inlining literals (`iris_executor.py:1825-1848`); the unified path must keep that behaviour or
  replace it with something measured.
- **An IRIS version that reports metadata differently.** Measured on 2026.2:
  `iris.sql.exec`'s result object has **no `_meta` attribute**, so the branch in
  `_materialize_embedded_result` that reads it is dead here. Other versions were not tested.

---

## Requirements *(mandatory)*

### Functional Requirements

**One place decides**

- **FR-001**: Exactly **one** code path MUST decide the column metadata (name, PostgreSQL type OID,
  size, format) of a result set. Both backends MUST reach it. A second implementation of that decision
  is a defect, not a variant.
- **FR-002**: The unified path MUST be reachable without instantiating an executor, so it can be
  tested directly and so neither executor can quietly diverge from it. *(This is already true of
  `sql_translator/column_types.py`; FR-001 extends the property from "the part 044 had to extract" to
  the whole decision.)*
- **FR-003**: A test MUST fail if either backend stops routing through the unified path. Asserting the
  behaviour on one backend is not sufficient — T011g passed its own tests while shipping broken on the
  other one.

**The declared type must not depend on the row count**

- **FR-004**: The PostgreSQL type declared for a column MUST be identical whether the query returns
  zero rows or many. A statement Describe and an Execute of the same statement MUST agree.
- **FR-005**: Metadata MUST be sourced in a defined precedence, and the precedence MUST NOT include
  "whatever the first row happened to be" above a source that is available without rows. Measured
  order of availability: what the **statement text** settles; what the **driver** reports; then, only
  as a last resort, the row values.
- **FR-006**: Where the driver reports a usable type, the system MUST use it. Measured: the native
  driver reports distinct ODBC codes (`12`, `-7`, `4`) with no row present, and
  `_map_dbapi_type_to_oid` collapses every one of them to `1043` (varchar) because it string-matches a
  numeric code. That mapping MUST be corrected as part of this feature; it is the upstream cause of
  the value-based refinement that FR-005 forbids relying on.
- **FR-007**: Where no source settles a column's type, the system MUST declare a defined fallback and
  MUST NOT guess from an absent value. A wrong confident type breaks a binary-format client, which is
  the whole failure being prevented.

**Error classification holds on both backends**

- **FR-008**: Error classification MUST hold on **both** backends, and MUST keep the scores T027
  established — 9/9 over the wire, 13/13 embedded. Reclassification MUST be driven by the message
  text as well as any SQLCODE, because measured: the embedded backend carries no SQLCODE for a missing
  table or column, and a third-party embedded facade raises the raw ObjectScript `%Status` `$LIST`
  with 28–30 non-printable bytes and no SQLCODE either. A driver-layer change MUST NOT be accepted
  without re-running both probes.

**Cross-backend behaviour**

- **FR-009**: For any observable behaviour, the two backends MUST agree, **or** the difference MUST be
  recorded with the measurement that establishes it and the reason it cannot be unified. An
  undocumented divergence is a defect. *(Constitution Principle IV.)*
- **FR-010**: The empty string and SQL NULL MUST be distinguishable to the client on both backends,
  and MUST be represented as PostgreSQL represents them — a zero-length value and NULL. Measured
  today: the native driver is already correct (`''` / `None`); `iris.sql.exec` returns `'\x00'` for
  the empty string and `''` for NULL. Closing this requires first verifying the wire-level behaviour
  end-to-end, which the spike could not do; that verification is part of this feature, and if the wire
  behaviour turns out to be correct already, this requirement is satisfied and the finding is recorded
  as a driver-level quirk our layer absorbs.

**Regression guarantee**

- **FR-011**: The existing test suite MUST keep passing. The measured baseline on 2026-08-17 is
  **5120 passed, 2 failed, 5 skipped** in `tests/unit`, where the two failures are the DDL-casing pair
  recorded as Complexity Tracking **C-1** in `specs/044-catalog-as-views/plan.md`
  (`test_generated_columns.py::test_generated_column_skip` and `::test_generated_column_multiple_skip`).
  **Nothing else may break, and this feature MUST NOT "fix" those two by changing DDL casing** — that
  is C-1's exit condition, owned elsewhere.
- **FR-012**: Every defect fixed in `docs/orm-introspection-findings.md` and in feature 044 MUST stay
  fixed, verified by re-running 044's own probes rather than by inspection. This is not optional
  politeness: 044's verification was performed against the current driver layer, and a driver change
  invalidates it.
- **FR-013**: Non-metadata behaviour MUST NOT change — ordinary SQL, DDL, DML, transactions,
  `RETURNING` emulation, `COPY`, and vector operations are unaffected by this feature.
- **FR-014**: The per-statement cost of the unified path MUST be measured against the Principle V 5 ms
  budget before merge, in the manner of `tests/unit/test_translation_gate_budget.py`. Consolidation
  that adds a per-column pass on the hot path is a performance change, not a refactor.

**Dependency posture**

- **FR-015**: This feature MUST NOT add a runtime dependency in order to satisfy FR-001 through
  FR-007. Those requirements are satisfiable in-house, which the spike established. A new dependency
  MAY be adopted only if it clears the evidence bar in §Alternatives, and MUST then be adopted as a
  separate, revertible change with its own verification.
- **FR-016**: Any driver-layer package adopted MUST NOT overwrite or shadow a file owned by another
  installed distribution. Measured: `iris-embedded-python-wrapper` 0.6.1 and
  `intersystems-irispython` 5.4.0 both install `iris/__init__.py`, so installing the former replaces
  the latter's package initialiser and uninstalling it deletes the file. It additionally claims the
  top-level name `iris_ep`, which InterSystems itself ships at
  `/usr/irissys/lib/python/iris_ep.py`; measured, when IRIS's copy wins, `iris.runtime` exists to
  `hasattr` and raises `Cannot call an iris.package wrapper … Given name was: runtime.get` on use.

### Key Entities

- **Result Materialisation**: turning a driver result into rows plus column metadata. Three
  implementations today; one after this feature.
- **Column Metadata**: per output column — name, PostgreSQL type OID, size, type modifier, format
  code. What the RowDescription carries and what the DataRow encoding must match.
- **Metadata Source**: statement text, driver-reported description, or row values — with a defined
  precedence (FR-005).
- **Backend**: embedded (`iris.sql.exec` under `irispython`) or DBAPI (connection pool over 1972),
  selected by configuration, never by a code fork.
- **Error Classification**: IRIS failure text → PostgreSQL SQLSTATE, in
  `sql_translator/sqlstate.py`.

---

## Success Criteria *(mandatory)*

- **SC-001**: **One** implementation decides column metadata, asserted by a test that both backends
  route through it. Count of independent implementations goes from **3 to 1**.
- **SC-002**: For a corpus of at least **20 statement shapes** — including catalog queries, boolean
  expressions, casts, `SELECT *`, aggregates, vectors and zero-row cases — the declared column types
  are **identical** on both backends. Zero divergences, or each divergence documented under FR-009.
- **SC-003**: For every statement in that corpus, the declared types with **zero rows** equal the
  declared types with **rows**. Zero exceptions.
- **SC-004**: `specs/044-catalog-as-views/spikes/probe_statement_describe.py` reports **PASS** on both
  backends (today: PASS on the backend 044 verified).
- **SC-005**: SQLSTATE classification stays at **9/9** over the wire and **13/13** on the embedded
  backend, re-measured, not assumed.
- **SC-006**: `tests/unit` shows **no new failures** against the 2026-08-17 baseline of 5120 passed /
  2 failed (C-1) / 5 skipped.
- **SC-007**: The empty string and SQL NULL are distinguishable and PostgreSQL-correct in **4/4**
  cases (literal and bound, each of empty and NULL) on **both** backends — or the residual gap is
  documented with its measurement.
- **SC-008**: Lines of result-materialisation code decrease. Consolidation that only adds an
  abstraction over three retained copies has not achieved SC-001 and is not this feature.
- **SC-009**: The unified path costs under **25%** of the 5 ms Principle V budget per statement,
  measured, matching the ceiling SC-009 of feature 044 set for the translation gates.
- **SC-010**: **Zero** new runtime dependencies, unless the §Alternatives evidence bar was cleared and
  the decision recorded here.

---

## Alternatives considered

The spike existed to choose between these two. They are not equally weighted, and the reason is
measurement, not preference.

### A. Consolidate in-house (recommended)

Put the metadata decision behind one internal interface both executors call, extend it to cover what
the three materialisers do today, and fix `_map_dbapi_type_to_oid` so the driver's own type codes are
used instead of discarded.

- **Achieves**: FR-001…FR-007 in full. FR-010 as far as measurement supports.
- **New dependencies**: none. The project depends only on the official SDK today, and this keeps it
  that way.
- **Invalidates 044's verification?** No. The driver underneath is unchanged, so 044's probes are
  re-run as a regression check rather than as a re-qualification.
- **Cost**: the work is ours. ~5,700 lines of executor to read and carefully reduce; no upstream help.
- **Evidence it is sufficient**: measured — the native driver already satisfies FR-004 and reports
  distinct types with zero rows; the row-count dependence came from our own five-line mapper; and
  the third-party embedded facade reports *no* column types, so it cannot satisfy FR-001 anyway.

### B. Adopt `iris-embedded-python-wrapper` as the driver layer

Replace `iris.sql.exec` and the DBAPI pool with `iris.dbapi` from the wrapper, in `runtime="auto"`.

- **What it actually delivers, measured**: a working DB-API facade whose native mode is a
  **pass-through** to the official driver (it returns `iris.dbapi.IRISConnection` itself); a real
  `iris.runtime` model; embedded access from ordinary `python3`; and **correct `''` / `None`
  normalisation on the embedded path**, which is the one thing it does better than we do today.
- **What it does not deliver**: FR-001 — the embedded facade reports `type_code=None` for every
  column, so a unified metadata decision on top of it still needs
  `sql_translator/column_types.py`. FR-008 — errors are *not* normalised; the embedded facade raises
  the raw `%Status` `$LIST` with control bytes and no SQLCODE, which is harder to classify than the
  plain text `iris.sql.exec` gives today (classification survived at 3/3, by wording match, which is
  luck rather than contract).
- **Costs, measured**: a **single-maintainer, Development-Status-4-Beta package on the critical path
  of every query**; a file collision with the official SDK (`iris/__init__.py`, FR-016); a
  module-name collision with InterSystems' own `iris_ep` inside IRIS, whose failure signature names
  neither cause; and an embedded-local mode that reports `embedded_available=True` and answers
  `SELECT $ZVERSION` while DDL fails with `<UNIMPLEMENTED>ddtab+83^%qaqpsq` when `LD_LIBRARY_PATH` is
  not set before Python starts — measured, and it dropped SQLSTATE classification to 2/3 by replacing
  the IRIS error with the loader error.
- **Invalidates 044's verification?** Yes. Every result in 044 was measured through the current
  driver; swapping the driver means re-qualifying `pg_catalog` views, `PG_ARRAY`, boolean handling,
  binary array parameters and the SQLSTATE probes from scratch.
- **Does not remove the `docker cp` workflow**: measured — there is no IRIS installation on the host
  at all, so embedded-local mode is unreachable from where pgwire runs. The benefit that motivated
  looking at it does not exist in this deployment shape.

### C. Do nothing

Keep three materialisers. Rejected on recorded history: two client-visible defects already came from
this duplication, one of them invisible on the backend its author tested. The next one costs the same
and arrives the same way.

### The evidence bar for choosing B later

Route B wins only if **all** of the following become true, each measured:

1. The wrapper's **embedded** DB-API reports usable per-column type metadata — at minimum
   distinguishing boolean, integer and string with **zero rows** present. Today: `None` for every
   column.
2. Its embedded error surface either carries a SQLCODE or a stable plain-text wording, so FR-008 rests
   on a contract rather than on a substring surviving inside a serialised `%Status`.
3. It stops claiming `iris/__init__.py` and `iris_ep`, or the project accepts a documented,
   pinned install layout in which neither collision can occur.
4. Embedded-local mode fails **loudly at configuration time** when the loader path is wrong, rather
   than after N successful statements.
5. Route A has been completed first, so that adoption is measured as a *replacement of a known-good
   layer* — with 044's probes as the oracle — rather than as a simultaneous refactor and dependency
   change.

Point 5 is not negotiable regardless of 1–4: a driver swap and a consolidation performed together
have no bisectable failure.

---

## Assumptions

- **The native driver's `cursor.description` is row-count independent and type-distinguishing.**
  *Verified by measurement* on IRIS 2026.2 — identical output at 10 rows and 0 rows, codes
  `12`/`-7`/`4`. Not verified on other IRIS versions.
- **`iris.sql.exec` results carry no `_meta` on this IRIS build.** *Verified by measurement.* The
  branch in `_materialize_embedded_result` that reads it is therefore dead here; other versions
  untested, so the branch is not assumed removable without a version check.
- **The embedded backend reports no per-column type codes through a DB-API surface.** *Verified* for
  the third-party facade. Whether `%SQL.Statement` metadata is reachable another way (e.g.
  `%GetMetadata`) is **not** verified and is a Phase 0 question for the plan.
- **`sql_translator/column_types.py` is the right shape for the unified decision.** *Partly verified*:
  it already serves both executors and is row-count independent by construction. Whether it can absorb
  name normalisation, size and format decisions is a design question, not a measurement.
- **IRIS is required for all verification; there is no mock and none will be introduced.**
  Constitution Principle II.
- The 5 ms translation budget is per statement and already 12.4% consumed by 044's gates (measured
  there); a metadata pass must be costed against the remainder.

## Dependencies

- A running IRIS instance for every measurement (`localhost:1972`, namespace `USER`; also the
  `iris-pgwire-db` container for the embedded backend).
- `irispython` inside the container for anything touching the embedded backend — the host has no IRIS
  installation (measured), so embedded verification is `docker cp` plus `docker exec`.
- Feature 044's probes as the regression oracle: `probe_statement_describe.py`,
  `verify_sqlstate_e2e.py`, `probe_embedded_error_wording.py`, `verify_any_e2e.py`.
- `sql_translator/column_types.py`, `sql_translator/sqlstate.py` and `backend_selector.py` as they
  stand.

## Out of Scope

- **Adopting `iris-embedded-python-wrapper`.** Evaluated here and deferred behind the evidence bar
  above. If it is adopted later it is its own feature, with its own re-qualification of 044.
- **Rewriting either executor wholesale.** This feature unifies the metadata decision and the result
  path around it; the ~5,700 lines of transaction, pooling, `COPY` and vector handling are not in
  scope except where they call the materialisers.
- **DDL identifier casing.** C-1 in `specs/044-catalog-as-views/plan.md`, owned by
  `docs/identifier-casing-inconsistency.md`. FR-011 forbids touching it here.
- **New PostgreSQL type coverage.** Declaring *correct* types for constructs already supported is in
  scope; supporting new types is not.
- **Removing the embedded backend, or the `iris.connect` external path inside `IRISExecutor`.**
  Principle IV requires both backends stay functional. Whether path 2 and path 3 above are the *same*
  path wearing two names is a Phase 0 question; deleting either is not assumed.
- **The `iris.sql.exec` bound-`None` inlining workaround** (`iris_executor.py:1825-1848`) — kept
  as-is unless a measurement justifies replacing it.
