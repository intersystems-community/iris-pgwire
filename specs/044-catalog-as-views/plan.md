# Implementation Plan: Catalog Emulation as IRIS Views

**Branch**: `044-catalog-as-views` (on `claude/iris-pglite-replicache-3ysrqe`) | **Date**: 2026-08-16
**Spec**: [spec.md](spec.md) | **Evidence**: [`docs/orm-introspection-findings.md`](../../docs/orm-introspection-findings.md)

## Summary

Replace shape-matching `pg_catalog` handlers with **real IRIS views** in a schema named
`pg_catalog`, sourced from `INFORMATION_SCHEMA`, with OIDs from a `SqlProc`. IRIS then evaluates
introspection SQL itself, so projections, aliases, joins, `WHERE` and CTEs stop being features we
implement. Migration is table-by-table: add a view, make the router decline that table, verify.

Every risk was cleared by spike before planning — see spec Assumptions.

## Technical Context

**Language/Version**: Python 3.11 (host) / 3.12 (irispython); ObjectScript for the catalog classes
**Primary Dependencies**: none new — IRIS SQL, existing `schema_mapper`, existing `CatalogRouter`
**Storage**: IRIS views over `INFORMATION_SCHEMA` (read-only, no materialisation, no cache)
**Testing**: pytest against real IRIS 2026.2; `prisma db pull` as the end-to-end oracle
**Target Platform**: both backends — embedded (irispython) and DBAPI
**Performance Goals**: 50-table introspection < 10 s (SC-007); no change to the 5 ms query budget
**Constraints**: read-only; identifiers stable across restarts; no new runtime dependency
**Scale/Scope**: `pg_namespace` and `pg_class` are views today; `pg_attribute`, `pg_constraint` and
`pg_index` remain, then `pg_type`, `pg_attrdef`, `pg_enum`, `pg_extension`

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.0.0 before Phase 0 and after Phase 1.*

| # | Principle | Gate | Status |
|---|-----------|------|--------|
| I | Protocol Fidelity | Unsupported constructs must error, never degrade. **This feature exists to fix a Principle I violation**: catalog queries returned empty results instead of errors. FR-008 makes it explicit. | ✅ PASS — improves compliance |
| II | Test-First | Real IRIS, real clients, no mocks. `prisma db pull` is the oracle; unit tests cover pure logic; tests land before each view. **But the suite does not pass 100%**: two tests in `tests/unit/test_generated_columns.py` fail, and they are not this feature's. See Complexity Tracking C-1. | ⚠️ CONDITIONAL — deviation recorded |
| III | Phased Implementation | Spike ran before planning; all six unknowns cleared with recorded evidence. | ✅ PASS |
| IV | IRIS Integration | Views are server-side, so both backends inherit identical behaviour. FR-012 + a parity test. | ✅ PASS — strengthens parity |
| V | Production Readiness | Introspection is off the hot query path, but FR-015's translation gates run on **every** statement, so the budget is *not* untouched. Measured 2026-08-17: **0.09 ms** on a plain 30-column query, **0.62 ms (12.4% of 5 ms)** on a paren-heavy one, `has_boolean_projection` dominating. Pinned by `tests/unit/test_translation_gate_budget.py` and by SC-009. | ✅ PASS — measured, not assumed |
| VI | Vector Performance | Not touched. | N/A |

Technical Constraints: no change to import naming; container restart required after Python changes
(already the working practice); `public` → IRIS schema mapping is **reused**, not reimplemented
(FR-005).

### Complexity Tracking

