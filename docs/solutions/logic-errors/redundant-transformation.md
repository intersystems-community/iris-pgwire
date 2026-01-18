# Solution: Redundant SQL Transformation (Double Patch)

**Category:** Logic Errors
**Date:** 2026-01-17
**Status:** Solved

## Problem Symptom
SQL identifiers were becoming incorrectly nested, for example `SQLUser."SQLUser."TABLE""`. This led to syntax errors in IRIS.

## Investigation Steps
1. Observed the malformed SQL in logs.
2. Traced the execution path in `IRISExecutor`.
3. Found that `translate_input_schema` was being called explicitly inside `_execute_embedded_async`.
4. Discovered that `SQLTranslator` (which is called earlier in the protocol phase) already applies `translate_input_schema`.

## Root Cause
The `IRISExecutor` had legacy code that manually performed schema translation. When the centralized `SQLTranslator` was updated to include this translation, it resulted in the SQL being processed twice. Since the translation logic adds `SQLUser.` prefixes and quotes, the second pass treated the already-translated string as new input and added another layer of transformation.

## Working Solution
Removed the redundant call to `translate_input_schema` in `IRISExecutor`. The `SQLTranslator` is now the single source of truth for SQL normalization and translation.

```python
# DELETED redundant call in iris_executor.py
# optimized_sql = translate_input_schema(optimized_sql)
```

## Prevention Strategies
- Centralize all SQL transformations in the `SQLTranslator` pipeline.
- Maintain a clear "one-pass" architecture for SQL processing.
- Use idempotent transformation functions where possible.

## Cross-References
- [iris_executor.py](../../src/iris_pgwire/iris_executor.py)
- [schema_mapper.py](../../src/iris_pgwire/schema_mapper.py)
- [normalizer.py](../../src/iris_pgwire/sql_translator/normalizer.py)
