# Contract: Prepared Statement Parameter Translation

## Purpose
Guarantee that prepared statements use IRIS-compatible parameter placeholders across all protocol paths.

## Inputs
- SQL statement containing PostgreSQL positional parameters (`$1`, `$2`, ...).

## Outputs
- SQL statement with IRIS-compatible `?` placeholders and translated casts.

## Rules
1. **Placeholder translation**: All `$n` placeholders MUST be translated to `?`.
2. **Type cast translation**: PostgreSQL `::type` casts MUST be rewritten as IRIS `CAST(... AS type)`.
3. **Apply to all query paths**: Translation MUST run for simple and extended protocol flows.

## Error Handling
- If translation encounters unsupported casts, return a clear error specifying the cast.

## Acceptance Criteria
- Prepared statements using `$n` placeholders execute successfully on IRIS.
- Parameter description inference aligns with translated casts.