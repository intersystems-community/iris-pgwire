# Feature Specification: One Executor, Two Connection Adapters

**Feature Branch**: `051-unified-executor`
**Created**: 2026-09-20
**Status**: Draft — grilled, ordering settled, awaiting plan review
**Supersedes**: `specs/045-unified-iris-driver` (same disease, half the diagnosis)

**Running spec-kit commands on this feature**: the scripts resolve the feature from a `NNN-` branch
prefix. On a branch without that prefix, every invocation needs the override:

```bash
SPECIFY_FEATURE=051-unified-executor bash .specify/scripts/bash/check-prerequisites.sh --json
```

**Input**: Backend selection is supposed to be configuration. It is two classes. Make it
configuration — one statement path, two connection adapters — and make a test fail the moment it
stops being one.

---

## Why

Constitution Principle IV says it outright: _"Backend selection MUST be configuration, never a code
fork."_ Today it is a code fork. `BackendSelector` builds either `IRISExecutor` (4,455 lines) or
`DBAPIExecutor` (1,513 lines), and each carries its own copy of the statement path.

### The measurement that makes this a defect rather than an aesthetic

Of the last 300 commits touching either executor: **15 touched both, 44 touched only
`iris_executor.py`, 3 touched only `dbapi_executor.py`.** 74% of changes were one-sided. That is not
carelessness; it is what two classes with the same job produce.

What it produced most recently: `optimize_vector_query` (`vector_optimizer.py:809`) has **exactly one
call site in all of `src/`** — `iris_executor.py:885`, inside the private `_prepare_sql`. So on the
DBAPI backend, which `tests/conftest.py:692` makes the default outside Docker, `<=>` and `<#>` reach
IRIS untranslated and the server answers `SQLCODE -25, Input ('>) encountered after end of query`.
22 `tests/e2e` tests fail on that, **including `test_readme_vector_similarity_search` — the README's
own example of the headline feature**.

Physical location decided which backend got the feature. The 12 rewrite **functions** that live in
`sql_translator/` are imported identically by both executors and work on both — of which six are
applied by the duplicated inline block and the rest by other call sites (R4 counted the call sites;
12 is the module inventory, not a per-statement count). The three that live outside it — `vector_optimizer`, `schema_mapper`, `inline_limit_offset_params` — reach only the
embedded path. Nobody decided that.

### The interface that was supposed to prevent this

`backend_selector.py:24-84` declares an `Executor` Protocol: 61 lines of interface, 0 of
implementation. It is not `@runtime_checkable`, there are **zero `isinstance` checks anywhere in
`src/`**, neither executor inherits it, and there is no `ABC` or `abstractmethod` anywhere in
`src/`. It declares `sql_pipeline: Any` — which both executors construct and neither uses — omits
`metadata_cache`, which is read three times via `getattr(..., None)` and does not exist on DBAPI, and
types `execute_query -> Any`, which hides an error-mode split: `IRISExecutor` returns
`{"success": False, ...}` at four sites while `DBAPIExecutor` re-raises at `dbapi_executor.py:338`,
making `protocol.py:3560`'s error branch unreachable on the default backend.

An interface with no adapters is a comment.

### What the tests were doing instead

325 test files. By what they cross: 98 pure-function, 33 through an executor, 88 over the wire.
**Zero** run the same statement through both adapters and compare. `tests/conftest.py:691-692` is
session-scoped and reads `PGWIRE_BACKEND_TYPE` once, so all 88 wire files exercise one adapter per
run.

Someone already saw this failure mode and had no seam to assert against.
`tests/unit/test_column_type_resolution.py:157 TestBothExecutorsUseIt` says in its own docstring:
_"The defect existed because the same logic lived in only one executor... A shared resolver is only a
fix if both call it."_ It enforces that with
`assert "resolve_column_type_oids" in inspect.getsource(dbapi_executor)` — a text search. It cannot
fail when the call is present and unreachable, and it cannot fail when a _different_ shared function
is dropped.

### Relationship to feature 045

045 diagnosed this correctly and scoped it to half. It counted three implementations of the
**outbound** decision — what a result looks like — and specified collapsing them to one. Its own Out
of Scope section rules out "rewriting either executor wholesale" and asks whether two of the three
paths are "the same path wearing two names."

The vector defect is the **inbound** half of the same disease: three implementations of what happens
to a statement on the way _in_. 045's requirements are right and are carried forward here verbatim
where they apply. 051 exists because the inbound and outbound halves cannot be unified separately
without restructuring the same code twice.

