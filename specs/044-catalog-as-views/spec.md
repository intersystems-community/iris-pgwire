# Feature Specification: Catalog Emulation as IRIS Views

**Feature Branch**: `044-catalog-as-views` (developed on `claude/iris-pglite-replicache-3ysrqe`)
**Created**: 2026-08-16 · **Updated**: 2026-08-17
**Status**: In progress — Phases 1–2 implemented, Phase 3 next. No open clarifications.

**Running spec-kit commands on this feature**: the scripts resolve the feature from a `NNN-` branch
prefix, and development happens on `claude/iris-pglite-replicache-3ysrqe`, so every invocation needs
the override:

```bash
SPECIFY_FEATURE=044-catalog-as-views bash .specify/scripts/bash/check-prerequisites.sh --json
```
**Input**: Replace pattern-matched `pg_catalog` emulation with real IRIS views, so introspection SQL
is evaluated by the database instead of by handlers that match query shapes.

**Evidence**: [`docs/orm-introspection-findings.md`](../../docs/orm-introspection-findings.md) —
six defects found running real ORM introspection, five fixed, and a spike proving this approach.

---

## Why

Schema introspection currently fails. `prisma db pull` cannot enumerate a single table against
either backend, so every schema-driven tool — typed clients, generated forms, generated admin UIs,
BI connectors — is unreachable.

The cause is architectural, not a missing case. Catalog tables are emulated by handlers that
recognise **query shapes**. A handler that does not recognise a shape returns *zero rows*, not an
error. Three of the six defects found were caused by this, and all three failed silently:

- a handler required `FROM pg_namespace` and so missed `FROM pg_catalog.pg_namespace`
- a handler answered a boolean question with raw table rows
- a handler's own internal query was intercepted by the handler layer

A spike (recorded in the findings doc) confirmed IRIS can evaluate real introspection SQL —
including CTEs, aliases and joins — when the catalog is exposed as views. Prisma's exact
table-enumeration query returned correct results against views with no interception code in the
path.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Introspect an IRIS schema with a standard ORM (Priority: P1)

A developer points Prisma at IRIS through iris-pgwire and runs `db pull`. They get a schema file
describing their tables, columns, primary keys and foreign keys — the same as against PostgreSQL.

**Why this priority**: This is the whole feature. It is also the gate on everything downstream:
typed clients, Zod schemas, generated CRUD UIs and the sync work in `043` all derive from it.

**Independent Test**: Create tables with primary and foreign keys in IRIS, run `prisma db pull`
through iris-pgwire, and compare the generated schema against the tables that exist.

**Acceptance Scenarios**:

1. **Given** three IRIS tables with a foreign key chain, **When** a developer runs `prisma db pull`,
   **Then** the generated schema contains all three models with their columns.
2. **Given** the same tables, **When** introspection completes, **Then** primary keys and foreign
   key relations appear in the generated schema.
3. **Given** an empty schema, **When** introspection runs, **Then** it reports an empty database
   rather than failing. *(Consistent with FR-008b: the query is evaluable, so zero rows is the
   answer.)*
4. **Given** either backend (embedded or DBAPI), **When** the same introspection runs, **Then** the
   result is identical.

---

### User Story 2 — Catalog queries answer the question that was asked (Priority: P2)

Any client issuing a `pg_catalog` query gets a result matching its projection: the columns it
selected, under the aliases it chose, filtered by its `WHERE` clause.

**Why this priority**: This is the property that makes P1 hold for clients other than Prisma. It is
separately testable and is what stops the next ORM from failing the same way.

**Independent Test**: Issue projections, aliases, joins, `WHERE` filters and a CTE against catalog
tables and confirm each returns what was requested.

**Acceptance Scenarios**:

1. **Given** a query selecting two columns, **When** it runs, **Then** exactly those two columns are
   returned — not the full table.
2. **Given** a query using column aliases, **When** it runs, **Then** results carry the aliases.
3. **Given** a join between two catalog tables, **When** it runs, **Then** the join is applied.
4. **Given** a `WHERE` filter on a catalog column, **When** it runs, **Then** non-matching rows are
   excluded.
5. **Given** a query the system cannot satisfy, **When** it runs, **Then** it returns an error —
   **never** an empty result that reads as "no such objects".

