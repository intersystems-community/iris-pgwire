# Research: IRIS pgwire compatibility fixes

## Comment handling in multi-statement SQL
- **Decision**: Preserve SQL comments during execution; ensure statement splitting is comment-aware and do not inject no-op SQL for skipped DDL.
- **Rationale**: IRIS supports standard `--` and `/* */` comments; the observed failures stem from incorrect splitting or from replacing DDL with a no-op SELECT in migration paths.
- **Alternatives considered**: Strip comments prior to execution (rejected because comments are supported and stripping can complicate statement mapping and diagnostics); protocol-level short-circuit for DDL skip (deferred in favor of normalizer-level adjustment).

## DEFAULT in VALUES clause
- **Decision**: Rewrite INSERT statements that use `DEFAULT` within VALUES by omitting the column and value pairs.
- **Rationale**: IRIS supports `DEFAULT VALUES` for entire rows but does not allow `DEFAULT` as a value expression.
- **Alternatives considered**: Replace `DEFAULT` with `NULL` (rejected because it changes semantics when defaults are non-nullable or computed).

## Timestamp formats and timezone suffixes
- **Decision**: Normalize ISO 8601 timestamps with timezone suffixes to IRIS-accepted formats (strip timezone suffix; use ODBC-like `YYYY-MM-DD HH:MM:SS[.fff]`).
- **Rationale**: IRIS expects ODBC-style timestamp strings and does not accept `Z` or offset suffixes in standard TIMESTAMP literals.
- **Alternatives considered**: Use `TO_TIMESTAMP(str, format)` for all timestamps (rejected due to increased translation complexity and risk of misformatting across client paths).

## ALTER TABLE SET DATA TYPE / DROP NOT NULL
- **Decision**: Translate to IRIS `ALTER COLUMN` syntax when supported; if unsupported, return a clear actionable error.
- **Rationale**: IRIS supports `ALTER COLUMN` with datatype/NULL/NOT NULL actions, but not PostgreSQL’s `SET DATA TYPE`/`DROP NOT NULL` keywords.
- **Alternatives considered**: Strip or ignore unsupported actions (rejected to avoid silent schema drift).

## Query Execution Paths
- **Simple Query (MSG_QUERY)**:
  - Flow: `PGWireProtocol.handle_query_message` → `translate_postgres_parameters()` → `_handle_single_statement` → `translate_sql()` → `IRISExecutor.execute_query`.
  - Migrations typically use this path (e.g., Drizzle with `prepare: false`).
- **Extended Protocol (Parse/Bind/Execute)**:
  - Flow: `Parse` ($n \to ?$) → `Bind` → `Execute`.
  - Prepared statements use this path.
- **Translation Ordering**:
  - Parameter translation ($n \to ?$) must occur before semantic normalization to ensure placeholders are correctly handled during SQL parsing/rewriting.
  - Normalization should avoid injecting "no-op" SELECTs for skipped DDL to prevent parsing errors in IRIS.

