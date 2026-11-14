# Tasks: One Executor, Two Connection Adapters

**Feature**: `051-unified-executor`
**Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)

**Phase gate rule**: each user-story phase ends with its E2E/differential gate. The gate MUST pass
before the next phase begins. Tests come first within every phase — they define the acceptance
criteria. No test is deferred to polish.

**Container**: every task touching IRIS uses `iris-pgwire-db` (port 2972) under
`DOCKER_CONTEXT=orbstack`, and never any other IRIS container. Run each container-backed suite in its
own pytest process. **Measured ceiling: 7 concurrent connections** (`research.md` §R5) — the 8th
connect fails with `Unable to allocate a license`, so two suites at once produce licence errors rather
than results, and the default `connection_pool_size` of 10 already exceeds it (FR-013).

---

## Phase 1: Setup

- [x] T001 Create `specs/051-unified-executor/research.md` with one empty section per Phase 0
      question R1-R6 from `plan.md`, each naming its method and its command — written with a decision,
      a method and a command per question; probes in `specs/051-unified-executor/spikes/`
- [ ] T002 [P] Stand up a reference **pgvector-enabled** PostgreSQL 16 container
      (`pgvector/pgvector:pg16`) and add it to `docker-compose.test.yml` as a profile that is off by
      default, so FR-016 measurements are reproducible without changing the default developer setup.
      R3 was measured on plain `postgres:16-alpine` as `iris-pgwire-pgref`, where `<=>` and `::vector`
      have no reference answer for an image reason rather than a dialect reason — per FR-016 the
      committed profile MUST close that gap
- [ ] T003 [P] Add a `backend_sensitive` marker to `pyproject.toml`'s pytest config with a docstring
      explaining that a marked test must state why its outcome depends on the adapter
- [ ] T004 [P] Create `docs/adr/README.md` indexing ADR-0001 and ADR-0002 and stating the numbering
      convention
- [ ] T085 [P] Record the SC-013 baseline as **one reproducible command**, committed alongside its
      output, and re-run that same command at every phase gate. `tests/unit` at 5821 passed / 10 skipped
      is only meaningful when captured the same way twice: the e2e two-session tests pass only in their
      own pytest process, so a baseline taken whole-suite and a check taken per-file disagree for
      reasons that have nothing to do with this feature. The comparison, not the number, is the
      deliverable

---

## Phase 2: Foundational (blocking — every user story depends on these)

### Phase 0 measurements

- [x] T005 Answer R1 in `research.md`: run the same 5 statements through
      `IRISExecutor._execute_embedded_async`, `IRISExecutor._execute_external_async` and
      `DBAPIExecutor` directly, and record whether external and DBAPI produce identical raw results.
      Decide the adapter count — two or three — and record it — **two**. 29/29 measurements identical
      via `spikes/probe_r1_host_adapters.py`; confirmed in both a clean venv and the wrapper-loaded
      project venv. Also measured: neither factory is callable under `irispython`, so the adapters
      live in disjoint environments (feeds FR-012)
- [x] T006 Answer R2 in `research.md`: `docker exec` + `irispython`, attempt per-column metadata
      retrieval via `%SQL.Statement` for a boolean/integer/varchar result, and record whether the
      embedded adapter can report types by any route — **it can**, and the earlier negative was
      wrong. `_Prepare` → `._Metadata` → `.columns.GetAt(i).ODBCType` yields `12`, `4`, `-7`, matching
      DBAPI's `description` exactly. `spikes/probe_r2b_embedded_metadata.py`. Hazard recorded: `dir()`
      on a `%SQL.Statement` proxy aborts the process uncatchably
- [x] T007 Answer R4 in `research.md`: time the full preparation sequence per adapter using the
      method of `tests/unit/test_translation_gate_budget.py`, and record the before number against
      the 5 ms Principle V budget. Include the cost of `SQLRefiner.refine` running twice
      (`normalizer.py:258` and `pipeline.py:61`) — unified preparation **0.055 ms worst case = 1.1%**
      of budget, so unification is affordable; the double refine costs **12.2%**, more than the whole
      rewrite block. `spikes/probe_r4_preparation_cost.py`. T028 reproduced with a string vector param
- [x] T008 Answer R5 in `research.md`: re-run the two-session transaction reproducer from
      `KNOWN_LIMITATIONS.md:366-391`, extend it with and without explicit `BEGIN`, and derive
      `max_concurrent_sessions` and `isolation_levels_in_force` per adapter from what is observed —
      DBAPI has per-session transaction **ownership** but dirty reads occur on both adapters;
      `isolation_levels_in_force` is empty on both; **licence ceiling 7** against a pool default of 10.
      `spikes/probe_r5_dbapi_sessions.py`
