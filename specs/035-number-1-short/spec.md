# Feature Specification: PostgreSQL DDL Compatibility (ENUM, RLS, Boolean Defaults)

**Feature Branch**: `035-number-1-short`  
**Created**: 2026-01-17  
**Status**: Draft  
**Input**: User description: "Feature 035: PostgreSQL DDL Compatibility - ENUM Types, RLS, and Boolean Defaults

Following the v1.0.6 release that addressed prepared statements, timestamps, and ALTER TABLE translation, there remain three categories of PostgreSQL DDL statements that cause IRIS compatibility failures when using ORM migration tools like Drizzle:

## Problem Statement

When running Drizzle ORM migrations against IRIS via iris-pgwire, 64 problematic statements across 35 migration files fail:

1. **ENUM Types (13 statements + column usages)**: PostgreSQL `CREATE TYPE ... AS ENUM` is not supported by IRIS. Column definitions using enum types also fail.

2. **Row Level Security (3 statements)**: PostgreSQL `ALTER TABLE ... ENABLE/DISABLE ROW LEVEL SECURITY` causes IRIS syntax errors. IRIS uses different security mechanisms.

3. **Boolean Defaults (48 statements)**: PostgreSQL `DEFAULT true` and `DEFAULT false` literals are not understood by IRIS, which expects `DEFAULT 1` and `DEFAULT 0` for BIT columns.

## Required Capabilities

### ENUM Type Handling
- Skip `CREATE TYPE \"name\" AS ENUM (...)` statements (return success without executing)
- Track registered enum type names during session
- Translate column type references from enum types to `VARCHAR(64)`
- Handle PostgreSQL enum type casts like `'value'::\"public\".\"enum_type\"` → `'value'`
- Handle `ALTER TABLE ... ALTER COLUMN ... SET DATA TYPE \"enum_type\"` → `VARCHAR(64)`
- Skip `DROP TYPE \"enum_type\"` for registered enum types

### RLS Statement Handling
- Skip `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` (return success)
- Skip `ALTER TABLE ... DISABLE ROW LEVEL SECURITY` (return success)
- Skip `CREATE POLICY ... ON ...` statements (return success)
- Skip `DROP POLICY ... ON ...` statements (return success)

### Boolean Default Translation
- Translate `DEFAULT true` → `DEFAULT 1` in DDL (CREATE TABLE, ALTER TABLE)
- Translate `DEFAULT false` → `DEFAULT 0` in DDL
- Must not affect string literals (e.g., `'true'` should remain unchanged)
- Must not affect comments
- Optionally translate boolean literals in DML for completeness

## Execution Flow (main)
```
1. Parse user description from Input
   → If empty: ERROR "No feature description provided"
2. Extract key concepts from description
   → Identify: actors, actions, data, constraints
3. For each unclear aspect:
   → Mark with [NEEDS CLARIFICATION: specific question]
4. Fill User Scenarios & Testing section
   → If no clear user flow: ERROR "Cannot determine user scenarios"
5. Generate Functional Requirements
   → Each requirement must be testable
   → Mark ambiguous requirements
6. Identify Key Entities (if data involved)
7. Run Review Checklist
   → If any [NEEDS CLARIFICATION]: WARN "Spec has uncertainties"
   → If implementation details found: ERROR "Remove tech details"
8. Return: SUCCESS (spec ready for planning)
```

---

## ⚡ Quick Guidelines
- ✅ Focus on WHAT users need and WHY
- ❌ Avoid HOW to implement (no tech stack, APIs, code structure)
- 👥 Written for business stakeholders, not developers

### Section Requirements
- **Mandatory sections**: Must be completed for every feature
- **Optional sections**: Include only when relevant
- When a section doesn't apply, remove it entirely (don't leave as "N/A")

---

## Clarifications

### Session 2026-01-17
- Q: Should enum value constraints be enforced or allow any string? → A: Allow any string value.
- Q: How should RLS statements be handled when skipped? → A: Fail-safe skip (no-op result).

## User Scenarios & Testing *(mandatory)*

### Primary User Story
A database developer runs ORM migrations against InterSystems IRIS through the PostgreSQL wire protocol and expects common PostgreSQL DDL (enums, row-level security toggles, and boolean defaults) to execute without manual SQL rewrites or migration edits.

### Acceptance Scenarios
1. **Given** a migration that defines PostgreSQL enum types and uses them in table columns, **When** the migration is executed through pgwire, **Then** it completes successfully and the columns are created with compatible text-based types.
2. **Given** a migration that enables or disables row-level security or defines RLS policies, **When** it is executed through pgwire, **Then** the statements are accepted without errors and the migration continues.
3. **Given** a migration that sets column defaults using `true` or `false`, **When** it is executed through pgwire, **Then** the defaults are applied successfully with equivalent boolean behavior.
4. **Given** a migration that uses enum casts in default expressions or updates, **When** it is executed through pgwire, **Then** the casted values are accepted without errors.

### Edge Cases
- Enum types are defined and later dropped within the same migration batch.
- Enum types are referenced with schema-qualified names or quoted identifiers.
- Boolean literals appear inside string literals or comments and must remain unchanged.
- RLS statements appear interleaved with other DDL in a multi-statement batch.

## Requirements *(mandatory)*

### Functional Requirements
- **FR-001**: The system MUST accept PostgreSQL enum type definition statements without failing the migration.
- **FR-002**: The system MUST treat columns declared with enum types as compatible text-based columns for IRIS execution without enforcing value constraints.
- **FR-003**: The system MUST skip PostgreSQL RLS enable/disable statements with a no-op success result.
- **FR-004**: The system MUST skip PostgreSQL RLS policy statements with a no-op success result.
- **FR-005**: The system MUST normalize boolean defaults written as `true` or `false` to IRIS-compatible defaults in DDL.
- **FR-006**: The system MUST preserve literal strings and comments containing the words `true` or `false` without modification.
- **FR-007**: The system MUST process enum type casts in defaults or expressions without migration failure.
- **FR-008**: The system MUST meet current performance expectations for migration execution under normal workloads.

### Key Entities *(include if feature involves data)*
- **Migration Statement**: A DDL or DML statement submitted by an ORM migration tool.
- **Enum Type Definition**: A PostgreSQL-defined type with a set of labeled values referenced by columns.
- **Compatibility Translation**: The transformation applied to unsupported PostgreSQL constructs so they execute on IRIS.

---

## Success Criteria
- At least 64 previously failing migration statements execute successfully without manual edits.
- Migration runs complete without errors for ORM scripts containing enums, RLS, and boolean defaults.
- No regression is observed in the existing compatibility test suite for PostgreSQL clients.
- Migration execution latency stays within established performance expectations under normal workloads.

## Assumptions
- Users rely on standard PostgreSQL migration tools and expect compatibility without editing generated SQL.
- Treating enum-typed columns as text-based columns is acceptable for the compatibility layer when native enum support is unavailable.
- Skipping row-level security statements is acceptable because IRIS enforces access control through different mechanisms.

## Dependencies
- None beyond existing SQL compatibility layers and migration execution flows.

---

## Review & Acceptance Checklist
*GATE: Automated checks run during main() execution*

### Content Quality
- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

### Requirement Completeness
- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

---

## Execution Status
*Updated by main() during processing*

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [x] Review checklist passed

---
