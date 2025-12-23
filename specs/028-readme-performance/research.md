# Research: README Performance Benchmarks Section

**Feature**: 028-readme-performance
**Phase**: Phase 0 - Research
**Date**: 2025-12-18

## Benchmark Data Analysis

### Data Source
**File**: `benchmarks/results/benchmark_4way_results.json`
**Test Date**: 2025-10-05 17:07:56
**Configuration**:
- Iterations: 50
- Vector Dimensions: 128

### Raw Results

#### Simple SELECT Queries

| Connection Path | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Min (ms) | Max (ms) |
|-----------------|----------|----------|----------|----------|----------|----------|
| PostgreSQL (pgvector) | 0.32 | 0.29 | 0.39 | 0.77 | 0.26 | 0.77 |
| **IRIS DBAPI Direct** | **0.21** | 0.20 | 0.25 | 0.73 | 0.16 | 0.73 |
| PGWire + DBAPI | 3.82 | 3.99 | 4.29 | 4.80 | 1.96 | 4.80 |
| PGWire + Embedded | 4.75 | 4.33 | 7.01 | 7.63 | 1.99 | 7.63 |

#### Vector Similarity Queries

| Connection Path | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Min (ms) | Max (ms) |
|-----------------|----------|----------|----------|----------|----------|----------|
| PostgreSQL (pgvector) | 0.59 | 0.43 | 1.21 | 2.40 | 0.33 | 2.40 |
| **IRIS DBAPI Direct** | **2.35** | 2.13 | 4.74 | 5.03 | 2.01 | 5.03 |
| PGWire + DBAPI | 6.76 | 6.94 | 8.05 | 8.57 | 4.39 | 8.57 |
| PGWire + Embedded | N/A | N/A | N/A | N/A | N/A | N/A |

### Key Findings

1. **IRIS DBAPI Direct is Fastest for Simple Queries**
   - 0.21ms average vs 0.32ms PostgreSQL (34% faster)
   - This is due to optimized IRIS SQL engine for simple operations

2. **PostgreSQL pgvector is Fastest for Vector Queries**
   - 0.59ms average vs 2.35ms IRIS DBAPI (4× faster)
   - Native pgvector operators are highly optimized

3. **PGWire Protocol Translation Overhead**
   - Adds ~3.5-4.5ms to query latency
   - Consistent overhead across query types
   - Acceptable for PostgreSQL client compatibility

4. **PGWire + DBAPI vs PGWire + Embedded**
   - DBAPI path slightly faster (3.82ms vs 4.75ms)
   - Embedded path has higher variance (p95: 7.01ms)

### Performance Comparison Summary

| Metric | IRIS DBAPI Direct | PGWire + DBAPI | Overhead |
|--------|-------------------|----------------|----------|
| Simple SELECT | 0.21ms | 3.82ms | **18.2×** |
| Vector Similarity | 2.35ms | 6.76ms | **2.9×** |

### Decision: Section Content

**Decision**: Include performance table with all 4 connection paths, highlighting IRIS DBAPI Direct as the fastest option for users who can use the IRIS driver directly.

**Rationale**:
- Developers need to understand the performance tradeoffs
- IRIS DBAPI Direct should be highlighted for performance-critical applications
- PGWire overhead is acceptable for PostgreSQL compatibility requirements

**Alternatives Considered**:
- Only showing PGWire results (rejected: doesn't show full picture)
- Including all percentile metrics (rejected: too detailed for README)
- Separate performance documentation only (rejected: key info should be in README)

### Recommended README Content

```markdown
## Performance Benchmarks

Connection path latency comparison (50 iterations, 128-dimensional vectors):

| Connection Path | Simple SELECT | Vector Similarity | Best For |
|-----------------|---------------|-------------------|----------|
| **IRIS DBAPI Direct** | **0.21ms** | 2.35ms | Maximum performance |
| PGWire + DBAPI | 3.82ms | 6.76ms | PostgreSQL compatibility |
| PGWire + Embedded | 4.75ms | N/A | Single-container deployment |
| PostgreSQL (baseline) | 0.32ms | 0.59ms | Reference comparison |

**Key Takeaways**:
- IRIS DBAPI direct connection is ~18× faster than PGWire for simple queries
- PGWire adds ~4ms protocol translation overhead for PostgreSQL client compatibility
- For maximum performance, use IRIS DBAPI driver directly when PostgreSQL compatibility isn't required

*Benchmarks run on [date]. See [benchmarks/README_4WAY.md](benchmarks/README_4WAY.md) for methodology.*
```

## Research Complete

All questions resolved - ready for implementation.