| # | Deviation | Why it is accepted | Exit |
|---|---|---|---|
| C-1 | Principle II requires the suite to pass with no skipped or quarantined failures. Two tests fail: `test_generated_columns.py::test_generated_column_skip` and `::test_generated_column_multiple_skip`. | **Diagnosed, not shrugged at.** `IdentifierNormalizer` deliberately preserves lowercase column names in `CREATE TABLE` (there is an explicit "CRITICAL FIX" comment saying PostgreSQL clients expect lowercase), so these two tests assert pre-fix behaviour. But the preservation is *inconsistent*: a DDL containing a string literal (`DEFAULT 'val'`) takes a different code path and uppercases column names, which is the only reason `test_cast_removal.py` passes. Deciding the correct casing changes what every client sees for `CREATE TABLE` — that is a DDL decision, not a catalog one, and making it inside 044 would be scope creep with wide blast radius. | Logged in `docs/identifier-casing-inconsistency.md` for its own feature. 044 must not make these two tests worse, and must not "fix" them by changing DDL casing. |
| C-2 | `tests/integration/test_pg_array_against_iris.py` skips when IRIS is unreachable. | Principle II forbids skipping to make a build green. This skip is about *environment availability*, not about a failing assertion: when IRIS **is** reachable the suite fails rather than skips if a function is missing, which is the property that matters. | Revisit if CI ever runs without IRIS, where a silent skip would hide real breakage. |

**No unjustified violations.**

## Project Structure

```text
specs/044-catalog-as-views/
├── spec.md
├── plan.md              # this file
├── tasks.md
├── research-t011a.md    # the %INLIST decision, its revision, and the built-in alternatives
├── checklists/requirements.md   # requirement-quality gate (48 items)
└── spikes/              # probes; each finding in the docs traces to one

src/iris_pgwire/catalog/
├── views/                   # NEW
│   ├── definitions.py       # view DDL + BOOLEAN_CATALOG_COLUMNS + CATALOG_COLUMN_TYPE_OIDS
│   └── installer.py         # create/verify, idempotent
├── functions.py             # NEW — the four PGWire SQL functions
├── function_installer.py    # NEW — installs them before the views
├── _reentrancy.py           # NEW — guard extracted to break an import cycle
└── catalog_router.py        # gains a per-table decline list

src/iris_pgwire/sql_translator/   # FR-015 — constructs catalog SQL contains
├── array_params.py          # NEW — = ANY($n) -> %INLIST PGWire.PG_ARRAY($n)
├── pg_array.py              # NEW — encodes the array for PG_ARRAY
├── boolean_expr.py          # NEW — boolean projections, boolean literals, select-list splitting
├── pg_functions.py          # NEW — unqualified catalog function calls -> PGWire schema
├── verbatim.py              # NEW — do not translate SQL pgwire wrote itself
└── refiner.py               # ORDER BY alias expansion made idempotent

src/iris_pgwire/
├── protocol.py              # binary array parameters decoded to lists, not vector literals
└── iris_executor.py         # CAST/catalog column type detection; copy_context for the guard

tests/
├── unit/test_catalog_views.py, test_catalog_functions.py, test_pg_array.py,
│         test_boolean_expr.py, test_cast_type_detection.py, test_catalog_column_types.py,
│         test_order_by_alias_idempotence.py, test_translation_gate_budget.py
└── integration/test_pg_array_against_iris.py   # drives the installed function on real IRIS
```

There is no `tests/e2e/test_orm_introspection.py`; `prisma db pull` is driven manually against a
real instance, and the repeatable parts live in `spikes/verify_any_e2e.py`. **T014 owns turning that
into a committed E2E test.**

## Design

### 1. SQL functions in a `PGWire` schema

`$SYSTEM.Encryption.SHAHash` is not SQL-callable inline (`SQLCODE -12`), so the OID computation has
to live in a routine. **Revised 2026-08-17**: these are created with
`CREATE OR REPLACE FUNCTION … LANGUAGE OBJECTSCRIPT`, ordinary SQL DDL, rather than as `SqlProc`
methods on a shipped `.cls`.

The original plan said `PGWire.Catalog.cls` with a `SqlProc`. That class is deleted, because it had
to be loaded by hand with `$SYSTEM.OBJ.Load` and **nothing in the codebase did it** — the views
worked only on an instance someone had already prepared, and a fresh one would have aborted at
startup. `CREATE FUNCTION` needs only a connection, so the same installer runs on both backends,
where loading a class file needs the source on the *server's* filesystem.

