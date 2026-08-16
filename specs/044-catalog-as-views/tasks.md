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
- [~] **T011a** **`ANY($n)` → `IN (…)` expansion.** *Partially done.*
  Implemented in `sql_translator/array_params.py`, unit-tested (5 tests), and wired into
  `execute_query` on **both** executors. Works for the simple-query path and for extended-protocol
  *Execute*.
  *Discovered when it still did not fix Prisma*: the failure is at **Prepare/Describe**, not
  Execute. `protocol.py:3071` describes the statement using `dummy_params` — the real array does
  not exist yet — and IRIS cannot prepare `= ANY(?)` at all, so it errors before any value is
  bound. Note the router never had this problem because it answered such queries without ever
  preparing them.
  **Remaining**: make the statement preparable at Describe time. Options — rewrite `= ANY(?)` to a
  single-element `IN (?)` for preparation and re-expand at Execute (parameter count changes), or
  synthesise the row description without asking IRIS to prepare. Needs a decision before coding.
  **This is the current blocker.**
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
| `nspname = ANY($1)` | never reached | ❌ **T011a — current blocker** |

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

## Notes

Task order follows what unblocks introspection, not the catalog's alphabetical order. Phases 1–2
are the minimum that makes `prisma db pull` produce a usable schema.