---

### User Story 3 — Catalog reflects the live database (Priority: P3)

A developer creates a table and re-runs introspection. The new table appears without restarting the
server or clearing a cache.

**Why this priority**: Introspection is used during active development, when the schema is changing.
A stale catalog produces confusing results.

**Independent Test**: Introspect, create a table, introspect again, confirm the new table appears.

**Acceptance Scenarios**:

1. **Given** a completed introspection, **When** a table is created and introspection re-run,
   **Then** the new table appears.
2. **Given** a dropped table, **When** introspection re-runs, **Then** it is absent.

---

### Edge Cases

- **A catalog object exists in IRIS but has no PostgreSQL equivalent** — it must be omitted or
  mapped, never surfaced as a broken row.
- **Two objects hash to the same identifier.** Identifiers must be distinct across the objects a
  client can see.
- **Identifiers must be stable across restarts** — a client caching one must not find it pointing
  elsewhere later.
- **A client queries a catalog table that has no view yet**, during incremental migration.
- **Schema and table names differing only by case**, given IRIS and PostgreSQL differ here.
- **The deployment lacks privileges** to create the catalog objects — this must fail loudly at
  setup, not silently at query time.

---

## Requirements *(mandatory)*

### Functional Requirements

**Catalog surface**

- **FR-001**: The system MUST expose PostgreSQL system catalog tables as objects the database itself
  can query, so that projections, aliases, joins, `WHERE` predicates and CTEs are evaluated by the
  database rather than by request-matching code.
- **FR-002**: Catalog objects MUST be addressable both bare (`pg_class`) and schema-qualified
  (`pg_catalog.pg_class`).
- **FR-003**: Catalog contents MUST derive from the live IRIS schema, with no separate cache to
  invalidate.
- **FR-004**: Column names, order and types MUST match what PostgreSQL clients expect.
- **FR-005**: The PostgreSQL `public` schema MUST appear as an existing schema, consistent with the
  existing `public` ↔ IRIS-schema mapping.

**Object identifiers**

- **FR-006**: Every catalog object MUST have an identifier that is **stable** across restarts,
  **distinct** between objects, and inside the range PostgreSQL reserves for user objects.
- **FR-007**: Identifiers MUST be computable by the database, so they can be produced inside a
  catalog object's own definition.

**Behaviour under failure**

- **FR-008**: Whether a catalog query is answered with rows, with zero rows, or with an error MUST
  depend on whether the query can be **evaluated** — never on how many rows the answer contains.
  *(Resolved 2026-08-17, CHK045. The original wording — "a query that cannot be satisfied MUST
  return an error, MUST NOT return an empty result" — conflicted with User Story 1 scenario 3, which
  requires an empty schema to report as empty rather than failing. On the wire those are the same
  thing. Measured against real PostgreSQL 15 rather than argued: `spikes/probe_pg_empty_vs_error.py`,
  10 shapes, a clean 5/5 split.)*

  - **FR-008a**: A query naming a catalog table, column or function the system does not provide, or
    using a construct it cannot translate, MUST return an error that names what was missing.
    PostgreSQL does this for a missing relation, a missing column, a missing function, bad syntax and
    wrong arity alike.
  - **FR-008b**: A query that is fully evaluated and matches nothing MUST return zero rows. That is
    an **answer**, not a failure — PostgreSQL returns empty for a non-matching filter, an empty
    schema, a table with no constraints, and `= ANY('{}')`. `psql \dt` on an empty schema prints
    "Did not find any relations." and exits 0.
  - **FR-008c**: The system MUST NOT manufacture a zero-row catalog result. Zero rows may arise only
    from the database evaluating the query. *This is the enforceable form of the requirement, and the
    one the original defects violated: three separate handlers returned a synthetic empty success for
    a query shape they did not recognise. Emptiness was never the bug — fabricating it was.*

  Note the boundary is the query's shape, not whether the object exists: `\d no_such_table` returns
  **zero rows** in PostgreSQL, because the name is a literal in a `WHERE` clause rather than a
  relation reference. Measured.
- **FR-009**: Setup MUST fail loudly and early if the catalog objects cannot be created.

**Migration**

