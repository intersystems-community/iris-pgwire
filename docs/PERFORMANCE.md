# Performance: IRIS PGWire Benchmarks

**Last Updated**: 2025-12-27
**Related**: [Architecture](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ARCHITECTURE.md), [Vector Parameter Binding](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md), [4-Way Benchmark Results](https://github.com/intersystems-community/iris-pgwire/blob/main/benchmarks/README_4WAY.md)

---

## Executive Summary

**Protocol Translation Overhead**: ~4ms per query (acceptable trade-off for PostgreSQL ecosystem access)

**Key Findings**:
- ✅ ~4ms protocol overhead enables entire PostgreSQL ecosystem
- ✅ Binary parameter encoding 40% more compact than text
- ✅ 100% success rate across all dimensions and execution paths
- ✅ HNSW indexes provide 5.14× speedup on 100K+ vector datasets

**Bottom Line**: IRIS PGWire preserves IRIS native performance while providing PostgreSQL wire protocol compatibility.

---

## Benchmarked Results

### Query Latency

| Metric | Result | Baseline | Overhead | Notes |
|--------|--------|----------|----------|-------|
| **Simple SELECT** | 3.99ms avg, 4.29ms P95 | 0.20ms (IRIS DBAPI) | +3.79ms | Protocol translation |
| **Vector Similarity (128D)** | 6.76ms avg | 2.35ms (IRIS DBAPI) | +4.41ms | Binary parameter encoding |
| **Vector Similarity (1024D)** | 6.94ms avg, 8.05ms P95 | ~2.5ms (estimated) | +4.44ms | High-dimensional vectors |
| **Catalog Query** | ~1.3ms | N/A | N/A | pg_class introspection |

**Measurement Methodology**: 50 iterations per test, cold and warm cache, median and P95 reported.

**Environment**: macOS 14.5, M1 Max, 64GB RAM, Docker Desktop 4.25.0

### Connection Performance

| Metric | Result | Notes |
|--------|--------|-------|
| **Connection Pool Size** | 50 concurrent + 20 overflow | DBAPI backend only |
| **Pool Acquisition Time** | <1ms average | Pre-warmed pool |
| **Connection Latency** | ~15ms (cold), <1ms (warm) | TCP handshake + auth |

### Vector Operations

| Operation | Performance | Speedup | Requirements |
|-----------|-------------|---------|--------------|
| **Cosine Similarity** | 2.35ms (IRIS DBAPI) | Baseline | 128D vectors |
| **Cosine + PGWire** | 6.76ms total | - | Adds ~4.4ms overhead |
| **HNSW Index (100K vectors)** | 5.14× faster | 5.14× | Requires ≥100K dataset |
| **Binary Encoding** | 40% more compact | - | vs text encoding |

**Detailed Vector Benchmarks**: See [Vector Parameter Binding Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md)

---

## See Also

- [4-Way Benchmark Results](https://github.com/intersystems-community/iris-pgwire/blob/main/benchmarks/README_4WAY.md) - Detailed performance comparison
- [Vector Parameter Binding](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md) - Vector optimization guide
- [Architecture](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ARCHITECTURE.md) - System design and overhead sources