---

## User Scenarios & Testing _(mandatory)_

### User Story 1 — A divergence between the adapters cannot go unnoticed (Priority: P1)

A maintainer runs one test module and learns every way the two connection adapters currently behave
differently, each classified as a deliberate pin or an open defect. Nothing is unclassified.

**Why this priority**: It is the only story that can be built against today's code with no refactor
at all, and every later story is gated on it. It is also what 045 stalled on — its two Phase-0
gating measurements are exactly this. Building it first front-loads the discovery risk: if the
adapters diverge in ways nobody has enumerated, that is found for the price of a test file rather
than with the core half-built.

**Independent Test**: run the differential corpus against the current `IRISExecutor` and
`DBAPIExecutor`. It passes when every divergence it finds is present in the ledger; it fails when it
finds one that is not.

**Acceptance Scenarios**:

1. **Given** a statement in the corpus, **When** it is executed through each adapter, **Then** the
   rows, per-column types, affected-row count and error classification are compared and any
   difference is reported with both observed values.
2. **Given** a difference that is recorded in the ledger as a pin, **When** the corpus runs,
   **Then** it passes, and the pin's measurement is cited in the output.
3. **Given** a difference that is not in the ledger, **When** the corpus runs, **Then** it fails,
   and the failure names the statement and both observed values.
4. **Given** a test whose outcome depends on which adapter served it, **When** it is collected,
   **Then** it carries the `backend_sensitive` marker and runs against every adapter.

---

### User Story 2 — A statement is prepared once, the same way, for either adapter (Priority: P1)

A maintainer adds or corrects a rewrite. Both backends get it. There is no second place to add it to
and no way to add it to only one.

**Why this priority**: This is the defect that occasioned the feature. `<=>` on the DBAPI backend is
the visible symptom; the 37-line rewrite sequence duplicated verbatim — including its comments — at
`iris_executor.py:1230-1266` and `dbapi_executor.py:242-278` is the cause.

**Independent Test**: delete the vector rewrite from the single preparation path; assert that the
corpus fails for **both** adapters. Restore it; assert both pass. A change that can break one
adapter and not the other has not satisfied this story.

**Acceptance Scenarios**:

1. **Given** `SELECT ... ORDER BY embedding <=> $1 LIMIT $2`, **When** it is prepared for either
   adapter, **Then** the emitted SQL and the parameter list are identical, and the parameters are
   renumbered to match the SQL. _(Measured defect today: `optimize_vector_query` returns SQL still
   saying `LIMIT $2` with parameters `[5]`.)_
2. **Given** a statement using `<->` (L2), **When** it is prepared, **Then** preparation fails with
   `NOT IMPLEMENTED` on both adapters — never reaching IRIS, never silently substituting cosine.
3. **Given** the **six** rewrites currently inline in `IRISExecutor.execute_query` and the **seven**
   preparation steps applied only inside `_prepare_sql` — counted by measurement in `research.md` §R4
   — **When** preparation runs for the DBAPI adapter, **Then** all thirteen apply.
4. **Given** the rewrite sequence, **When** it is read, **Then** it exists in exactly one place;
   `grep` finds no second ordered copy.

---

### User Story 3 — A result means the same thing whichever adapter produced it (Priority: P1)

A frontend receives the same column types, the same empty-string-versus-NULL distinction and the
same row count regardless of which adapter served the statement.

**Why this priority**: This is 045's scope, and it is carried at P1 because the corpus from US1
measures it whether or not anyone unifies it. Doing it after US2 rather than before means the
instrument exists and one path already runs through it.

**Independent Test**: 045's own — `specs/044-catalog-as-views/spikes/probe_statement_describe.py`
on both adapters, plus the corpus asserting type equality at zero rows and at many.

**Acceptance Scenarios**:

1. **Given** a statement whose parameters match nothing, **When** its statement Describe is read,
   **Then** the declared types equal those declared when the same statement matches many rows.
2. **Given** an adapter that reports per-column types, **When** a result is materialised, **Then**
   those types are used. _(Measured defect today: `_map_dbapi_type_to_oid`,
   `dbapi_executor.py:1241`, does `str(dbapi_type).upper()` on a numeric ODBC code and collapses
   `12`, `-7` and `4` all to `1043`.)_
