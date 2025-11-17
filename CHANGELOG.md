# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **P6 COPY Protocol** (Feature 023): PostgreSQL COPY FROM STDIN and COPY TO STDOUT for bulk data operations
  - Bulk data import/export with CSV processing and streaming
  - 1000-row batching for memory efficiency (<100MB for 1M rows)
  - Transaction integration with automatic rollback on errors
  - Query-based export support (`COPY (SELECT ...) TO STDOUT`)
  - Performance: 600+ rows/second sustained throughput
- **Package Quality Validation System** (Feature 025): Automated PyPI readiness validation
  - Comprehensive validators for metadata, code quality, security, and documentation
  - CLI tool: `python -m iris_pgwire.quality` with JSON/Markdown output
  - Integration with pyroma, black, ruff, mypy, bandit, pip-audit, interrogate
  - 95.4% docstring coverage (exceeds 80% target)
  - PEP 621 dynamic versioning support
- **PostgreSQL Parameter Placeholders** (Feature 018): Support for `$1, $2` parameter syntax with type inference
  - Automatic type inference from CAST expressions (`$1::INTEGER`)
  - Translation to IRIS `?` placeholders with proper type mapping
  - asyncpg client compatibility improvements
- **PostgreSQL Transaction Verbs** (Feature 022): BEGIN/COMMIT/ROLLBACK translation
  - Translation of PostgreSQL `BEGIN` to IRIS `START TRANSACTION`
  - Full transaction state management
  - Constitutional compliance: <0.1ms translation overhead

### Fixed
- Dynamic versioning recognition in package metadata validation
- Python bytecode cleanup (95+ artifacts removed from git)
- Black code formatting (20 files reformatted to compliance)
- asyncpg parameter type OID inference from CAST expressions
- PostgreSQL compatibility documentation improvements

### Security
- Upgraded authlib to 1.6.5 (fixes 3 HIGH severity CVEs)
- Upgraded cryptography to 46.0.3 (fixes 1 HIGH severity CVE)

### Performance
- IRIS executemany() optimization for 4-10× performance improvement in bulk operations
- COPY protocol optimized for 600+ rows/second sustained throughput
- Memory-efficient streaming for large result sets

## [0.1.0] - 2025-01-05

### Added
- PostgreSQL wire protocol server for InterSystems IRIS
- Dual backend execution paths (DBAPI and Embedded Python)
- Support for vectors up to 188,962 dimensions (1.44 MB)
- pgvector compatibility layer with operator translation
- Async SQLAlchemy support (86% complete, production-ready)
- FastAPI integration with async database sessions
- Zero-configuration BI tools integration (Apache Superset, Metabase, Grafana)
- SQL Translation REST API with <5ms SLA
- Connection pooling with 50+20 async connections
- HNSW vector index support (5× speedup at 100K+ scale)
- Binary parameter encoding for large vectors (40% more compact)
- Constitutional compliance framework with 5ms SLA tracking
- Comprehensive documentation and examples

### Performance
- ~4ms protocol translation overhead (preserves IRIS native performance)
- Simple query latency: 3.99ms avg, 4.29ms P95
- Vector similarity (1024D): 6.94ms avg, 8.05ms P95
- 100% success rate across all dimensions and execution paths

### Documentation
- Complete BI tools setup guide
- Async SQLAlchemy quick reference
- Vector parameter binding documentation
- Dual-path architecture guide
- HNSW performance investigation findings
- Translation API reference

[Unreleased]: https://github.com/intersystems-community/iris-pgwire/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/intersystems-community/iris-pgwire/releases/tag/v0.1.0
