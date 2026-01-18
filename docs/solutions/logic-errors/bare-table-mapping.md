# Solution: Bare Table Mapping and Qualified Identifier Normalization

**Category:** Logic Errors
**Date:** 2026-01-17
**Status:** Solved

## Problem Symptom
1. Bare table names (e.g., `FROM "workflow"`) were not being mapped to `SQLUser`, causing "Class not found" errors in IRIS when ORMs omitted the schema.
2. Already-mapped qualified identifiers (e.g., `SQLUser."USER"`) were being mis-normalized because the regex matched the schema and table separately, often force-uppercasing `SQLUser` to `SQLUSER`.

## Investigation Steps
1. Observed that Drizzle and other ORMs frequently omit the `public.` prefix for table references.
2. Analyzed `schema_mapper.py` and found it only handled explicit `public.` prefixes.
3. Analyzed `identifier_normalizer.py` and found its `_identifier_pattern` regex excluded the dot (`.`), treating qualified names as separate tokens.

## Root Cause
- **Bare Tables**: The schema mapping logic lacked a "context-aware" pass to identify table positions (following `FROM`, `JOIN`, etc.) that lacked a schema prefix.
- **Qualified Identifiers**: The identifier normalizer was too granular. By not matching the dot as part of the identifier, it lost the relationship between the schema and the table, leading to incorrect casing of the protected `SQLUser` prefix.

## Working Solution
1. **Bare Table Logic**: Added a new regex pass in `translate_input_schema` that matches table-preceding keywords (`FROM`, `JOIN`, `UPDATE`, etc.) and automatically prefixes bare identifiers with `SQLUser."NAME"`.
2. **Qualified Normalization**: Updated the `_identifier_pattern` to include dots and sequences of identifiers. The normalization logic was also updated to split these qualified names and normalize each part while preserving `SQLUser` casing.

```python
# identifier_normalizer.py
self._identifier_pattern = re.compile(
    r'((?:"[^"]+"|\b[a-zA-Z_][a-zA-Z0-9_]*\b)(?:\s*\.\s*(?:"[^"]+"|\b[a-zA-Z_][a-zA-Z0-9_]*\b))*)'
)
```

## Prevention Strategies
- Always handle qualified identifiers as a single unit during normalization.
- Ensure "table-position" identifiers are schema-prefixed for IRIS if they are missing one.
- Use double-quoting for all mapped table names to avoid reserved word conflicts (e.g., `USER`).

## Cross-References
- [schema_mapper.py](../../src/iris_pgwire/schema_mapper.py)
- [identifier_normalizer.py](../../src/iris_pgwire/sql_translator/identifier_normalizer.py)
