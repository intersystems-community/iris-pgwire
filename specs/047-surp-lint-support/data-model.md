# Data Model: surp Lint and ERD Support (047)

This feature adds no persistent data model. All state is in IRIS catalog views (DDL
installed at server start) and SQL function bodies (ObjectScript). The "entities" are
the new catalog objects and SQL functions.

## New Catalog Views

### pg_depend (always empty)

| Column      | Type   | Notes                                             |
| ----------- | ------ | ------------------------------------------------- |
| classid     | oid    | OID of system catalog the object is in            |
| objid       | oid    | OID of the specific object                        |
| objsubid    | int4   | Column number, 0 for non-column objects           |
| refclassid  | oid    | OID of system catalog the referenced object is in |
| refobjid    | oid    | OID of the referenced object                      |
| refobjsubid | int4   | Column number of referenced object                |
| deptype     | "char" | Dependency type code                              |

**View body**: `SELECT 0 AS classid, 0 AS objid, 0 AS objsubid, 0 AS refclassid, 0 AS refobjid, 0 AS refobjsubid, '' AS deptype WHERE 1=0`

### pg_extension (always empty)

| Column         | Type | Notes            |
| -------------- | ---- | ---------------- |
| oid            | oid  | Extension OID    |
| extname        | name | Extension name   |
| extowner       | oid  | Owner OID        |
| extnamespace   | oid  | Namespace OID    |
| extrelocatable | bool | Relocatable flag |
| extversion     | text | Version string   |

**View body**: `SELECT 0 AS oid, '' AS extname, 0 AS extowner, 0 AS extnamespace, 0 AS extrelocatable, '' AS extversion WHERE 1=0`

### pg_index (data-backed)

| Column         | Type | Notes                                              |
| -------------- | ---- | -------------------------------------------------- |
| indexrelid     | oid  | OID of the index (pg_class entry)                  |
| indrelid       | oid  | OID of the indexed table                           |
| indnatts       | int4 | Total columns in index                             |
| indnkeyatts    | int4 | Key columns (= indnatts for non-INCLUDE indexes)   |
| indisunique    | bool | Is unique index                                    |
| indisprimary   | bool | Is primary key index                               |
| indisexclusion | bool | Is exclusion constraint (always 0)                 |
| indimmediate   | bool | Uniqueness check enforced immediately (always 1)   |
| indisclustered | bool | Was table last clustered on this index (always 0)  |
| indisvalid     | bool | Index is ready for use (always 1)                  |
| indcheckxmin   | bool | Always 0                                           |
| indisready     | bool | Always 1                                           |
| indislive      | bool | Always 1                                           |
| indisreplident | bool | Is replica identity (always 0)                     |
| indkey         | text | Space-separated column attnum list (e.g., `"1 2"`) |
| indpred        | text | Partial index predicate (always NULL)              |

**Data source**: `INFORMATION_SCHEMA.TABLE_CONSTRAINTS` filtered to PK and UNIQUE
constraints; joins `INFORMATION_SCHEMA.KEY_COLUMN_USAGE` and
`INFORMATION_SCHEMA.COLUMNS` for column positions.

### pg_policy (always empty)

| Column        | Type   | Notes                                           |
| ------------- | ------ | ----------------------------------------------- |
| oid           | oid    |                                                 |
| polname       | name   | Policy name                                     |
| polrelid      | oid    | Table OID                                       |
| polcmd        | "char" | Command type                                    |
| polpermissive | bool   | Is permissive                                   |
| polroles      | text   | Role OID list (as text; IRIS has no oid[] type) |
| polqual       | text   | USING expression                                |
| polwithcheck  | text   | WITH CHECK expression                           |

### pg_rewrite (always empty)

| Column     | Type   | Notes           |
| ---------- | ------ | --------------- |
| oid        | oid    |                 |
| rulename   | name   | Rule name       |
| ev_class   | oid    | Table OID       |
| ev_type    | "char" | Event type      |
| ev_enabled | "char" | Firing mode     |
| is_instead | bool   | Is INSTEAD rule |
| ev_qual    | text   | Rule qualifier  |
| ev_action  | text   | Rule action     |

## New SQL Functions

### PGWire.FORMAT2(pattern VARCHAR, arg1 VARCHAR) RETURNS VARCHAR

Implements PostgreSQL `format(pattern, arg)` with `%s`/`%I`/`%L`/`%%` substitution.

| Input   | Constraint                         |
| ------- | ---------------------------------- |
| pattern | VARCHAR — the format string        |
| arg1    | VARCHAR — first substitution value |

**Returns**: VARCHAR — the formatted string, or NULL if arg1 is NULL.

### PGWire.FORMAT3(pattern VARCHAR, arg1 VARCHAR, arg2 VARCHAR) RETURNS VARCHAR

Three-argument variant of FORMAT2.

### PGWire.JSONB_BUILD_OBJECT4(k1 VARCHAR, v1 VARCHAR, k2 VARCHAR, v2 VARCHAR) RETURNS VARCHAR

Builds a 2-key JSON object: `{"k1":"v1","k2":"v2"}`.

| Input  | Constraint                                      |
| ------ | ----------------------------------------------- |
| k1, k2 | VARCHAR — key names (must not be NULL)          |
| v1, v2 | VARCHAR — values (NULL rendered as JSON `null`) |

**Returns**: VARCHAR (wire type json / OID 114).

### PGWire.JSONB_BUILD_OBJECT6(k1, v1, k2, v2, k3, v3 VARCHAR) RETURNS VARCHAR

Three-key variant.

## Rewriter Logic

### rewrite_any_col_to_instr(sql: str) → str

Input pattern: `(\w+(?:\.\w+)?)\s*=\s*ANY\s*\(\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\)`
(where the `ANY` operand is a column reference, not `$n` or a string literal)

Output: `INSTR(',' || REPLACE(REPLACE({col}, '{', ''), '}', '') || ',' , ',' || CAST({expr} AS VARCHAR) || ',') > 0`

### rewrite_array_literals(sql: str) → str

Input pattern: `ARRAY\s*\[\s*((?:'[^']*'(?:\s*,\s*'[^']*')*)?)\s*\]`

Output: `'{val1,val2,...}'` (values stripped of their individual quotes, joined with
commas inside braces, and wrapped in a single outer SQL string literal)
