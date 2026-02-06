# Smart DEFAULT handling for IRIS PGWire gateway

## Background

PostgreSQL allows the `DEFAULT` keyword inside the `VALUES(...)` list to request that the server-side default expression be used. IRIS historically has spotty support for `DEFAULT` in that context, and our current strategy of translating it to `NULL` breaks when a column is declared `NOT NULL` without an explicit default. This spec defines a metadata-backed translation layer that brings IRIS closer to PostgreSQL semantics without requiring broad database engine modifications.

## Goals

1. Build a lightweight cache of `INFORMATION_SCHEMA.COLUMNS` data (`COLUMN_NAME`, `COLUMN_DEFAULT`, `IS_NULLABLE`).
2. Leverage cached metadata to omit explicitly defaulted columns when an insert includes a column list.
3. Replace `DEFAULT` literals with the canonical column default expression when no explicit column list is supplied.
4. Surfacing a PostgreSQL-compatible error when a `DEFAULT` is requested on a `NOT NULL` column that also lacks a default.

## Architecture

### Components

- **Default Metadata Cache**: A per-schema cache keyed by `table_name`/`column_name`. Stores:
  - `column_default` (SQL expression or `null`)
  - `is_nullable` (`"YES"`/`"NO"` or boolean equivalent)
  - Last-refresh timestamp + optional TTL (e.g., 5 minutes)
- **INSERT Rewriter**: Intercepts incoming PostgreSQL `INSERT` queries and rewrites them according to the combination of parsed column list and presence of `DEFAULT` literals.
- **Error Translator**: Converts IRIS or gateway errors into PostgreSQL-compatible error codes when default expectations cannot be satisfied.

### Flow

1. On first use or after the TTL expires, query `INFORMATION_SCHEMA.COLUMNS` for the target table/schema and populate the cache.
2. Before forwarding `INSERT` statements:
   - Parse the query to identify the target table, column list (if present), and individual `DEFAULT` placeholders.
   - Use regex-driven heuristics (see section below) to manage rewriting safely.
3. If the column list is explicit, drop the column/default pair from the rewritten query so IRIS applies its internal default. If no column list is present, replace each `DEFAULT` token with the cached expression.
4. If the cache lacks a default for a mandatory column, return a PostgreSQL-style error instead of issuing `NULL`.

## Metadata Cache Strategy

1. **Keying**: Cache entries are keyed using fully-qualified schema and table names (supporting quoted identifiers). The value for each column includes `column_default` and `is_nullable`.
2. **Population**:
   - Query `SELECT column_name, column_default, is_nullable FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2`.
   - Normalize identifier casing: PostgreSQL parsing will supply tokens already (e.g., quoted vs unquoted). The cache should store the normalized column name that matches parser output.
3. **TTL & Invalidation**:
   - Use a configurable TTL (e.g., 5 minutes). Upon expiration or explicit refresh (DDL changes), repopulate the cache.
   - Cache misses should re-trigger a metadata fetch before rewriting an insert.
4. **Graceful Fallback**:
   - If the metadata query fails (e.g., insufficient permissions), fall back to the existing behavior (treat `DEFAULT` as `NULL`) but log telemetry so the issue can be surfaced.

## INSERT Parsing Requirements

The rewriter must identify the following components via regex-friendly patterns (the gateway already tokenizes SQL to some degree):

1. **Optional column list**: `INSERT INTO <qualified table> \(([^\)]+)\)` (capture comma-separated columns, honoring quoted identifiers). Each column entry may be quoted.
2. **VALUES clause**: Identify literal `DEFAULT`s inside the corresponding tuple.
3. **DEFAULT Locator**: A regex such as `(?i)DEFAULT` that is constrained to value positions.

### Regex Guidance

- Column list pattern: `INSERT\s+INTO\s+(?<schema>[\w"]+(?:\.[\w"]+)?)\s*\((?<columns>[^\)]*)\)`
  - Split `columns` on commas while preserving quoted identifiers (handling escaped quotes).
- Values list pattern: `VALUES\s*\((?<values>.+)\)` (needs to handle nested parentheses; a simple counter-based parser or minimal tokenizer is acceptable).
- Default token detection: match `DEFAULT` only between commas or parentheses boundaries to avoid false positives (e.g., `DEFAULTS` should not match).

## Rewriting Strategies

### Omission Strategy (with column list)

1. Map each column from the explicit list to the matching value position within the `VALUES(...)` tuple(s).
2. When a value is the literal `DEFAULT`:
   - Remove the column from the column list.
   - Remove that value from every tuple in the `VALUES` clause (all tuples must match column order).
   - This omission triggers IRIS to apply its default when the statement is executed.
3. If removing columns reduces the list to zero items, rewrite the query to use `INSERT INTO table DEFAULT VALUES` or a minimal placeholder that aligns with IRIS syntax.

### Replacement Strategy (without column list)

1. Replace each `DEFAULT` literal in the tuple with the cached `column_default` expression.
2. If the cached default is `NULL`, preserve it (i.e., replace `DEFAULT` with `NULL`).
3. If the column is `NOT NULL` and the cache reports no default expression, abort with a PostgreSQL-like error (see Error Handling).

## Error Handling

- When `DEFAULT` appears for a `NOT NULL` column without `column_default`:
  - Immediately raise a PostgreSQL-compatible error (e.g., `ERROR: column "x" contains null value`, `SQLSTATE 23502`).
  - Avoid shipping a rewritten query to IRIS.
- When metadata is unavailable, log an informative warning and fall back to the current behavior (translation to `NULL`), while clearly surfacing the shortcoming to operators.

## Examples

1. Column list example:
   ```sql
   INSERT INTO schema.table (a, b, c) VALUES (DEFAULT, 1, DEFAULT);
   ```
   After omission, the gateway forwards:
   ```sql
   INSERT INTO schema.table (b) VALUES (1);
   ```
2. No column list example (fallback to replacement):
   ```sql
   INSERT INTO table VALUES (DEFAULT, 5);
   ```
   If the first column has default `nextval('seq')`, the gateway rewrites to:
   ```sql
   INSERT INTO table VALUES (nextval('seq'), 5);
   ```

## Testing & Validation

- Unit tests should cover:
  - Insertion rewriting when column list present/absent.
  - Cache refresh and fallback scenarios.
  - Error path when `DEFAULT` targets a `NOT NULL` column with no default.
- Integration tests should verify compatibility with IRIS versions that do and do not support `DEFAULT` natively.

## Observability

- Emit metrics for cache hits/misses, metadata refresh frequency, and rewrite failures.
- Log warnings when default metadata is absent so DBA teams can add explicit defaults or fix permissions.

## Security & Permissions

- The gateway must have `SELECT` privileges on `INFORMATION_SCHEMA.COLUMNS`. Document this requirement in the deployment guide.
