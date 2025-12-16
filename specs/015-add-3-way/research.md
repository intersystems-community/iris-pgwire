# Research: 3-Way Database Performance Benchmark

## Overview
Research findings for implementing a comprehensive performance benchmark comparing three database access methods: IRIS with PGWire, PostgreSQL with psycopg3, and IRIS with DBAPI.

## PostgreSQL Setup with pgvector

### Decision
Use PostgreSQL with pgvector extension for vector similarity operations comparable to IRIS VECTOR functions.

### Rationale
- pgvector is the de facto standard for vector operations in PostgreSQL
- Provides operators (`<->`, `<#>`, `<=>`) matching those being tested in PGWire translation
- Supports HNSW indexing comparable to IRIS HNSW indexes
- Well-documented performance characteristics for production-scale datasets

### Alternatives Considered
- **PostgreSQL without pgvector**: Cannot test vector similarity operations, defeating purpose of benchmark
- **Custom vector implementation**: Unnecessary complexity, pgvector is battle-tested

### Implementation Notes
```sql
-- Required PostgreSQL setup
CREATE EXTENSION vector;
CREATE TABLE vectors (
    id INTEGER PRIMARY KEY,
    embedding VECTOR(1024)  -- Matches FR-003 default dimension
);
CREATE INDEX ON vectors USING hnsw (embedding vector_cosine_ops);
```

## IRIS DBAPI Connection Methods

### Decision
Use intersystems-iris-dbapi package for IRIS DBAPI testing leg of benchmark.

### Rationale
- Official InterSystems Python database API driver
- Follows Python DB-API 2.0 specification
- Already documented limitations with vector parameter binding (IRIS_DBAPI_LIMITATIONS_JIRA.md)
- Represents real-world external application connection pattern

### Alternatives Considered
- **JDBC via JPype**: Adds unnecessary Java dependency, complicates setup
- **ODBC**: Platform-specific, less portable than native Python driver

### Implementation Notes
```python
import iris
# Connection pattern for DBAPI leg
conn = iris.connect(hostname='localhost', port=1972,
                   namespace='USER', username='_SYSTEM', password='SYS')
```

## Benchmark Metrics Collection

### Decision
Use Python `time.perf_counter()` for high-resolution timing and numpy percentile calculations for P50/P95/P99.

### Rationale
- `perf_counter()` provides nanosecond precision, monotonic clock
- numpy percentile is standard, well-tested statistical function
- Matches constitutional 5ms measurement precision requirements
- Lightweight, no additional profiling overhead

### Alternatives Considered
- **timeit module**: Designed for microbenchmarks, too much warmup overhead
- **cProfile**: Adds profiling overhead, affects measured performance
- **Manual percentile calculation**: numpy is faster and more accurate

### Implementation Pattern
```python
import time
import numpy as np

timings = []
for i in range(iterations):
    start = time.perf_counter()
    # Execute query
    elapsed = time.perf_counter() - start
    timings.append(elapsed * 1000)  # Convert to ms

p50 = np.percentile(timings, 50)
p95 = np.percentile(timings, 95)
p99 = np.percentile(timings, 99)
qps = len(timings) / (sum(timings) / 1000)
```

## Test Data Generation

### Decision
Use numpy random number generation with fixed seed for reproducible 1024-dimensional vectors.

### Rationale
- Ensures identical test data across all three methods (FR-008 requirement)
- Numpy is fast enough to generate 1M vectors in reasonable time
- Fixed seed ensures reproducibility across benchmark runs
- Vectors distributed in unit hypersphere (realistic embedding distribution)

### Implementation Pattern
```python
import numpy as np

def generate_test_vectors(count: int, dimensions: int = 1024, seed: int = 42):
    """Generate reproducible random vectors for all three database methods"""
    np.random.seed(seed)
    vectors = np.random.uniform(-1.0, 1.0, size=(count, dimensions))
    # Normalize to unit vectors (realistic for embeddings)
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors
```

