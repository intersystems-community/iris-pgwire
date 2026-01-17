# Feature Specification: DDL Compatibility Enhancements for PostgreSQL → IRIS

**Feature Branch**: `[###-feature-name]`  
**Created**: [DATE]  
**Status**: Draft  
**Input**: User description: "$ARGUMENTS"

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
- As a database engineer, I want migrations to succeed when using PostgreSQL DDL features that IRIS does not support, so I can run existing migration scripts without modification.
Database engineers run migration scripts containing PostgreSQL‑specific DDL constructs (e.g., `SET (fillfactor)`, generated columns, `USING btree`, casts, enums, `CHECK` constraints). The driver processes these scripts against InterSystems IRIS, automatically handling unsupported constructs according to the configured `strict_ddl` flag, allowing the migration to complete without manual script modifications.

### Acceptance Scenarios
1. **Given** a migration script with `CREATE TABLE ... (col1 INT GENERATED ALWAYS AS ... STORED)`, **When** executed with `strict_ddl=false`, **Then** the table is created without the generated column and a warning is logged.
2. **Given** a script with `CREATE TYPE ... AS ENUM ('a', 'b')`, **When** executed with `strict_ddl=false`, **Then** the statement is skipped, the type is registered, and subsequent columns using it become `VARCHAR(64)`.
3. **Given** any unsupported construct, **When** executed with `strict_ddl=true`, **Then** the driver must raise an error and abort the current statement execution.

### Edge Cases
- **Nested Constructs**: Handling of cast syntax within a complex `DEFAULT` expression (e.g., `DEFAULT ('val'::text || 'ue'::text)`).
- **Index Dependencies**: Ensuring a `CREATE INDEX` for a table that failed creation (due to other errors) is skipped gracefully.

## Requirements *(mandatory)*

### Functional Requirements
- **FR-008**: System MUST provide a configurable `strict_ddl` flag (default `false`). When set to `true`, any unsupported PostgreSQL DDL construct must raise an error and abort the migration; when `false`, the construct is skipped with a warning.
- **FR-001**: System MUST skip `SET (fillfactor = …)` statements and log a warning.
- **FR-002**: System MUST skip column definitions containing `GENERATED ALWAYS AS … STORED` while preserving other columns and log a warning.
- **FR-003**: System MUST strip the `USING btree` clause from `CREATE INDEX` statements and log a warning.
- **FR-004**: System MUST remove PostgreSQL cast syntax (`'value'::type`) from column default expressions and log a warning.
- **FR-005**: System MUST register `CREATE TYPE … AS ENUM` definitions, skip their execution, and map any column using a registered enum to `VARCHAR(64)`.


- **FR-006**: System MUST skip `ADD CONSTRAINT … CHECK (…)` statements and log a warning.
- **FR-007**: System MUST maintain a set of table names whose `CREATE TABLE` statements were skipped and automatically skip any `CREATE INDEX` statements that reference those tables, logging a warning.



---

## Clarifications

### Session 2026-01-17
- Q: Default `strict_ddl` value → A: false (skip with warning)
- Q: Warning log format → A: "[DDL‑SKIP] <statement> ignored"
- Q: Enum column length → A: VARCHAR(64)

### Session 2026-01-17
- Q: How should unsupported PostgreSQL DDL constructs be handled? → A: Raise an error to the client so the migration fails and must be fixed manually.

## Review & Acceptance Checklist
*GATE: Automated checks run during main() execution*

### Content Quality
- [ ] No implementation details (languages, frameworks, APIs)
- [ ] Focused on user value and business needs
- [ ] Written for non-technical stakeholders
- [ ] All mandatory sections completed

### Requirement Completeness
- [x] No [NEEDS CLARIFICATION] markers remain
- [ ] Requirements are testable and unambiguous  
- [ ] Success criteria are measurable
- [ ] Scope is clearly bounded
- [ ] Dependencies and assumptions identified

---

## Execution Status
*Updated by main() during processing*

- [ ] User description parsed
- [ ] Key concepts extracted
- [ ] Ambiguities marked
- [ ] User scenarios defined
- [ ] Requirements generated
- [ ] Entities identified
- [ ] Review checklist passed

---
