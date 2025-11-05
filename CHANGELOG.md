# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial PyPI release preparation

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
