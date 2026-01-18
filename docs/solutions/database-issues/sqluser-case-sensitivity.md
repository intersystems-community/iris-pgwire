# Solution: SQLUser Schema Case Sensitivity

**Category:** Database Issues
**Date:** 2026-01-17
**Status:** Solved

## Problem Symptom
IRIS returns "Class not found" for queries like `FROM SQLUSER.WORKFLOW` when the actual class is `SQLUser.WORKFLOW`. The SQL normalizer was force-uppercasing the schema prefix.

## Investigation Steps
1. Observed that IRIS package/schema names are case-sensitive.
2. Verified that `SQLUser` is the required casing for the standard user schema.
3. Identified that `IdentifierNormalizer` was mapping all unquoted identifiers to uppercase, including `SQLUser`.

## Root Cause
The `IdentifierNormalizer` lacked specific protection for the `SQLUser` identifier. In IRIS, while table/class names are often uppercase, the package name `SQLUser` must preserve its exact casing to be resolved correctly by the SQL engine.

## Working Solution
Updated the `IdentifierNormalizer` to explicitly recognize and preserve the `SQLUser` casing while still uppercasing other unquoted identifiers.

```python
elif upper_unquoted == "SQLUSER":
    # Feature 036 Fix: Preserve SQLUser case (IRIS is case-sensitive for schema names)
    identifier_count += 1
    return "SQLUser"
```

## Prevention Strategies
- Always treat `SQLUser` as a reserved identifier with protected casing in IRIS translation logic.
- Ensure all schema mapping logic (e.g., `public` -> `SQLUser`) uses the correct case.

## Cross-References
- [identifier_normalizer.py](../../src/iris_pgwire/sql_translator/identifier_normalizer.py)
- [schema_mapper.py](../../src/iris_pgwire/schema_mapper.py)
- [AGENTS.md](../../AGENTS.md)
