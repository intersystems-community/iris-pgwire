# Feature Specification: README Performance Benchmarks Section

**Feature Branch**: `028-readme-performance`
**Created**: 2025-12-18
**Status**: Draft
**Input**: User description: "add/restore section to readme with performance numbers that highlight speed of intersystems dbapi direct connection (multiple optimizations of our wire protocol) compared to pgwire + embedded, and pgwire + dbapi"

## Execution Flow (main)
```
1. Parse user description from Input
   → Feature: Add performance comparison section to README
2. Extract key concepts from description
   → Actors: Developers evaluating connection options, users choosing deployment paths
   → Actions: View, compare, understand performance tradeoffs
   → Data: Benchmark results (latency, throughput) for 4 connection paths
   → Constraints: Must use existing benchmark data, highlight DBAPI direct as fastest
3. For each unclear aspect:
   → No critical clarifications needed - benchmark data exists
4. Fill User Scenarios & Testing section
   → Scenario: Developer choosing between deployment options based on performance
5. Generate Functional Requirements
   → Each requirement must be testable
6. Identify Key Entities (if data involved)
   → Benchmark results, connection paths, latency metrics
7. Run Review Checklist
   → PASS - spec ready for planning
8. Return: SUCCESS (spec ready for planning)
```

---

## ⚡ Quick Guidelines
- ✅ Focus on WHAT users need (performance comparison visibility) and WHY (informed deployment decisions)
- ❌ Avoid HOW to implement (no specific markdown formatting or layout decisions)
- 👥 Written for developers choosing deployment options

---

## User Scenarios & Testing *(mandatory)*

### Primary User Story

**As a** developer evaluating IRIS PGWire for my project,
**I want to** see clear performance comparisons between different connection paths,
**So that** I can make an informed decision about which deployment option best fits my performance requirements.

### Acceptance Scenarios

1. **Given** a developer reading the README, **When** they reach the performance section, **Then** they can see latency comparisons for all supported connection paths (IRIS DBAPI direct, PGWire + DBAPI, PGWire + Embedded, PostgreSQL baseline).

2. **Given** benchmark data exists in the repository, **When** the README displays performance numbers, **Then** the numbers accurately reflect the actual benchmark results with proper context (test conditions, dimensions, iterations).

3. **Given** a user wants maximum performance, **When** they read the performance section, **Then** they can clearly identify that IRIS DBAPI direct connection is the fastest option and understand why.

4. **Given** a user prioritizing PostgreSQL client compatibility, **When** they read the performance section, **Then** they understand the performance tradeoff (~4ms overhead) for the PGWire protocol translation layer.

### Edge Cases
- What happens when benchmark data is outdated? (Note: Include benchmark date/version)
- How does performance vary with vector dimensions? (Note: State test conditions)

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: README MUST include a dedicated section displaying performance benchmark results comparing all supported connection paths.

- **FR-002**: Performance section MUST show latency metrics (average, p50, p95) for each connection path.

- **FR-003**: Performance section MUST include results for at least two query types: simple SELECT and vector similarity search.

- **FR-004**: Performance section MUST clearly highlight that IRIS DBAPI direct connection provides the best performance (baseline).

- **FR-005**: Performance section MUST explain the ~4ms protocol translation overhead for PGWire paths.

- **FR-006**: Performance section MUST include test conditions (iterations, vector dimensions, test date) for reproducibility context.

- **FR-007**: Performance section MUST include a reference to detailed benchmark documentation for users wanting full methodology.

- **FR-008**: Performance comparison MUST present data in a format that allows quick visual comparison (table or similar).

### Success Criteria

- Users can identify the fastest connection option within 10 seconds of viewing the section
- Performance tradeoffs between deployment options are clearly articulated
- Benchmark methodology is transparent (conditions documented)
- Section integrates naturally with existing README structure

### Key Entities

- **Connection Path**: A method of connecting to IRIS (DBAPI direct, PGWire + DBAPI, PGWire + Embedded, PostgreSQL baseline)
- **Benchmark Result**: Performance measurement including latency percentiles, query type, and test conditions
- **Performance Tradeoff**: The balance between PostgreSQL compatibility (PGWire) and raw speed (DBAPI direct)

### Assumptions

- Existing benchmark data in `benchmarks/results/benchmark_4way_results.json` is accurate and representative
- Performance section will be placed in the existing README structure near deployment/architecture information
- Numbers will be rounded appropriately for readability (e.g., 0.21ms, 3.82ms, 4.75ms)

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
- [x] Ambiguities marked (none critical)
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [x] Review checklist passed

---

## Notes

**Benchmark Data Available** (from `benchmark_4way_results.json`):

| Connection Path | Simple SELECT (avg) | Vector Similarity (avg) |
|-----------------|---------------------|-------------------------|
| IRIS DBAPI Direct | 0.21ms | 2.35ms |
| PGWire + DBAPI | 3.82ms | 6.76ms |
| PGWire + Embedded | 4.75ms | N/A |
| PostgreSQL (baseline) | 0.32ms | 0.59ms |

**Key Insight**: IRIS DBAPI direct is ~18× faster than PGWire paths for simple queries, demonstrating that users prioritizing raw performance should use DBAPI direct, while PGWire provides PostgreSQL compatibility with acceptable ~4ms overhead.
