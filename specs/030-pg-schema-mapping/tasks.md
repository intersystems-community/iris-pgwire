# Tasks: PostgreSQL Schema Mapping

**Input**: Design documents from `/specs/030-pg-schema-mapping/`
**Prerequisites**: plan.md (required), research.md, data-model.md, contracts/

## Summary

| Metric | Value |
|--------|-------|
| Total Tasks | 12 |
| Setup Phase | 1 task |
| Contract Tests Phase | 2 tasks |
| Core Implementation | 3 tasks |
| Integration | 2 tasks |
| E2E Validation | 4 tasks |
| Parallel Opportunities | 6 tasks |

## Phase 1: Setup

- [x] T001 Create schema_mapper.py module skeleton in src/iris_pgwire/schema_mapper.py

## Phase 2: Contract Tests (TDD) ⚠️ MUST COMPLETE BEFORE Phase 3

**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

- [x] T002 [P] Contract tests for translate_input_schema() in tests/contract/test_schema_mapping_input.py
- [x] T003 [P] Contract tests for translate_output_schema() in tests/contract/test_schema_mapping_output.py

## Phase 3: Core Implementation (ONLY after tests are failing)

- [x] T004 Implement translate_input_schema() regex logic in src/iris_pgwire/schema_mapper.py
- [x] T005 Implement translate_output_schema() column-aware replacement in src/iris_pgwire/schema_mapper.py
- [x] T006 Add performance validation (<1ms) in src/iris_pgwire/schema_mapper.py

## Phase 4: Integration

- [x] T007 Integrate schema mapper into SQL translator pipeline in src/iris_pgwire/sql_translator/
- [x] T008 Integrate output translation into protocol result handling in src/iris_pgwire/iris_executor.py

## Phase 5: E2E Validation (ORM Compatibility)

- [x] T009 [P] E2E test information_schema queries via psycopg3 in tests/integration/test_schema_mapping_e2e.py
- [ ] T010 [P] E2E test Prisma db pull introspection in tests/e2e/test_prisma_introspection.py (deferred - requires Prisma setup)
- [ ] T011 [P] E2E test SQLAlchemy metadata.reflect() in tests/e2e/test_sqlalchemy_reflection.py (deferred - requires SQLAlchemy setup)
- [x] T012 [P] E2E test schema-qualified queries (public.tablename) in tests/integration/test_schema_mapping_e2e.py

## Dependencies

```
T001 → T002, T003 (setup before tests)
T002, T003 → T004, T005 (tests before implementation)
T004, T005 → T006 (core before performance)
T006 → T007, T008 (implementation before integration)
T007, T008 → T009, T010, T011, T012 (integration before E2E)
```

## Parallel Execution Examples

### Contract Tests (Phase 2)
```
# Launch T002-T003 together:
Task: "Contract tests for translate_input_schema() in tests/contract/test_schema_mapping_input.py"
Task: "Contract tests for translate_output_schema() in tests/contract/test_schema_mapping_output.py"
```

### E2E Validation (Phase 5)
```
# Launch T009-T012 together:
Task: "E2E test information_schema queries via psycopg3"
Task: "E2E test Prisma db pull introspection"
Task: "E2E test SQLAlchemy metadata.reflect()"
Task: "E2E test schema-qualified queries (public.tablename)"
```

## Task Details

### T001: Module Skeleton
Create `src/iris_pgwire/schema_mapper.py` with:
```python
"""PostgreSQL public schema to IRIS SQLUser schema mapping."""

SCHEMA_MAP = {"public": "SQLUser"}
REVERSE_MAP = {"SQLUser": "public"}

def translate_input_schema(sql: str) -> str:
    """Replace 'public' with 'SQLUser' in incoming queries."""
    raise NotImplementedError

def translate_output_schema(rows: list, columns: list) -> list:
    """Replace 'SQLUser' with 'public' in result sets."""
    raise NotImplementedError
```

### T002: Input Translation Contract Tests
Per contracts/schema-mapping.md:
- test_where_clause_public
- test_schema_qualified_name
- test_case_insensitive
- test_sqluser_unchanged
- test_system_schema_unchanged

### T003: Output Translation Contract Tests
Per contracts/schema-mapping.md:
- test_table_schema_translation
- test_system_schema_unchanged
- test_non_schema_column_unchanged

### T004: Input Translation Implementation
Regex patterns for:
- `table_schema = 'public'` (case-insensitive)
- `FROM public.tablename`
- `public.` prefix in identifiers

### T005: Output Translation Implementation
Column-aware replacement:
- Target columns: `table_schema`, `schema_name`, `nspname`
- Only replace `SQLUser` → `public` in those columns
- Preserve system schemas (`%*`)

### T006: Performance Validation
Add timing assertions:
- Process 1000 queries, assert p99 < 1ms

### T007-T008: Integration Points
- T007: Call `translate_input_schema()` before SQL execution
- T008: Call `translate_output_schema()` on information_schema results

### T009-T012: E2E Tests
Per quickstart.md validation scenarios:
- T009: Basic psycopg3 information_schema queries
- T010: `npx prisma db pull` completes successfully
- T011: `metadata.reflect(schema='public')` discovers tables
- T012: `SELECT * FROM public.tablename` resolves correctly

## Implementation Strategy

**MVP Scope**: T001-T005 (contract tests + core implementation)
- Delivers working schema translation
- Can be manually tested before integration

**Incremental Delivery**:
1. T001-T005: Core translation logic
2. T007-T008: Wire into existing pipeline
3. T009-T012: Validate ORM compatibility

## Notes

- [P] tasks = different files, no dependencies
- Estimated implementation: ~50 lines code + ~200 lines tests
- No new dependencies required (regex is stdlib)
- All tests use existing pytest infrastructure