- [ ] T009 Answer R6 in `research.md`: run `tests/e2e`, `tests/integration` and `tests/protocol`
      once per adapter with `--timeout`, diff the results, and list the files that pass on one and
      fail on the other. Record the known limit of this method — files that pass on both for
      different reasons are invisible to it — as a coverage caveat.
      **BLOCKED, and the blockage is recorded as the finding.** 106 of 151 host wire tests error in
      session setup before any adapter behaviour runs, from `iris-devtester`'s
      `fixtures/loader.py:312 _verify_load` feeding `None` to a regex; `:311` reports the `TypeError`
      as "Table verification failed". The embedded half cannot run on the host at all (T005). Unblocked
      by T075-T077; the diff itself moves to the nightly per-adapter job (T071). Until then the
      `backend_sensitive` population comes from the call-site divergence table in `research.md` §R4,
      not from a diff
- [x] T010 Answer R3 in `research.md`: run the draft corpus statements against a reference PostgreSQL,
      capture type OIDs, `RowDescription` shapes, command tags and row counts, and enumerate the
      statements PostgreSQL cannot run at all — that set is where incumbent embedded behaviour
      becomes the reference — captured from PostgreSQL 16.14 as `iris-pgwire-pgref` via
      `spikes/probe_r3_reference_postgres.sql`. Six statements have no reference answer, which is why
      FR-015 now has a third disposition. **The image carried no pgvector**, so `<=>` has no reference
      answer yet; T002 fixes that with `pgvector/pgvector:pg16` and the affected rows are re-captured
      then

### Shared vocabulary and structures

- [ ] T011 Write `tests/differential/test_ledger_format.py` asserting that every entry in the
      divergence ledger has a statement shape, one observed value per adapter, a classification of
      exactly one of `pin`, `fix` or `no_reference_answer`, a measurement if `pin`, an owner if `fix`,
      and a named IRIS construct if `no_reference_answer` — and that an entry missing any of these
      fails. The third disposition is FR-015 as amended by R3; a two-value classification would force
      six measured statements into `pin` and make `pin` mean two different things
- [ ] T012 Create `tests/differential/ledger.yaml` (or `.json`, whichever `T011` settles) seeded with
      the divergences already measured in `research.md`: `iris.sql.exec` returns `'\x00'` for empty
      string and `''` for NULL where PostgreSQL returns `''` and `NULL` (**fix**, FR-017); embedded
      errors carry no SQLCODE and DBAPI carries it only inside the message text where PostgreSQL gives
      SQLSTATE `42P01` (**fix**, FR-018); DBAPI cannot describe a prepared statement without executing
      it, while both embedded and PostgreSQL can (**fix**); DBAPI reports rowcount `-1` for SELECT
      (**pin**, must never reach a command tag); DBAPI has pool eviction and embedded has no connection
      to lose (**pin**); embedded transactions are process-scoped (**pin**, `KNOWN_LIMITATIONS.md`);
      dirty reads occur across sessions on **both** adapters (**pin**, not a divergence — recorded so
      the corpus does not read the embedded note as adapter-specific); the six IRIS-dialect statements
      from R3 (**no reference answer**). Also seed the three `TO_VECTOR` divergences from
      `research.md` §R7, all **fix**: embedded returns zero rows for any `SELECT` that projects a
      `VECTOR` column, where DBAPI returns the exact values. That one is already fixed; seed it
      with its fix, `tests/e2e/test_vector_projection.py`, as the first corpus rows. Untyped `TO_VECTOR(%s)` gets `FLOAT`
      substituted; pgvector `<=>` gets `DOUBLE` hard-coded. The last two fail against the other column
      type on both adapters. Do **not** seed "embedded reports no per-column types" — R2 measured the
      opposite
- [ ] T013 Write `tests/unit/test_seam_types.py` for `PreparedStatement`, `RawResult` and
      `Capabilities` — construction, the `answered locally` versus `sent to the adapter` distinction,
      and that `RawResult.driver_types is None` is a valid state rather than an error
- [ ] T014 Implement the seam types in `src/iris_pgwire/core/types.py`, per `plan.md` §The seam types.
      No behaviour, no imports from either executor. Include FR-004's adapter interface as an explicit
      declaration of its four elements — execute prepared SQL with ordered parameters, return a
      `RawResult`, declare its `Capabilities`, and nothing else — so that T062's runtime enforcement has
      a written interface to enforce rather than one inferred from the two implementations
