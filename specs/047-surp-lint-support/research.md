# Research: surp Lint and ERD Support (047)

All research questions were resolved by reading the existing codebase. No external spike
was required because the platform constraints and encoding choices are already documented
in source-file comments.

## R1 — `ANY(col)` rewrite for conkey/indkey

**Decision**: Regex rewrite `expr = ANY(col)` →
`INSTR(',' || REPLACE(REPLACE(col, '{', ''), '}', '') || ',' , ',' || CAST(expr AS VARCHAR) || ',') > 0`

**Why**: `conkey` is stored as PostgreSQL int2[] text format (`{1,2,...}`), verified at
`catalog/views/definitions.py:243`. The outer braces must be stripped before INSTR
matching. The existing `rewrite_any_to_inlist()` in `array_params.py` handles
`= ANY($n)` (bound parameters); `expand_array_literals()` handles `= ANY('{…}')` (string
literals). A third case — `= ANY(col)` where `col` is a bare column reference — is not
yet handled and is the new code.

**Alternatives rejected**:

- Expand FK rows in the catalog view (one row per conkey element): breaks aggregate
  queries; multiplies result set size for multi-column constraints.
- JSON_CONTAINS: IRIS SQL has no such function.
- `%INLIST` approach: `%INLIST` requires a `$LIST` value, which requires PG_ARRAY
  encoding; a column value is not a bound parameter and cannot be pre-encoded.

## R2 — `format()` implementation

**Decision**: Fixed-arity `PGWire.FORMAT2(pattern, arg1)` and
`PGWire.FORMAT3(pattern, arg1, arg2)` SQL functions in ObjectScript. Rewrite in
`pg_functions.py` counts arguments and routes to the correct variant.

**Why**: IRIS SQL functions are not variadic. The existing `PGWire.*` function pattern
(used for `PGWire.FORMAT_TYPE`, `PGWire.OBJ_DESCRIPTION`, etc.) requires a fixed
signature. surp's `format()` calls are `format('%I %s', a, b)` — at most 3 arguments
in splinter.sql. Fixed-arity covers all real cases without adding a new encoding layer.

**%I / %L quoting**:

- `%I`: wrap in double-quotes, double any internal double-quotes.
- `%L`: wrap in single-quotes, double any internal single-quotes.
- `%s`: passthrough.
- `%%`: literal `%`.

**NULL behaviour**: PostgreSQL `format()` returns NULL if any argument is NULL.
IRIS ObjectScript: check each `arg = ""` after passing through SQL (NULL arrives as
`""`); return `""` (which the wire layer serialises as SQL NULL).

## R3 — `jsonb_build_object()` implementation

**Decision**: `PGWire.JSONB_BUILD_OBJECT4(k1, v1, k2, v2)` and
`PGWire.JSONB_BUILD_OBJECT6(k1, v1, k2, v2, k3, v3)`. surp's splinter.sql uses exactly
`jsonb_build_object('type', 'lint', 'check_id', check_id_expr)` — 4 arguments.

**Return type**: VARCHAR / text (OID 114 — json). IRIS has no JSONB binary type; the wire
protocol difference between `json` (114) and `jsonb` (3802) is invisible to surp because
it reads the value as a string.

**Odd-argument guard**: the 4-arg and 6-arg functions are inherently even. If a 5-arg call
is sent, the rewriter has no matching variant — it falls through to IRIS as-is, which
returns an error. That is correct PostgreSQL behaviour (argument count must be even).

## R4 — `ARRAY[...]` rewrite

**Decision**: Pre-pipeline regex rewrite in a new `sql_translator/array_literal.py`.
Pattern: `ARRAY\s*\[\s*((?:'[^']*'(?:\s*,\s*'[^']*')*)?)\s*\]`.
Output: a single-quoted PostgreSQL array literal `'{val1,val2,...}'`.

**Scope**: applied to the full SQL text (not restricted to SELECT list); however, the
pattern only matches `ARRAY[` followed by a simple list of single-quoted string literals,
which is the exact form surp uses (`ARRAY['PERFORMANCE']`). Integer and complex
expressions are not matched, so the risk of incorrectly rewriting a WHERE clause is
effectively zero given the actual query shapes.

**Alternatives rejected**: AST rewriting — overkill given the regex translator pattern
used throughout the codebase.

## R5 — New catalog views

| View           | Approach                           | Rationale                                                                                                        |
| -------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `pg_depend`    | Always-empty view                  | IRIS has no extension dependency tracking; LEFT JOIN still works with zero rows                                  |
| `pg_extension` | Always-empty view                  | IRIS has no loadable extensions                                                                                  |
| `pg_index`     | Data-backed from TABLE_CONSTRAINTS | `indkey` needed for ERD query; `indisprimary`/`indisunique` needed for no_primary_key and duplicate_index checks |
| `pg_policy`    | Always-empty view                  | IRIS has no RLS; surp checks return zero rows                                                                    |
| `pg_rewrite`   | Always-empty view                  | IRIS has no rule system; referenced in pg_views chain                                                            |

**pg_index indkey format**: space-separated text (e.g., `"1 2"`) per clarification.
Rationale: mirrors PostgreSQL `int2vector` serialisation so `indkey::text` casts are
no-ops. The `::text` cast is used in `string_to_array(indkey::text, ' ')` in some lint
branches, but those branches (`unindexed_foreign_keys`) are out of scope for the 5
supported checks.

## R6 — Pipeline integration order

Rewrite passes must run in this order (each pass's output is the next pass's input):

1. `rewrite_array_literals(sql)` — `ARRAY[...]` → `'{...}'` (must run before IRIS sees any syntax)
2. `rewrite_pg_function_calls(sql)` — redirect `format(`, `jsonb_build_object(` to `PGWire.*`
3. `rewrite_any_to_inlist(sql)` — `= ANY($n)` → `%INLIST PGWire.PG_ARRAY($n)` (existing)
4. `expand_array_literals(sql)` — `= ANY('{a,b}')` → `IN (…)` (existing)
5. `rewrite_any_col_to_instr(sql)` — `= ANY(col)` → `INSTR(…)` (new)

Steps 1–2 must precede steps 3–5 because the function redirects and array literal
rewrites affect the SQL text that the array membership rewrites scan.