## Query Templates

### Decision
Define query templates covering three complexity tiers with parameterized vector values.

### Rationale
- Simple SELECT: Baseline database overhead measurement
- Vector similarity: Core use case, tests VECTOR_COSINE/pgvector translation
- Complex joins: Realistic application workload with multiple tables

### Query Categories
1. **Simple**: `SELECT id, value FROM test_table WHERE id = ?`
2. **Vector Similarity**: `SELECT id FROM vectors ORDER BY embedding <-> ? LIMIT 10`
3. **Complex Join**: `SELECT t1.id, t2.value FROM table1 t1 JOIN table2 t2 ON t1.fk = t2.id WHERE t1.vector <-> ? < 0.5`

## Connection Warmup Strategy

### Decision
Execute 100 warmup queries before measurements per FR-009 (avoid cold-start bias).

### Rationale
- Database connections have JIT compilation, query plan caching
- First queries are unrepresentative of steady-state performance
- 100 queries empirically sufficient to reach steady state
- Constitutional compliance with fair comparison requirements

## Error Handling and Abort Behavior

### Decision
Validate all three connections before starting any measurements, abort on first failure.

### Rationale
- FR-006: Abort entire benchmark on connection failure
- Early validation prevents wasted time on partial benchmarks
- Clear error messages indicate which connection method failed

### Implementation Pattern
```python
def validate_connections():
    """Validate all three database connections before benchmarking"""
    errors = []

    try:
        # Test IRIS + PGWire
        pgwire_conn = psycopg.connect("host=localhost port=5432")
        pgwire_conn.close()
    except Exception as e:
        errors.append(f"PGWire connection failed: {e}")

    try:
        # Test PostgreSQL + psycopg3
        pg_conn = psycopg.connect("host=localhost port=5433")
        pg_conn.close()
    except Exception as e:
        errors.append(f"PostgreSQL connection failed: {e}")

    try:
        # Test IRIS + DBAPI
        dbapi_conn = iris.connect(...)
        dbapi_conn.close()
    except Exception as e:
        errors.append(f"IRIS DBAPI connection failed: {e}")

    if errors:
        raise RuntimeError("Connection validation failed:\n" + "\n".join(errors))
```

## Output Formatting

### Decision
Use Python `json` module for JSON output and `tabulate` library for console tables.

### Rationale
- FR-010: Both JSON and console table formats required
- json module is stdlib, no dependencies
- tabulate is lightweight, produces professional tables
- Separate output files prevent mixing formats

### Implementation Pattern
```python
import json
from tabulate import tabulate

# JSON output
results = {
    "timestamp": datetime.utcnow().isoformat(),
    "config": { "vector_dims": 1024, "dataset_size": 100000 },
    "results": {
        "iris_pgwire": { "qps": 1234, "p50": 8.5, "p95": 12.3, "p99": 15.7 },
        "postgresql_psycopg3": { "qps": 2345, "p50": 4.2, "p95": 6.8, "p99": 9.1 },
        "iris_dbapi": { "qps": 987, "p50": 10.1, "p95": 14.5, "p99": 18.3 }
    }
}

with open("results/json/benchmark_run.json", "w") as f:
    json.dump(results, f, indent=2)

# Console table output
table_data = [
    ["IRIS + PGWire", 1234, 8.5, 12.3, 15.7],
    ["PostgreSQL + psycopg3", 2345, 4.2, 6.8, 9.1],
    ["IRIS + DBAPI", 987, 10.1, 14.5, 18.3]
]

print(tabulate(table_data, headers=["Method", "QPS", "P50 (ms)", "P95 (ms)", "P99 (ms)"]))
```

## Research Complete

All unknowns from Technical Context have been resolved. No NEEDS CLARIFICATION markers remain. Ready to proceed to Phase 1: Design & Contracts.