- [ ] T015 Add the terms `raw result`, `prepared statement` and `capability` to `CONTEXT.md` if
      `T005`-`T010` sharpened any of their definitions

**Phase 2 gate**: `research.md` has a decision for every one of R1-R6, and
`pytest tests/unit/test_seam_types.py tests/differential/test_ledger_format.py` passes.

Gate status: **R1-R5 measured. R6 was not executed** — its method is blocked by a named external
defect, and it is deferred to T009 with a replacement method (the `research.md` §R4 call-site
divergence table supplies what the diff would have). Calling that "answered" would be the partial
evidence Constitution Principle III forbids, so it is recorded as an open gap the phase is closed
_with_, not as a decision. The design-freezing questions — adapter count, metadata reachability,
preparation cost, capability values, reference answers — are all closed, so Phase 3 is not waiting on
R6. T013-T015 remain.

---

## Phase 3: User Story 1 — A divergence between the adapters cannot go unnoticed (P1)

**Goal**: an executable oracle, built against today's code, with no refactor.

**Independent test**: the corpus runs against the current `IRISExecutor` and `DBAPIExecutor`, passes
when every divergence it finds is in the ledger, fails when it finds one that is not.

- [ ] T016 [US1] Write `tests/differential/test_corpus_harness.py` — tests for the harness itself:
      that it reports both observed values on a mismatch, that an unclassified divergence fails, that
      a `pin` passes and cites its measurement, that a `no_reference_answer` passes and names its IRIS
      construct, and that a missing adapter is a hard error rather than a skip
- [ ] T017 [US1] Implement the harness in `tests/differential/harness.py`: given a statement and a
      list of adapters, execute through each, capture a `RawResult`, compare, and consult the ledger.
      It must work against the **current** executors via a thin shim, so no production code changes
      in this phase
- [ ] T018 [P] [US1] Write the corpus statements in `tests/differential/corpus/` — at least 20
      shapes per SC-001: catalog queries, boolean expressions, casts, `SELECT *`, aggregates, vector
      cosine and dot-product ordering, DDL, `INSERT ... RETURNING`, empty string and NULL as literals
      and as bound parameters, and a zero-row variant of every shape that can have one
- [ ] T019 [P] [US1] Add the L2 `<->` refusal case to the corpus, asserting `NOT IMPLEMENTED` from
      both adapters — it currently only holds on one
- [ ] T020 [US1] Run the corpus against both current executors, and enter every divergence it finds
      in `ledger.yaml` (FR-014, SC-002) under exactly one of FR-015's **three** dispositions: `pin` with its measurement,
      `fix` with an owner, or `no_reference_answer` with the named IRIS construct. This task's output is
      a populated ledger and a list of newly discovered defects
- [ ] T021 [US1] Apply the `backend_sensitive` marker to the files named in the call-site divergence
      table in `research.md` §R4, each with a one-line reason, and make the marker run those files
      against every adapter. **The population comes from the table, not from T009** — T009's
      two-adapter suite diff is blocked upstream (`iris-devtester` fixture loader) and sits in Phase 9,
      so this Phase 3 task must not depend on it. When T009 eventually runs it corroborates this list
      or adds to it; it is not a prerequisite
- [ ] T022 [US1] Delete the `inspect.getsource` assertion in
      `tests/unit/test_column_type_resolution.py:157 TestBothExecutorsUseIt` and replace it with a
      corpus case that executes the same statement through both adapters and compares the resolved
      type (FR-003)
- [ ] T083 [US1] Add a Describe-versus-Execute corpus case (FR-007): for each adapter, Describe the
      statement, then Execute it, and assert the declared PostgreSQL type is identical — then assert it
      across adapters. R2 makes this sharper than it looks: `describe_without_execute` is true on
      **embedded only**, so the two adapters reach the declared type by different routes, and this is
      the exact shape of the T011h defect (a manufactured `description` on a route that has none). The
      zero-rows-versus-many half of FR-007 is already covered; the Describe half is not
- [ ] T023 [US1] Add the corpus to `docs/RELEASE_CHECKLIST.md` §2 as its own gate, with the
      own-process rule and a `--timeout`

**Phase 3 gate (US1)**: `pytest tests/differential -q` passes against unmodified `src/`, with zero
unclassified divergences, and the newly discovered defects from T020 are recorded.

---

## Phase 4: User Story 2 — A statement is prepared once, the same way, for either adapter (P1)

