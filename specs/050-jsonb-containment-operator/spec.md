# Feature Specification: JSONB Containment Operator (@>) Support

**Feature Branch**: `050-jsonb-containment-operator`
**Created**: 2026-08-25
**Status**: Draft
**Input**: Bug 5 from SimpleMem fork — `::jsonb @>` containment operator crashes IRIS; needs `PGWire.JSONB_CONTAINS()` emulation

## User Scenarios & Testing *(mandatory)*

### User Story 1 - JSONB Containment in WHERE Clause (Priority: P1)

A developer queries IRIS via iris-pgwire using the PostgreSQL jsonb containment operator `@>` in a WHERE clause, e.g. `WHERE metadata::jsonb @> '{"role":"admin"}'::jsonb`. IRIS has no native `@>` operator so this currently throws a syntax error. The server must translate this to an equivalent IRIS expression.

**Why this priority**: The `@>` operator is the most common jsonb filter pattern in Prisma and raw psycopg3 apps. Without it, any JSON-based filtering crashes.

**Independent Test**: Run `SELECT id FROM users WHERE metadata::jsonb @> '{"role":"admin"}'::jsonb` via psycopg3 against a table with a JSON column; verify rows with matching JSON are returned.

**Acceptance Scenarios**:

1. **Given** a table `users(id INT, metadata VARCHAR)` with rows `(1, '{"role":"admin"}')` and `(2, '{"role":"user"}')`, **When** `SELECT id FROM users WHERE metadata::jsonb @> '{"role":"admin"}'::jsonb`, **Then** only row 1 is returned.
2. **Given** a column cast `col::jsonb @> $1::jsonb` with parameter `'{"key":"val"}'`, **Then** parameter binding works correctly and correct rows returned.
3. **Given** a nested JSON containment `WHERE doc::jsonb @> '{"address":{"city":"Boston"}}'::jsonb`, **Then** only rows where the nested key-value matches are returned.
4. **Given** a query with no `@>` operator, **When** translated, **Then** SQL passes through unchanged (no regressions).

---

### User Story 2 - JSONB Containment in JOIN Condition (Priority: P2)

A developer uses `@>` in a JOIN ON clause, e.g. `JOIN tags ON doc::jsonb @> tags.filter::jsonb`. This is less common but valid PostgreSQL syntax.

**Why this priority**: Needed for completeness but lower urgency than WHERE-clause use.

**Independent Test**: Execute a JOIN query with `@>` in the ON clause; verify join works correctly.

**Acceptance Scenarios**:

1. **Given** a JOIN using `ON a.doc::jsonb @> b.filter::jsonb`, **When** executed, **Then** join produces correct rows.

---

### Edge Cases

- What if the right-hand side of `@>` is a parameter placeholder (`$1`) rather than a literal?
- What if `@>` appears inside a subquery or CTE?
- What happens with the reverse operator `<@` (contained-by)? Should it also be translated?
- What if the JSON value contains special characters, quotes, or unicode?
- How is `@>` handled when the column is not cast (bare column, no `::jsonb`)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The SQL translator MUST detect `@>` containment operator in SQL and rewrite it to a call to `PGWire.JSONB_CONTAINS(left, right)`.
- **FR-002**: The `::jsonb` cast on both sides of `@>` MUST be stripped as part of the rewrite (IRIS does not need explicit JSON casts when calling `PGWire.JSONB_CONTAINS`).
- **FR-003**: The `PGWire.JSONB_CONTAINS` ObjectScript stored procedure MUST be implemented and installed in the IRIS namespace; it must accept two VARCHAR arguments (JSON strings) and return 1 if `right` is contained in `left`, 0 otherwise.
- **FR-004**: The rewrite MUST handle parameter placeholders (`?` or `$N`) on either side of `@>` without breaking parameter binding.
- **FR-005**: The rewrite MUST be applied in the normalization pipeline before SQL reaches IRIS, with overhead not exceeding 1ms per query.
- **FR-006**: The reverse operator `<@` (contained-by) MUST also be translated by swapping arguments: `left <@ right` → `PGWire.JSONB_CONTAINS(right, left)`.
- **FR-007**: Queries containing no `@>` or `<@` operators MUST pass through the translator with zero modification.

### Key Entities

- **JSONB_CONTAINS Procedure**: An ObjectScript stored procedure in the `PGWire` package that implements JSON containment semantics: given two JSON strings, returns 1 if all key-value pairs in the second argument exist in the first.
- **Containment Rewrite**: A regex/pattern-based SQL translation step in `normalizer.py` (consistent with existing ILIKE, vector, boolean rewriters) that finds `@>` and `<@` and rewrites them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Queries using `col::jsonb @> '{"k":"v"}'::jsonb` execute without error and return correct rows.
- **SC-002**: The `PGWire.JSONB_CONTAINS` procedure returns correct results for nested JSON, arrays, and scalar values.
- **SC-003**: Translation overhead for a query with `@>` does not exceed 1ms.
- **SC-004**: All existing 5,500+ unit tests continue to pass after changes.
- **SC-005**: At least 5 unit tests cover the rewrite logic; at least 3 cover the ObjectScript procedure behavior.

## Assumptions

- IRIS stores JSON columns as VARCHAR; explicit `::jsonb` casts in PostgreSQL SQL are cosmetic and can be stripped.
- The `PGWire` package already exists in IRIS (used for `JSONB_BUILD_OBJECT4/6`, `FORMAT2/3`, etc.); `JSONB_CONTAINS` is a new addition to that package.
- JSON containment semantics: `a @> b` means "every key-value pair in `b` exists somewhere in `a`" (PostgreSQL standard). For arrays, every element of `b` must appear in `a`.
- Full recursive/array containment logic in ObjectScript is within scope; performance for large JSON documents is acceptable if correctness is maintained.
