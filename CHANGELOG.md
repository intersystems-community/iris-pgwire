# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.5.9] - 2026-07-19

### Fixed

- **`integratedml.py` `%ModelExists` check never matched** (`integratedml.py`): `handle_system_function_query` compared the literal `"%SYSTEM.ML.%ModelExists"` against `sql.upper()`, so it never matched because the literal itself was mixed-case. Fixed by uppercasing the literal to `"%SYSTEM.ML.%MODELEXISTS"`.
- **`VectorQueryRequest` field validation silently skipped dimension check** (`models/vector_query_request.py`): `query_vector` was declared before `vector_dimensions` in the Pydantic v2 model; `info.data` at validator time therefore never contained `vector_dimensions`, so the dimension mismatch check was always skipped. Fixed by swapping field declaration order so `vector_dimensions` is visible in `info.data` when `query_vector` is validated.
- **`IdentifierNormalizer` CREATE TABLE regex consumed closing parenthesis** (`sql_translator/identifier_normalizer.py`): The `create_table_pattern` regex included a trailing `(\))` capture group that absorbed the closing paren before the manual paren-depth scanner could find it, causing `normalize_create_table` to silently return the original SQL unchanged for any CREATE TABLE with nested parens. Removed the trailing group; the paren scanner now handles termination correctly.

### Added

- **`AGENTS.md` agent-oriented rewrite**: Replaced Codex boilerplate with actionable AI agent guidance — when to use iris-pgwire, where to look, AI agent workflows (SQL translation verify via `iris_query`, wire protocol debug, integration test run patterns), IRIS DBAPI reference, iad ecosystem integration with `.iris-agentic-dev.toml` config, and agent skill pointers.
- **`skills/iris-pgwire/SKILL.md`**: New agent skill file covering psycopg3/asyncpg/SQLAlchemy connection strings, parameter style (`$N` wire → `?` IRIS), PostgreSQL→IRIS type mapping, full SQL translation differences, integration test patterns (container attach, skip fixtures, pure translation tests), transaction semantics, environment variables, and gotchas.
- **`pip install iris-pgwire[ai]`** (`pyproject.toml`): Added `ai` optional dependency group (`iris-agentic-dev>=1.0`) for iad-powered IRIS introspection during development.

### Changed

- **Test coverage**: 47% → 92% (5,349 tests across unit, contract, integration, and e2e suites).
- **README**: Rewritten for accuracy — removed fabricated "171/171 tests" stat, dead ZPM class reference, and wrong version. Reflects actual 92% coverage, v1.5.9, correct Quick Start.
- **Root cleanup**: Removed 12 debug/scratch scripts and 3 AI-tooling files from git tracking; added to `.gitignore`.
- **JS dependencies**: Resolved 41 Dependabot CVEs in `examples/prisma-iris-demo` (hono, defu, effect, lodash) and `tests/client_compatibility/nodejs` (js-yaml, picomatch) via package bumps and `overrides`.

## [1.5.8] - 2026-06-08

### Added

- **HNSW DDL translation** (`vector_optimizer.py`): pgvector-style `CREATE INDEX USING hnsw` DDL is now translated to IRIS HNSW syntax with `Distance=` parameter mapping (`vector_cosine_ops` → `Cosine`, `vector_ip_ops` → `DotProduct`). L2 (`vector_l2_ops`) raises `NotImplementedError` as IRIS does not support L2 HNSW indexes.
- **JSON operator translation** (`vector_optimizer.py`): PostgreSQL `->` / `->>` JSON operators are now translated to IRIS `JSON_QUERY` / `JSON_VALUE` equivalents, enabling ORMs and clients that use JSON column access patterns to work transparently.
- **`IF NOT EXISTS` duplicate-error suppression** (`vector_optimizer.py`, `protocol.py`): `CREATE TABLE IF NOT EXISTS` and similar DDL statements that trigger IRIS duplicate-object errors (SQLCODE -5016, -5019, -5002) are now silently suppressed with a synthetic success response, matching PostgreSQL `IF NOT EXISTS` semantics.

## [1.5.7] - 2026-03-09

### Fixed

- **`_prepare_sql` overwrote translated SQL with untranslated original after RETURNING strip**: After the 1.5.6 fix, `_prepare_sql` correctly used `original_sql` for `ReturningPlan.from_sql` RETURNING detection. However, line 699 then unconditionally did `optimized_sql = plan.stripped_sql`. Since `plan` was built from `original_sql`, `plan.stripped_sql` was the _original_ (untranslated) SQL with just `RETURNING` removed — still containing `DEFAULT`, `$1`-style params, unquoted schema names, etc. This overwrote the correctly-translated `optimized_sql` from the normalization pipeline, causing IRIS to receive e.g. `INSERT INTO "SESSION" (...) VALUES (..., DEFAULT)` → `SQLCODE -12`. Fixed by applying `ReturningPlan._strip_clauses()` directly to `optimized_sql` when `original_sql` was provided, rather than using `plan.stripped_sql`. The `else` branch (no `original_sql`) continues to use `plan.stripped_sql` as before.

## [1.5.6] - 2026-03-09

