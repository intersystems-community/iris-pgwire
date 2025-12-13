# Feature Specification: Benchmark Debug Capabilities and Vector Optimizer Fix

**Feature Branch**: `016-add-requirements-to`
**Created**: 2025-10-03
**Status**: Draft
**Input**: User description: "add requirements to fix and have debug capabilities for this benchmark"

## Execution Flow (main)
```
1. Parse user description from Input
   → Feature: Fix benchmark failures and add debug tooling
2. Extract key concepts from description
   → Actors: Developers running performance benchmarks
   → Actions: Debug hanging queries, identify optimizer bugs, measure performance
   → Data: Query execution traces, SQL transformations, timing metrics
   → Constraints: Must work with 3-way comparison (PostgreSQL, IRIS PGWire, IRIS DBAPI)
3. Unclear aspects identified:
   → [RESOLVED] Debug output format - structured logs with query traces
   → [RESOLVED] Performance targets - existing 5ms translation SLA
4. User Scenarios defined
5. Functional Requirements generated
6. Key Entities identified
7. Review Checklist: IN PROGRESS
```

---

## ⚡ Quick Guidelines
- ✅ Focus on WHAT users need and WHY
- ❌ Avoid HOW to implement (no tech stack, APIs, code structure)
- 👥 Written for business stakeholders, not developers

---

## User Scenarios & Testing

### Primary User Story
As a developer working on the IRIS PGWire benchmark suite, I need to identify why vector similarity queries are hanging and causing IRIS compiler errors, so that I can measure accurate performance comparisons between PostgreSQL, IRIS via PGWire, and IRIS via DBAPI.

**Current Problem**: Benchmark timeouts when executing vector similarity queries with pgvector operators. Simple SELECT queries work, but vector operations cause IRIS SQL compiler crashes with SQLCODE -400 errors.

### Acceptance Scenarios
1. **Given** a vector similarity query with pgvector operators, **When** executed through PGWire, **Then** the system logs the original SQL, optimized SQL, and any transformation errors
2. **Given** the benchmark is running, **When** a query times out, **Then** the debug logs show exactly which query failed and at what stage (connection, optimization, IRIS execution)
3. **Given** the vector optimizer transforms a query, **When** it generates invalid IRIS SQL, **Then** the error is caught and logged with the problematic SQL snippet
4. **Given** a successful benchmark run, **When** viewing results, **Then** I can see query-by-query performance metrics for all three database methods
5. **Given** vector literals in queries, **When** the optimizer processes them, **Then** bracket preservation is validated before sending to IRIS

### Edge Cases
- What happens when vector optimizer strips brackets from literals (current bug)?
- How does system handle IRIS compiler errors without hanging indefinitely?
- What debug output is needed to identify SQL transformation bugs?
- How can developers verify optimizer correctness without running full benchmarks?

## Requirements

### Functional Requirements

#### Core Fixes
- **FR-001**: System MUST preserve vector literal formatting (brackets) when optimizing pgvector operators to IRIS vector functions
- **FR-002**: System MUST validate optimized SQL syntax before sending to IRIS to prevent compiler crashes
- **FR-003**: System MUST detect and report IRIS SQLCODE -400 errors with actionable context (query, optimization stage)
- **FR-004**: System MUST implement query timeouts to prevent indefinite hangs on compiler errors

#### Debug Capabilities
- **FR-005**: Benchmark MUST log original SQL, optimized SQL, and transformation time for every query
- **FR-006**: System MUST provide query-by-query timing breakdown showing connection, optimization, execution, and result fetch phases
- **FR-007**: System MUST capture and display IRIS error messages with full query context when failures occur
- **FR-008**: Debug output MUST include vector literal format validation results (bracket detection)
- **FR-009**: Benchmark MUST support dry-run mode that validates queries without executing them against IRIS

#### Diagnostic Tooling
- **FR-010**: System MUST provide standalone diagnostic script that tests individual query templates with timeout protection
- **FR-011**: Debug logs MUST be structured (timestamped, categorized by query type, filterable by success/failure)
- **FR-012**: System MUST track and report query success/failure rates per database method (PostgreSQL, PGWire, DBAPI)
- **FR-013**: Benchmark MUST support incremental debugging (test simple queries first, then vector queries, then joins)

#### Performance Validation
- **FR-014**: System MUST measure and report vector optimization overhead (target: <5ms per query)
- **FR-015**: Benchmark MUST compare query performance across all three methods with identical test data
- **FR-016**: System MUST validate that optimized queries produce correct results (not just performance)
- **FR-017**: Debug output MUST show P50/P95/P99 latency percentiles for each query template

### Key Entities

- **Query Template**: Pre-defined SQL pattern (simple SELECT, vector similarity, complex join) used across all three database methods with identical parameters
- **Optimization Trace**: Record of SQL transformation including original query, optimized query, transformation time, and validation status
- **Benchmark Result**: Performance metrics for a single query template including execution time, row count, error status, and database method
- **Debug Log Entry**: Timestamped record containing query ID, transformation details, execution phase, and error context
- **IRIS Error Context**: Captured error including SQLCODE, error message, problematic SQL snippet, and optimizer state

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

**Dependencies**:
- Existing vector optimizer in vector optimizer module
- 3-way benchmark infrastructure (PostgreSQL, IRIS, PGWire containers)
- Diagnostic script for hanging queries (exists, needs enhancement)

**Assumptions**:
- IRIS requires vector literals in TO_VECTOR to have brackets
- Current optimizer bug strips brackets, causing SQLCODE -400 compiler errors
- Performance SLA remains 5ms for vector optimization overhead

---

## Execution Status

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked (all resolved)
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [x] Review checklist passed

**Status**: ✅ Specification complete and ready for planning phase
