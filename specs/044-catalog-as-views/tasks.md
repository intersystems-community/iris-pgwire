# Tasks: Catalog Emulation as IRIS Views

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)
**Constitution**: Test-First is non-negotiable — the test for a task lands before its implementation.
**Spec-kit commands**: prefix with `SPECIFY_FEATURE=044-catalog-as-views` — the scripts resolve the
feature from a `NNN-` branch prefix and work happens on `claude/iris-pglite-replicache-3ysrqe`.

Legend: `[P]` = parallelisable · `[X]` = done

---

## Phase 1 — Foundation

- [X] **T001** `PG_OID` callable from SQL. *Superseded in flight*: planned as a `SqlProc` on a
  shipped `PGWire.Catalog.cls`, delivered as `CREATE OR REPLACE FUNCTION … LANGUAGE OBJECTSCRIPT`
  (`catalog/functions.py`) because nothing installed the class file — see plan.md Design §1.
  *Exit*: callable as `SELECT PGWire.PG_OID('sqluser:table:x')`, stable, distinct, ≥ 16384. ✅
- [X] **T002** Test: OID properties — stability, distinctness, range, and **parity with Python's
  `OIDGenerator`** for the same identity string.
- [X] **T003** `views/definitions.py` — view DDL registry, one entry per catalog table, each with
  its PostgreSQL column list. Start with `pg_namespace`.
- [X] **T004** `views/installer.py` — idempotent create/verify, loud failure on missing privilege
  (FR-009).
- [X] **T005** Test [P]: installer is idempotent; a second run is a no-op.
- [X] **T006** Router decline list: `CatalogRouter` declines tables served by views (FR-010/011).
- [X] **T007** Test [P]: decline list and handler map are disjoint — exactly one path per table.
- [X] **T008** Wire the installer into server startup on **both** backends.
- [X] **T009** E2E: `SELECT nspname FROM pg_catalog.pg_namespace` served by the view, both backends.

## Phase 2 — Unblock introspection

- [X] **T010** `pg_class` view over `INFORMATION_SCHEMA.TABLES` with OIDs and `relkind`.
- [X] **T011** Test: projection, alias, `WHERE` and JOIN all honoured against `pg_class` (SC-003).
- [X] **T011a** **`ANY($n)` membership.** Rewritten to IRIS's `%INLIST`, with the bound array
  encoded as a `$LIST`. Research and measurements: [research-t011a.md](research-t011a.md).
  Verified end-to-end through the wire protocol on **both** backends — 8/8 cases including the
  empty array, negation, a mixed array + scalar parameter list, and the Prisma join shape.
- [X] **T011b** **Boolean expressions in a projection.** `(a and b = 'x') AS flag` →
  `CAST(CASE WHEN a <> 0 AND b = 'x' THEN 1 ELSE 0 END AS BIT)`. Two rewrites, not one: a bare
  column cannot stand alone as a predicate operand either (SQLCODE -14), and Prisma's first operand
  is exactly that. `sql_translator/boolean_expr.py`, 44 unit tests, both backends.
- [X] **T011c** **`obj_description`.** Installed as `PGWire.OBJ_DESCRIPTION`, returning NULL — IRIS
  records no comment reachable from an OID, and PostgreSQL returns NULL for an uncommented object.
  Unqualified calls are pointed at the PGWire schema (`sql_translator/pg_functions.py`), which is
  the mechanism `format_type` will use for T013.
- [X] **T011d** **Boolean literals against catalog boolean columns.** `relispartition = 'f'` → `= 0`.
  **A correctness fix, not merely crash-avoidance** — which matters, because CHK046 later decided
  that passing an IRIS crash through is acceptable, and that decision does not retire this task.
  Measured straight against IRIS with pgwire out of the path:

  | untranslated | result | correct |
  |---|---|---|
  | `relispartition = 'f'` flat | **0 rows, silently** | 5 |
  | `relispartition = 'f'` nested | SQLCODE -400 fatal | 5 |
  | `relispartition = 0` either way | 5 rows | 5 |

  So the flat form is a wrong answer of exactly the kind FR-008b forbids, and the crash is a second,
  separate symptom. The IRIS crash itself remains worth reporting upstream.
