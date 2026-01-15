# Feature Specification: Address IRIS Bridge Gaps

**Feature Branch**: `026-address-gaps-in`  
**Created**: 2026-01-15  
**Status**: Ready for Implementation  
**Input**: Lessons learned from sim project IRIS backend integration (`/Users/tdyar/ws/sim/IRIS_COMPATIBILITY_REPORT.md`)

## Overview

The iris-pgwire bridge has been tested in production with the **sim** project (an AI agent workflow platform) using Drizzle ORM. This spec captures the **four critical gaps** identified during that integration and proposes **structural improvements** to the existing `sql_translator` architecture rather than ad-hoc patches.

### Key Insight from sim Project

The sim project's `IRIS_COMPATIBILITY_REPORT.md` documents:
- **53 tables** successfully migrated to IRIS
- **DDL phase complete**, DML phase started
- Critical gaps blocking production stability

The existing codebase already has a sophisticated `sql_translator` module with:
- `mappings/functions.py` – function registry
- `mappings/datatypes.py` – type mappings  
- `mappings/constructs.py` – SQL construct translations
- `mappings/document_filters.py` – JSON operator handling

**This spec extends that architecture rather than creating parallel systems.**

---

## User Stories

### US-001: HNSW Vector Index Translation (Priority: P1)

**As a** backend developer using Drizzle/Prisma ORM,  
**I want** the bridge to translate PostgreSQL `CREATE INDEX ... USING hnsw` statements into IRIS syntax,  
**So that** vector search indexes are created automatically during migrations without manual SQL changes.

**Why P1**: Vector search is core to AI workloads in sim; without this, developers cannot use IRIS's integrated vector engine.

**Acceptance Criteria**:
1. `CREATE INDEX idx ON table USING hnsw (col vector_cosine_ops)` → `CREATE INDEX idx ON table (col) AS HNSW`
2. Distance metrics `vector_cosine_ops` and `vector_ip_ops` map to IRIS `COSINE` and `DOT_PRODUCT`
3. **`vector_l2_ops` (Euclidean) is NOT supported by IRIS** – bridge returns clear error message
4. `IF NOT EXISTS` is respected; re-running migration doesn't fail
5. Unsupported HNSW options (e.g., `ef_construction`) emit a warning but don't block index creation

**Test**: Run a Drizzle migration containing HNSW index DDL; verify index exists in IRIS via `%Dictionary.IndexDefinition`.

---

### US-002: Native Fast Insert Path (Priority: P2)

**As a** data engineer,  
**I want** the bridge to provide a binary-parameter-binding fast-insert path,  
**So that** bulk data loads complete efficiently without the current "inlining" workaround.

**Why P2**: The sim project's current `execute_many` implementation inlines parameters as string literals (see `iris_executor_fixed.py:409-414`), which is slow and unstable for production loads.

**Acceptance Criteria**:
1. Bulk inserts of ≥10,000 rows use native `executemany` with parameter binding (not string inlining)
2. Performance target: 10,000 rows in ≤30 seconds on standard hardware
3. Partial failures roll back cleanly with clear error reporting
4. Works in both embedded-Python and external-connection modes

**Test**: Insert 10,000 rows via the bridge; measure time; verify row count matches.

---

### US-003: Recursive Nested JSON Operators (Priority: P3)

**As a** developer querying JSON columns,  
**I want** the bridge to translate arbitrarily nested PostgreSQL JSON operators (`->`, `->>`),  
**So that** deep JSON structures can be queried without manual rewrites.

**Why P3**: The sim project has complex metadata stored in JSON columns; current translation only handles single-level access.

**Current State** (from `document_filters.py`):
- `col->>'key'` → `JSON_VALUE(col, '$.key')` ✅
- `col->'a'->>'b'` → **NOT SUPPORTED** ❌

**Acceptance Criteria**:
1. Two-level: `col->'a'->>'b'` → `JSON_VALUE(col, '$.a.b')`
2. Three-level: `col->'a'->'b'->>'c'` → `JSON_VALUE(col, '$.a.b.c')`
3. Array access: `col->'items'->0->>'name'` → `JSON_VALUE(col, '$.items[0].name')`
4. Mixed access preserved: `->` returns JSON object, `->>` returns text

**Test**: Execute `SELECT data->'a'->'b'->>'c' FROM test_json` and verify correct value extraction.

---

### US-004: Protocol-Level DDL Idempotency (Priority: P4)

**As a** DevOps engineer,  
**I want** the bridge to handle `IF NOT EXISTS` at the protocol level,  
**So that** migrations can be safely re-run in CI pipelines.

**Why P4**: The sim project's `IRIS_COMPATIBILITY_REPORT.md` notes the executor currently "swallows" duplicate object errors; this should be formalized.

**Current State**:
- Duplicate errors are caught and suppressed
- No logging of skipped objects
- No distinction between `IF NOT EXISTS` and unexpected errors

**Acceptance Criteria**:
1. `CREATE TABLE IF NOT EXISTS` on existing table → success + warning log
2. `CREATE INDEX IF NOT EXISTS` on existing index → success + warning log  
3. DDL without `IF NOT EXISTS` on existing object → proper error raised
4. All idempotent operations logged with object name and action taken