3. **Given** an adapter that reports no per-column types for a statement, **When** a result is
   materialised, **Then** the declared type comes from the statement text or a defined fallback —
   never from an absent value. _(Measured: this is no longer either adapter's steady state. Both
   report ODBC codes, embedded via `%SQL.Statement._Metadata` and DBAPI via `cursor.description`. It
   remains the case for the `iris.sql.exec` route, whose result object has no metadata member, and for
   error paths — so the scenario stays, describing a route rather than an adapter.)_
4. **Given** a non-NULL empty string and a SQL NULL, **When** each is read on either adapter,
   **Then** the frontend receives a zero-length value and NULL respectively, and the two are
   distinguishable. _(Measured today on embedded: `iris.sql.exec` returns `'\x00'` for the empty
   string and `''` for NULL — the inverse of Python's convention — and
   `_normalize_iris_null` maps `''` to `None`, so a real empty string reaches the frontend as one
   NUL byte.)_

---

### User Story 4 — An impossible configuration is refused at startup, not discovered in production (Priority: P2)

An operator starts the server with a configuration the selected adapter cannot honour. The server
refuses to start and says which capability is missing.

**Why this priority**: The two known cases are both measured and both currently silent. It is
separable from US1-US3 and does not block them.

**Independent Test**: start the server with each impossible configuration; assert a startup failure
naming the capability. Then assert the possible configurations still start.

**Acceptance Scenarios**:

1. **Given** the embedded adapter, which declares `per_session_transactions = False` because an IRIS
   transaction belongs to the process and not the thread, **When** the server is configured to serve
   concurrent client transactions, **Then** it refuses to start and names that capability.
   _(Measured and recorded in `KNOWN_LIMITATIONS.md:366-391`, including a two-thread visibility
   leak. Today it is a paragraph in a document rather than a fact about an interface.)_
2. **Given** an IRIS licence that allows 7 concurrent connections, **When** the pool size is 10 —
   which is the default at both `server.py:76` and `server.py:349` — **Then** startup refuses and
   names the licence count. _(Measured: the 8th DBAPI connect raises
   `OperationalError: ... Unable to allocate a license`, so the default exceeds the ceiling by three.
   This is why `tests/contract/test_dbapi_executor_contract.py` hangs rather than fails: once the pool
   is exhausted every acquisition retries roughly 2s apart, forever.)_
3. **Given** a requested isolation level the adapter cannot put in force, **When** it is requested,
   **Then** it is refused rather than accepted-and-ignored. _(Measured, `KNOWN_LIMITATIONS.md:350`:
   `SET TRANSACTION ISOLATION LEVEL READ COMMITTED` returning success does not mean the level is in
   force for the next read.)_
4. **Given** a capability set, **When** it is read, **Then** it is declared by the adapter, not
   inferred by the core through `hasattr` or `getattr(..., None)`.

---

### User Story 5 — A statement enters the executor once (Priority: P2)

A maintainer can read the statement path top to bottom without the path calling back into its own
entry point, and the running executor's behaviour is the behaviour of the code that was tested.

**Why this priority**: Re-entrancy is why "does the rewrite sequence run?" was only answerable by
reading, and the monkey-patch is why the tested object is not the running object. Both must go before
US6 can delete anything, because neither is bisectable.

**Independent Test**: instrument the core's entry point with a counter; assert that a catalog query,
a metadata lookup and an isolation change each increment it exactly once.

**Acceptance Scenarios**:

1. **Given** a catalog statement, **When** it is prepared, **Then** it resolves to _answered
   locally_, and no code path calls the executor's entry point again. _(Today: both executors call
   `catalog_router.handle_catalog_query` from inside `execute_query`, and `catalog_router.py:949`,
   `:972`, `:1027`, `:1088` call `executor.execute_query` back.)_
2. **Given** a metadata lookup, **When** it needs to query IRIS, **Then** it uses an explicit
   internal call, not the frontend entry point. _(Today: `sql_translator/metadata_cache.py:70`.)_
3. **Given** an isolation change, **When** it executes its own SQL, **Then** it does so without a
   `_skip_isolation` flag, because nothing re-enters. _(Today: `_isolation.py:250` and `:406`.)_
4. **Given** IntegratedML is enabled, **When** the server starts, **Then** it is a declared
   preparation step and no method is rebound at runtime. _(Today:
   `integratedml.py:367-372 enhance_iris_executor_with_integratedml` does
   `original_execute_query = iris_executor.execute_query` and replaces it.)_
