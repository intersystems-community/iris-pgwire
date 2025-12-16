# Data Model: 3-Way Database Performance Benchmark

## Core Entities

### BenchmarkConfiguration
Represents the configuration for a single benchmark run.

**Fields**:
- `vector_dimensions: int` - Dimension count for vector operations (default: 1024)
- `dataset_size: int` - Number of rows in test dataset (100K-1M per clarification)
- `iterations: int` - Number of times to execute each query pattern
- `concurrent_connections: int` - Number of concurrent database connections
- `warmup_queries: int` - Number of warmup queries before measurements (default: 100)
- `random_seed: int` - Seed for reproducible vector generation (default: 42)
- `connection_configs: Dict[str, ConnectionConfig]` - Connection parameters for each method

**Validation Rules**:
- `vector_dimensions` must be > 0, recommended: 1024 (FR-003)
- `dataset_size` must be >= 100,000 and <= 1,000,000 (clarification: production scale)
- `iterations` must be > 0
- `concurrent_connections` must be > 0
- All three connection configs must be present: "iris_pgwire", "postgresql_psycopg3", "iris_dbapi"

**State**: Immutable once benchmark starts (no transitions)

---

### ConnectionConfig
Represents connection parameters for a single database access method.

**Fields**:
- `method_name: str` - Identifier for the method ("iris_pgwire", "postgresql_psycopg3", "iris_dbapi")
- `host: str` - Database host
- `port: int` - Database port
- `database: str` - Database/namespace name
- `username: str` - Authentication username (if required)
- `password: str` - Authentication password (if required)
- `connection_timeout: float` - Timeout in seconds for connection establishment

**Validation Rules**:
- `method_name` must be one of the three supported methods
- `port` must be 1-65535
- `connection_timeout` must be > 0

---

### TestQuery
Represents a single query pattern to be benchmarked.

**Fields**:
- `query_id: str` - Unique identifier for the query
- `category: str` - Query category ("simple", "vector_similarity", "complex_join")
- `template: str` - SQL query template with parameter placeholders
- `parameter_generator: Callable` - Function to generate query parameters
- `expected_result_format: Dict` - Schema describing expected result shape

**Validation Rules**:
- `query_id` must be unique within a benchmark run
- `category` must be one of: "simple", "vector_similarity", "complex_join" (FR-002)
- `template` must be valid SQL syntax for target database
- For `vector_similarity` queries: must include vector comparison operator or function

**Relationships**:
- Used by BenchmarkConfiguration (one-to-many)
- Generates multiple PerformanceResult instances

---

### PerformanceResult
Represents measured metrics for a single query execution.

**Fields**:
- `result_id: str` - Unique identifier for this result
- `method_name: str` - Which database method was tested
- `query_id: str` - Reference to the TestQuery that was executed
- `timestamp: datetime` - When the measurement was taken
- `elapsed_ms: float` - Query execution time in milliseconds
- `success: bool` - Whether query completed successfully
- `error_message: Optional[str]` - Error details if query failed
- `row_count: int` - Number of rows returned
- `resource_usage: Optional[Dict]` - Memory/CPU metrics if available

**Validation Rules**:
- `elapsed_ms` must be >= 0
- If `success` is False, `error_message` must be present
- `row_count` must be >= 0
- `method_name` must match one of the three configured methods

**Relationships**:
- Belongs to a TestQuery (many-to-one)
- Aggregated into BenchmarkReport

---

### BenchmarkReport
Represents aggregated results comparing all three database access methods.

**Fields**:
- `report_id: str` - Unique identifier for this report
- `config: BenchmarkConfiguration` - The configuration used for this benchmark
- `start_time: datetime` - When benchmark started
- `end_time: datetime` - When benchmark completed
- `total_duration_seconds: float` - Total benchmark execution time
- `method_results: Dict[str, MethodResults]` - Aggregated results per method
- `raw_results: List[PerformanceResult]` - All individual query results
- `validation_errors: List[str]` - Any validation failures encountered

**MethodResults Structure** (embedded):
```python
{
    "method_name": str,
    "queries_executed": int,
    "queries_failed": int,
    "qps": float,  # Queries per second
    "latency_p50_ms": float,
    "latency_p95_ms": float,
    "latency_p99_ms": float,
    "by_category": {
        "simple": CategoryMetrics,
        "vector_similarity": CategoryMetrics,
        "complex_join": CategoryMetrics
    }
}
```

**CategoryMetrics Structure** (embedded):
```python
{
    "count": int,
    "qps": float,
    "p50_ms": float,
    "p95_ms": float,
    "p99_ms": float
}
```

**Validation Rules**:
- Must have results for all three methods (FR-001) unless abort occurred (FR-006)
- If any method has `queries_failed > 0` during connection phase, entire report is invalid
- All percentile values must be >= 0
- `qps` must be > 0 if any queries succeeded

**State Transitions**:
1. `initializing` → `running` - Benchmark started, connections validated
2. `running` → `completed` - All queries executed successfully
3. `running` → `failed` - Connection failure triggered abort (FR-006)
4. `completed` → `exported` - Results written to JSON/console table (FR-010)

---

## Entity Relationships

```
BenchmarkConfiguration (1) --- (N) TestQuery
                |
                |
                v
          BenchmarkReport (1) --- (N) PerformanceResult
                                       |
                                       |
                                       v
                                  TestQuery (N) --- (1)
```

## Data Volume Estimates

Based on FR-005 clarification (100K-1M rows):

- **Test vectors**: 1M rows × 1024 dimensions × 4 bytes (float32) = ~4GB per database
- **PerformanceResult instances**: ~300 results (3 methods × 3 categories × 33 iterations) = ~50KB
- **BenchmarkReport**: ~100KB including all aggregations
- **Total memory footprint**: <10MB per constitutional requirement (excluding database storage)

## Serialization Formats

### JSON Output (FR-010)
```json
{
  "report_id": "benchmark_2025_01_03_12_34_56",
  "config": {
    "vector_dimensions": 1024,
    "dataset_size": 100000,
    "iterations": 1000
  },
  "results": {
    "iris_pgwire": {
      "qps": 1234.5,
      "latency_p50_ms": 8.3,
      "latency_p95_ms": 12.7,
      "latency_p99_ms": 15.9
    },
    "postgresql_psycopg3": { ... },
    "iris_dbapi": { ... }
  }
}
```

### Console Table Output (FR-010)
```
Method                 QPS      P50 (ms)  P95 (ms)  P99 (ms)
-------------------  -------  ----------  --------  --------
IRIS + PGWire        1234.5        8.3      12.7      15.9
PostgreSQL + psycopg 2345.6        4.2       6.8       9.1
IRIS + DBAPI          987.3       10.1      14.5      18.3
```

## Implementation Notes

1. **Identical Test Data (FR-008)**: All three methods use same TestQuery instances with same parameter_generator functions seeded identically.

2. **Abort on Failure (FR-006)**: BenchmarkReport transitions to `failed` state on first connection error, preventing partial results.

3. **Raw Metrics (FR-007)**: No statistical significance testing, only raw percentile calculations.

4. **Constitutional Compliance**: PerformanceResult.elapsed_ms precision validates <5ms translation overhead requirement.
