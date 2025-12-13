# Quickstart: 3-Way Database Performance Benchmark

## Prerequisites

1. **IRIS Database**: Existing container from kg-ticket-resolver running on port 1972
2. **PostgreSQL with pgvector**: New container required on port 5433
3. **PGWire Server**: Running on port 5432 (from iris-pgwire project)
4. **Python 3.11+**: With uv package manager

## Setup Steps

### 1. Start PostgreSQL with pgvector

```bash
# Pull and start PostgreSQL container with pgvector extension
docker run --name postgres-benchmark \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=benchmark \
  -p 5433:5432 \
  -d pgvector/pgvector:pg16

# Verify pgvector extension
docker exec postgres-benchmark psql -U postgres -d benchmark \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 2. Install Python Dependencies

```bash
# From iris-pgwire repository root
uv pip install psycopg[binary] numpy tabulate intersystems-iris-dbapi
```

### 3. Verify All Three Connections

Run the connection validation script:

```bash
python benchmarks/validate_connections.py
```

Expected output:
```
✅ IRIS + PGWire connection successful (localhost:5432)
✅ PostgreSQL + psycopg3 connection successful (localhost:5433)
✅ IRIS + DBAPI connection successful (localhost:1972)

All three database methods ready for benchmarking.
```

## Running the Benchmark

### Basic Benchmark Run

```bash
# Run with default configuration (1024D vectors, 100K rows)
python benchmarks/3way_comparison.py

# Output displays to console and saves to:
# - benchmarks/results/json/benchmark_TIMESTAMP.json
# - benchmarks/results/tables/benchmark_TIMESTAMP.txt
```

### Custom Configuration

```bash
# Run with custom parameters
python benchmarks/3way_comparison.py \
  --vector-dims 512 \
  --dataset-size 500000 \
  --iterations 2000
```

### Configuration File

Create `benchmarks/config.yaml`:

```yaml
vector_dimensions: 1024
dataset_size: 100000
iterations: 1000
concurrent_connections: 1
warmup_queries: 100
random_seed: 42

connections:
  iris_pgwire:
    host: localhost
    port: 5432
    database: USER
  postgresql_psycopg3:
    host: localhost
    port: 5433
    database: benchmark
    username: postgres
    password: postgres
  iris_dbapi:
    host: localhost
    port: 1972
    database: USER
    username: _SYSTEM
    password: SYS
```

Run with config file:

```bash
python benchmarks/3way_comparison.py --config benchmarks/config.yaml
```

## Expected Output

### Console Table (FR-010)

```
3-Way Database Performance Benchmark
=====================================
Configuration:
  Vector Dimensions: 1024
  Dataset Size: 100,000 rows
  Iterations: 1000 per query type

Results:
Method                    QPS      P50 (ms)  P95 (ms)  P99 (ms)
----------------------  -------  ----------  --------  --------
IRIS + PGWire           1234.5        8.3      12.7      15.9
PostgreSQL + psycopg3   2345.6        4.2       6.8       9.1
IRIS + DBAPI             987.3       10.1      14.5      18.3

Benchmark completed in 123.4 seconds.
Results saved to benchmarks/results/json/benchmark_20250103_123456.json
```

### JSON Output (FR-010)

```json
{
  "report_id": "benchmark_20250103_123456",
  "timestamp": "2025-01-03T12:34:56Z",
  "config": {
    "vector_dimensions": 1024,
    "dataset_size": 100000,
    "iterations": 1000
  },
  "duration_seconds": 123.4,
  "results": {
    "iris_pgwire": {
      "qps": 1234.5,
      "latency_p50_ms": 8.3,
      "latency_p95_ms": 12.7,
      "latency_p99_ms": 15.9,
      "queries_executed": 3000,
      "queries_failed": 0
    },
    "postgresql_psycopg3": {
      "qps": 2345.6,
      "latency_p50_ms": 4.2,
      "latency_p95_ms": 6.8,
      "latency_p99_ms": 9.1,
      "queries_executed": 3000,
      "queries_failed": 0
    },
    "iris_dbapi": {
      "qps": 987.3,
      "latency_p50_ms": 10.1,
      "latency_p95_ms": 14.5,
      "latency_p99_ms": 18.3,
      "queries_executed": 3000,
      "queries_failed": 0
    }
  }
}
```

## Validation Scenarios

### Acceptance Scenario 1: All Three Methods Configured (FR-001)

```bash
# Test: Benchmark runs with all three methods
python benchmarks/3way_comparison.py

