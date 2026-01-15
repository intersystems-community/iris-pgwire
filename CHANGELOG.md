# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Multi-Action ALTER TABLE Splitting**: Automatically decomposes PostgreSQL-style multi-column `ALTER TABLE` statements (e.g., multiple `ADD COLUMN` or `DROP COLUMN` actions) into individual IRIS-compatible statements.
- **IRIS Bridge Gaps** (Feature 026): Comprehensive performance and functionality enhancements for IRIS integration
  - **Fast Path Bulk Insert**: Protocol-level batching achieving 3,700+ rows/second (11× improvement)
  - **HNSW Index Translation**: Support for PostgreSQL `USING hnsw` translated to IRIS `AS HNSW`
  - **Recursive JSON Pathing**: Support for nested `->` and `->>` operators translated to `JSON_VALUE`
  - **DDL Idempotency**: Full `IF NOT EXISTS` support for `CREATE TABLE` and `CREATE INDEX`
  - **Simple Query Translation**: Enabled full SQL translation for the standard PostgreSQL query protocol
- **P6 COPY Protocol** (Feature 023): PostgreSQL COPY FROM STDIN and COPY TO STDOUT for bulk data operations
  - Bulk data import/export with CSV processing and streaming
  - 1000-row batching for memory efficiency (<100MB for 1M rows)
  - Transaction integration with automatic rollback on errors
  - Query-based export support (`COPY (SELECT ...) TO STDOUT`)
  - Performance: 600+ rows/second sustained throughput

### Fixed
- Fixed critical bug in translation cache causing `TypeError` with mixed naive/aware datetimes
- Standardized all internal timestamps to timezone-aware UTC
- Fixed `CREATE INDEX` idempotency via specialized comment marker `/* IF_NOT_EXISTS */`
- Dynamic versioning recognition in package metadata validation
- Python bytecode cleanup (95+ artifacts removed from git)
- Black code formatting (20 files reformatted to compliance)
- asyncpg parameter type OID inference from CAST expressions
- PostgreSQL compatibility documentation improvements

### Security
- Upgraded authlib to 1.6.5 (fixes 3 HIGH severity CVEs)
- Upgraded cryptography to 46.0.3 (fixes 1 HIGH severity CVE)

### Performance
- High-performance DML Fast Path: Buffering and collapsing `Sync` cycles into bulk IRIS calls
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