**Test**: Run `CREATE TABLE IF NOT EXISTS foo ...` twice; verify second execution logs "table 'foo' already exists, skipping".

---

## Structural Requirements

### SR-001: Centralize Conversion Utilities

**Problem**: Date/horolog conversions are duplicated across 6+ executor files in the sim project.

**Solution**: Create `src/iris_pgwire/conversions/` package:
```
conversions/
├── __init__.py          # Public exports
├── date_horolog.py      # horolog_to_pg(), pg_to_horolog()
├── json_path.py         # build_json_path(), parse_json_operators()
├── vector_syntax.py     # translate_hnsw_index(), normalize_vector()
└── ddl_idempotency.py   # wrap_if_not_exists(), check_object_exists()
```

All conversion functions must:
- Be pure (no side effects)
- Have full type annotations
- Include docstrings with examples
- Have unit tests

---

### SR-002: Extend Existing Mapping Registries

**Problem**: New functionality should integrate with existing `sql_translator/mappings/` architecture.

**Solution**: Add entries to existing registries rather than creating parallel systems:

| Registry | New Entries |
|----------|-------------|
| `constructs.py` | HNSW index translation patterns |
| `document_filters.py` | Recursive JSON operator handling |
| `functions.py` | Vector distance function mappings |

---

### SR-003: Unified Error Handling for DDL

**Problem**: DDL errors are handled inconsistently across the codebase.

**Solution**: Create `DdlErrorHandler` class that:
- Classifies errors (duplicate object, permission denied, syntax error, etc.)
- Checks for `IF NOT EXISTS` clause presence
- Logs appropriate messages
- Returns structured result (success/skip/fail)

---

## Functional Requirements

| FR | Description |
|----|-------------|
| FR-001 | **HNSW Translation**: Parse `USING hnsw (col distance_ops)` and emit `(col) AS HNSW`. Map `vector_cosine_ops` → COSINE, `vector_ip_ops` → DOT_PRODUCT. **Reject `vector_l2_ops` with clear error** (IRIS does not support L2/Euclidean distance for HNSW). |
| FR-002 | **Fast Insert**: Implement `execute_many_native()` that uses IRIS cursor `executemany()` with proper parameter binding. Fall back to current inlining only if native fails. |
| FR-003 | **Recursive JSON**: Implement `JsonPathBuilder` that accumulates `->` and `->>` operators into a single JSONPath string. Handle array indices. |
| FR-004 | **DDL Idempotency**: Wrap DDL execution in `DdlErrorHandler`. Log skipped objects. Distinguish intentional idempotency from unexpected errors. |
| FR-005 | **Audit Trail**: All transformations emit structured log entries with: original SQL, transformed SQL, transformation type, duration. |

---

## Non-Functional Requirements

| NFR | Description | Target |
|-----|-------------|--------|
| NFR-001 | Translation latency | <5ms for 95th percentile (per constitution) |
| NFR-002 | Bulk insert throughput | ≥10,000 rows in 30 seconds |
| NFR-003 | Memory overhead | <50MB additional for batch operations |
| NFR-004 | Backward compatibility | All existing tests pass unchanged |

---

## Success Criteria

| SC | Metric | Target |
|----|--------|--------|
| SC-001 | HNSW index creation via ORM | 100% success rate in clean environment |
| SC-002 | Bulk insert benchmark | ≥333 rows/second sustained |
| SC-003 | Nested JSON accuracy | ≥99% correct results for 3-level nesting |
| SC-004 | Migration re-run safety | Zero errors on duplicate DDL with `IF NOT EXISTS` |
| SC-005 | Code duplication | Zero duplicate conversion functions across modules |

---

## Edge Cases

1. **HNSW with unsupported distance metric**: `vector_l2_ops` (Euclidean) → return error: "IRIS does not support L2 distance for HNSW indexes. Use vector_cosine_ops or vector_ip_ops."
2. **HNSW with unsupported options**: `ef_construction`, `m` parameters → log warning, create index without those options
3. **Bulk insert packet overflow**: Requests >50MB → reject with 413 Payload Too Large
4. **Malformed JSON path**: Invalid operator sequence → return clear error message with position
5. **DDL on non-existent schema**: `CREATE TABLE schema.table` where schema doesn't exist → proper error (not masked)
6. **Mixed DDL batch**: Script with some `IF NOT EXISTS` and some without → handle each statement individually

---

## Assumptions

- IRIS version supports HNSW indexes (`CREATE INDEX ... AS HNSW`)
- IRIS supports `JSON_VALUE` function with dot-notation paths
- The bridge runs in Docker with access to IRIS embedded Python or external connection
- Drizzle ORM is the primary consumer (Prisma patterns similar)

---

## References

- sim project compatibility report: `/Users/tdyar/ws/sim/IRIS_COMPATIBILITY_REPORT.md`
- Existing translator architecture: `src/iris_pgwire/sql_translator/`
- IRIS vector documentation: InterSystems docs on Integrated Vector Search
- PostgreSQL JSON operators: https://www.postgresql.org/docs/current/functions-json.html

---

*Revised spec based on production learnings from sim project IRIS integration.*