**Goal**: one preparation sequence. The vector gap becomes structurally impossible.

**Independent test**: remove the vector rewrite from the single path; the corpus fails for **both**
adapters. Restore it; both pass.

- [ ] T024 [US2] Write `tests/unit/test_preparation_sequence.py`: the ordered sequence applies all
      **six** rewrites currently inline in `IRISExecutor.execute_query` (`:1230-1266`) and all **seven**
      steps currently applied only inside `_prepare_sql` (`:848-948`), in a defined order, with no
      adapter argument. Counts are `research.md` §R4's measurement, which supersedes the earlier
      estimate of 10 and 8; the two sets are disjoint, so thirteen steps must be present
- [ ] T025 [US2] Write `tests/unit/test_preparation_vector.py`: `ORDER BY embedding <=> $1 LIMIT $2`
      emits SQL and a parameter list that agree, with parameters renumbered — the measured defect
      today is SQL still saying `LIMIT $2` with parameters `[5]`
- [ ] T026 [US2] Write `tests/unit/test_preparation_ordering.py`: the four `has_X`/`rewrite_X` pairs
      apply in the one correct order, and a caller cannot invoke a rewriter without its predicate
- [ ] T027 [US2] Implement `src/iris_pgwire/core/preparation.py`, assembled from the existing
      `sql_translator/` functions plus `vector_optimizer`, `schema_mapper` and
      `inline_limit_offset_params` — the three that currently reach only the embedded path (FR-001,
      SC-003: three preparation implementations become one)
- [ ] T028 [US2] Fix the parameter-renumbering defect in `vector_optimizer.optimize_vector_query`
      (`vector_optimizer.py:809`) so the returned SQL and parameters agree
- [ ] T029 [US2] Fold each `has_X` predicate into its `rewrite_X` so the pair presents one name, per
      candidate 6 of the architecture review, and update the exports in
      `sql_translator/__init__.py`
- [ ] T030 [US2] Make `SQLRefiner.refine` run exactly once per statement, keeping
      `tests/unit/test_order_by_alias_idempotence.py` green. Three parts, because T007 measured the
      _cost_ of the double call without settling _which_ call is redundant: 1. Read both call sites (`normalizer.py:258`, `pipeline.py:61`) and decide which one owns
      refinement — the other is removed. Record the reason in the commit, since `refine` is
      idempotent and therefore silent about which caller is superfluous. 2. Add a unit test asserting exactly one invocation per statement, so the second call cannot
      return unnoticed. 3. Re-run `spikes/probe_r4_preparation_cost.py` and put the before and after numbers in
      `research.md` §R4 — Constitution Principle V requires a measurement with a performance change.
      Measured before: **12.2% of the 5 ms budget** on a 30-column select (0.3047 → 0.6095 ms), 5.5x
      the entire six-rewrite block and the largest single item in preparation
- [ ] T031 [US2] Route the unified preparation path from behind the new selector value, leaving both
      existing executors untouched and still selectable (FR-022)
- [ ] T032 [US2] Extend the corpus to run each statement through old-embedded, old-DBAPI and the new
      path, asserting new-versus-old and new-versus-PostgreSQL, with PostgreSQL winning any conflict
      and the old behaviour entered as a ledger `fix` (FR-016)
- [ ] T033 [US2] Re-measure the per-statement preparation cost against T007's before number and the
      5 ms budget (FR-027)

**Phase 4 gate (US2)**: the corpus passes for every adapter through the new path; deleting the vector
rewrite fails both adapters; `pytest tests/e2e -q --timeout=90` shows the 22 translation failures
reduced, with the remaining count named (**SC-005**). Re-run T085's baseline command here.

---

## Phase 5: User Story 3 — A result means the same thing whichever adapter produced it (P1)

**Goal**: 045's scope, with the instrument from US1 already in place.

**Independent test**: `specs/044-catalog-as-views/spikes/probe_statement_describe.py` PASSes on both
adapters; the corpus asserts type equality at zero rows and at many.

- [ ] T034 [US3] Write `tests/unit/test_materialisation_precedence.py`: metadata is sourced as
      statement text, then driver report, then row values, and never row values above an available
      source (FR-008)
- [ ] T035 [US3] Write `tests/unit/test_dbapi_type_codes.py`: ODBC codes `12`, `-7` and `4` map to
      **distinct** PostgreSQL OIDs. Measured today: all three collapse to `1043` because
      `_map_dbapi_type_to_oid` (`dbapi_executor.py:1241`) string-matches a numeric code
