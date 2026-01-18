# Solution: Qualified Identifier Normalization and Mapping Idempotency

**Category:** Logic Errors
**Date:** 2026-01-17
**Status:** Solved

## Problem Symptom
1. Schema-qualified names like `SQLUser . "workflow"` (with spaces) were being mis-normalized. The `SQLUser` part would often be force-uppercased to `SQLUSER` because the regex didn't treat the dot and following name as a single unit.
2. SQL statements were being double-prefixed with the schema, e.g., `SQLUser.SQLUser."TABLE"`, when the translation engine was called multiple times or when the input already had a partial prefix.

## Investigation Steps
1. Reproduced the "dangling quote" and "double prefix" using a script with varied whitespace around dots.
2. Found that word boundaries (`\b`) in regexes are unreliable when identifiers are quoted or joined by dots.
3. Identified that lookbehind assertions `(?<!\.)` in `schema_mapper.py` only checked the immediate character, failing if a space was present (e.g., `. "table"`).

## Root Cause
- **Normalization**: The regex matched identifiers too granularly. By excluding the dot, it lost the context that `SQLUser` was part of a qualified name that needed protection.
- **Idempotency**: The bare-table mapping logic lacked a robust "already-mapped" check that accounted for whitespace and existing prefixes.

## Working Solution
1. **Unified Regex**: Updated `identifier_normalizer.py` to match sequences of identifiers joined by dots as a single logical unit.
   ```python
   # Match: "Quoted" | Unquoted followed by (dot + ("Quoted" | Unquoted)) repeated
   pattern = r'((?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\.\s*(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_]*))*)'
   ```
2. **Look-back Idempotency**: Replaced the fragile regex lookbehind with a manual string look-back check in the replacement function.
   ```python
   prefix_candidate = processed_sql[max(0, match.start()-20):match.start()].rstrip()
   if prefix_candidate.endswith('.') or prefix_candidate.upper().endswith(IRIS_SCHEMA.upper()):
       return match.group(0) # Skip mapping
   ```

## Prevention Strategies
- Treat qualified names as atomic tokens in the translation pipeline.
- Implement idempotency checks using content-aware logic (look-back/look-forward) rather than simple character boundaries.

## Cross-References
- [identifier_normalizer.py](../../src/iris_pgwire/sql_translator/identifier_normalizer.py)
- [schema_mapper.py](../../src/iris_pgwire/schema_mapper.py)
- [redundant-transformation.md](./redundant-transformation.md)
