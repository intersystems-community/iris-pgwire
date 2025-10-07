# 4-Way Database Performance Benchmark

Comprehensive comparison of all architectural paths for vector similarity queries.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     4-Way Benchmark Paths                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. psycopg3 → PostgreSQL:5433 → pgvector (BASELINE)            │
│     [External Python] → [PostgreSQL] → [pgvector extension]     │
│                                                                  │
│  2. DBAPI → IRIS:1974 (DIRECT)                                  │
│     [External Python] → [IRIS SuperServer TCP]                  │
│                                                                  │
│  3. psycopg3 → PGWire:5434 (DBAPI) → IRIS:1974                  │
│     [External Python] → [PGWire DBAPI backend] → [IRIS TCP]     │
│                                                                  │
│  4. psycopg3 → PGWire:5435 (EMBEDDED) → IRIS:1975               │
│     [External Python] → [PGWire embedded] → [IRIS irispython]   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Start all services and run benchmark (100 iterations, 1024D vectors)
./benchmarks/run_4way_benchmark.sh

# Quick test (10 iterations)
./benchmarks/run_4way_benchmark.sh 10 1024

# Production benchmark (1000 iterations)
./benchmarks/run_4way_benchmark.sh 1000 1024
```

## Manual Setup

### 1. Start Services

```bash
cd benchmarks
docker compose -f docker-compose.4way.yml up -d
```

**Services Started**:
- `postgres-4way` (port 5433) - PostgreSQL 16 with pgvector
- `iris-4way` (port 1974) - IRIS main instance (paths 2 & 3)
- `pgwire-4way-dbapi` (port 5434) - PGWire with DBAPI backend
- `iris-4way-embedded` (port 1975+5435) - IRIS with embedded PGWire

### 2. Setup Test Data

```bash
python3 benchmarks/setup_4way_data.py
```

This creates `benchmark_vectors` table with 1000 1024-dimensional vectors across all databases.

### 3. Run Benchmark

```bash
python3 benchmarks/4way_comparison.py \
    --iterations 100 \
    --dimensions 1024 \
    --output benchmarks/results/my_results.json
```

## Configuration

### Environment Variables

**PGWire DBAPI Backend** (docker-compose.4way.yml):
```yaml
- PGWIRE_BACKEND_TYPE=dbapi
- IRIS_HOSTNAME=iris-benchmark
- IRIS_PORT=1972
- IRIS_USERNAME=_SYSTEM
- IRIS_PASSWORD=SYS
```

**PGWire Embedded Backend**:
```yaml
- PGWIRE_BACKEND_TYPE=embedded
# No IRIS connection needed - runs inside IRIS process
```

### Benchmark Parameters

```bash
python3 benchmarks/4way_comparison.py \
    --iterations 1000 \        # Number of iterations per query
    --dimensions 1024 \        # Vector dimensions
    --output results.json \    # Output file
    --skip-validation          # Skip connection validation (not recommended)
```

## Output Format

### Console Output

```
4-WAY BENCHMARK SUMMARY
================================================================================

SIMPLE_SELECT
--------------------------------------------------------------------------------
Path                            Avg (ms)   P95 (ms)   P99 (ms)  Success %
--------------------------------------------------------------------------------
1_postgres_pgvector                1.23       1.45       1.67       100.0
2_dbapi_iris_direct                0.89       1.12       1.34       100.0
3_pgwire_dbapi_iris                1.45       1.78       2.01       100.0
4_pgwire_embedded_iris             0.95       1.23       1.45       100.0

VECTOR_SIMILARITY
--------------------------------------------------------------------------------
Path                            Avg (ms)   P95 (ms)   P99 (ms)  Success %
--------------------------------------------------------------------------------
1_postgres_pgvector                5.67       6.23       6.89       100.0
2_dbapi_iris_direct                3.45       4.12       4.67       100.0
3_pgwire_dbapi_iris                4.23       5.01       5.67       100.0
4_pgwire_embedded_iris             3.67       4.34       4.89       100.0

================================================================================
WINNERS BY QUERY TYPE
================================================================================
simple_select: 2_dbapi_iris_direct (0.89ms avg)
vector_similarity: 2_dbapi_iris_direct (3.45ms avg)
```

### JSON Output

```json
{
  "benchmark_config": {
    "iterations": 100,
    "dimensions": 1024,
    "timestamp": "2025-10-05 17:30:00"
  },
  "results": [
    {
      "path_name": "1_postgres_pgvector",
      "query_type": "simple_select",
      "iterations": 100,
      "avg_latency_ms": 1.23,
      "p50_latency_ms": 1.20,
      "p95_latency_ms": 1.45,
      "p99_latency_ms": 1.67,
      "min_latency_ms": 0.98,
      "max_latency_ms": 2.01,
      "success_rate": 100.0
    }
  ]
}
```

## Expected Results

Based on Feature 018 performance requirements and vector optimization (FR-018):

**Hypothesis**:
1. **Path 2 (DBAPI direct)**: Fastest - no protocol overhead
2. **Path 4 (PGWire embedded)**: Close second - no TCP overhead to IRIS
3. **Path 3 (PGWire DBAPI)**: Slight overhead from DBAPI connection pooling
4. **Path 1 (PostgreSQL)**: Baseline for comparison

**Vector Performance SLA** (Constitutional Principle VI):
- Translation overhead <5ms for paths 3 & 4
- All IRIS paths should outperform PostgreSQL for large vectors (>1000D)

## Troubleshooting

### Connection Failures

Check service health:
```bash
docker compose -f benchmarks/docker-compose.4way.yml ps
docker compose -f benchmarks/docker-compose.4way.yml logs pgwire-dbapi
docker compose -f benchmarks/docker-compose.4way.yml logs iris-pgwire-embedded
```

### PGWire Server Not Starting

Check IRIS embedded Python logs:
```bash
docker exec iris-4way-embedded cat /tmp/pgwire.log
```

### Data Setup Failures

Manually verify connections:
```bash
# PostgreSQL
psql -h localhost -p 5433 -U postgres -d benchmark -c "SELECT COUNT(*) FROM benchmark_vectors"

# IRIS via DBAPI
docker exec iris-4way iris sql -U%SYS "SELECT COUNT(*) FROM benchmark_vectors"
```

## Cleanup

```bash
# Stop all services
docker compose -f benchmarks/docker-compose.4way.yml down

# Remove volumes
docker compose -f benchmarks/docker-compose.4way.yml down -v
```

## References

- **Feature 018**: DBAPI Backend Option (specs/018-add-dbapi-option/)
- **Constitutional Principle VI**: Vector Performance Requirements
- **FR-018**: Translation Overhead <5ms P95 for 100K vectors