- [ ] T036 [US3] Write `tests/unit/test_materialisation_no_types.py`: when
      `RawResult.driver_types is None`, the declared type comes from the statement text or the
      defined fallback, never from a row value (FR-010)
- [ ] T037 [US3] Write `tests/integration/test_empty_string_vs_null.py`: 4 cases — literal and bound,
      each of empty string and NULL — on both adapters, compared against the PostgreSQL reference
      fixtures (FR-017, SC-007)
- [ ] T038 [US3] Implement `src/iris_pgwire/core/materialisation.py` as the single implementation,
      absorbing `_materialize_embedded_result` (`iris_executor.py:2366`),
      `_materialize_external_result` (`:2959`) and `_fetch_standard_results`
      (`dbapi_executor.py:605`) (FR-001, SC-004)
- [ ] T082 [US3] Write `tests/unit/test_core_paths_standalone.py`: import and drive both
      `core/preparation.py` and `core/materialisation.py` with **no adapter instantiated and no
      connection opened** — preparation from a statement string, materialisation from a hand-built
      `RawResult` — and assert the modules import without `iris` present (FR-002). This is the cheapest
      proof that the seam is real rather than nominal: if either path needs an executor to run, the
      consolidation moved the fork instead of removing it
- [ ] T039 [US3] Correct `_map_dbapi_type_to_oid` to use the driver's numeric codes (FR-009), and
      delete the value-based refinement it forced
- [ ] T040 [US3] Fix empty-string versus NULL on the embedded path, replacing or documenting
      `_normalize_iris_null`'s treatment of `'\x00'` and `''`
- [ ] T041 [US3] Collapse the two error modes into one (FR-006) and delete the dead error branch at
      `protocol.py:3560` if it is unreachable once the modes agree
- [ ] T042 [US3] Re-run 044's probes — `probe_statement_describe.py`, `verify_sqlstate_e2e.py`,
      `probe_embedded_error_wording.py`, `verify_any_e2e.py` — on both adapters and record the scores
      (FR-025, SC-006)
- [ ] T043 [US3] Assert SC-010 progress: report the line count of the statement path before and
      after, confirming it decreases rather than growing an abstraction over retained copies

**Phase 5 gate (US3)**: corpus type equality holds at zero rows and at many for every statement;
`probe_statement_describe.py` PASSes on both adapters; SQLSTATE stays 9/9 wire and 13/13 embedded.

---

## Phase 6: User Story 4 — An impossible configuration is refused at startup (P2)

**Independent test**: each impossible configuration fails at startup naming the capability; each
possible one still starts.

- [ ] T044 [US4] Write `tests/unit/test_capabilities.py`: every adapter declares **all eight** FR-011
      fields as data — `per_session_transactions`, `cross_session_dirty_reads`,
      `max_concurrent_sessions`, `isolation_levels_accepted`, `isolation_levels_in_force`,
      `reports_column_types`, `describe_without_execute`, `available_under_irispython` — and the core
      reads them without `hasattr` or `getattr(..., None)` (FR-011). Assert `_accepted` and `_in_force`
      are separate fields; collapsing them is the mistake that produced a retracted isolation model
      once already
- [ ] T045 [US4] Write `tests/integration/test_startup_refusal.py`: concurrent client transactions on
      the embedded adapter refuse at startup; a pool size above the instance's licence units refuses
      at startup; an isolation level the adapter cannot put in force is refused rather than
      accepted-and-ignored (FR-012, SC-008)
- [ ] T046 [US4] Implement `Capabilities` declaration on both adapters. T008 measured the DBAPI side
      only; the embedded `isolation_levels_accepted` cell is measured by **T081**, which must land
      before this task can declare all eight fields as data rather than as a `None` placeholder. T081
      carries a Phase 9 number but is a **Phase 6 prerequisite** — run it here (see its own note)
- [ ] T047 [US4] Implement the startup check in `server.py`, refusing with a message that names the
      missing capability and the configuration that requires it
- [ ] T048 [US4] Fix the pool default: `server.py:76` and `server.py:349` both default to 10 against a
      **measured ceiling of 7** concurrent connections on CE — the 8th connect raises
      `OperationalError: ... Unable to allocate a license` (`research.md` §R5). Make exhaustion fail
      rather than retry roughly 2s apart forever (FR-013)
- [ ] T049 [US4] Re-run `pytest tests/contract/test_dbapi_executor_contract.py -q --timeout=45` and
      confirm it now fails or passes rather than hanging