Four functions (`catalog/functions.py`, installed by `catalog/function_installer.py`):

| Function | Purpose |
|---|---|
| `PGWire.PG_OID(identity)` | deterministic OID; byte-for-byte equal to Python's `OIDGenerator` |
| `PGWire.PG_PUBLIC_SCHEMA()` | the name `public`, never as a literal (the translator would rewrite it) |
| `PGWire.PG_ARRAY(encoded)` | builds the `$LIST` that `%INLIST` needs from one bound string (FR-015) |
| `PGWire.OBJ_DESCRIPTION(oid, catalog)` | always NULL; IRIS records no comment reachable from an OID |

Identity strings keep the existing Python convention — `namespace:type:name`, lowercased — so OIDs
match what `OIDGenerator` already produces for the same object. That keeps the two paths consistent
during migration, and a test asserts the equality.

Two constraints on writing ObjectScript inside SQL DDL, both learned the hard way: a bare `:` is read
as a host-variable marker (so `for i = 1:1:4` fails), and the DDL passes through pgwire's own
translation, which uppercases identifiers — fatal for case-sensitive class names. SQL pgwire authors
itself is therefore executed verbatim (`sql_translator/verbatim.py`).

### 2. Views in a `pg_catalog` schema

One view per catalog table, columns in PostgreSQL's order and names (FR-004). `public` is projected
from the configured IRIS schema via the existing mapping (FR-005). Contents come from
`INFORMATION_SCHEMA` at query time, so there is nothing to invalidate (FR-003, US3).

Order of work follows what unblocks introspection: `pg_namespace` → `pg_class` → `pg_attribute` →
`pg_constraint` → `pg_index` → the rest.

### 3. Router decline list

`CatalogRouter` gains a set of table names served by views. When a query targets only declined
tables, `handle_catalog_query` returns `None` and the SQL reaches IRIS (FR-010, FR-011). This is
the same mechanism as the existing unevaluable-expression guard, so it is a small extension rather
than new machinery.

### 4. Installation

Idempotent installer invoked at server startup: verify each view, create what is missing, fail
loudly if it cannot (FR-009). Not a migration script — the server converges its own catalog.

## Phases

**Phase 0 — Research**: ✅ complete. Spike cleared all six unknowns.

**Phase 1 — Foundation**: OID SqlProc + installer + decline mechanism, with `pg_namespace` as the
first view. Exit: `SELECT nspname FROM pg_catalog.pg_namespace` served by a view on both backends,
router declining it.

**Phase 2 — Unblock introspection**: `pg_class` and `pg_attribute`. Exit: `prisma db pull` generates
models with columns (SC-001).

**Phase 2b — Constructs (FR-015)**: added 2026-08-17, not foreseen. Once catalog SQL reaches IRIS,
the SQL itself has to be answerable. Seven constructs sat between a working view and a working
`prisma db pull`; each was found by running the client, not by review. T011a–T011g.

**Phase 3 — Relations**: `pg_constraint`, `pg_index`. Exit: primary and foreign keys appear (SC-002).

**Phase 4 — Generality**: remaining tables; second ORM (SC-005); performance (SC-007).

## Risks

| Risk | Mitigation |
|---|---|
| A view's column set does not match client expectations | Compare against real PostgreSQL `pg_catalog` column lists; the ORM is the oracle |
| Deployment lacks privileges to create the schema | FR-009 — fail loudly at startup |
| View performance on large schemas | SC-007 bounds it; `INFORMATION_SCHEMA` is already the source today |
| Partial migration leaves both paths serving one table | FR-011 + a test asserting the decline list and handler map are disjoint |
| OID drift between Python and SQL implementations | Same identity-string convention; a test asserts both produce the same value |