- **FR-010**: The new surface and the existing handlers MUST be able to coexist, one catalog table
  at a time, so migration is incremental and reversible.
- **FR-011**: Once a catalog table is served by the new surface, the old handler for it MUST NOT
  intercept — exactly one path answers any given table.
- **FR-012**: Behaviour MUST be identical on both backends (Constitution Principle IV).

**Constructs the catalog surface exposes**

- **FR-015**: PostgreSQL constructs that appear in real introspection SQL MUST be translated well
  enough for a catalog query to reach IRIS and be answered. This is a **consequence of FR-001**: once
  the database evaluates catalog SQL instead of a handler recognising its shape, every construct in
  that SQL becomes IRIS's problem rather than a pattern to match. Scope is bounded by evidence — a
  construct is in scope when a real client is observed to emit it against a catalog table.
  *(Added 2026-08-17. Seven such constructs were found by running `prisma db pull`: `= ANY($n)`,
  a boolean expression used as a projected value, a bare boolean operand, boolean literals compared
  against a boolean column, `obj_description()`, binary-format array parameters, and column type
  metadata for boolean and array columns. See tasks T011a–T011g.)*

**Compatibility**

- **FR-013**: Non-catalog behaviour MUST NOT change — ordinary SQL, DDL, DML and vector operations
  are unaffected.
- **FR-014**: Existing catalog-dependent features that pass today MUST continue to pass.

### Key Entities

- **Catalog Object**: a PostgreSQL system catalog table (`pg_class`, `pg_namespace`,
  `pg_attribute`, `pg_constraint`, `pg_index`, `pg_type`, `pg_attrdef`, …) exposed as queryable
  data.
- **Object Identifier**: the stable numeric identity of a catalog object, derived from its name and
  kind.
- **Schema Mapping**: the correspondence between PostgreSQL `public` and the configured IRIS schema.

---

## Success Criteria *(mandatory)*

- **SC-001**: `prisma db pull` generates a schema containing **100%** of the user tables present,
  with their columns, on **both** backends.
- **SC-002**: Primary keys and foreign key relations appear for **100%** of tables that have them.
- **SC-003**: A catalog query returns **exactly** the columns requested — zero cases of a projection
  being ignored.
- **SC-004**: **Zero** catalog queries return an empty result where an error is the correct answer,
  measured across the conformance suite.
- **SC-005**: At least **two independent ORMs** introspect successfully, demonstrating the result
  generalises beyond the client it was developed against.
- **SC-006**: A table created after server start appears in introspection **without a restart**.
- **SC-007**: Introspection of a 50-table schema completes in **under 10 seconds**.
- **SC-008**: The existing test suite passes unchanged, and every defect fixed in
  `docs/orm-introspection-findings.md` stays fixed.
- **SC-009**: The per-statement cost of deciding whether a catalog translation applies stays under
  25% of the Principle V 5 ms budget, measured (not asserted).

---

## Assumptions

- IRIS SQL can evaluate the constructs real introspection emits — CTEs, aliases, joins, `WHERE`
  predicates. **Verified by spike**, not assumed.
- A stable identifier can be computed by the database. **Verified by spike.**
- Catalog objects can live in a schema named `pg_catalog`. **Verified by spike.**
- Introspection is a development-time operation; correctness and generality matter more than
  microsecond latency.
- `regclass` casts and PostgreSQL-specific operators remain the translation layer's job and are out
  of scope here.

## Dependencies

- A running IRIS instance for all verification. No mock IRIS exists or will be introduced
  (Constitution Principle II).
- Privileges to create schema objects in the target namespace.
- Existing `public` ↔ IRIS-schema mapping in `schema_mapper.py`.

## Out of Scope

- `regclass` casts, and PostgreSQL-specific operator translation **not required to answer a catalog
  query**. Translation that a catalog query does require is in scope under FR-015 — that boundary was
  redrawn on 2026-08-17, when seven such constructs turned out to sit between a working view and a
  working `prisma db pull`. The alternative, a sibling feature, would have had no independent user
  value and a circular dependency with this one.
- Catalog **writes** — the surface is read-only.
- `pg_catalog` tables no client in evidence queries.
- Making PostgREST work; it needs `NOTIFY`, tracked separately.
