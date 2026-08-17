# Tasks: Catalog Emulation as IRIS Views

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)
**Constitution**: Test-First is non-negotiable — the test for a task lands before its implementation.

Legend: `[P]` = parallelisable · `[X]` = done

---

## Phase 1 — Foundation

- [X] **T001** Write `PGWire.Catalog` ObjectScript class with `PG_OID` SqlProc.
  *Exit*: callable as `SELECT PGWire.PG_OID('sqluser:table:x')`, stable, distinct, ≥ 16384.
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
- [ ] **T011b** **Boolean expressions in a projection.** The next thing `prisma db pull` hits once
  T011a is out of the way. Prisma's table query projects a boolean *value*:
  `(tbl.relhassubclass and tbl.relkind = 'p') as is_partition`. IRIS allows `AND` only in a
  predicate, and answers `ERROR: ) expected, AND found`. Needs a translation to `CASE WHEN … THEN 1
  ELSE 0 END`, applied to boolean expressions appearing in a select list.
- [ ] **T012** `pg_attribute` view over `INFORMATION_SCHEMA.COLUMNS`.
- [ ] **T013** Test: column types and ordinal positions match what clients expect.
- [ ] **T014** E2E: `prisma db pull` generates models with columns (SC-001), both backends.

## Phase 3 — Relations

- [ ] **T015** `pg_constraint` view (primary and foreign keys).
- [ ] **T016** `pg_index` view.
- [ ] **T017** E2E: generated schema carries PKs and FK relations (SC-002).

## Phase 4 — Generality

- [ ] **T018** Remaining views: `pg_type`, `pg_attrdef`, `pg_enum`, `pg_extension`.
- [ ] **T019** E2E with a second ORM (SC-005).
- [ ] **T020** Error-not-empty audit: unsatisfiable catalog queries error (FR-008, SC-004).
- [ ] **T021** Performance: 50-table introspection under 10 s (SC-007).
- [ ] **T022** Remove handlers whose tables are fully served by views.

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
| Boolean value in a projection | never reached | ❌ **T011b — current blocker** |

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
