# Feature Specification: PostgreSQL Transaction Verb Compatibility

**Feature Branch**: `022-postgresql-transaction-verb`
**Created**: 2025-11-08
**Status**: Draft
**Input**: User description: "Translate PostgreSQL transaction control verbs (BEGIN/COMMIT/ROLLBACK) to IRIS-compatible equivalents (START TRANSACTION/COMMIT/ROLLBACK) at the protocol layer to enable standard PostgreSQL client transaction syntax"

## Execution Flow (main)
```
1. Parse user description from Input
   → ✅ Feature clearly defined: Protocol-layer transaction verb translation
2. Extract key concepts from description
   → Actors: PostgreSQL clients (psql, psycopg, SQLAlchemy)
   → Actions: Send BEGIN/COMMIT/ROLLBACK commands
   → Data: SQL transaction control statements
   → Constraints: Must maintain <5ms constitutional SLA, <0.1ms translation overhead
3. For each unclear aspect:
   → No ambiguities - feature scope is well-defined from user feedback
4. Fill User Scenarios & Testing section
   → ✅ Clear user flow: Client issues BEGIN → Server translates → IRIS executes
5. Generate Functional Requirements
   → ✅ All requirements are testable and measurable
6. Identify Key Entities (if data involved)
   → No persistent data entities - transaction control is ephemeral
7. Run Review Checklist
   → ✅ No implementation details beyond protocol-level requirement
   → ✅ No [NEEDS CLARIFICATION] markers
8. Return: SUCCESS (spec ready for planning)
```

---

## ⚡ Quick Guidelines
- ✅ Focus on WHAT users need and WHY
- ❌ Avoid HOW to implement (no tech stack, APIs, code structure)
- 👥 Written for business stakeholders, not developers

---

## User Scenarios & Testing *(mandatory)*

### Primary User Story
PostgreSQL client applications (psql, psycopg, SQLAlchemy) expect to control transactions using standard PostgreSQL syntax: `BEGIN`, `COMMIT`, and `ROLLBACK`. IRIS SQL uses `START TRANSACTION` instead of `BEGIN`. Without translation, clients issuing `BEGIN` commands will fail or produce unexpected behavior. The PGWire protocol layer must transparently translate these commands so clients can use familiar PostgreSQL transaction syntax while IRIS receives compatible statements.

### Acceptance Scenarios
1. **Given** a PostgreSQL client connected to IRIS via PGWire, **When** the client issues `BEGIN`, **Then** IRIS receives and executes `START TRANSACTION` without error
2. **Given** an active transaction initiated by `BEGIN`, **When** the client issues `COMMIT`, **Then** IRIS commits the transaction successfully
3. **Given** an active transaction initiated by `BEGIN`, **When** the client issues `ROLLBACK`, **Then** IRIS rolls back the transaction successfully
4. **Given** a PostgreSQL client using SQLAlchemy, **When** the application uses context manager syntax (`with connection.begin():`), **Then** all transaction commands are translated correctly
5. **Given** multiple rapid transaction commands, **When** translation occurs, **Then** overhead remains below 0.1ms per command (constitutional 5ms SLA maintained)

### Edge Cases
- What happens when client sends `BEGIN TRANSACTION` (verbose PostgreSQL syntax)? → Translate to `START TRANSACTION`
- What happens when client sends `START TRANSACTION` directly? → Pass through unchanged (already IRIS-compatible)
- What happens when transaction verb appears mid-query (e.g., string literal)? → Must NOT translate (only translate when it's a command)
- How does system handle nested BEGIN attempts? → IRIS error handling applies (IRIS does not support nested transactions)
- What happens with `BEGIN WORK` or `BEGIN ISOLATION LEVEL`? → Translate BEGIN keyword, preserve modifiers

## Requirements *(mandatory)*

### Functional Requirements
- **FR-001**: System MUST translate `BEGIN` command to `START TRANSACTION` before sending to IRIS
- **FR-002**: System MUST translate `BEGIN TRANSACTION` to `START TRANSACTION` (verbose PostgreSQL syntax)
- **FR-003**: System MUST pass `COMMIT` command to IRIS unchanged (same keyword in both dialects)
- **FR-004**: System MUST pass `ROLLBACK` command to IRIS unchanged (same keyword in both dialects)
- **FR-005**: System MUST preserve transaction modifiers when present (e.g., `BEGIN ISOLATION LEVEL READ COMMITTED`)
- **FR-006**: System MUST NOT translate `BEGIN` when it appears in contexts other than transaction control (e.g., inside string literals, comments, or PL/SQL blocks)
- **FR-007**: System MUST maintain translation overhead below 0.1ms per command (to preserve constitutional 5ms total query SLA)
- **FR-008**: System MUST handle both Simple Query Protocol (`Query` message with `BEGIN`) and Extended Query Protocol (`Parse` message with `BEGIN` in statement)
- **FR-009**: System MUST support case-insensitive matching (`BEGIN`, `begin`, `Begin` all translate to `START TRANSACTION`)
- **FR-010**: Translation MUST occur before SQL normalization (to maintain Feature 021 normalization pipeline)

### Performance Requirements
- **PR-001**: Transaction verb translation MUST complete in <0.1ms (measured via performance monitoring)
- **PR-002**: E2E transaction workflow (BEGIN + INSERT + COMMIT) MUST complete within constitutional 5ms SLA
- **PR-003**: Translation MUST NOT introduce additional round-trips to IRIS

### Testing Requirements
- **TR-001**: Unit tests MUST verify translation for all verb variants (`BEGIN`, `BEGIN TRANSACTION`, `BEGIN WORK`)
- **TR-002**: E2E tests MUST validate with real psql client executing transactions
- **TR-003**: E2E tests MUST validate with psycopg executing parameterized statements in transactions
- **TR-004**: Performance tests MUST measure translation overhead in isolation
- **TR-005**: Regression tests MUST ensure Feature 021 normalization continues to work after translation

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
- [x] Success criteria are measurable (0.1ms overhead, 5ms total SLA)
- [x] Scope is clearly bounded (transaction verb translation only)
- [x] Dependencies identified (Feature 021 normalization, constitutional SLA)

---

## Execution Status
*Updated by main() during processing*

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked (none found)
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified (N/A - no persistent data)
- [x] Review checklist passed

---

## Dependencies & Context

### Related Features
- **Feature 021**: PostgreSQL-Compatible SQL Normalization - Transaction verb translation must integrate with existing normalization pipeline
- **P2 Phase**: Extended Query Protocol implementation - Translation must work with prepared statements

### Constitutional Requirements
- **Principle VI**: 5ms query translation SLA - Transaction overhead must not violate this limit
- **Principle II**: Test-First Development - E2E tests with real PostgreSQL clients required
- **Principle I**: Protocol Fidelity - Must maintain PostgreSQL wire protocol compliance

### Known Constraints
- IRIS does not support nested transactions - Translation cannot fix this limitation
- IRIS `%COMMITMODE` setting is session-level - May require connection-time configuration (out of scope for this feature)
- Feature 021 normalization already processes SQL - Translation must occur in compatible location

---