5. **Given** a call to a private method of a specific executor, **When** the suite runs, **Then**
   none exists. _(Today: `bulk_executor.py:358` calls `_execute_external_async`, which exists on one
   executor only; `catalog/catalog_functions.py:261`, `:376`, `:420`, `:476`, `:489` call
   `self.executor._execute_iris_query(...)`, which is defined on **neither** executor, inside `try:`
   blocks that swallow the `AttributeError`.)_

---

### User Story 6 — There is one executor (Priority: P3)

`iris_executor.py` and `dbapi_executor.py` no longer exist, and the selector value that chose
between them is gone.

**Why this priority**: Last because it is the only irreversible step, and it is in scope because
this project's measured failure mode is that transitional things survive. `SQLPipeline` is a 63-line
container both executors construct and neither uses. `sql_translator/api.py`,
`confidence_analyzer.py` and `metrics.py` are 1,853 lines with zero inbound edges from `src/`.
`_execute_iris_query` is called five times and defined nowhere. Each was once a reasonable
intermediate state.

**Independent Test**: `git grep -c 'class IRISExecutor\|class DBAPIExecutor'` returns 0, the full
suite passes, and the corpus from US1 passes against the two adapters of the unified core.

**Acceptance Scenarios**:

1. **Given** the unified core passes the corpus and the full suite, **When** the old executors are
   deleted, **Then** nothing imports them and the rollback environment variable is removed in the
   same change.
2. **Given** the feature is claimed complete, **When** the tree is inspected, **Then** no module,
   flag or environment variable exists whose only purpose was the transition.

---

### Edge Cases

Carried from 045 because they are measured and still live:

- **A query returns zero rows** — declared types identical to the non-empty case. This is the T011h
  shape and must be a test.
- **`SELECT *` expansion** where the select-list item count does not match the column count: an
  override is declined rather than applied to the wrong column.
- **A column nothing settles the type of** — reachable via the `iris.sql.exec` route, whose result
  object exposes no metadata member (measured), and via error paths. _Not_ the embedded adapter as a
  whole: `%SQL.Statement._Metadata` reports ODBC codes matching DBAPI's (measured). What is declared
  must be defined, not incidental.
- **A statement executed for its side effect** (DDL, `INSERT` without `RETURNING`) — no
  `RowDescription`; the unified path must not invent one.
- **`RETURNING` emulation**, which builds rows with no driver cursor at all.
- **A parameter bound as `None` on the embedded adapter**, worked around today by inlining literals
  (`iris_executor.py:1825-1848`). Kept or replaced with something measured, not dropped.
- **An IRIS version that reports metadata differently.** Measured on 2026.2: the `iris.sql.exec`
  result object has **no `_meta` attribute**, so the branch in `_materialize_embedded_result` that
  reads it is dead here. Other versions untested, so it is not assumed removable without a version
  check.

New to 051:

- **`SQLRefiner.refine` currently runs twice per statement** — `normalizer.py:258` and
  `pipeline.py:61` — which is why `tests/unit/test_order_by_alias_idempotence.py` exists. The
  unified path runs it once; that test must keep passing for the opposite reason.
- **A statement answered locally that then fails** — a catalog view that raises. It must produce the
  same error classification as a statement that failed in IRIS.
- **An adapter that loses its connection mid-statement.** The DBAPI adapter has pool eviction
  (`dbapi_executor.py:295-313`); the embedded adapter has no connection to lose. The difference is a
  pin, and it needs wording.
- **Two adapters configured at once.** Out of scope, and the core must refuse it rather than pick.

---

## Requirements _(mandatory)_

### Functional Requirements

#### One place decides — carried from 045, widened from the result to the statement

- **FR-001**: Exactly **one** code path MUST prepare a statement, and exactly **one** MUST decide
  the column metadata of a result. Both adapters MUST reach both. A second implementation of either
  decision is a defect, not a variant. _(045 FR-001, extended to preparation.)_
- **FR-002**: Both paths MUST be reachable without instantiating an executor or opening a
  connection, so they can be tested directly and neither adapter can quietly diverge. _(045
  FR-002.)_
- **FR-003**: A test MUST fail if either adapter stops routing through either path, **by execution
  and not by source inspection**. Asserting the behaviour on one adapter is not sufficient — T011g
  passed its own tests while shipping broken on the other one, and
  `TestBothExecutorsUseIt` asserts the current property with `inspect.getsource`, which cannot
  detect a call that is present and unreachable. _(045 FR-003, with the enforcement mechanism
  named.)_

#### The adapter interface