- [X] **T011e** **ORDER BY alias expansion was not idempotent.** The refiner replaced a select-list
  alias with its expression using a `\b` pattern, once per alias. The extended protocol translates
  at Parse, Describe *and* Execute, so Prisma's `namespace.nspname AS namespace ... ORDER BY
  namespace` became `ORDER BY NAMESPACE.NSPNAME.NSPNAME.NSPNAME`. Now a single pass that skips any
  occurrence already part of a qualified reference.
- [X] **T011f** **Binary array parameters were rendered, not decoded.** `_decode_array_binary_parameter`
  built a pgvector literal for *every* element type, so a `text[]` bound in binary format — which is
  what Prisma sends — arrived as the string `"[public]"` and was encoded as a one-element set
  containing that text. `= ANY($1)` matched nothing, silently. Now returns a list for every element
  type except float4/float8, where the vector path needs the literal.
- [X] **T011g** **Catalog columns reported at the wrong PostgreSQL type.** `is_partition` went out
  as int4 while the client had asked for binary results and reads it as `bool` — four bytes where it
  expects one — so Prisma read all five tables and exited without writing a schema, printing
  nothing. Three parts:
  * `_detect_cast_type_oid` only matched `CAST(? AS BIT)`, a cast of a *parameter*. Generalised to a
    cast of any expression, verifying the enclosing call really is a `CAST` by walking back to the
    matching paren rather than trusting the shape.
  * A plain catalog column has no cast to read, and the embedded backend infers a type from the
    *value* — which is a Python `int` even for a `CAST(… AS BIT)` column (measured). And clients
    rename these (`tbl.relrowsecurity as has_row_level_security`), so the output name is no help.
    Added `CATALOG_COLUMN_TYPE_OIDS` and resolve the alias back to the expression behind it.
  * `_masked` blanked quoted identifiers to *whitespace*, so `"col" AS x` began with spaces and the
    alias separator matched at position 0, returning an empty expression. Masks to a filler now, so
    positions survive.
- [X] **T011h** **The declared column type depends on whether the query happened to return rows.**
  Found while starting T015: `prisma db pull` does not reach a constraints query at all, so the
  `xid` failure recorded under T015 is not the current blocker. Prisma now fails on the *tables*
  query:

  ```
  called `Result::unwrap()` on an `Err` value: "Getting is_partition from ResultRow
  { types: [Text, …], values: [Text(Some("\0")), …] } as bool failed"
  ```

  Measured with a raw wire client that sends Prisma's exact message order
  (`spikes/probe_statement_describe.py` — psycopg3 cannot reproduce it, because it describes the
  *portal* after Bind and so takes the other route): the statement Describe declares **1043 for all
  seven columns**, while the DataRow carries a 1-byte bool for `is_partition` and a 4-byte int for
  `has_row_level_security`. A client that reads the Describe cannot decode the row it is then sent.

  Root cause, and it is worth stating plainly: **T011g fixed one of two executors.** The `dbapi`
  backend does not use `IRISExecutor` — `backend_selector` builds a separate `DBAPIExecutor`, which
  has its own metadata code. There, `_fetch_standard_results` takes every type from
  `cursor.description` (IRIS DBAPI reports type_code 4, hence 1043 for everything) and then
  *refines* the 1043s **from the first row's Python value** — `if rows`. Describe runs the statement
  with dummy parameters, which match nothing, so there is no first row and no refinement:

  * Execute (7 rows) → `is_partition` 16, `has_row_level_security` 23
  * Describe (0 rows) → both 1043

  So the declared type is a function of the row count. That is not catalog-specific: any query whose
  Describe returns no rows is described wrongly on this backend. It gated T015's own verification,
  since nothing downstream of the tables query was reachable.

  **Fixed** in `sql_translator/column_types.py`: each select-list item is resolved from the statement
  text — explicit cast, then known catalog column, then boolean expression — and `None` ("no opinion")
  otherwise, leaving whatever IRIS reported in place. It lives outside both executors because the
  defect was precisely that the logic existed in only one of them; both call it, and a test asserts
  both still do. Value-based refinement stays as the last resort. 29 unit tests; the raw-wire probe
  goes from 7 mismatches to PASS, with `has_row_level_security` now encoded as one byte to match its
  bool declaration.
- [ ] **T012** `pg_attribute` view over `INFORMATION_SCHEMA.COLUMNS`.
- [ ] **T013** Test: column types and ordinal positions match what clients expect.
- [ ] **T014** E2E: `prisma db pull` generates models with columns (SC-001), both backends.

## Phase 3 — Relations

- [X] **T015** `pg_constraint` view (primary and foreign keys). Requirements written first, closing
  CHK002 for this table: **FR-016…FR-021**, drawn from the query Prisma actually sends rather than
  from the whole PostgreSQL catalog.

  All 26 PostgreSQL 15 columns, in attnum order, over `TABLE_CONSTRAINTS` joined to
  `REFERENTIAL_CONSTRAINTS`, with correlated `LIST()` subqueries for `conkey`/`confkey` (IRIS has no
  `LIST_AGG`). `PGWire.PG_GET_CONSTRAINTDEF` installed alongside, because an unknown function fails
  the statement at *prepare* time whatever the result set would be. 27 unit tests, **15 integration
  tests against real IRIS**.

  Three things the work turned up, none of them the recorded diagnosis on its own:

  1. **`conkey` cannot come from `KEY_COLUMN_USAGE.ORDINAL_POSITION`.** That is the column's position
     *within the constraint* — 1 for every single-column key. It has to be the table-relative position
     `pg_attribute.attnum` reports, so it comes from `INFORMATION_SCHEMA.COLUMNS`. Measured: the
     foreign key on `T015Child.parent_id`, the table's second column, yields `{2}`; the naive version
     reported a plausible-looking `{1}`.
  2. **A `pg_*` *function* name counted as a targeted catalog table.** `extract_catalog_tables`
     matched any word with a `pg_` prefix, so `pg_get_constraintdef(constr.oid)` made the targeted set
     larger than the view-backed set, the decline never fired, and the pg_class handler answered
     regardless. That, not the missing view, was the immediate cause of the `xid` failure — an earlier
     version of the routing test passed precisely because it omitted the function call. A name
     followed by `(` is now read as a call.
  3. **`schema_mapper.VIEW_BACKED_TABLES` is a second list** that must also name the table, or a bare
     `pg_constraint` is never qualified to `pg_catalog` and IRIS answers `-30 Table or view not found`
     (reported as `42P01` thanks to T027, which Prisma surfaced as P1014).

  The superseded handler tests are rewritten to assert the decline, following the pattern established
  when pg_class became a view — including one that hands the router an executor that raises, since a
  fallback answering with an empty result would tell a client the schema has no constraints at all.

  **Verified end to end**: `prisma db pull` answers the constraints query with its own 7 columns and
  moves on. The `xid` error is gone from that statement.
- [X] **T015a** **`pg_views`, and the routing invariant its absence exposed.** With T015 done,
  `prisma db pull` advanced to `SELECT views.viewname, views.definition … FROM pg_catalog.pg_views`
  and failed with the *same* `xid` message. The cause was structural rather than particular to any
  table: `handle_catalog_query` walked a priority list and called the first handler whose table
  appeared **anywhere** in the statement, so `pg_class` — named only in a JOIN — answered a question
  about `pg_views` with pg_class's own 32 columns. The same mechanism produced T015's failure, and
  would have produced the next one.

  Two parts:

  * **`pg_views`** over `INFORMATION_SCHEMA.VIEWS`, four columns measured against
    postgres:15-alpine (`schemaname`, `viewname`, `viewowner`, `definition`). `schemaname` comes from
    `PGWire.PG_PUBLIC_SCHEMA()` for the same reason pg_namespace's does. The `TABLE_SCHEMA` filter is
    load-bearing: the instance genuinely contains `pg_catalog.pg_class` and friends, and without it an
    ORM would generate models for pgwire's own emulation — asserted directly.
  * **`primary_catalog_relation()`** — the catalog table a statement is *about*, its `FROM` relation,
    as distinct from `get_target_catalog()`'s highest-priority table mentioned anywhere. A handler may
    only answer for the primary relation, so a JOIN partner can never substitute its column set.

  **Scoped deliberately.** The invariant fires only on the *substitution* case: the primary relation
  has no handler and some other table in the statement does. A statement whose only catalog table is
  unhandled (`SELECT * FROM pg_roles`) still receives the fabricated empty result — that is FR-008c's
  defect, already located, and removing it is **T020**'s own verification pass rather than something
  to smuggle in under this scope. The first draft of the fix removed it as a side effect and broke
  `test_fallback_empty_response_for_unrecognized_pg_table`; narrowing it was the right call, and a
  test now records the boundary so it reads as a decision.

  14 unit tests, 7 integration tests against real IRIS (all made against a view the test creates, so
  an always-empty view could not pass, plus a guard that empty means "none" not "broken").

  **Verified end to end**: `prisma db pull` goes from 6 statements to **12** — the whole introspection
  sequence: views, enums, base types, columns, foreign keys, indexes, procedures.
- [ ] **T015b** **The columns query is the next blocker** (this is T012/T013's ground, now reached).
  Prisma's statement 8 is the one that matters and it needs four things we do not have:
  `pg_attribute` as a view, `format_type(atttypid, atttypmod)`, `pg_get_expr(adbin, adrelid)` for
  column defaults, and `col_description(attrelid, ordinal_position)`. Introspection ends in **P1014
  "The underlying table for model `(not available)` does not exist"** — Prisma has the tables but no
  columns for them.

  Also newly reached, and each legitimately unserved: `pg_enum`/`pg_type` (statements 6–7),
  `pg_index` with `unnest`/`generate_subscripts` over `indkey` (statement 10 — note it needs real
  array columns, not the NULLs the views currently carry), and `pg_proc` with
  `pg_get_functiondef` (statement 11). `pg_proc` currently reaches IRIS and is reported as `42P01`,
  which is the honest answer the routing invariant now guarantees.
- [ ] **T016** `pg_index` view.
- [ ] **T017** E2E: generated schema carries PKs and FK relations (SC-002).

## Phase 3.5 — Coverage gaps found by `/speckit.analyze` (2026-08-17)

These are requirements the spec states and no task covered. Listed here rather than silently
inherited by "Phase 4".

- [ ] **T023** E2E: a table created *after* server start appears in introspection with no restart
  (**SC-006**, User Story 3). The views read `INFORMATION_SCHEMA` at query time so this should hold
  by construction — which is exactly why it needs a test rather than an assumption.
- [ ] **T024** Regression guarantee (**SC-008**, **FR-013**, **FR-014**): ordinary SQL, DDL, DML and
  vector paths unchanged, and every defect in `docs/orm-introspection-findings.md` still fixed. One
  task, run before each phase exit.
- [ ] **T025** Edge cases from spec §Edge Cases with no coverage: schema and table names differing
  only by case; an IRIS object with no PostgreSQL equivalent (must be omitted or mapped, never
  surfaced as a broken row).
- [X] **T027** **SQLSTATE classification (FR-008e).** The precondition that makes the CHK046
  pass-through decision safe. Every failure used to reach the client as `42000`
  (`syntax_error_or_access_rule_violation`), so an IRIS fatal was indistinguishable from the client's
  own bad SQL, and a client's retry logic — which keys on the SQLSTATE class — concluded "fix your
  query" when the database broke. Measured against PostgreSQL 15: syntax `42601`, undefined column
  `42703`, undefined table `42P01`, undefined function `42883`; internal failure `XX000`.

  `src/iris_pgwire/sql_translator/sqlstate.py` maps 11 measured IRIS SQLCODEs plus the backend's
  message wording; `tests/unit/test_sqlstate_classification.py` (53 tests) pins it.
  **9/9 over the wire** (`spikes/verify_sqlstate_e2e.py`) and **13/13 on the embedded backend**
  (`spikes/probe_embedded_error_wording.py`). Three findings changed the shape of the task:

  1. **The two hardcoded `42000` sites were not the ones that mattered.** IRIS errors on the query
     path arrive as *Python exceptions*, not as `result["error"]`, so they reached the generic
     handler and were reported as **`08000` connection_exception** — worse than `42000`, because a
     driver may discard the session over a plain typo. Five sites now classify, each keeping its own
     code as the fallback for a genuinely unrecognised failure.
  2. **The backends do not word errors alike.** DB-API delivers `[SQLCODE: <-30>:<Table or view not
     found>]`; the embedded backend raises `Table 'SQLUSER.X' not found` with **no SQLCODE at all**.
     A SQLCODE-only classifier measured 2/5 on embedded. Both wordings are matched for every family.
  3. **Two more SQLCODEs measured while verifying**: `-1` invalid SQL statement (`SELECT FROM WHERE`
     is `-1`, not `-4`) and `-149` error inside an installed SQL function → `XX000`, since IRIS does
     not surface the inner condition.

  Where IRIS gives no way to tell two conditions apart — an over-length string and an unparseable
  number are both "failed validation" — the shared class `22000` is used rather than guessing
  between PostgreSQL's `22001` and `22P02`.
- [X] **T026** **SC-009** — measure what the translation gates cost per statement.
  `tests/unit/test_translation_gate_budget.py`: 0.09 ms plain, 0.62 ms paren-heavy (12.4% of the
  5 ms Principle V budget), with a 25% ceiling enforced so it cannot drift.

## Phase 4 — Generality

- [ ] **T018** Remaining views: `pg_type`, `pg_attrdef`, `pg_enum`, `pg_extension`.
- [ ] **T019** E2E with a second ORM (SC-005).
- [ ] **T020** Error-not-empty audit against the rule CHK045 settled (**FR-008a/b/c**, SC-004).
  Two halves, and the second is the one that bites:
  1. an unanswerable catalog query errors and names what was missing (FR-008a);
  2. **no code path fabricates a zero-row catalog result** (FR-008c). **Already located**:
     `catalog/catalog_router.py:415-425`, the branch whose own log line calls it the
     "empty fallback". Any catalog query that `can_handle()` claims but no handler recognises gets
     `{"success": True, "rows": [], "columns": [], "command_tag": "SELECT 0"}`. It is the exact
     mechanism behind three of the original six defects, and `columns: []` makes it worse than
     empty — the client cannot even see a result shape.
     Removing it is a **behaviour change** for every unrecognised catalog query (empty → whatever
     IRIS says), so it needs its own verification pass rather than being slipped in: enumerate what
     currently reaches it, confirm each either has a view, has a handler, or should error.
  The oracle is `spikes/probe_pg_empty_vs_error.py`, which records what PostgreSQL 15 does for the
  same ten query shapes.
- [ ] **T021** Performance: 50-table introspection under 10 s (SC-007).
- [ ] **T022** Remove handlers whose tables are fully served by views. Includes deleting
  `catalog/catalog_functions.py` — Python implementations of `format_type`,
  `pg_get_constraintdef` and friends from feature 033 that **no longer have any caller**: they
  worked when a handler answered a whole query in Python, which stopped being true once catalog
  tables became views. Whatever is still needed must be reinstated as an installed SQL function
  (T013 needs `format_type`). Its name also collides confusingly with `catalog/functions.py`.

## Progress — 2026-08-16

Phase 1 complete and Phase 2 partially done, all verified against real IRIS 2026.2 on the embedded
backend. 52 unit tests pass.

Introspection now gets materially further than it did:

| Stage | Before 044 | Now |
|---|---|---|
| Schema probe | tried `CREATE SCHEMA "public"` | ✅ answered |
| Table enumeration | 0 rows | ✅ 4 tables |
| Projection honoured | 32 columns for a 2-column request | ✅ exactly what was asked |
| Aliased JOIN + filter | not answerable | ✅ correct rows |
| `nspname = ANY($1)` | never reached | ✅ `%INLIST PGWire.PG_ARRAY(?)`, both backends |
| Boolean value in a projection | never reached | ✅ `CAST(CASE WHEN … AS BIT)`, both backends |
| Table enumeration through a real client | hard error | ✅ Prisma receives all 5 tables |
| Statement Describe declares usable types | varchar for a bool, whatever the row count | ✅ resolved from the SQL, T011h |
| Constraints / relations | never reached | ✅ answered by `pg_catalog.pg_constraint`, T015 |
| `pg_get_constraintdef` | unknown function, statement failed at prepare | ✅ installed, renders PK/UNIQUE/FK |
| Views enumeration (`pg_views`) | answered with pg_class's columns | ✅ `pg_catalog.pg_views`, T015a |
| A handler answering for a table the query is not about | happened, silently | ✅ only the `FROM` relation's handler may answer |
| Introspection statements Prisma completes | 4 of 12 | **12 of 12 issued**, 8 answered |
| Column enumeration | never reached | ❌ **T015b — current blocker** (`format_type`, `pg_attribute`) |

Three defects were found and fixed *while building this*, each caught by running against a real
instance rather than by reasoning:

1. **The installer's own DDL was intercepted.** `CREATE VIEW pg_catalog.pg_class AS …` contains
   "pg_class", so the router handed it to the pg_class handler, which answered with a synthetic
   success. Installation reported success while creating nothing. Fixed by suppressing routing
   during installation.
2. **A literal `'public'` in view DDL was rewritten** to the IRIS schema name, so the view reported
   `SQLUser` — the exact value the mapping exists to hide. Fixed with a `PG_PUBLIC_SCHEMA()`
   SqlProc so no literal appears in DDL.
3. **`WHERE nspname = 'public'` matched nothing.** `schema_mapper` deliberately rewrites the string
   literal `'public'` to the IRIS schema on restore — correct when comparing against IRIS's own
   catalog, wrong against the emulated views where `public` is the stored value. Prisma filters on
   this throughout, so it silently emptied every result. Scoped the rewrite to non-catalog queries.
4. **…and the scoping missed the spelling clients actually use.** The guard added for defect 3
   excluded any table name preceded by a dot, so `pg_catalog.pg_namespace` did not count as a
   catalog view and the literal was still rewritten. Defect 3 was therefore only half fixed; the
   qualified form kept returning nothing. Found by the T011a end-to-end run, not by review — the
   unit tests for defect 3 all used the bare spelling.

## Notes

Task order follows what unblocks introspection, not the catalog's alphabetical order. Phases 1–2
are the minimum that makes `prisma db pull` produce a usable schema.

## Progress — 2026-08-17

T011a landed, then its implementation was replaced. The first version reproduced IRIS's `$LIST`
byte format in Python, inferred from `IRISList.getBuffer()` output. It passed every test, but the
format is undocumented and — as the skip list showed — the parity tests that were supposed to guard
it were skipping in the unit run. `PGWire.PG_ARRAY`, a `CREATE FUNCTION … LANGUAGE OBJECTSCRIPT`
that builds the list with `$LISTBUILD`, costs 4.6 µs per query and uses nothing private.

Three more defects surfaced while making that change, none of them from review:

5. **Nothing installed the ObjectScript the views depend on.** Loaded by hand during development,
   so it worked here and would have aborted startup anywhere else.
6. **pgwire translated its own DDL.** The pipeline uppercased ObjectScript function bodies,
   producing `%SYSTEM.ENCRYPTION` (class names are case-sensitive) and a parameter cased
   differently from its uses. Both installed cleanly and failed on every call. Fixed with a
   verbatim-SQL guard.
7. **That guard did nothing at first.** The embedded backend runs its executor through
   `loop.run_in_executor`, which does not carry ContextVars into the worker thread the way
   `asyncio.to_thread` does. Now wrapped in an explicit `contextvars.copy_context()`.