- [ ] T050 [US4] Move the process-scoped-transaction limitation from prose in
      `KNOWN_LIMITATIONS.md:366-391` to a cited capability, leaving the prose pointing at the
      declaration
- [ ] T051 [US4] Delete the three `getattr(..., 'metadata_cache', None)` reads once the capability
      mechanism covers what they were probing for

**Phase 6 gate (US4)**: every configuration in US4's scenarios fails at startup with a naming
message, 0 reach a first statement, and the contract suite no longer hangs.

---

## Phase 7: User Story 5 — A statement enters the executor once (P2)

**Independent test**: a counter on the core's entry point increments exactly once for a catalog
query, a metadata lookup and an isolation change.

- [ ] T052 [US5] Write `tests/unit/test_no_reentry.py`: instrument the entry point and assert exactly
      one increment per statement for a catalog query, a metadata lookup and an isolation change
      (FR-019, SC-009)
- [ ] T053 [US5] Write `tests/unit/test_no_runtime_rebinding.py`: no method of the core is rebound at
      runtime; asserted by identity, not by grep (FR-020)
- [ ] T054 [US5] Write `tests/unit/test_no_private_reachthrough.py`: no module outside the core calls
      a private method of the core or an adapter (FR-021)
- [ ] T055 [US5] Make catalog routing a preparation outcome: a catalog statement resolves to
      `answered locally`, and the four callbacks at `catalog_router.py:949`, `:972`, `:1027`, `:1088`
      become explicit internal calls
- [ ] T056 [US5] Convert `sql_translator/metadata_cache.py:70` from an entry-point callback to an
      explicit internal call
- [ ] T057 [US5] Remove the `_skip_isolation` kwarg and the recursive calls at `_isolation.py:250`
      and `:406`, and rewrite the `IsolationMixin` docstring at `:76-78` so it states its own
      contract rather than its host's
- [ ] T058 [US5] Replace the IntegratedML monkey-patch — `integratedml.py:367-372
enhance_iris_executor_with_integratedml` — with a declared preparation step selected by
      configuration, and update the wiring at `server.py:134`
- [ ] T084 [US5] Before T058-T060 change any wiring, capture the current observable behaviour of
      `COPY`, bulk loading and IntegratedML — command tags, row counts, error wordings — and assert it
      unchanged afterwards (FR-026). Name the suites that serve as the gate in the task's commit. Three
      call paths are being rewired here, including one runtime monkey-patch; "remains a caller, not a
      part" is a claim that needs an assertion, not an inspection
- [ ] T059 [US5] Resolve `bulk_executor.py:358`'s call to `_execute_external_async` so bulk loading
      goes through the core's interface
- [ ] T060 [US5] Resolve the five calls to `self.executor._execute_iris_query(...)` in
      `catalog/catalog_functions.py:261`, `:376`, `:420`, `:476`, `:489` — a method defined on
      neither executor, failing silently inside `try:` blocks — and remove the swallowing
- [ ] T061 [US5] Delete `sql_translator/pipeline.py`'s `SQLPipeline` and the four tests that patch
      `iris_pgwire.dbapi_executor.SQLPipeline`, since its construction is unused and mocking it is
      what hid that
- [ ] T062 [US5] Make the adapter interface runtime-enforced — `@runtime_checkable` or an `ABC` — and
      add a test that fails when an adapter does not satisfy it (FR-005)

**Phase 7 gate (US5)**: re-entries per statement 0; runtime rebinds in `src/` 0; external calls to
private methods 0; the full corpus and `tests/unit` still pass.

---

## Phase 8: User Story 6 — There is one executor (P3)

**Independent test**: `git grep -c 'class IRISExecutor\|class DBAPIExecutor' src/` returns 0, the
full suite passes, and the corpus passes against the unified core's adapters.

- [ ] T063 [US6] Write `tests/unit/test_no_legacy_executors.py` asserting that neither class exists
      in `src/`, that nothing imports either module, and that no transitional flag or environment
      variable remains (FR-023, SC-011) — FR-023 says the feature is not complete while either file or
      the flag exists, so this test is the definition of done, not a check on it
- [ ] T064 [US6] Move any remaining behaviour out of `iris_executor.py` and `dbapi_executor.py` into
      the core or an adapter, with the corpus green after each move
- [ ] T065 [US6] Delete `src/iris_pgwire/iris_executor.py` and
      `src/iris_pgwire/dbapi_executor.py`
- [ ] T066 [US6] Remove the transitional selector value and the rollback environment variable from
      `backend_selector.py` and `server.py`, leaving `PGWIRE_BACKEND_TYPE` selecting between the two
      adapters only