- **FR-004**: A connection adapter's interface MUST be: execute prepared SQL with ordered
  parameters, and return a raw result comprising rows, driver-reported per-column types **or the
  declared absence of them**, affected-row count, and the unparsed error if any. An adapter MUST NOT
  rewrite SQL, decide a PostgreSQL type, or manufacture metadata it was not given.
- **FR-005**: The adapter interface MUST be enforced at runtime, not declared and ignored. Every
  adapter MUST be checkable against it, and a test MUST fail if an adapter does not satisfy it.
  _(Today: 61 lines of Protocol, zero `isinstance` checks, no `abstractmethod` in `src/`, neither
  executor inheriting it.)_
- **FR-006**: There MUST be exactly one error mode across the interface. A failure is reported the
  same way by both adapters, and dead error-handling branches MUST NOT survive the change. _(Today:
  four `{"success": False}` returns in `IRISExecutor` versus a re-raise at
  `dbapi_executor.py:338-340`, which makes `protocol.py:3560` unreachable on the default backend.)_

#### Metadata precedence — carried from 045

- **FR-007**: The PostgreSQL type declared for a column MUST be identical whether the statement
  returns zero rows or many; a statement Describe and an Execute MUST agree. _(045 FR-004.)_
- **FR-008**: Metadata MUST be sourced in a defined precedence, and that precedence MUST NOT place
  "whatever the first row happened to be" above a source available without rows. Measured order:
  what the **statement text** settles, then what the **driver** reports, then row values as a last
  resort. _(045 FR-005.)_
- **FR-009**: Where the driver reports a usable type, the system MUST use it, and
  `_map_dbapi_type_to_oid` MUST be corrected. Measured: `12`, `-7` and `4` all map to `1043` today
  because a numeric code is string-matched. This is the upstream cause of the value-based refinement
  FR-008 forbids relying on. _(045 FR-006.)_
  **Both adapters report types, and they report the same codes.** R2 measured
  `%SQL.Statement._Prepare(sql)` → `._Metadata` → `.columns.GetAt(i).ODBCType` returning `12`, `4`,
  `-7` for a varchar/integer/bit result — identical to the DBAPI adapter's `cursor.description`. One
  shared ODBC-code-to-OID table therefore serves both, and the corrected mapping MUST be exercised
  against both. _(Reverses this feature's earlier record of "no metadata by any route"; that was wrong
  API names, not absent metadata.)_
- **FR-010**: Where nothing settles a column's type, the system MUST declare a defined fallback and
  MUST NOT guess from an absent value. _(045 FR-007.)_ Per R2 the fallback is **not** the embedded
  common case: it applies to the `iris.sql.exec` route, whose result object exposes no metadata member
  at all, and to error paths. The embedded adapter MUST therefore prepare via `%SQL.Statement` rather
  than `iris.sql.exec` where column metadata is needed, and the choice of route MUST be stated
  wherever the fallback is declared, so a future route change cannot silently widen the fallback.

#### Capabilities

- **FR-011**: A connection adapter MUST declare its capabilities — at minimum
  `per_session_transactions`, `cross_session_dirty_reads`, `max_concurrent_sessions`,
  `isolation_levels_accepted`, `isolation_levels_in_force`, `reports_column_types`,
  `describe_without_execute` and `available_under_irispython`. The core MUST NOT infer them by
  `hasattr`, `getattr(..., None)` or class name. Measured values are in `research.md` §R5 and §R2.
  - `isolation_levels_accepted` and `isolation_levels_in_force` MUST remain separate fields.
    Measured: DBAPI accepts `READ UNCOMMITTED` and `READ COMMITTED` and enforces neither, and a
    session sees another session's uncommitted rows on **both** adapters. A single
    "supports isolation" boolean would restate the error already retracted once.
  - `per_session_transactions` describes **ownership, not isolation**. Measured on DBAPI: session B
    sees A's uncommitted row, yet `A.rollback()` discards A's work and `B.commit()` does not commit
    it — final count 0, which is what PostgreSQL would report. On embedded the same sequence ends at
    1. `cross_session_dirty_reads` carries the part that is true of both.
- **FR-012**: A configuration the declared capabilities cannot honour MUST be refused at startup
  with a message naming the capability. It MUST NOT be silently degraded and MUST NOT fail later.
  _(Constitution Principle I — the rule that rejects L2 `<->` and refuses `REPEATABLE READ`.)_
  The refusal set MUST include **requesting the DBAPI adapter while running under `irispython`**.
  Measured: in that interpreter `iris.connect` and `iris.dbapi.connect` are both uncallable
  `iris.package` objects that raise `NameError: Cannot call an iris.package wrapper`, so the adapter
  is unavailable rather than slow. `available_under_irispython` is the capability that names it.
