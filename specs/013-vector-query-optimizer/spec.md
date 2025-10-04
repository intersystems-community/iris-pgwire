# Feature Specification: Vector Query Optimizer for HNSW Compatibility

**Feature Branch**: `013-vector-query-optimizer`
**Created**: 2025-10-01
**Status**: Draft
**Input**: User description: "Server-side SQL transformation to convert parameterized vector queries into literal form, enabling IRIS HNSW index optimization for high-performance vector similarity searches"

## Execution Flow (main)
```
1. Parse user description from Input
   → Feature: Transform parameterized TO_VECTOR() calls to literals
2. Extract key concepts from description
   → Actors: PostgreSQL clients, PGWire server, IRIS database
   → Actions: Query transformation, parameter substitution, HNSW optimization
   → Data: Vector embeddings in base64/JSON array/comma-delimited formats
   → Constraints: Must preserve query semantics, <10ms transformation overhead
3. For each unclear aspect:
   → Performance target: 335+ qps (based on DBAPI benchmark)
   → All ambiguities resolved via technical context
4. Fill User Scenarios & Testing section
   → Scenario 1: pgvector client executes ORDER BY <-> similarity query
   → Scenario 2: Bulk vector similarity search with HNSW acceleration
5. Generate Functional Requirements
   → FR-001 through FR-012 covering transformation, format support, performance
6. Identify Key Entities
   → Vector Query, Vector Parameter, Transformation Context, Vector Format
7. Run Review Checklist
   → No [NEEDS CLARIFICATION] markers (technical context complete)
   → No implementation details in requirements (focused on WHAT/WHY)
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

---

## User Scenarios & Testing *(mandatory)*

### Primary User Story
**As a** data scientist using pgvector-compatible PostgreSQL clients to query IRIS vector embeddings
**I want** vector similarity queries to execute with HNSW index optimization (sub-50ms latency)
**So that** I can perform real-time semantic search over large document collections without changing my existing pgvector-based application code

**Current Problem**: When PostgreSQL clients execute parameterized vector similarity queries like:
```sql
SELECT * FROM documents
ORDER BY embedding <-> %s
LIMIT 5
```
The parameter binding (`%s`) prevents IRIS from recognizing the vector pattern needed to use HNSW indexes, causing queries to timeout (>60 seconds) instead of completing in milliseconds.

**Desired Outcome**: The PGWire server automatically transforms these parameterized queries into literal form that IRIS can optimize, achieving 335+ queries/second throughput with <50ms latency per query.

### Acceptance Scenarios

1. **Given** a pgvector client executing a parameterized similarity query with base64-encoded vector
   **When** the query contains `ORDER BY VECTOR_COSINE(column, TO_VECTOR(%s))` with base64 parameter
   **Then** the server transforms it to `ORDER BY VECTOR_COSINE(column, TO_VECTOR('[1.0,2.0,...]', FLOAT))`
   **And** IRIS executes using HNSW index with <50ms latency

2. **Given** a query with JSON array format vector parameter `[0.1,0.2,0.3]`
   **When** the query uses `ORDER BY VECTOR_DOT_PRODUCT(embedding, TO_VECTOR(%s, FLOAT))`
   **Then** the server preserves the JSON array format in the literal transformation
   **And** IRIS applies DP-444330 pre-parser optimization for HNSW acceleration

3. **Given** a query with multiple parameters (e.g., `SELECT TOP %s ... ORDER BY ... LIMIT %s`)
   **When** only the vector parameter appears in ORDER BY clause
   **Then** the server transforms only the vector parameter to literal form
   **And** preserves other parameters for normal parameter binding

4. **Given** a non-vector query with regular parameter binding
   **When** the query has no ORDER BY clause or no TO_VECTOR() calls
   **Then** the server passes the query through unchanged
   **And** normal parameter binding behavior is preserved

5. **Given** concurrent vector similarity queries from multiple clients
   **When** 16 clients execute similarity searches simultaneously
   **Then** the system sustains 335+ queries/second aggregate throughput
   **And** transformation overhead adds <10ms to query latency

### Edge Cases

#### Vector Format Handling
- What happens when vector parameter is in unknown format (not base64, JSON array, or comma-delimited)?
  **Expected**: System logs warning and attempts query with original parameter (graceful degradation)

- What happens when base64 decoding fails due to invalid base64 data?
  **Expected**: System catches decoding exception, logs error, passes through original parameter

- What happens when JSON array format contains invalid float values?
  **Expected**: System preserves malformed array, lets IRIS handle validation and return appropriate SQL error

#### Query Pattern Variations
- What happens when ORDER BY contains multiple vector functions (e.g., `ORDER BY VECTOR_COSINE(...), VECTOR_DOT_PRODUCT(...)`)?
  **Expected**: System transforms all vector parameters in ORDER BY clause

- What happens when TO_VECTOR() appears in SELECT clause but not ORDER BY?
  **Expected**: No transformation (optimization only applies to ORDER BY for HNSW usage)

- What happens when query has ACORN-1 hint already (`/*#OPTIONS {"ACORN-1":1} */`)?
  **Expected**: Transformation still applies; hint is preserved in SQL string

#### Performance & Scaling
- What happens when vector dimensionality is very large (e.g., 4096 dimensions)?
  **Expected**: Transformation completes within 10ms overhead budget; large literals don't affect parsing

- What happens when transformation overhead exceeds constitutional 5ms SLA?
  **Expected**: System logs SLA violation warning but completes transformation (constitutional monitoring captures metric)

#### Error Handling
- What happens when regex pattern matching fails to find TO_VECTOR() in ORDER BY?
  **Expected**: System returns original SQL and parameters unchanged (no-op behavior)

- What happens when parameter index calculation is incorrect?
  **Expected**: System logs parameter mismatch error and passes through original query to avoid breaking client

---

## Requirements *(mandatory)*

### Functional Requirements

#### Query Transformation
- **FR-001**: System MUST detect parameterized TO_VECTOR() calls within ORDER BY clauses using pattern matching
- **FR-002**: System MUST transform parameterized TO_VECTOR(%s) to literal form TO_VECTOR('[1.0,2.0,...]', FLOAT) when vector parameter is detected
- **FR-003**: System MUST preserve all non-vector parameters for standard parameter binding
- **FR-004**: System MUST maintain original query semantics and result ordering after transformation
- **FR-005**: System MUST handle queries with no ORDER BY clause or no TO_VECTOR() calls without transformation (pass-through behavior)

#### Vector Format Support
- **FR-006**: System MUST support base64-encoded vector format (e.g., `base64:ABC123...`)
  - Must decode base64 to binary float32 array
  - Must convert to JSON array string format `[1.0,2.0,3.0,...]`

- **FR-007**: System MUST support JSON array vector format (e.g., `[0.1,0.2,0.3]`)
  - Must preserve existing JSON array format (pass-through)

- **FR-008**: System MUST support comma-delimited vector format (e.g., `1.0,2.0,3.0`)
  - Must wrap in square brackets to form JSON array

#### Error Handling & Resilience
- **FR-009**: System MUST gracefully degrade when vector format is unrecognized
  - Must log warning with sample of unrecognized format
  - Must pass through original query without transformation

- **FR-010**: System MUST handle base64 decoding failures without breaking query execution
  - Must catch decoding exceptions
  - Must log error with diagnostic information
  - Must pass through original parameter

- **FR-011**: System MUST handle parameter index mismatches without corrupting query
  - Must validate parameter count matches placeholder count
  - Must log parameter mismatch errors
  - Must fall back to original query on validation failure

#### Performance & Monitoring
- **FR-012**: System MUST complete query transformation within 10ms overhead budget
  - Must measure transformation duration for performance tracking
  - Must log constitutional SLA violations (>5ms as warning)
  - Must not block query execution even if transformation is slow

#### Integration Requirements
- **FR-013**: System MUST integrate with IRIS executor before SQL execution
  - Must be invoked after query parsing, before IRIS database call
  - Must return both optimized SQL and remaining parameters

- **FR-014**: System MUST support all IRIS vector similarity functions in ORDER BY:
  - VECTOR_COSINE(column, vector)
  - VECTOR_DOT_PRODUCT(column, vector)
  - VECTOR_L2(column, vector)

### Performance Requirements

- **PR-001**: System MUST achieve 335+ queries/second throughput for vector similarity searches (based on DBAPI benchmark baseline)
- **PR-002**: System MUST maintain <50ms latency for individual vector similarity queries (P95 latency)
- **PR-003**: System MUST add <5ms transformation overhead to query execution path (constitutional SLA requirement)
- **PR-004**: System MUST handle concurrent queries from 16 clients without degradation (optimal IRIS connection pool size)
- **PR-005**: System MUST comply with constitutional 5ms SLA for SQL translation (warn on violations, do not block execution)

### Success Metrics

#### Performance Targets
- **Throughput**: 335+ queries/second (95% of DBAPI baseline 356.5 qps; 82% of theoretical max 433.9 ops/sec from Epic hackathon)
- **Latency**: <50ms P95 latency for HNSW-optimized queries
- **Transformation Overhead**: <5ms SLA (constitutional requirement; 10ms warning threshold for monitoring)
- **Constitutional Compliance**: <5% violation rate for 5ms SLA (measured via performance monitor)

#### Functional Correctness
- **Query Correctness**: 100% of transformed queries return identical results to DBAPI literal queries
- **Format Support**: 100% support for base64, JSON array, and comma-delimited vector formats
- **Graceful Degradation**: 0% query failures due to transformation errors (must pass through on failure)

#### Comparison Baseline
- **Current PGWire Performance**: Timeout (>60 seconds) for parameterized vector queries
- **Target Performance**: Match DBAPI performance (356.5 qps observed in testing)
- **Improvement Factor**: 10-50× improvement over linear scan (via HNSW index activation)

### Key Entities *(include if feature involves data)*

#### Vector Query
- **Represents**: SQL query containing vector similarity operations in ORDER BY clause
- **Key Attributes**:
  - Original SQL text with parameter placeholders (%s or ?)
  - Parameter list including vector embeddings
  - Query pattern (simple query vs extended protocol)
  - Vector function type (COSINE, DOT_PRODUCT, L2)
- **Relationships**: Contains one or more Vector Parameters

#### Vector Parameter
- **Represents**: Vector embedding data passed as query parameter
- **Key Attributes**:
  - Encoding format (base64, JSON array, comma-delimited)
  - Dimensionality (number of vector components)
  - Data type (FLOAT, INT, DECIMAL)
  - Parameter position in query (for multi-parameter queries)
- **Relationships**: Part of Vector Query, transformed into Vector Literal

#### Vector Literal
- **Represents**: JSON array string format suitable for IRIS HNSW optimization
- **Key Attributes**:
  - JSON array string (e.g., `[1.0,2.0,3.0,...]`)
  - Component count (vector dimensionality)
  - Data type specifier (FLOAT, INT)
- **Relationships**: Replaces Vector Parameter in transformed query

#### Transformation Context
- **Represents**: Metadata about query transformation process
- **Key Attributes**:
  - Transformation timestamp
  - Duration (milliseconds)
  - Parameter formats detected
  - Parameter count (original vs remaining after transformation)
  - Success/failure status
  - Constitutional SLA compliance flag
- **Relationships**: Associated with Vector Query, used for performance monitoring

#### Vector Format
- **Represents**: Supported encoding formats for vector parameters
- **Key Attributes**:
  - Format identifier (base64, json_array, comma_delimited)
  - Detection pattern (prefix or structure)
  - Conversion logic requirements
- **Relationships**: Determines how Vector Parameter is converted to Vector Literal

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

### Technical Context
- [x] Performance targets defined (335+ qps, <50ms latency, <10ms overhead)
- [x] Vector format support specified (base64, JSON array, comma-delimited)
- [x] Error handling behavior documented (graceful degradation)
- [x] Integration points identified (IRIS executor, performance monitor)
- [x] Constitutional compliance addressed (5ms SLA monitoring)

---

## Execution Status
*Updated by main() during processing*

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked (none remaining - technical context complete)
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [x] Review checklist passed

---

## Dependencies & Assumptions

### Technical Dependencies
- **IRIS Build 127 EHAT**: Required for DP-444330 pre-parser optimization supporting JSON array format in ORDER BY
- **HNSW Indexes**: Must exist on vector columns for ACORN-1 optimization to activate
- **Vector Licensing**: IRIS vector operations require proper licensing (iris.key mounted)
- **Performance Monitor**: Constitutional compliance tracking requires performance monitoring integration

### Assumptions
- **DBAPI Baseline**: 356.5 qps throughput with HNSW optimization represents achievable target for PGWire
- **Vector Format Usage**: Clients primarily use base64 encoding (psycopg2 default) or JSON arrays (DP-444330 optimized)
- **Query Patterns**: Vector similarity queries follow standard pgvector patterns (ORDER BY <-> operator)
- **IRIS Optimization**: TO_VECTOR() with literal JSON array in ORDER BY triggers HNSW index usage
- **Parameter Binding Limitation**: IRIS cannot optimize parameterized TO_VECTOR() calls (confirmed via testing)

### Known Constraints
- **Transformation Scope**: Only applies to ORDER BY clauses (SELECT clause TO_VECTOR() not affected)
- **Constitutional SLA**: 5ms translation limit is aspirational; 10ms overhead budget allows for practical implementation
- **Connection Pooling**: Optimal performance requires 16 concurrent clients (from IRIS performance report)
- **Protocol Overhead**: PGWire protocol adds 81.9% overhead vs native DBAPI (measured: 120 vs 662 vec/sec ingestion)

---

## Out of Scope

The following are explicitly **not** part of this feature:

### Vector Type System
- pg_catalog.pg_type entries for vector type (covered by separate P5 vector support feature)
- PostgreSQL OID assignment for vector type
- pgvector operator translation (<->, <#>, <=>) to IRIS functions

### HNSW Index Management
- Automatic HNSW index creation/detection
- ACORN-1 hint injection into queries
- Index health monitoring or optimization

### Performance Infrastructure
- Constitutional governance framework implementation
- Performance monitoring system
- SLA violation alerting mechanisms

### Query Rewriting Beyond Vectors
- General SQL dialect translation (covered by existing sql_translator module)
- pgvector-specific functions beyond ORDER BY optimization
- Advanced query optimization (joins, subqueries, CTEs)

### Client Compatibility
- pgvector extension installation/emulation
- Custom vector data type registration
- Binary vector protocol (COPY protocol binary mode)

---

## Success Criteria Summary

This feature will be considered successful when:

1. **Functional Correctness**: pgvector clients can execute vector similarity queries through PGWire without code changes, receiving identical results to DBAPI literal queries

2. **Performance Target**: Vector similarity queries achieve 335+ qps throughput with <50ms P95 latency (matching DBAPI baseline)

3. **Transformation Efficiency**: Query transformation adds <10ms overhead (measured via performance monitor)

4. **Format Support**: All three vector formats (base64, JSON array, comma-delimited) are correctly transformed

5. **Reliability**: Zero query failures due to transformation errors (100% graceful degradation on edge cases)

6. **Constitutional Compliance**: <5% SLA violation rate for 5ms translation target (warning threshold, not blocking)

7. **Integration Completeness**: Optimizer integrates with IRIS executor, performance monitor, and constitutional governance

8. **End-to-End Validation**: Real PostgreSQL clients (psycopg2, psql) successfully execute vector similarity searches with HNSW optimization

---

## References

- **Epic Vector Search Hackathon Summary**: Context on ACORN-1, DP-444330 pre-parser change, PostgREST architecture
- **IRIS Performance Report**: 433.9 ops/sec target, 16-client optimal pool, 4.5× HNSW improvement factor
- **DBAPI Benchmark Results**: 356.5 qps (82% of target), 662 vec/sec ingestion baseline
- **Constitutional Framework**: 5ms SLA mandate, performance monitoring requirements
- **DP-444330 Pre-parser Change**: JSON array literal support in ORDER BY for IRIS vector optimization
