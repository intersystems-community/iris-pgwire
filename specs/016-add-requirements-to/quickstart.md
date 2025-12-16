# Quickstart: Benchmark Debug Capabilities and Vector Optimizer Fix

**Feature**: Fix vector optimizer bracket bug and add debug capabilities
**Expected Duration**: 5-10 minutes for validation
**Prerequisites**: Docker, Python 3.11+, pytest

## Objective

Validate that the vector optimizer correctly preserves brackets in vector literals and that benchmark debug capabilities provide actionable troubleshooting information.

## Setup

```bash
# Ensure Docker containers are running
cd /Users/tdyar/ws/iris-pgwire/benchmarks
docker-compose -f docker-compose.benchmark.yml up -d

# Wait for IRIS to be ready
docker exec iris-benchmark /usr/irissys/dev/Cloud/ICM/waitISC.sh

# Activate virtual environment (if using)
cd /Users/tdyar/ws/iris-pgwire
source .venv/bin/activate  # or your venv activation
```

## Test Procedure

### Step 1: Verify Contract Tests Pass

Validate that the vector optimizer preserves brackets in vector literals.

```bash
# Run contract tests
pytest tests/contract/test_vector_optimizer_syntax.py -v

# Expected output:
# test_optimizer_preserves_brackets_in_literals PASSED
# test_optimizer_handles_all_pgvector_operators PASSED
# test_optimizer_validates_bracket_presence PASSED
```

**Acceptance Criteria**:
- ✅ All contract tests PASS
- ✅ No "brackets stripped" assertion failures

---

### Step 2: Run Dry-Run Mode Validation

Test query validation without executing against IRIS.

```bash
# Run dry-run mode on benchmark queries
python benchmarks/3way_comparison.py \
  --vector-dims 128 \
  --dataset-size 100 \
  --iterations 5 \
  --dry-run

# Expected output:
# ✅ Query validation: simple_select_all - PASS
# ✅ Query validation: vector_cosine - PASS (brackets detected: True)
# ✅ Query validation: vector_l2 - PASS (brackets detected: True)
# ✅ Query validation: vector_inner_product - PASS (brackets detected: True)
# ℹ️ Dry-run mode: No queries executed against database
```

**Acceptance Criteria** (FR-009):
- ✅ All queries validated successfully
- ✅ Bracket detection confirms `[...]` format in vector literals
- ✅ No IRIS execution occurred (dry-run mode)

---

### Step 3: Execute 3-Way Benchmark with Debug Logging

Run full benchmark with enhanced debug output.

```bash
# Run benchmark with debug logging enabled
ENABLE_DEBUG_LOGGING=true python benchmarks/3way_comparison.py \
  --vector-dims 128 \
  --dataset-size 100 \
  --iterations 5

# Expected output:
# [1/5] Setup complete
# [2/5] PostgreSQL: 100 queries, 0 errors
# [3/5] IRIS PGWire: 100 queries, 0 errors
# [4/5] IRIS DBAPI: 100 queries, 0 errors
# [5/5] Results exported to benchmarks/results/
```

**Acceptance Criteria** (FR-005, FR-006, FR-011):
- ✅ No query timeouts (all queries complete within timeout)
- ✅ No IRIS SQLCODE -400 errors
- ✅ Debug logs contain original SQL and optimized SQL
- ✅ Debug logs include query-by-query timing breakdown

---

### Step 4: Verify Debug Output Format

Inspect debug logs for required information.

```bash
# Check JSON output for optimization traces
cat benchmarks/results/json/benchmark_*.json | python -m json.tool | head -50

# Expected structure:
# {
#   "query_id": "vector_cosine",
#   "database_method": "PGWIRE",
#   "execution_time_ms": 12.34,
#   "row_count": 5,
#   "optimization_trace": {
#     "original_sql": "SELECT ... <=> '[0.1,0.2,0.3]' ...",
#     "optimized_sql": "SELECT ... VECTOR_COSINE(..., TO_VECTOR('[0.1,0.2,0.3]', FLOAT)) ...",
#     "transformation_time_ms": 0.45,
#     "validation_status": "PASS",
#     "bracket_detected": true
#   }
# }
```

**Acceptance Criteria** (FR-008, FR-014):
- ✅ `optimization_trace` present for PGWIRE queries
- ✅ `bracket_detected: true` for all vector queries
- ✅ `transformation_time_ms` < 5ms (constitutional requirement)
- ✅ `validation_status: PASS` for all queries

