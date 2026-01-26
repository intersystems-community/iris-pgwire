# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.23] - 2026-01-25

### Fixed
- **Namespace Stabilization**: Added a `%SYS` reset and retry logic to `SetNamespace` in embedded mode. This prevents `<NAMESPACE>` errors when switching context immediately after a database restore or creation.
- **Improved Reliability**: Mitigated race conditions and stale configuration cache issues in `irispython` environments.

## [1.2.22] - 2026-01-25

## [1.2.21] - 2026-01-18

### Fixed
- **Vector Cast Support**: Added explicit translation for `CAST(expr AS vector)` and `expr::vector` into IRIS-native `TO_VECTOR(expr, DOUBLE)`, resolving the "'VECTOR' is not a supported CAST target" error.
- **Function Mapping**: Integrated pgvector function name mapping (e.g., `vector_cosine_distance` → `VECTOR_COSINE`) into the unified translation pipeline.
- **Robust Placeholder Handling**: Updated translator to convert `%s` placeholders to `?` early, preventing incorrect normalization to `%S`.

## [1.2.1] - 2026-01-17

### Fixed
- **Definitive Model Stabilization**: Bumping version to ensure all TDD-verified model fixes are included in the published package. Resolves `KeyError: 'cache_hit'` by ensuring consistent `PerformanceStats` object propagation.

## [1.2.0] - 2026-01-17

### Added
- **Quality Assurance Suite**: Introduced `test_sql_translation_pipeline_quality.py` to ensure model consistency and protocol stability across releases.

### Fixed
- **Major Model Stabilization**: Unified `TranslationResult` and `PerformanceStats` across the entire pipeline.
- **Protocol Reliability**: Fixed `AttributeError` and `KeyError` in `protocol.py` by standardizing on validated dataclass objects instead of raw dictionaries.
- **Consistent Schema Naming**: Ensured `translated_sql` is used consistently across all integration tests and the core pipeline.

## [1.1.9] - 2026-01-17


## [1.1.8] - 2026-01-17

### Fixed
- **Protocol Data Model Alignment**: Switched from object attribute to dictionary access for `performance_stats` in `protocol.py`. This fixes the `AttributeError` when processing queries.
- **Cache Hit Metric**: Ensured `cache_hit` is always present in the performance dictionary returned by the SQL pipeline, resolving `KeyError` crashes.
- **Authorship & License**: Updated LICENSE and documentation to correctly reflect Thomas Dyar as the author and owner.

## [1.1.7] - 2026-01-17

### Fixed
- **AttributeError in Protocol**: Fixed `PGWireProtocol` to use dictionary access instead of dot notation for `performance_stats` returned by the new `SQLPipeline`.
- **KeyError in Protocol**: Added missing `cache_hit` key to the `performance_stats` dictionary in `SQLTranslator` to prevent crashes during statement parsing.
- **Embedded Namespace Context**: Strengthened the `SetNamespace` logic in background execution threads to ensure consistent IRIS namespace context and prevent intermittent "Class not found" errors.
- **Redundant SQL Mapping**: Removed legacy schema translation code in `iris_executor.py` that was conflicting with the centralized `SQLPipeline`.

## [1.1.6] - 2026-01-17

### Changed
- **Structural Simplification**: Decoupled 350+ lines of query interception logic from `IRISExecutor` into a dedicated `SQLInterceptor` registry.
- **Centralized SQL Pipeline**: Implemented `SQLPipeline` to orchestrate all SQL transformations (filtering, normalization, refinement, optimization) in a single pass, ensuring consistency and preventing redundant processing.
- **Unified SQL Refinement**: Created `SQLRefiner` to host ad-hoc IRIS-specific fixes (like the `ORDER BY` alias fix), removing redundant and inconsistent regex logic from `protocol.py` and `vector_optimizer.py`.

## [1.1.5] - 2026-01-17

### Fixed
- **Robust Identifier Normalization**: Removed word boundaries from the `IdentifierNormalizer` regex to ensure qualified names (e.g., `SQLUser."WORKFLOW"`) are always matched as a single unit, even with complex quoting or whitespace around dots.
- **Idempotent Bare Table Mapping**: Added a look-back check in `schema_mapper.py` to prevent double-prefixing of tables (e.g., `SQLUser.SQLUser."TABLE"`) when the schema is already present but separated by whitespace.
- **Improved SAVEPOINT Handling**: Ensured savepoint identifiers are matched correctly within the new unified identifier pattern.

## [1.1.4] - 2026-01-17

### Changed
- **Author Update**: Formally updated `__author__` to Thomas Dyar.
- **Status Update**: Promoted package to "Stable/Production" status.

## [1.1.3] - 2026-01-17

### Fixed
- **Redundant SQL Transformation**: Removed a redundant call to `translate_input_schema` in `IRISExecutor`. This prevented "double patching" where identifiers could be incorrectly nested (e.g., `SQLUser."SQLUser."TABLE""`).
- **Namespace Context in Embedded Python**: Added explicit `SetNamespace` calls in the background threads used by `iris.sql.exec`. This ensures reliable class resolution and prevents "Class not found" errors in embedded mode.
- **Qualified Identifier Normalization**: Updated the identifier normalizer regex and replacement logic to handle dots properly. Schema-qualified names (like `SQLUser."USER"`) are now handled as single units, ensuring consistent casing and quoting across the entire identifier.
- **Improved CREATE TABLE Parsing**: Fixed a bug where qualified table names in `CREATE TABLE` statements (e.g., `SQLUser."workflow"`) were being incorrectly uppercased to `SQLUSER`.

## [1.1.2] - 2026-01-17

### Fixed
- **Dynamic Schema Mapping**: Fixed hardcoded "public" schema references in `translate_input_schema`. Now builds regex dynamically from `SCHEMA_MAP` keys (e.g., handles `drizzle`, `public`, etc.).
- **Bare Table Mapping**: Implemented automatic schema prefixing for bare table names (e.g., `FROM "workflow"` -> `FROM SQLUser."WORKFLOW"`). This ensures IRIS can resolve classes when ORMs omit the schema.
- **Robust Table Normalization**: Ensured all mapped table names are consistently uppercased and double-quoted to prevent conflicts with IRIS reserved words (like `USER`) and satisfy case-sensitive identifier requirements.
- **Reliable Schema Regex**: Refined regex patterns to correctly handle all combinations of quoted and unquoted schemas and table names, resolving "dangling quote" errors.

## [1.1.1] - 2026-01-17

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