- [ ] T067 [US6] Rewrite the `Executor` Protocol at `backend_selector.py:24-84` as the enforced
      adapter interface, or delete it if `core/types.py` now carries it
- [ ] T068 [US6] Update `docs/DBAPI_BACKEND.md`, `docs/ARCHITECTURE.md` and `KNOWN_LIMITATIONS.md` to
      describe one core with two adapters (linting is T074's job for every `.md` this feature touches,
      including these three)

**Phase 8 gate (US6)**: 0 legacy executor classes, 0 transitional flags, full suite at or above the
FR-024 baseline, corpus green.

---

## Phase 9: Polish and cross-cutting

- [ ] T069 Update `specs/045-unified-iris-driver/spec.md` status to record that 051 delivered its
      requirements, listing which FRs were satisfied where
- [ ] T070 [P] Record the final line-count comparison for SC-010 and the final cost measurement for
      SC-012 in `research.md`
- [ ] T071 [P] Add the nightly per-adapter container job — the FR-003 backstop that the
      container-free pre-merge CI cannot host
- [ ] T072 [P] Review every ledger `fix` entry: each is either closed by this feature or has an owner
      and a reason it outlived it
- [ ] T073 Update `CHANGELOG.md` under `[Unreleased]`, classifying the breaking changes, and bump
      `src/iris_pgwire/__init__.py` for 1.9.0
- [ ] T074 Run `markdownlint-cli2 --fix` and `prettier --write` on every `.md` this feature touched

### Added by Phase 0 measurement

These did not exist before the probes ran. T075-T077 unblock T009; T079-T081 are findings that would
otherwise be lost. (The double-`refine` finding lives in **T030**, where the task already existed —
adding a second one here was the duplication `/speckit.analyze` caught.)

- [ ] T075 Pin the test dependency set so `tests/e2e` and `tests/protocol` are runnable from a clean
      checkout. Measured gap: the project venv has no `pytest`, `pytest-asyncio`, `pytest-timeout`,
      `psycopg`, `sqlalchemy`, `docker`, `sqlparse`, `testcontainers` or `testcontainers-iris`, and
      `uv run pytest` fails at resolution. Add them to the `dev` extra and assert the import in a
      collection-time check, so a missing test dependency reports itself rather than surfacing as a
      fixture error. Add these to the **`dev` extra only** and assert in the same check that the runtime
      dependency set is unchanged (FR-028) — a test dependency is not a runtime dependency, and the
      assertion is what keeps that true. Pin the install layout while here, so the two overlapping
      `intersystems_irispython` dist-infos R1 measured cannot drift further (FR-029 as scoped)
- [ ] T076 Draft an upstream defect report for `iris-devtester`
      `iris_devtester/fixtures/loader.py`: `_verify_load` feeds `None` to a regex after the tables
      compile successfully, and `:311-312` catches every exception and re-raises it as
      "Table verification failed", so a `TypeError` in the dependency is reported as a data problem in
      the consumer. Include the measured evidence that the same root cause surfaces a second time as
      `DBAPI verification failed after password remediation`. **Draft only — filing is Tom's call**,
      and the file lives in another repository
- [ ] T077 Remove or define the `iris-pgwire-test` container name. Five wire tests skip with
      `Container 'iris-pgwire-test' not found`; no compose file in this repository defines it, and the
      project's container is `iris-pgwire-db`. A skip guard standing in for a container that cannot
      exist is not portability
- [ ] T079 [P] Stop `optimize_vector_query` logging at INFO on every call, including statements it
      does not modify. Two records and a metrics dict per invocation on the hot path; it swamped the
      R4 measurement run and had to be silenced to take the numbers
- [ ] T080 [P] Measure the normalizer's own cost and add it to `research.md` §R4. It is the one
      preparation step still without a number: the R4 probe referenced `SQLNormalizer`, but the class
      is `SQLTranslator` (`sql_translator/normalizer.py:44`), so that benchmark did not run
- [ ] T081 [P] Measure `isolation_levels_accepted` on the embedded adapter — the one empty cell in
      FR-011's table. Run the same `SET TRANSACTION ISOLATION LEVEL` sweep as
      `spikes/probe_r5_dbapi_sessions.py` in-container under `irispython`. **Run this before T046**
      (Phase 6), not in Phase 9 — T046 cannot declare the field as data without it, and a capability
      declared as a placeholder is the `getattr(..., None)` pattern FR-011 exists to remove. The number
      is small and the probe already exists; only the position in the list is wrong.
      `isolation_levels_in_force` stays empty on both adapters either way