- **FR-013**: The default pool size MUST NOT exceed the licence units available to the configured
  instance, and exhaustion MUST fail rather than retry forever.

#### Cross-adapter behaviour and its record

- **FR-014**: For any observable behaviour, the two adapters MUST agree, **or** the difference MUST
  be recorded in the divergence ledger with the measurement that establishes it and the reason it
  cannot be unified. An undocumented divergence is a defect. _(045 FR-009, Constitution Principle
  IV.)_
- **FR-015**: Every ledger entry MUST be classified as exactly one of **pin**, **fix**, or
  **no reference answer**. An unclassified entry MUST fail the corpus. A pin MUST cite its
  measurement; a fix MUST name its owner; a `no reference answer` entry MUST name the IRIS construct
  that puts it outside PostgreSQL's opinion and cite the project's own documented intent in place of
  a reference measurement.
  - The third disposition exists because it was measured, not anticipated. R3 found six corpus
    statements PostgreSQL 16.14 cannot parse or run at all: `SELECT TOP`, `%ID`, a `SQLUser.` schema
    reference, `$SYSTEM.` function calls, `CAST(... AS VECTOR(...))` and the `<=>` operator. Forcing
    these into `pin` would make "pin" mean two different things — a difference we chose, and a
    question the reference cannot answer.
- **FR-016**: **Real PostgreSQL 15/16 is the reference** for any behaviour it has an opinion about —
  type OIDs, `RowDescription` shape, empty-string versus NULL, row counts, command tags. Where
  PostgreSQL has no answer for an IRIS construct, the incumbent embedded behaviour is the reference
  and the choice is recorded under FR-015's third disposition. Old-versus-new equality alone MUST NOT
  be the acceptance criterion, because it would certify the defects this feature exists to remove.
  - The reference container MUST be **pgvector-enabled** (`pgvector/pgvector:pg16` or equivalent).
    Measured: on plain `postgres:16-alpine`, `<=>` and `::vector` fall into the unadjudicable set —
    which would leave the operators behind this feature's headline defect with no reference answer for
    a reason that is an image choice rather than a real dialect gap. L2 `<->` stays unadjudicable by
    intent, since the constitution requires refusing it (Principle VI).
  - Captured reference answers are in `research.md` §R3, from PostgreSQL **16.14** running as this
    repository's own `iris-pgwire-pgref`. Two divergences it settles: PostgreSQL describes a prepared
    statement without executing it, and PostgreSQL distinguishes `''` from `NULL` where the embedded
    adapter returns `'\x00'` and `''` respectively.
- **FR-017**: The empty string and SQL NULL MUST be distinguishable to the frontend on both
  adapters, represented as PostgreSQL represents them. _(045 FR-010.)_
- **FR-018**: Error classification MUST hold on both adapters and MUST keep the scores T027
  established — 9/9 over the wire, 13/13 embedded — re-measured, not assumed, and driven by message
  text as well as any SQLCODE because the embedded adapter carries no SQLCODE for a missing table or
  column. _(045 FR-008.)_

#### One entry point

- **FR-019**: The core's entry point MUST NOT be re-entered while preparing or executing a
  statement. Catalog routing MUST be an outcome of preparation; metadata discovery MUST be an
  explicit internal call; the isolation path MUST NOT need a flag to suppress re-entry.
- **FR-020**: No method of the core MAY be rebound at runtime. Optional behaviour — IntegratedML
  today — MUST be a declared preparation step selected by configuration, so the object that was
  tested is the object that runs.
- **FR-021**: No module outside the core MAY call a private method of the core or of an adapter. The
  five existing calls to `_execute_iris_query`, which is defined on neither executor, MUST be
  resolved rather than kept working by accident.

#### Migration discipline

- **FR-022**: The unified core MUST be built alongside the existing executors, selectable by
  configuration, with the old pair retained as the differential oracle during the transition.
- **FR-023**: The feature is **not complete** while `iris_executor.py`, `dbapi_executor.py` or the
  transitional selector value exists. Their deletion is in scope, in this feature, not deferred.

#### Regression guarantee