### Fixed

- **`INSERT ... RETURNING` returns empty array with Extended Query Protocol (Drizzle / Better Auth) — complete fix**: v1.5.5 fixed the Describe phase (NoData → RowDescription), but the Execute phase still returned zero rows. Two additional root causes:

  1. **Fast-batch bypass used translated SQL for `has_returning` check** (`protocol.py` Execute handler): The batch fast-path (`is_dml and not has_returning`) inspected `translated_query` (RETURNING stripped) instead of `original_query`. This caused `has_returning=False`, so INSERT...RETURNING was incorrectly fast-batched — the INSERT executed and sent a synthetic `CommandComplete` immediately, but `_emulate_returning` was never reached and zero DataRows were returned.

  2. **`_prepare_sql` used translated SQL for `ReturningPlan`** (`iris_executor.py`): Even when the fast-batch was bypassed, `_prepare_sql` built `ReturningPlan` from `optimized_sql` (which has RETURNING stripped by the normalization pipeline). `plan.has_returning` was therefore always `False`, so the RETURNING emulation block was never entered. Fixed by adding an `original_sql` parameter to `_prepare_sql`, `_execute_external_async`, `_execute_embedded_async`, and `execute_query`, threading the pre-translation SQL all the way through so `ReturningPlan` can detect RETURNING correctly.

- **Impact**: Affects both embedded and external IRIS connection modes. Better Auth "Failed to create session", Drizzle `.returning()` always `[]`, SQLAlchemy `.returning()` with psycopg3.

## [1.5.5] - 2026-03-09

### Fixed