### Added after 2.0.0 (agreed with Tom, 2026-11-13)

- [ ] T086 [P] Adopt the SQLCODE-to-SQLSTATE mappings that irispython-dx's `iris_dx/_sqlstate.py`
      measured against PostgreSQL 16 and pgwire lacks. Of its 26 codes pgwire agrees on 14; the other
      12 pgwire reports as `XX000` (-400, -384, -324, -201, -146, -124, -121, -111, -51, -20, -14,
      -12; for example -201 is `42P07`, -121/-124 are `23503`, -146 is `22007`). Write the tests first
      from that table, then extend `sql_translator/sqlstate.py`. Copy the measured values, not the
      module: no new runtime dependency (FR-028)
- [ ] T087 Spike: an embedded adapter on the iris_dx layer's DB-API connection instead of
      `iris.sql.exec`, measured on the differential corpus against both. Two modes, both measured:
      `same_job` (SQL in the server's own `$JOB`, transactions shared as today) and `server_job`
      (a second job per connection, which may give embedded per-session transactions and so change
      ADR-0001's capability table). Expected gains: column types from `description`, VECTOR values as
      text without the ODBC re-fetch, `-114` raised rather than an empty result. Settle first how the
      layer installs under `irispython` (a stock kit's built-in `iris` shadows the vendor wheel's
      `iris.irissdk`) and whether that satisfies FR-029; `same_job` reproduces a vendor-gated helper
      (DP-451138) and silently falls back to `server_job`, which an adapter must refuse rather than
      accept. Whether pgwire depends on the layer, vendors it, or neither is Tom's decision; this
      task produces the measurements for it

### Added by track 4 (agreed with Tom, 2026-11-14)

- [ ] T088 Guard the embedded adapter against concurrent transactions. Every wire session on it
      shares one IRIS process and therefore one transaction, so one client's `COMMIT` commits
      another's work (`KNOWN_LIMITATIONS.md`, "Sessions Share One Transaction"). While one session
      has a transaction open, refuse `BEGIN` (and the first statement of an implicit transaction)
      from any other session with a clear error, rather than letting the two merge. Test first: two
      psycopg sessions on the embedded backend; assert the second `BEGIN` is refused and that A's
      `ROLLBACK` afterwards leaves the table empty. T087's `server_job` mode would retire this guard
      if it gives per-session transactions. Spec 052 (PostgreSQL transaction semantics) targets
      DBAPI only and relies on this task for embedded

---

## Dependencies

```text
Phase 1 (Setup)
   └── Phase 2 (Foundational: R1-R6 + seam types + ledger)
          └── Phase 3 — US1  (the oracle; gates everything after it)
                 ├── Phase 4 — US2  (preparation)
                 │      └── Phase 5 — US3  (materialisation; needs one prepare path first)
                 ├── Phase 6 — US4  (capabilities; independent of US2/US3)
                 └── Phase 7 — US5  (one entry point; needs US2 and US3 landed)
                        └── Phase 8 — US6  (deletion; needs all of the above)
                               └── Phase 9 (Polish)
```

US4 is independent of US2 and US3 and may run in parallel with them. US6 depends on every other
story. Nothing may start before Phase 3's gate passes — the corpus is what makes the later phases
verifiable rather than plausible.

## Parallel opportunities

- **Phase 2**: T005, T006, T008 each need the container in its own process, so serialise them; T010
  needs only PostgreSQL and runs alongside any of them. _(All four are done; recorded because the
  serialisation is a licence constraint — R5 measured a ceiling of 7 concurrent connections — and the
  same constraint applies to any later phase that opens sessions.)_
- **Phase 9**: T079 and T080 are parallel with each other and with T070-T072. T075 blocks T009 and
  should land early if the wire suite is needed before Phase 9. **T081 is not a Phase 9 task in
  practice** — T046 depends on it, so run it before Phase 6.
- **Phase 3**: T018, T019 and T083 (corpus authoring) are parallel with each other and with T021.
- **Phase 5**: T034, T035, T036 and T082 are parallel — four separate test files, no shared fixture.
- **Phase 1**: T002, T003, T004 and T085 are parallel; T085 only needs a working `pytest`.

## MVP scope

**US1 alone.** A populated divergence ledger and a running corpus is a deliverable in its own right:
it converts "the backends might differ" into an enumerated list, and it is the artefact that would
have caught the vector defect, T011h and T027. Everything after it is a refactor that the corpus
keeps honest.
