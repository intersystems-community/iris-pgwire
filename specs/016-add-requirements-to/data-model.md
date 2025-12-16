# Phase 1: Data Model

**Feature**: Benchmark Debug Capabilities and Vector Optimizer Fix
**Date**: 2025-10-03

## Entities

### 1. OptimizationTrace

Represents the transformation of a SQL query by the vector optimizer.

**Fields**:
- `original_sql` (str): Original PostgreSQL-compatible SQL with pgvector operators
- `optimized_sql` (str): Transformed SQL with IRIS vector functions
- `transformation_time_ms` (float): Time taken for optimization in milliseconds
- `validation_status` (enum: PASS | FAIL): SQL syntax validation result
- `bracket_detected` (bool): Whether vector literals have brackets (FR-008)

**Validation Rules**:
- `transformation_time_ms` MUST be <5ms (constitutional requirement)
- `bracket_detected` MUST be True for valid vector literals
- `validation_status` MUST be PASS before SQL execution

**Relationships**:
- Embedded in BenchmarkResult (one-to-one)
- Referenced by DebugLogEntry (one-to-many)

**State Transitions**:
```
[Created] → [Validated: PASS] → [Executed]
         → [Validated: FAIL] → [Rejected]
```

**Usage** (FR-005):
- Log original SQL and optimized SQL for every query
- Measure and track transformation time
- Validate bracket preservation in vector literals

---

### 2. BenchmarkResult

Represents the outcome of a single query execution in the 3-way comparison.

**Fields**:
- `query_template_id` (str): Identifier from `benchmarks/test_data/query_templates.py`
- `database_method` (enum: POSTGRESQL | PGWIRE | DBAPI): Execution method
- `execution_time_ms` (float): Query execution time (excluding optimization)
- `row_count` (int): Number of rows returned
- `error_status` (Optional[str]): Error message if query failed
- `optimization_trace` (Optional[OptimizationTrace]): Optimizer trace (only for PGWIRE)

**Validation Rules**:
- `execution_time_ms` > 0
- `row_count` >= 0
- `optimization_trace` MUST exist when `database_method` is PGWIRE
- `error_status` MUST be None for successful queries

**Relationships**:
- Contains OptimizationTrace (for PGWIRE method only)
- Aggregated into benchmark reports (P50/P95/P99 metrics)

**State Transitions**:
```
[Pending] → [Executing] → [Success: row_count > 0]
                       → [Error: error_status set]
                       → [Timeout: error_status = "TIMEOUT"]
```

**Usage** (FR-015, FR-016, FR-017):
- Compare query performance across all 3 database methods
- Validate identical results from all methods
- Calculate P50/P95/P99 latency percentiles

---

### 3. IRISErrorContext

Captures detailed error information when IRIS query execution fails.

**Fields**:
- `sqlcode` (int): IRIS error code (e.g., -400 for compiler crash)
- `error_message` (str): Full error message from IRIS
- `problematic_sql` (str): The SQL statement that caused the error
- `optimizer_state` (dict): Optimizer configuration and internal state at time of error

**Validation Rules**:
- `sqlcode` MUST be negative (IRIS convention)
- `problematic_sql` MUST match the SQL that was executed
- `optimizer_state` MUST include enabled/disabled flags

**Relationships**:
- Referenced by DebugLogEntry (one-to-one)
- Can reference OptimizationTrace (shows before/after SQL)

**Usage** (FR-003, FR-007):
- Capture IRIS error messages with full query context
- Provide actionable debugging information
- Track SQLCODE patterns to identify recurring issues

---

### 4. DebugLogEntry

Structured log entry for query execution pipeline stages.

**Fields**:
- `timestamp` (datetime): When the log entry was created
- `query_id` (str): Unique identifier for the query (query_template_id + iteration)
- `transformation_details` (OptimizationTrace): SQL transformation trace
- `execution_phase` (enum: CONNECTION | OPTIMIZATION | EXECUTION | FETCH): Pipeline stage
- `error_context` (Optional[IRISErrorContext]): Error details if failure occurred

**Validation Rules**:
- `timestamp` MUST be chronologically ordered within same `query_id`
- `transformation_details` MUST exist when `execution_phase` is OPTIMIZATION
- `error_context` MUST exist when entry represents a failure

**Relationships**:
- References OptimizationTrace (one-to-one per query)
- References IRISErrorContext (optional, one-to-one on error)
- Aggregated by query_id for full pipeline trace

**State Transitions**:
```
CONNECTION → OPTIMIZATION → EXECUTION → FETCH → [Complete]
          ↘ [Error at any phase] → error_context set
```

**Usage** (FR-006, FR-011):
- Query-by-query timing breakdown (connection, optimization, execution, fetch)
- Structured, timestamped, filterable debug logs
- Track success/failure rates per database method

---

## Relationships Diagram

```
BenchmarkResult
├── contains: OptimizationTrace (1:1, when database_method=PGWIRE)
└── aggregates into: Benchmark Report (P50/P95/P99 metrics)

DebugLogEntry
├── references: OptimizationTrace (1:1)
└── references: IRISErrorContext (0:1, optional on error)

OptimizationTrace
├── embedded in: BenchmarkResult (1:1)
├── referenced by: DebugLogEntry (1:many)
└── may reference: IRISErrorContext (shows pre/post SQL on error)

IRISErrorContext
├── referenced by: DebugLogEntry (1:1)
└── may reference: OptimizationTrace (shows SQL transformation)
```

---

## Implementation Notes

### Existing Code Integration

**BenchmarkResult** - Enhance existing structure:
- File: `benchmarks/config.py`
- Add `optimization_trace` field (Optional[OptimizationTrace])
- Modify `MethodResults.validate()` to require optimization_trace for PGWIRE

**OptimizationTrace** - New data class:
- File: `src/iris_pgwire/vector_optimizer.py`
- Return from `VectorOptimizer.optimize_query()`
- Include validation results and timing

**IRISErrorContext** - New error capture:
- File: `src/iris_pgwire/iris_executor.py`
- Capture SQLCODE from `iris.Error` exceptions
- Include optimizer state from environment/config

**DebugLogEntry** - New structured logging:
- File: `benchmarks/runner.py` or new `benchmarks/debug_logger.py`
- Log at each pipeline stage (connection, optimization, execution, fetch)
- JSON output for programmatic analysis

---

*Data model derived from functional requirements FR-001 through FR-017 in spec.md.*
