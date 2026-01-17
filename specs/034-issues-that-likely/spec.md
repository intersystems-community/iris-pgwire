# Feature Specification: IRIS pgwire compatibility fixes

**Feature Branch**: `034-issues-that-likely`  
**Created**: 2026-01-16  
**Status**: Draft  
**Input**: User description: "🔥 Issues That Likely Need iris-pgwire Fixes
These are true upstream bugs, not Sim hacks:
1. Multi-statement DDL with comments
   -- comment\nCREATE TABLE ... results in IRIS receiving SELECT 1 or corrupt statements.
   Suggest: protocol/normalizer should strip comments before splitting and avoid corrupt return.
2. Prepared statement translation ($1 → ?)
   SQL still reaches IRIS with $1 placeholders in runtime DML.
   Suggest: translate_postgres_parameters() should be applied before normalize_sql and in all query paths.
3. Default keyword in VALUES clause
   IRIS does not support DEFAULT inside VALUES, causing runtime insert failure.
4. Timestamp binding
   IRIS rejects ISO strings with T and Z unless converted; should be normalized to IRIS acceptable format.
5. ALTER TABLE .. SET DATA TYPE + DROP NOT NULL
   Needs translator support or should be stripped for IRIS."

## Clarifications

### Session 2026-01-16
- Q: How should ALTER TABLE SET DATA TYPE / DROP NOT NULL be handled? → A: Best-effort translate; if unsupported, return a clear, actionable error.

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
- **Optional sections**: Include only when relevant to the feature
- When a section doesn't apply, remove it entirely (don't leave as "N/A")

### For AI Generation
When creating this spec from a user prompt:
1. **Mark all ambiguities**: Use [NEEDS CLARIFICATION: specific question] for any assumption you'd need to make
2. **Don't guess**: If the prompt doesn't specify something (e.g., "login system" without auth method), mark it
3. **Think like a tester**: Every vague requirement should fail the "testable and unambiguous" checklist item
4. **Common underspecified areas**:
   - User types and permissions
   - Data retention/deletion policies
   - Performance targets and scale
   - Error handling behaviors
   - Integration requirements
   - Security/compliance needs

---

## User Scenarios & Testing *(mandatory)*

### Primary User Story
A developer or data engineer runs standard PostgreSQL client queries against InterSystems IRIS through pgwire and expects statements to execute successfully without manual SQL rewrites.

### Acceptance Scenarios
1. **Given** a SQL script containing DDL with leading comments and multiple statements, **When** the script is executed through pgwire, **Then** each statement runs in order without corruption or mis-parsing.
2. **Given** a prepared statement with positional parameters, **When** it is executed with bound values, **Then** parameters are recognized and the statement executes successfully.
3. **Given** an insert statement using default values for specific columns, **When** it is executed, **Then** the insert succeeds and defaults are applied as expected.
4. **Given** timestamp values using ISO formats commonly produced by PostgreSQL clients, **When** they are bound or provided as literals, **Then** IRIS accepts them without errors.
5. **Given** an ALTER TABLE statement that changes column type and/or nullability, **When** it is executed through pgwire, **Then** the result is handled in a compatible way for IRIS without crashing the session.

### Edge Cases
- Comment-only lines or inline comments appear before DDL statements.
- Mixed DDL and DML statements are sent in a single request.
- Parameters include explicit type casts or are reused multiple times in a statement.
- Multiple DEFAULT values appear in a single VALUES list.
- Timestamps include timezone designators or millisecond precision.

## Requirements *(mandatory)*

### Functional Requirements
- **FR-001**: The system MUST accept SQL scripts that contain comments and multiple statements without corrupting statement boundaries.
- **FR-002**: The system MUST consistently translate positional parameters so bound statements execute successfully across all query paths.
- **FR-003**: The system MUST support inserts that rely on column defaults without requiring user-side SQL rewrites.
- **FR-004**: The system MUST accept common client-provided timestamp formats by normalizing them into IRIS-accepted formats.
- **FR-005**: The system MUST attempt to translate ALTER TABLE statements that change data types or nullability and, when IRIS cannot support a change, return a clear, actionable error.

### Key Entities *(include if feature involves data)*
- **SQL Statement**: A client-submitted command that may include comments, parameters, and multiple operations.
- **Parameter Binding**: The pairing of positional parameters with runtime values supplied by the client.
- **Timestamp Value**: A temporal value supplied by the client that must be accepted by IRIS.

---

## Success Criteria
- 100% of compatibility tests covering the five identified issue categories pass without manual SQL rewrites by users.
- For each issue category, a representative client query completes successfully within the service’s standard response time expectations under normal load.
- At least 95% of previously failing real-world queries in these categories execute successfully after the update.

## Assumptions
- Users submit SQL through PostgreSQL-compatible clients that rely on standard SQL semantics.
- The system remains responsible for compatibility adjustments rather than requiring client-side rewrites.

## Dependencies
- None beyond existing pgwire compatibility behavior and IRIS SQL constraints.

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