- **`INSERT ... RETURNING` always empty with Extended Query Protocol (Drizzle / postgres.js / Better Auth)**: When a client uses the Extended Query Protocol (Parse → Describe → Bind → Execute), the Describe phase was incorrectly sending `NoData` instead of `RowDescription` for `INSERT ... RETURNING` statements. Root cause: `handle_describe_message` built the `ReturningPlan` from `translated_query`, which has the `RETURNING` clause stripped (because IRIS doesn't support it natively). `has_returning` was therefore always `False` at Describe time, causing `send_no_data()`. Clients like postgres.js and Drizzle ORM rely on the Describe response to decide whether to read rows at Execute time — receiving `NoData` caused them to discard all returned rows silently. Fixed by using `original_query` (the pre-translation SQL, which still contains `RETURNING`) for `ReturningPlan` detection in both the "Describe Statement" (`describe_type == "S"`) and "Describe Portal" (`describe_type == "P"`) branches of `handle_describe_message`.
- **Impact**: Drizzle ORM `.returning()` returned `[]`. Better Auth failed at sign-in ("Failed to create session") because session creation uses `.returning()`. Any ORM or client using Extended Query Protocol with `RETURNING` (SQLAlchemy `returning()` with psycopg3, etc.) was affected.

### Added

- **E2E regression tests for RETURNING via Extended Query Protocol** (`tests/e2e/test_returning_extended_protocol.py`): 4 passing tests covering `INSERT ... RETURNING *`, specific columns, multiple rows, and RowDescription presence verification via `prepare=True` (forces Extended Query Protocol). 1 xfail for `UPDATE ... RETURNING` (separate pre-existing limitation).

## [1.5.4] - 2026-03-06

### Fixed

- **`CREATE INDEX USING HNSW WITH (...)` translation**: pgvector-style HNSW index DDL is now correctly translated to IRIS syntax. Both pgvector forms are handled:
  - `CREATE INDEX name ON table USING hnsw (col vector_cosine_ops)` — operator class maps to `Distance='Cosine'`
  - `CREATE INDEX name ON table (col) USING HNSW WITH (M=16, ef_construction=64)` — column-first form with explicit parameters
  - All three distance metrics: `vector_cosine_ops` → `'Cosine'`, `vector_ip_ops` → `'DotProduct'`, `vector_l2_ops` raises `NotImplementedError` (L2 distance not supported in IRIS HNSW)
  - Parameters `M` and `ef_construction`/`efConstruction` pass through correctly
  - Schema-qualified table names (e.g. `SQLUser.mytable`) supported
  - `IF NOT EXISTS` clause stripped (not supported by IRIS)
  - Native IRIS `AS HNSW(...)` syntax passes through untouched

### Added

- **E2E tests for HNSW index creation** (`tests/e2e/test_hnsw_index.py`): 12 tests covering pgvector syntax translation, live index creation/verification against IRIS, parameter passthrough, and native syntax passthrough.

## [1.5.3] - 2026-03-06

### Fixed

- **`<=>` cosine distance semantics**: `ORDER BY embedding <=> query ASC` now correctly returns the most-similar rows first. pgvector `<=>` is cosine _distance_ (0.0 = identical), but IRIS `VECTOR_COSINE()` is cosine _similarity_ (1.0 = identical). The translator was emitting bare `VECTOR_COSINE(...)`, which caused `ORDER BY ASC` to return the _least_-similar row first. Fixed by wrapping as `(1 - VECTOR_COSINE(...))` to convert similarity → distance. Affects both `<=>` operator rewrites in `vector_optimizer.py` (already fixed in v1.5.2) and explicit `cosine_distance()`/`vector_cosine_distance()` function calls in `sql_translator/normalizer.py` (fixed now).

### Added

- **E2E regression test for cosine ordering** (`tests/e2e/test_vector_cosine_ordering.py`): inserts three vectors with known relative similarities, queries with `<=>`, and asserts the most-similar row is returned first — the test that would have caught this bug before it shipped.

## [1.5.2] - 2026-03-05

### Fixed

- **RETURNING emulation silent failure (Extended Query Protocol)**: `INSERT ... RETURNING` returned no rows when using postgres.js, Drizzle ORM, or any client that uses the Extended Query Protocol. Root cause: column names extracted from the INSERT were kept lowercase (e.g. `"id"`), but IRIS stores unquoted column names in uppercase (`ID`). The quoted `WHERE "id" = ?` clause matched nothing. Fixed by uppercasing the extracted column name in both `iris_executor.py` and `dbapi_executor.py`.

## [1.5.1] - 2026-03-05

### Added

- **`PGWIRE_QUERY_TIMEOUT` env var**: Per-query execution timeout (default 30s) that cancels a stalled IRIS query and returns an error to the client immediately, rather than holding the pool slot for the full `PGWIRE_POOL_TIMEOUT`. On timeout the offending connection is evicted (closed) rather than recycled, preventing lock-held connections from polluting the pool. Fixes the concurrent write load pool exhaustion bug where IRIS row locks on `DELETE + INSERT + UPDATE` sequences blocked subsequent `SELECT` queries until the pool fully saturated.

### Fixed

- **COPY FROM STDIN without header**: Rows were silently dropped because the bulk executor used placeholder column names (`column_0`, `column_1`, …) that don't exist in IRIS. Now fetches real column names from `INFORMATION_SCHEMA.COLUMNS` via a direct DBAPI call that bypasses the pg_catalog emulation layer.
- **COPY FROM STDIN column list**: Same root cause — explicit column list COPY now correctly maps CSV values to the specified columns.

## [1.5.0] - 2026-02-28

### Added

- **Drizzle ORM Migration Support**: Complete compatibility with Drizzle-style migrations including UUID/JSON handling, boolean defaults, and enum type mappings.
- **Transaction Rollback Support**: Migrations now use explicit `START TRANSACTION` for proper rollback capability in IRIS.
- **Enhanced DDL Translation**:
  - UUID columns automatically use `%Library.UniqueIdentifier` native type
  - JSON/JSONB columns automatically use `%Library.DynamicObject` native type
  - `DEFAULT gen_random_uuid()` automatically skipped (IRIS limitation)
  - `DEFAULT NOW()` automatically converted to `CURRENT_TIMESTAMP`
  - `ALTER TABLE RENAME COLUMN` marked as unsupported

### Changed

- **Comprehensive Code Simplification**: Major readability and maintainability improvements across all source files — `protocol.py`, `iris_executor.py`, `dbapi_executor.py`, `sql_translator/`, `auth/`, and `catalog/`. Functions shortened, duplication eliminated, and nesting reduced. No behaviour changes.

### Fixed

- **DDL Parser Comment Handling**: `CREATE TABLE` statements prefixed with `--` SQL comments (as emitted by Drizzle CLI) are now correctly parsed.
- **Migration Failure Detection**: Invalid SQL statements (e.g. `CREATE TAABLE`) that the DDL parser cannot recognise are now executed raw against IRIS so the database rejects them and the migration fails as expected.
- **UUID/JSON DDL Handling**: Both CREATE TABLE and ALTER TABLE now correctly use IRIS native types for UUID and JSON columns.
- **Transaction Management**: Migration executor now disables auto-commit and uses explicit transaction control for reliable rollback.
- **Test Infrastructure**: All e2e tests pass; pool size increased to 20 to prevent exhaustion across sequential test classes.

## [1.3.0] - 2025-02-06

### Added

- **IRIS 2024.2+ compatibility**: Automatic `%EXACT` wrapping for `SELECT DISTINCT` and `UNION` preserves PostgreSQL set semantics on IRIS 2024.2+.
- **Enhanced RETURNING emulation**: Multi-column and `RETURNING *` workflows now return metadata-rich results without forcing separate queries.
- **ON CONFLICT support**: `DO NOTHING` and `DO UPDATE` branches replay IRIS-safe logic while keeping the client-facing `RETURNING` output consistent.
- **Metadata-driven DEFAULTs**: Translators consult IRIS metadata to expand `DEFAULT` references in INSERT/UPDATE statements.
- **Global boolean literals**: PostgreSQL `true`/`false` constants are translated into IRIS equivalents everywhere in the pipeline.
- **DBAPI session pinning**: Connections remain tied to their originating session so identity lookups (`LAST_IDENTITY()`/`%EXACT` selects) stay accurate.

### Fixed

- **TypeError in DBAPIConnection**: Connection age calculations no longer raise `TypeError` when the pool is drained.
- **IntegratedML decorators**: Signature mismatches in `IntegratedML` wrappers were corrected so they proxy arguments without losing positional context.

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