---

### Step 5: Test Query Timeout Protection

Validate that hanging queries timeout instead of blocking indefinitely.

```bash
# Test timeout protection with diagnostic script
python diagnose_hanging_queries.py

# Expected output:
# ✅ simple_select_all     - 10 rows
# ✅ simple_select_id      - 1 rows
# ✅ simple_count          - 1 rows
# ✅ vector_cosine         - 5 rows (with fix, no timeout!)
# ✅ vector_l2             - 5 rows
# ✅ vector_inner_product  - 5 rows
```

**Acceptance Criteria** (FR-004):
- ✅ All queries complete (no timeouts after fix)
- ✅ If timeout occurs, script exits gracefully after 10s
- ✅ No "another command is already in progress" errors

---

### Step 6: Validate Performance Metrics

Confirm P50/P95/P99 latency percentiles in benchmark output.

```bash
# Check console table output
cat benchmarks/results/benchmark_*.txt

# Expected output:
# ┌──────────────────┬─────────┬────────┬────────┬────────┐
# │ Query Template   │ Method  │ P50    │ P95    │ P99    │
# ├──────────────────┼─────────┼────────┼────────┼────────┤
# │ vector_cosine    │ PGWIRE  │ 0.45ms │ 0.62ms │ 0.73ms │
# │ vector_cosine    │ POSTGRES│ 0.58ms │ 1.58ms │ 1.64ms │
# │ vector_cosine    │ DBAPI   │ 0.38ms │ 0.51ms │ 0.59ms │
# └──────────────────┴─────────┴────────┴────────┴────────┘
```

**Acceptance Criteria** (FR-017):
- ✅ P50/P95/P99 latency percentiles displayed
- ✅ PGWIRE performance comparable to DBAPI (±20%)
- ✅ All methods return identical row counts

---

## Cleanup

```bash
# Stop Docker containers (optional, for teardown)
cd /Users/tdyar/ws/iris-pgwire/benchmarks
docker-compose -f docker-compose.benchmark.yml down -v
```

---

## Success Criteria Summary

| Requirement | Test Step | Status |
|-------------|-----------|--------|
| FR-001: Bracket preservation | Step 1 | Contract test PASS |
| FR-002: SQL validation | Step 2 | Dry-run mode PASS |
| FR-003: IRIS error context | Step 3 | No SQLCODE -400 errors |
| FR-004: Query timeouts | Step 5 | No indefinite hangs |
| FR-005: Optimization logging | Step 4 | Traces in JSON output |
| FR-006: Timing breakdown | Step 4 | Phases logged |
| FR-008: Bracket detection | Step 4 | `bracket_detected: true` |
| FR-009: Dry-run mode | Step 2 | Validates without execution |
| FR-014: <5ms optimization | Step 4 | `transformation_time_ms` < 5 |
| FR-017: P50/P95/P99 metrics | Step 6 | Percentiles displayed |

---

## Troubleshooting

### Issue: Contract tests fail with "brackets stripped"

**Diagnosis**: Vector optimizer regex not fixed
**Fix**: Check `src/iris_pgwire/vector_optimizer.py` for regex pattern
**Expected**: `r"([\w\.]+|'[^']*'|\[[^\]]*\])\s*<=>\s*(\[[^\]]*\])"` preserves brackets

### Issue: IRIS SQLCODE -400 errors still occur

**Diagnosis**: SQL validation not catching malformed syntax
**Fix**: Check `VectorOptimizer.validate_sql()` implementation
**Expected**: Validation MUST detect missing brackets before IRIS execution

### Issue: Queries still timeout after fix

**Diagnosis**: PGWire server not restarted with new code
**Fix**: Rebuild and restart pgwire-benchmark container:
```bash
docker-compose -f docker-compose.benchmark.yml down
docker-compose -f docker-compose.benchmark.yml build pgwire-benchmark
docker-compose -f docker-compose.benchmark.yml up -d
```

### Issue: Debug logs missing optimization traces

**Diagnosis**: `ENABLE_DEBUG_LOGGING` environment variable not set
**Fix**: Export before running benchmark:
```bash
export ENABLE_DEBUG_LOGGING=true
python benchmarks/3way_comparison.py --vector-dims 128 --dataset-size 100 --iterations 5
```

---

**Validation Complete**: If all 6 steps pass, the feature is working as specified.
