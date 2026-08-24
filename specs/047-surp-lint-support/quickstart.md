# Quickstart: surp Lint and ERD Support (047)

## Testing against surp

1. Start iris-pgwire with a running IRIS instance.
2. Install surp: `npm install -g surp` (or `bun add -g surp`).
3. Connect surp to iris-pgwire:

   ```text
   :connect postgresql://user:pass@localhost:5432/USER
   ```

4. Run lint:

   ```text
   :lint
   ```

   Expected: 5 checks return results or empty rows, no error banner.

5. Open ERD view:

   ```text
   :erd
   ```

   Expected: FK edges rendered for tables with FK constraints.

## Running the test suite for this feature

```bash
# Unit tests (no IRIS required)
pytest tests/unit/test_047_surp_lint.py -v

# E2E tests (requires running IRIS + iris-pgwire)
pytest tests/e2e/test_047_surp_e2e.py -v
```

## Key files changed

| File                                              | Change                                                             |
| ------------------------------------------------- | ------------------------------------------------------------------ |
| `src/iris_pgwire/catalog/functions.py`            | New FORMAT2, FORMAT3, JSONB_BUILD_OBJECT4, JSONB_BUILD_OBJECT6     |
| `src/iris_pgwire/catalog/views/definitions.py`    | New PG_DEPEND, PG_EXTENSION, PG_INDEX, PG_POLICY, PG_REWRITE views |
| `src/iris_pgwire/sql_translator/pg_functions.py`  | format() and jsonb_build_object() dispatch                         |
| `src/iris_pgwire/sql_translator/array_params.py`  | rewrite_any_col_to_instr()                                         |
| `src/iris_pgwire/sql_translator/array_literal.py` | NEW — rewrite_array_literals()                                     |
| `src/iris_pgwire/sql_translator/pipeline.py`      | Wire array_literal rewrite into pipeline                           |

## After any code change

Restart the IRIS container and iris-pgwire server before running E2E tests. The catalog
views are installed at server startup; a stale container will not see new views.
