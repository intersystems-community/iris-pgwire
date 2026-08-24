# Feature Specification: surp Lint and ERD Support

**Feature Branch**: `047-surp-lint-support`
**Created**: 2026-08-24
**Status**: Draft

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Lint Checks Return Results (Priority: P1)

A developer connects surp (<https://github.com/rexadbapp/surp>) to an IRIS database via
iris-pgwire and runs the lint command. At least 5 of the 15 checks produce meaningful
results instead of erroring out or returning nothing.

**Why this priority**: The lint feature is the stated motivation for this work. Even partial
results (5 checks) deliver real value — missing PKs, duplicate indexes, and unsafe function
search paths are directly actionable on IRIS.

**Independent Test**: Connect surp to iris-pgwire, trigger lint, verify at least the
`no_primary_key`, `duplicate_index`, `function_search_path_mutable`, `extension_in_public`,
and `unsupported_reg_types` checks return rows or empty-with-no-error.

**Acceptance Scenarios**:

1. **Given** a running iris-pgwire server, **When** surp runs its lint SQL (splinter.sql),
   **Then** the query completes without error and returns structured rows for the 5 supported
   checks.
2. **Given** a table without a primary key in IRIS, **When** lint runs, **Then** that table
   appears in `no_primary_key` results.
3. **Given** two identical indexes on the same table, **When** lint runs, **Then** the
   `duplicate_index` check identifies them.
4. **Given** Supabase-specific checks (RLS, policies, storage), **When** lint runs,
   **Then** those checks return zero rows without crashing.

---

### User Story 2 - Schema ERD Shows Foreign Key Relationships (Priority: P2)

A developer uses surp's ERD view to visualise table relationships in an IRIS database.
Foreign key edges appear correctly between related tables.

**Why this priority**: ERD is a core navigation feature of surp. Without FK edges the diagram
is just a list of tables, losing most of its value.

**Independent Test**: Create two IRIS tables with a FK constraint, connect surp, open ERD
view, verify the FK relationship edge is rendered.

**Acceptance Scenarios**:

1. **Given** tables `orders` and `customers` with a FK from `orders.customer_id` to
   `customers.id`, **When** the ERD view loads, **Then** an edge is drawn between the two
   tables.
2. **Given** a table with no FK constraints, **When** ERD loads, **Then** no edges appear
   for that table (no crash, no phantom edges).
3. **Given** a composite FK spanning two columns, **When** ERD loads, **Then** the
   relationship is detected and shown (or gracefully omitted if not supported).

---

### User Story 3 - Lint and ERD Do Not Crash on Unsupported Checks (Priority: P3)

All 15 lint checks and the ERD query execute without raising a SQL error or protocol
exception. Unsupported checks return zero rows.

**Why this priority**: A crash or protocol error stops surp entirely. Zero rows for
unsupported checks is correct, graceful behaviour.

**Independent Test**: Run the full splinter.sql verbatim against iris-pgwire; verify no
`ERROR` response is returned for any CTE branch.

**Acceptance Scenarios**:

1. **Given** surp's full lint SQL sent to iris-pgwire, **When** executed, **Then** the
   response is a valid result set (possibly all-empty) with no error message.
2. **Given** checks that reference `pg_policy` (not present in IRIS), **When** executed,
   **Then** they return zero rows, not an error.

---

### Edge Cases

- What happens when `format()` receives a NULL argument — should return NULL, not crash.
- What happens when `ARRAY[]` is an empty literal — should return an empty array value.
- What happens when `jsonb_build_object` receives an odd number of arguments — should
  return an error consistent with PostgreSQL behaviour.
- What happens when `pg_depend` LEFT JOIN produces no rows — the parent query must still
  return results (it just won't exclude extension-owned objects).
- What happens when `ANY(conkey)` is evaluated against a NULL array — should return false.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: The system MUST evaluate `format(pattern, arg1, arg2, ...)` using
  PostgreSQL-compatible `%s` / `%I` / `%L` substitution and return a text value.
- **FR-002**: The system MUST evaluate `jsonb_build_object(key, value, ...)` with any even
  number of arguments and return a JSON object string.
- **FR-003**: The system MUST rewrite `ARRAY['v1', 'v2', ...]` array literal constructor
  syntax, replacing it with a representable scalar value (e.g., a brace-quoted string
  `{v1,v2,...}`). The rewrite applies to the full SQL text but is pattern-constrained to
  lists of single-quoted string literals, which is the only form surp produces; this makes
  it safe to apply globally without a SELECT-list restriction.
- **FR-004**: The system MUST expose a `pg_catalog.pg_depend` view that returns zero rows
  (IRIS has no extension dependency tracking).
- **FR-005**: The system MUST expose a `pg_catalog.pg_extension` view that returns zero
  rows (IRIS has no loadable extensions).
- **FR-006**: The system MUST evaluate `ANY(array_column)` membership tests in WHERE and
  JOIN conditions by rewriting `expr = ANY(col)` to an INSTR-based check against a
  comma-separated text column; catalog views store `conkey` and `indkey` as comma-separated
  text rather than native array types.
- **FR-007**: Supabase-specific catalog objects referenced in lint SQL (`pg_policy`,
  `pg_rewrite`, `pg_roles`) MUST be implemented as stub empty views with correct PostgreSQL
  column schemas so the full splinter.sql parses and executes, returning zero rows for those
  checks. Query rewriting / branch stripping is explicitly out of scope for this requirement.
- **FR-008**: All 5 supported lint checks MUST complete and return valid (possibly empty)
  result sets when the full splinter.sql is executed in one statement.
- **FR-009**: The ERD foreign key query MUST correctly identify FK constraints using
  `pg_constraint` and resolve column positions via `conkey` array membership.

### Key Entities

- **pg_depend**: Catalog view representing object dependency tracking. In iris-pgwire this
  is always empty; its schema must match PostgreSQL's so LEFT JOINs do not error.
- **pg_extension**: Catalog view representing installed extensions. Always empty in
  iris-pgwire.
- **format() function**: String formatting function accepting a pattern and variadic
  arguments. Must support all three modes: `%s` (passthrough), `%I` (double-quote the
  argument as a PostgreSQL identifier), `%L` (single-quote the argument as a SQL literal
  with internal single-quote escaping).
- **jsonb_build_object() function**: Variadic function accepting alternating key/value
  pairs, returning a JSON object.
- **ARRAY[] literal**: Syntax construct producing an array value from a list of literals.
  Must survive SQL rewriting so downstream catalog queries can use it in output columns.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: At least 5 of 15 surp lint checks return valid (possibly empty) result sets
  with no SQL error when surp's full lint SQL is executed against iris-pgwire.
- **SC-002**: surp's ERD view correctly renders FK relationships for tables with FK
  constraints defined in IRIS.
- **SC-003**: The full splinter.sql (all 15 checks as one multi-CTE UNION) executes
  without returning any ERROR-level protocol response.
- **SC-004**: `format()`, `jsonb_build_object()`, and `ARRAY[]` are covered by unit tests
  that verify correct output for the patterns used in splinter.sql.
- **SC-005**: Query translation overhead for the lint SQL does not exceed 10ms (translation
  only, excluding IRIS execution time).

## Clarifications

### Session 2026-08-24

- Q: How should `ANY(array_column)` be implemented for `pg_constraint.conkey` and `pg_index.indkey`? → A: SQL rewriter intercepts `ANY(col)` and rewrites to an INSTR/CONTAINS check against a comma-separated text column; catalog views store these columns as comma-separated text.
- Q: Where in a query should `ARRAY[...]` constructor rewriting apply? → A: Full SQL text, but the pattern is constrained to lists of single-quoted string literals so it cannot accidentally match an expression in a WHERE clause. The earlier "SELECT output columns only" answer was overly restrictive; global application is safe given the pattern constraint.
- Q: Which substitution modes must `format()` support? → A: All three — `%s` (passthrough), `%I` (double-quoted identifier), `%L` (single-quoted literal with escaping).
- Q: How should Supabase-specific catalog objects (`pg_policy`, `pg_rewrite`, `pg_roles`) be handled? → A: Stub empty views with correct column schemas so queries parse and execute, returning zero rows.
- Q: How should `pg_index.indkey` be stored in the catalog view? → A: Space-separated text (e.g., `"1 2"`) mirroring PostgreSQL `int2vector` serialisation so `indkey::text` is a no-op cast.

## Assumptions

- surp connects as a plain PostgreSQL client; no Supabase management API is involved.
- IRIS CE (Community Edition) is the primary target; enterprise features like RLS are out
  of scope.
- `pg_policy`, `auth.*`, and `storage.*` references in lint SQL can be handled by returning
  zero rows from stub views — surp does not error if those checks are empty.
- `pg_depend` schema: `(classid oid, objid oid, objsubid int, refclassid oid, refobjid oid,
refobjsubid int, deptype char)` — must match exactly so the LEFT JOIN ON clause resolves.
- `pg_extension` schema: `(oid oid, extname name, extowner oid, extnamespace oid,
extrelocatable bool, extversion text, extconfig oid[], extcondition text[])`.
- Array literal support (`ARRAY[...]`) is implemented via SQL rewriting (pre-IRIS
  execution), not native IRIS array syntax.
- `ANY(array_column)` for `pg_constraint.conkey` (smallint[]) is implemented via SQL
  rewriting (INSTR-based), not native IRIS array operators. `conkey` is stored as
  comma-separated text in the catalog view.
- `pg_index.indkey` is stored as space-separated text (e.g., `"1 2"`) mirroring PostgreSQL
  `int2vector` serialisation; `indkey::text` casts are therefore no-ops.