- **FR-024**: The existing suite MUST keep passing against the measured baseline —
  `tests/unit`: **5821 passed, 10 skipped**; whole-tree collection: **7128 collected, 0 errors**.
  The known-red suites in `docs/RELEASE_CHECKLIST.md` §5 MUST NOT grow, and the e2e failures this
  feature fixes MUST be counted down explicitly.
  - **This baseline is not 100%, and Constitution Principle II requires 100% of the IRIS integration
    suite.** Measured in R6: the container-backed suites reach 106 errors and 5 skips before their
    first assertion, for a fixture-loader reason unrelated to this feature. 051 therefore holds the
    line rather than restoring it, and the deviation is recorded in `plan.md` §Complexity Tracking
    with T075-T077 as the route back to 100%. A baseline is a floor, never a licence for a new
    failure.
- **FR-025**: Every defect fixed in feature 044 and `docs/orm-introspection-findings.md` MUST stay
  fixed, verified by re-running 044's probes rather than by inspection. _(045 FR-012.)_
- **FR-026**: Non-statement behaviour MUST NOT change: `COPY`, bulk loading and IntegratedML remain
  callers of the core, not parts of it. _(045 FR-013, narrowed to what 051 leaves outside.)_
- **FR-027**: The per-statement cost of the unified path MUST be measured against the Principle V
  5 ms budget before merge, in the manner of `tests/unit/test_translation_gate_budget.py`. _(045
  FR-014.)_

#### Dependency posture

- **FR-028**: No new runtime dependency. _(045 FR-015; see ADR-0002.)_
- **FR-029**: No package **adopted by this feature** may overwrite or shadow a file owned by another
  installed distribution. _(045 FR-016.)_ Scoped to adoptions deliberately: R1 measured this repo's
  own `.venv` already in that state — two overlapping `intersystems_irispython` dist-infos (5.2.1 and
  5.3.2) and an SDK-sanctioned `iris_ep` handoff from `iris/__init__.py`. That is a pre-existing
  condition this feature does not create and does not fix; T075 pins the layout so it cannot drift
  further, and ADR-0002 records why it is not grounds for adopting the wrapper.

### Key Entities

Defined in `CONTEXT.md`, which this feature creates: **statement**, **preparation**, **prepared
statement** (_answered locally_ or _sent to the adapter_), **raw result**, **materialisation**,
**column metadata**, **metadata source**, **backend**, **connection adapter**, **capability**,
**divergence**, **divergence ledger**, **differential corpus**, **reference**.

---

## Success Criteria _(mandatory)_

- **SC-001**: The differential corpus covers at least **20 statement shapes** — catalog queries,
  boolean expressions, casts, `SELECT *`, aggregates, vectors, DDL, `RETURNING`, empty-string and
  NULL, and zero-row variants of each that can have one — and runs against every adapter.
- **SC-002**: Divergences found by the corpus: **zero unclassified**. Every one is a pin with a
  measurement or a fix with an owner.
- **SC-003**: Independent implementations of the statement-preparation sequence go from **3 to 1**
  (embedded-inline, embedded-`_prepare_sql`, DBAPI-inline). Independent implementations of result
  materialisation go from **3 to 1** (045 SC-001).
- **SC-004**: Declared column types are identical across adapters for every corpus statement, and
  identical at zero rows and at many. Zero exceptions (045 SC-002, SC-003).
- **SC-005**: The 22 failing `tests/e2e` tests caused by missing translation on the DBAPI backend
  pass, `test_readme_vector_similarity_search` among them, and the count is reported as a countdown
  rather than a claim.
- **SC-006**: `specs/044-catalog-as-views/spikes/probe_statement_describe.py` reports **PASS** on
  both adapters (045 SC-004). SQLSTATE classification stays at **9/9** over the wire and **13/13**
  embedded (045 SC-005).
- **SC-007**: Empty string versus NULL is PostgreSQL-correct in **4/4** cases — literal and bound,
  each of empty and NULL — on both adapters, or the residual gap is a pin with its measurement (045
  SC-007).
- **SC-008**: Every impossible configuration in US4 fails at startup with a message naming the
  capability. **0** reach a first statement.
- **SC-009**: Entry-point re-entries per statement: **0**, asserted by a counter. Runtime method
  rebinds in `src/`: **0**. Calls from outside the core to a private method of the core or an
  adapter: **0**.
- **SC-010**: Total lines in the statement path decrease. `iris_executor.py` (4,455) +
  `dbapi_executor.py` (1,513) = 5,968 lines are replaced by a core plus two adapters that together
  are smaller. An abstraction layered over two retained copies has not achieved SC-003 and is not
  this feature (045 SC-008).
