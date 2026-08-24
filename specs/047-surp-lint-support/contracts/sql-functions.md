# SQL Function Contracts (047)

These are the IRIS SQL functions this feature installs into the `PGWire` schema.

## PGWire.FORMAT2

```sql
CREATE OR REPLACE FUNCTION PGWire.FORMAT2(
    pattern VARCHAR(4096),
    arg1    VARCHAR(4096)
) RETURNS VARCHAR(4096)
LANGUAGE OBJECTSCRIPT
{ /* ObjectScript body — see catalog/functions.py */ }
```

**Semantics**:

- `%s` → arg1 as-is
- `%I` → `"` + double-quote-escaped arg1 + `"`
- `%L` → `'` + single-quote-escaped arg1 + `'`
- `%%` → literal `%`
- NULL arg1 → returns NULL
- Unknown format code → raises SQLCODE -400

**Wire type**: VARCHAR (OID 25, text)

## PGWire.FORMAT3

Same as FORMAT2 but accepts two substitution arguments. Each `%s`/`%I`/`%L`
placeholder consumes the next argument in left-to-right order.

```sql
CREATE OR REPLACE FUNCTION PGWire.FORMAT3(
    pattern VARCHAR(4096),
    arg1    VARCHAR(4096),
    arg2    VARCHAR(4096)
) RETURNS VARCHAR(4096)
```

## PGWire.JSONB_BUILD_OBJECT4

```sql
CREATE OR REPLACE FUNCTION PGWire.JSONB_BUILD_OBJECT4(
    k1 VARCHAR(512), v1 VARCHAR(4096),
    k2 VARCHAR(512), v2 VARCHAR(4096)
) RETURNS VARCHAR(32767)
LANGUAGE OBJECTSCRIPT
{ /* builds {"k1":"v1","k2":"v2"} */ }
```

**Semantics**:

- Keys are always double-quoted; internal double-quotes are escaped.
- NULL values render as JSON `null`.
- String values are double-quoted; internal double-quotes and backslashes escaped.
- Numeric values that can be parsed as integers are rendered unquoted.

**Wire type**: VARCHAR declared but annotated as OID 114 (json) in
`CATALOG_COLUMN_TYPE_OIDS` — same pattern used for other catalog columns.

## PGWire.JSONB_BUILD_OBJECT6

Three-key variant. Same semantics as JSONB_BUILD_OBJECT4 with k3/v3 appended.

## Rewriter contracts

### pg_functions.py — format() dispatch

```text
Input:  format(pattern, arg1)            → PGWire.FORMAT2(pattern, arg1)
Input:  format(pattern, arg1, arg2)      → PGWire.FORMAT3(pattern, arg1, arg2)
Input:  format(pattern, arg1, arg2, ...) → passes through unchanged (unsupported arity)
```

### pg_functions.py — jsonb_build_object() dispatch

```text
Input:  jsonb_build_object(k1, v1, k2, v2)            → PGWire.JSONB_BUILD_OBJECT4(k1, v1, k2, v2)
Input:  jsonb_build_object(k1, v1, k2, v2, k3, v3)    → PGWire.JSONB_BUILD_OBJECT6(k1, v1, k2, v2, k3, v3)
Input:  odd argument count                             → passes through (IRIS raises error, correct PG behaviour)
```

### array_params.py — ANY(col) dispatch

```text
Input:  expr = ANY(col)   where col is a bare identifier (no $n, no string literal)
Output: INSTR(',' || REPLACE(REPLACE(col, '{', ''), '}', '') || ',',
               ',' || CAST(expr AS VARCHAR) || ',') > 0
```

### array_literal.py — ARRAY[...] rewrite

```text
Input:  ARRAY['a', 'b', 'c']
Output: '{a,b,c}'

Input:  ARRAY['PERFORMANCE']
Output: '{PERFORMANCE}'

Input:  ARRAY[]
Output: '{}'
```
