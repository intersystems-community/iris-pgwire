# Feature Specification: IRIS SQL Constructs Translation

**Feature Branch**: `004-iris-sql-constructs`
**Created**: 2025-01-19
**Status**: Draft
**Input**: User description: "IRIS SQL Constructs Translation - 87+ IRIS-specific SQL syntax, functions, data types, and system functions automatically translated to PostgreSQL equivalents"

---

## User Scenarios & Testing

### Primary User Story
Developers and BI analysts need to use existing IRIS SQL queries and applications through PostgreSQL clients without modification. The system must transparently translate IRIS-specific SQL syntax, functions, and data types to PostgreSQL equivalents so that applications written for IRIS work seamlessly through the PostgreSQL wire protocol.

### Acceptance Scenarios
1. **Given** a query with IRIS system functions like `%SYSTEM.Version.GetNumber()`, **When** executed through PostgreSQL client, **Then** it translates to `version()` and returns proper version information
2. **Given** a query using `SELECT TOP 10 FROM table`, **When** executed via psql, **Then** it translates to `SELECT * FROM table LIMIT 10` and returns correct results
3. **Given** IRIS-specific functions like `%SQLUPPER(name)`, **When** processed, **Then** they translate to `UPPER(name)` with identical behavior
4. **Given** JSON_TABLE operations with IRIS syntax, **When** executed, **Then** they translate to PostgreSQL jsonb operations with equivalent functionality
5. **Given** queries mixing multiple IRIS constructs, **When** processed, **Then** all constructs are translated correctly and query executes successfully

### Edge Cases
- What happens when IRIS constructs have no direct PostgreSQL equivalent?
- How does the system handle nested IRIS functions within complex expressions?
- What occurs when translation changes query semantics or performance characteristics?
- How does the system handle IRIS-specific data types that don't map to PostgreSQL?
- What happens when queries use both IRIS and standard SQL syntax simultaneously?

## Clarifications

### Session 2025-01-19
- Q: What should happen when IRIS constructs have no direct PostgreSQL equivalent? → A: Hybrid strategy - combine approaches based on construct criticality
- Q: What is the acceptable translation performance overhead limit? → A: 50ms - moderate overhead acceptable for most business applications
- Q: What is the translation scope for IRIS constructs? → A: Comprehensive coverage - all IRIS-specific syntax with automatic detection
- Q: What level of translation monitoring and debugging detail is needed? → A: Debug mode - comprehensive trace with parsing steps and decision logic
- Q: How should IRIS-specific SQL hints and optimizer directives be handled? → A: Pass through - send hints to IRIS backend for native optimization

## Requirements

### Functional Requirements
- **FR-001**: System MUST translate IRIS system functions (%SYSTEM.*) to PostgreSQL equivalents maintaining identical return values and behavior
- **FR-002**: System MUST convert IRIS SQL extensions (TOP, FOR UPDATE NOWAIT) to equivalent PostgreSQL syntax
- **FR-003**: System MUST map IRIS-specific functions (%SQLUPPER, DATEDIFF_MICROSECONDS) to PostgreSQL standard functions
- **FR-004**: System MUST handle IRIS data type mappings (SERIAL, ROWVERSION, %List, %Stream) to appropriate PostgreSQL types
- **FR-005**: System MUST translate JSON_TABLE operations to PostgreSQL jsonb_to_recordset equivalents
- **FR-006**: System MUST support Document Database filter operations including restriction predicate arrays (["property","value","operator"]), JSON_TABLE functions, and document->property syntax translated to PostgreSQL jsonb_path_query operations
- **FR-007**: System MUST maintain query semantics during translation ensuring identical results between IRIS and PostgreSQL execution
- **FR-008**: System MUST provide comprehensive debug mode with detailed translation trace including before/after SQL, parsing steps, construct detection, mapping decisions, and performance statistics
- **FR-009**: System MUST handle unsupported constructs using hybrid strategy - critical constructs get best-effort translation with warnings, administrative/edge constructs fail with clear PostgreSQL-compatible errors, and comprehensive documentation lists unsupported features
- **FR-010**: System MUST support comprehensive coverage of all IRIS-specific syntax with automatic detection and translation of constructs as they are encountered
- **FR-011**: System MUST preserve parameter binding compatibility when translating parameterized queries
- **FR-012**: System MUST pass through IRIS-specific SQL hints and optimizer directives to the IRIS backend for native optimization while maintaining PostgreSQL protocol compatibility

### Performance Requirements
- **PR-001**: SQL translation MUST complete within 5ms for typical queries
- **PR-002**: Translation overhead MUST NOT exceed 5ms absolute time (aligning with constitutional performance standard)
- **PR-003**: System MUST cache translated queries using LRU strategy with 1000-entry limit and 1-hour TTL for performance optimization

### Compatibility Requirements
- **CR-001**: Translated queries MUST produce identical results to original IRIS execution with tolerance for format variations (string '1' vs boolean true) but strict semantic equivalence
- **CR-002**: System MUST support IRIS 2023.1+ (including JSON_TABLE functions) with embedded Python compatibility for current and future IRIS releases
- **CR-003**: Translation MUST maintain PostgreSQL 12+ compatibility including jsonb operations, window functions, and common table expressions while preserving ANSI SQL standard compliance

### Key Entities
- **SQL Translator**: Component responsible for parsing and transforming IRIS SQL constructs to PostgreSQL equivalents
- **Function Mapping Registry**: Comprehensive mapping table of IRIS functions to PostgreSQL function equivalents
- **Data Type Converter**: Translation layer for IRIS data types to PostgreSQL type system
- **Construct Parser**: SQL parsing component that identifies IRIS-specific syntax patterns
- **Translation Cache**: Performance optimization layer for storing previously translated queries
- **Compatibility Validator**: Component ensuring translated queries maintain semantic equivalence

---

## Review & Acceptance Checklist

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

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [ ] Review checklist passed
