# Feature Specification: JSONB Containment Operator (@>) Support

**Feature Branch**: `050-jsonb-containment-operator`
**Created**: 2026-08-25
**Status**: Draft
**Input**: Bug 5 from SimpleMem fork — `::jsonb @>` containment operator crashes IRIS; needs `PGWire.JSONB_CONTAINS()` emulation

## User Scenarios & Testing _(mandatory)_

### User Story 1 - JSONB Containment in WHERE Clause (Priority: P1)

A developer queries IRIS via iris-pgwire using `@>` in a WHERE clause, e.g. `WHERE metadata::jsonb @> '{"role":"admin"}'::jsonb`. IRIS has no native `@>` operator; the server must translate it.

**Why this priority**: `@>` is the primary jsonb filter pattern in Prisma and psycopg3 apps. Without it, any JSON-based filtering throws a syntax error.

**Independent Test**: Run `SELECT id FROM users WHERE metadata::jsonb @> '{"role":"admin"}'::jsonb` via psycopg3 against a table with a JSON column; verify only matching rows are returned.

**Acceptance Scenarios**:

1. **Given** `users(id INT, metadata VARCHAR)` with rows `(1, '{"role":"admin"}')` and `(2, '{"role":"user"}')`, **When** `SELECT id FROM users WHERE metadata::jsonb @> '{"role":"admin"}'::jsonb`, **Then** only row 1 is returned.
2. **Given** `col::jsonb @> $1::jsonb` with parameter `'{"key":"val"}'`, **Then** parameter binding works and correct rows returned.
3. **Given** `WHERE doc::jsonb @> '{"address":{"city":"Boston"}}'::jsonb`, **Then** only rows matching the nested key-value are returned.
4. **Given** a query with no `@>`, **When** translated, **Then** SQL passes through unchanged.

---

### User Story 2 - JSONB Containment in JOIN Condition (Priority: P2)

A developer uses `@>` in a JOIN ON clause, e.g. `JOIN tags ON doc::jsonb @> tags.filter::jsonb`.

**Why this priority**: Less common than WHERE-clause use; needed for SQL completeness.

**Independent Test**: Execute a JOIN query with `@>` in the ON clause; verify correct rows.

**Acceptance Scenarios**:

1. **Given** `ON a.doc::jsonb @> b.filter::jsonb`, **When** executed, **Then** join produces correct rows.

---

### Edge Cases

- RHS is a parameter placeholder (`$1`) rather than a literal.
- `@>` inside a subquery or CTE.
- Reverse operator `<@` (contained-by).
- JSON value contains special characters, quotes, or unicode.
- Column not cast (bare column, no `::jsonb`).

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: The SQL translator MUST detect `@>` and rewrite to `PGWire.JSONB_CONTAINS(left, right)`.
- **FR-002**: `::jsonb` casts on both sides MUST be stripped as part of the rewrite.
- **FR-003**: `PGWire.JSONB_CONTAINS` MUST be installed in the IRIS namespace; accepts two VARCHAR arguments (JSON strings); returns 1 if `right` is contained in `left`, 0 otherwise.
- **FR-004**: The rewrite MUST handle `?` and `$N` placeholders on either side without breaking parameter binding.
- **FR-005**: The rewrite MUST be applied before SQL reaches IRIS, with overhead not exceeding 1ms per query.
- **FR-006**: `<@` MUST be translated by swapping arguments: `left <@ right` → `PGWire.JSONB_CONTAINS(right, left)`.
- **FR-007**: Queries with no `@>` or `<@` MUST pass through with zero modification.

### Key Entities

- **JSONB_CONTAINS Procedure**: ObjectScript stored procedure in the `PGWire` package; given two JSON strings, returns 1 if all key-value pairs in the second exist in the first.
- **Containment Rewrite**: Regex-based translation step in `normalizer.py`, consistent with existing ILIKE and boolean rewriters.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: `col::jsonb @> '{"k":"v"}'::jsonb` executes without error and returns correct rows.
- **SC-002**: `PGWire.JSONB_CONTAINS` returns correct results for nested JSON, arrays, and scalars.
- **SC-003**: Translation overhead ≤ 1ms per query with `@>`.
- **SC-004**: All existing 5,500+ unit tests pass.
- **SC-005**: ≥ 5 unit tests cover the rewrite logic; ≥ 3 cover the procedure behavior.

## Assumptions

- IRIS stores JSON columns as VARCHAR; `::jsonb` casts are cosmetic and can be stripped.
- The `PGWire` package already exists in IRIS (`JSONB_BUILD_OBJECT4/6`, `FORMAT2/3`); `JSONB_CONTAINS` is a new addition.
- `a @> b` means every key-value pair in `b` exists in `a` (PostgreSQL standard). For arrays, every element of `b` must appear in `a`.
- Full array containment in ObjectScript is in scope; correctness takes priority over performance on large documents.
