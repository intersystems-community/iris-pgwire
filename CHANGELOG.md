# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] - 2026-01-17

### Fixed
- **Robust Schema Mapping**: Rewrote `translate_input_schema` to correctly handle double-quoted schema names (e.g., `"public"."table"`). Previously, word boundaries caused a dangling quote issue (e.g., `"SQLUser."table"`).
- **Reserved Word Conflict Protection**: Added automatic quoting and uppercasing for unquoted table names during schema mapping. This ensures that tables like `user` (an IRIS reserved word) are correctly translated to `SQLUser."USER"`.
- **Centralized Mapping in Executor**: Integrated the centralized `translate_input_schema` into `iris_executor.py`, ensuring consistent behavior between embedded and DBAPI modes.
- **Robust Generated Column Stripping**: Updated regex to handle multiline column definitions and nested parentheses more reliably.

## [1.1.0] - 2026-01-17

### Added
- **IRIS Technical Reference**: Added definitive guide to `AGENTS.md` covering DBAPI connection patterns, embedded SQL parameter passing, and case-sensitivity rules.

### Fixed
- **Robust Schema Mapping**: Rewrote `translate_input_schema` to correctly preserve table name quoting and casing (e.g., `public."workflow"` -> `SQLUser."workflow"`). This resolves "Class not found" errors in IRIS when ORMs use quoted identifiers.
- **Embedded Parameter Passing**: Ensured `iris.sql.exec` receives parameters as positional arguments using the splat operator (`*params`) in all execution paths.
- **Redundant Translation Cleanup**: Removed conflicting schema translation regexes in `iris_executor.py` that were previously stripping quotes from identifiers.

## [1.0.9] - 2026-01-17

### Fixed
- **Parameter Passing Bug**: Fixed `iris_executor.py` to correctly pass parameters to `iris.sql.exec(*params)`, enabling parameterized queries in embedded mode.
- **Schema Case Sensitivity**: Fixed normalizer to preserve `SQLUser` casing (instead of `SQLUSER`), satisfying case-sensitive package requirements in IRIS.
- **DDL Case Sensitivity**: Fixed `IdentifierNormalizer` to respect quoted identifier casing in `CREATE TABLE` statements, preventing "Class not found" errors during subsequent queries.

## [1.0.8] - 2026-01-17

### Added
- **Final DDL Compatibility Polish**: Refined regex patterns for `USING btree` and PostgreSQL cast stripping to handle broader syntax variations.
- **Enhanced Integration Testing**: Added comprehensive end-to-end migration test covering all Feature 036 constructs.

## [1.0.7] - 2026-01-17

### Added
- **PostgreSQL DDL Compatibility Enhancement**: Implemented automatic interception and transformation of PostgreSQL-specific DDL constructs to enable seamless migrations.
- **Generated Column Stripping**: Added support for automatically removing `GENERATED ALWAYS AS ... STORED` column definitions from `CREATE TABLE` statements.
- **Enum Type Registration**: Added logic to skip `CREATE TYPE ... AS ENUM`, register the type name, and automatically map subsequent columns using that type to `VARCHAR(64)`.
- **Index Dependency Tracking**: Implemented `SkippedTableSet` to track tables whose creation was skipped, ensuring dependent `CREATE INDEX` statements are also skipped.
- **Strict DDL Mode**: Added a configurable `strict_ddl` flag (default `false`) to control whether unsupported constructs should be skipped with a warning or raise an error.
- **Construct Stripping**: Added automatic stripping of `USING btree`, PostgreSQL type casts (`::type`), and `WITH (fillfactor)` from DDL statements.

## [1.0.6] - 2026-01-16

### Added
- **Multi-statement DDL with comments**: Updated `DdlSplitter` to be fully comment-aware and strip comments before execution to prevent IRIS parsing errors.
- **Prepared statement translation ($n → ?)**: Consolidated parameter translation logic into `SQLTranslator` for consistency across all query paths.
- **Default keyword in VALUES clause**: Implemented `DefaultValuesTranslator` to rewrite `INSERT` statements using `DEFAULT` within `VALUES` lists.
- **Timestamp binding normalization**: Updated `DATETranslator` and `IRISExecutor` to normalize ISO 8601 timestamps (stripping `T`, `Z`, and offsets) into IRIS-accepted ODBC formats.
- **ALTER TABLE translation**: Updated `DdlSplitter` to translate PostgreSQL `SET DATA TYPE` and `DROP NOT NULL` syntax to IRIS-compatible `ALTER COLUMN` commands.

### Fixed
- Fixed IRIS execution error "Input encountered after end of query" by improving semicolon and comment handling in the DDL splitter.
- Resolved "LITERAL (1) found" errors during migrations by avoiding no-op SELECT injections for skipped DDL.
- Enhanced IRIS data type mapping to better handle PostgreSQL OIDs (e.g., `BIGINT`, `TINYINT`).

## [1.0.5] - 2026-01-15


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