# Verify: Output shows results for all three methods
grep -c "iris_pgwire\|postgresql_psycopg3\|iris_dbapi" benchmarks/results/json/benchmark_*.json
# Expected: 3 (one for each method)
```

### Acceptance Scenario 2: Multiple Query Types (FR-002)

```bash
# Test: Benchmark executes simple, vector, and join queries
python benchmarks/3way_comparison.py --verbose

# Verify: Console shows all three categories
# Expected output includes:
#   Testing simple SELECT queries...
#   Testing vector similarity queries...
#   Testing complex join queries...
```

### Acceptance Scenario 3: Performance Metrics (FR-004)

```bash
# Test: Results include QPS and latency percentiles
python benchmarks/3way_comparison.py

# Verify: JSON contains required metrics
jq '.results.iris_pgwire | keys' benchmarks/results/json/benchmark_*.json
# Expected: ["latency_p50_ms", "latency_p95_ms", "latency_p99_ms", "qps", ...]
```

### Acceptance Scenario 4: Configuration Control (FR-005)

```bash
# Test: Custom parameters are respected
python benchmarks/3way_comparison.py --vector-dims 512 --dataset-size 200000

# Verify: Configuration in output
jq '.config' benchmarks/results/json/benchmark_*.json
# Expected: { "vector_dimensions": 512, "dataset_size": 200000, ... }
```

## Error Handling Tests

### Connection Failure Abort (FR-006)

```bash
# Test: Stop PostgreSQL container to simulate failure
docker stop postgres-benchmark

# Run benchmark
python benchmarks/3way_comparison.py

# Expected: Benchmark aborts with clear error message
# Error: Connection validation failed:
# PostgreSQL connection failed: could not connect to server
```

### Restart and retry:

```bash
docker start postgres-benchmark
python benchmarks/3way_comparison.py
# Expected: Successful completion
```

## Performance Validation

### Constitutional Compliance Check

```bash
# Test: Translation overhead < 5ms (constitutional requirement)
python benchmarks/3way_comparison.py --iterations 10000

# Verify: Check raw results for outliers
jq '.results[].latency_p99_ms' benchmarks/results/json/benchmark_*.json

# Expected: All P99 values should be reasonable (<100ms for simple queries)
# If translation overhead were >5ms, we'd see consistent baseline overhead
```

### Vector Scale Validation (Constitution Principle VI)

```bash
# Test: Large dataset performance (100K+ vectors)
python benchmarks/3way_comparison.py --dataset-size 100000

# Verify: HNSW indexes are being used (check EXPLAIN plans manually if needed)
# Expected: Vector similarity queries complete in reasonable time
```

## Cleanup

```bash
# Remove PostgreSQL benchmark container
docker stop postgres-benchmark
docker rm postgres-benchmark

# Clean up result files
rm -rf benchmarks/results/*
```

## Troubleshooting

### "IRIS + PGWire connection failed"
- Check PGWire server is running: `ps aux | grep iris_pgwire`
- Start server: `python -m iris_pgwire.server`

### "PostgreSQL connection failed"
- Check container status: `docker ps | grep postgres-benchmark`
- Check logs: `docker logs postgres-benchmark`

### "IRIS + DBAPI connection failed"
- Verify IRIS container running: `docker ps | grep iris`
- Check IRIS port: `netstat -an | grep 1972`

### "Out of memory during vector generation"
- Reduce dataset size: `--dataset-size 100000`
- Vector generation is memory-intensive with large dimensions

## Next Steps

After successful quickstart validation:

1. Review benchmark results to understand performance characteristics
2. Run with different dataset sizes to observe scaling behavior
3. Compare results across different query complexity tiers
4. Document any unexpected performance patterns for investigation

---

**Note**: This quickstart validates all functional requirements (FR-001 through FR-010) and constitutional compliance. Each scenario maps to specific acceptance criteria from spec.md.
