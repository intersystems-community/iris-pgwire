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
**Scale/Scope**: 10 catalog tables today; `pg_class`, `pg_namespace`, `pg_attribute` unblock Prisma

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.0.0 before Phase 0 and after Phase 1.*

| # | Principle | Gate | Status |
|---|-----------|------|--------|
| I | Protocol Fidelity | Unsupported constructs must error, never degrade. **This feature exists to fix a Principle I violation**: catalog queries returned empty results instead of errors. FR-008 makes it explicit. | ✅ PASS — improves compliance |
| II | Test-First | Real IRIS, real clients, no mocks. `prisma db pull` is the oracle; unit tests cover pure logic. Tests are written before each view lands (Phase 2). | ✅ PASS |
| III | Phased Implementation | Spike ran before planning; all six unknowns cleared with recorded evidence. | ✅ PASS |
| IV | IRIS Integration | Views are server-side, so both backends inherit identical behaviour. FR-012 + a parity test. | ✅ PASS — strengthens parity |
| V | Production Readiness | Introspection is off the hot query path. SC-007 bounds it; the 5 ms budget is untouched. | ✅ PASS |
| VI | Vector Performance | Not touched. | N/A |

Technical Constraints: no change to import naming; container restart required after Python changes
(already the working practice); `public` → IRIS schema mapping is **reused**, not reimplemented
(FR-005).

**No violations. No Complexity Tracking entries required.**

## Project Structure

```text
specs/044-catalog-as-views/
├── spec.md
├── plan.md              # this file
├── tasks.md
└── checklists/requirements.md

src/iris_pgwire/catalog/
├── views/               # NEW
│   ├── __init__.py
│   ├── definitions.py   # view DDL, one entry per catalog table
│   └── installer.py     # create/verify/drop, idempotent
└── catalog_router.py    # gains a per-table decline list

src/iris_pgwire/objectscript/   # NEW
└── PGWire.Catalog.cls          # PG_OID SqlProc

tests/
├── unit/test_catalog_views.py          # DDL shape, decline list, OID properties
└── e2e/test_orm_introspection.py       # real IRIS + real ORM
```

## Design

### 1. OID function — `PGWire.Catalog.PG_OID`

An ObjectScript `SqlProc`, since `$SYSTEM.Encryption.SHA1Hash` is not SQL-callable inline
(`SQLCODE -12`). Spike-verified: stable, distinct, ≥ 16384, usable inside `CREATE VIEW`.

```objectscript
ClassMethod PgOid(identity As %String) As %Integer [ SqlName = PG_OID, SqlProc ]
```

Identity strings keep the existing Python convention — `namespace:type:name`, lowercased — so OIDs
match what `OIDGenerator` already produces for the same object. That keeps the two paths consistent
during migration.

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