- **SC-011**: `git grep -c 'class IRISExecutor\|class DBAPIExecutor'` in `src/` returns **0**, and no
  transitional flag or environment variable remains.
- **SC-012**: The unified path costs under **25%** of the 5 ms Principle V budget per statement,
  measured (045 SC-009). **Zero** new runtime dependencies (045 SC-010).
- **SC-013**: `tests/unit` shows no new failures against **5821 passed / 10 skipped**, and whole-tree
  collection stays at **0 errors**.

---

## Assumptions

- **The DBAPI cursor's `description` is row-count independent and type-distinguishing.** _Verified by
  measurement_ on IRIS 2026.2 — identical at 10 rows and 0 rows, codes `12`/`-7`/`4`. Not verified on
  other IRIS versions.
- **`iris.sql.exec` results carry no `_meta` on this build.** _Verified by measurement._
- **The embedded adapter reports no per-column type codes through any DB-API-shaped surface.**
  _Verified_ for the third-party facade (ADR-0002). Whether `%SQL.Statement` metadata is reachable
  another way — `%GetMetadata` — is **not** verified and is a Phase 0 question.
- **`sql_translator/column_types.py` is the right shape for the unified metadata decision.** _Partly
  verified_: it already serves both executors and is row-count independent by construction (045).
- **The 12 rewrite functions in `sql_translator/` are already adapter-independent**, since both
  executors
  import them identically. _Verified by inspection of the import lists_; the corpus will confirm it
  by execution.
- **Real PostgreSQL is available for reference measurements.** A container, not the IRIS one.
- **IRIS is required for all verification; there is no mock and none will be introduced.**
  Constitution Principle II.
- **The 5 ms translation budget is per statement** and already 12.4% consumed by 044's gates.

## Dependencies

- `iris-pgwire-db` (IRIS 2026.1 CE, port 2972, **7 concurrent connections measured**) under
  `DOCKER_CONTEXT=orbstack`, and `irispython` inside it for anything touching the embedded adapter —
  the host has no IRIS installation (measured), so embedded verification is `docker cp` plus
  `docker exec`. The reverse also holds: the DBAPI adapter is not callable under `irispython`
  (measured), so the two adapters cannot be exercised from one process.
- A real **pgvector-enabled** PostgreSQL 16 for FR-016 reference measurements. R3 ran against
  PostgreSQL 16.14; a plain image leaves `<=>` and `::vector` without a reference answer.
- The test dependency set is currently **not** pinned: the project venv lacks `pytest`,
  `testcontainers` and six others, and `uv run pytest` fails at resolution (measured, T075).
- Feature 044's probes as a regression oracle: `probe_statement_describe.py`,
  `verify_sqlstate_e2e.py`, `probe_embedded_error_wording.py`, `verify_any_e2e.py`.
- `sql_translator/` as it stands, particularly `column_types.py`, `sqlstate.py` and `normalizer.py`.
- ADR-0001 (the adapters are peers) and ADR-0002 (no wrapper adoption) as settled context.

## Out of Scope

- **`COPY` and bulk loading.** They stay callers of the core. Their lifecycles are genuinely
  different — streaming and batching — and folding them in would widen the core's interface for no
  locality gain. `bulk_executor.py:358`'s reach-through to a private method is in scope (FR-021);
  restructuring bulk loading is not.
- **IntegratedML behaviour.** Converting it from a monkey-patch to a declared preparation step is in
  scope (FR-020); changing what it does is not.
- **Adopting `iris-embedded-python-wrapper`.** ADR-0002, with the five-point bar for reopening.
- **Deleting a backend.** Constitution Principle IV and ADR-0001 keep both. This feature makes the
  choice configuration rather than a fork; it does not narrow it.
- **DDL identifier casing.** Owned by `docs/identifier-casing-inconsistency.md`.
- **New PostgreSQL type coverage.** Declaring _correct_ types for supported constructs is in scope;
  supporting new types is not.
- **Repo-wide reformatting.** `black --check` reports 136 files and
  `tests/contract/test_code_quality_contract.py` cannot pass until that is done. It is its own
  change and would swamp this diff.
- **The dead half of `sql_translator/`.** `api.py`, `confidence_analyzer.py` and `metrics.py` —
  1,853 source lines with no inbound edges from `src/`, plus 2,244 lines of test across 154 passing
  tests — are a separate commit, not part of this feature.
- **Making CI run the tests.** Agreed separately as container-free CI; the differential corpus needs
  a live IRIS and therefore cannot be that gate. It runs locally and as a nightly container job.
