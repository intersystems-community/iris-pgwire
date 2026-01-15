# Research Summary: Address IRIS Bridge Gaps

## Overview

This research consolidates learnings from the **sim project** IRIS backend integration. The sim project successfully migrated 53 tables to IRIS and identified four critical gaps that this feature addresses.

## Source Material

| Source | Key Findings |
|--------|--------------|
| `/Users/tdyar/ws/sim/IRIS_COMPATIBILITY_REPORT.md` | DDL complete, DML gaps identified |
| `/Users/tdyar/ws/sim/iris/iris_executor_fixed.py` | Current workarounds for bulk insert |
| `/Users/tdyar/ws/sim/iris/translator.py` | Existing sql_translator architecture |
| `/Users/tdyar/ws/sim/iris-pgwire-source/src/iris_pgwire/sql_translator/mappings/` | Registry-based translation system |

---

## Decision 1: HNSW Index Translation Strategy

**Decision**: Parse `USING hnsw (col ops)` with regex, emit `(col) AS HNSW`

**Rationale**:
- IRIS HNSW syntax is simpler than PostgreSQL's
- Distance metric is inferred from operator name (`vector_cosine_ops` → cosine)
- Parameters like `ef_construction` have no IRIS equivalent; safe to ignore with warning

**Alternatives Considered**:
- Full SQL parser (sqlparse) → Overkill for single construct; regex sufficient
- Pass-through with error handling → Breaks ORM migrations

**Implementation**:
```python
# Pattern to match
HNSW_PATTERN = r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s+USING\s+hnsw\s*\(([^)]+)\)"

# Distance operator mapping (L2 NOT SUPPORTED by IRIS)
DISTANCE_OPS = {
    "vector_cosine_ops": "COSINE",
    "vector_ip_ops": "DOT_PRODUCT",
    # "vector_l2_ops": NOT SUPPORTED - raise error
}

UNSUPPORTED_OPS = {
    "vector_l2_ops": "IRIS does not support L2/Euclidean distance for HNSW indexes. Use vector_cosine_ops (cosine) or vector_ip_ops (dot product)."
}
```

---

## Decision 2: Fast Insert Implementation

**Decision**: Use native `cursor.executemany()` with parameter binding; fall back to inlining only on failure

**Rationale**:
- Current sim implementation inlines parameters as strings (line 409-414 of iris_executor_fixed.py)
- This is slow (string concatenation) and unstable (escaping issues)
- IRIS Python driver supports `executemany()` with proper binding

**Alternatives Considered**:
- COPY protocol → IRIS doesn't support PostgreSQL COPY natively
- Batch INSERT with VALUES → Still requires string building
- Stored procedure → Adds deployment complexity

**Implementation**:
```python
async def execute_many_native(self, sql: str, params_list: list[list]) -> dict:
    """Native executemany with parameter binding."""
    connection = self._get_pooled_connection()
    cursor = connection.cursor()
    try:
        cursor.executemany(sql, params_list)
        return {"success": True, "rows_affected": len(params_list)}
    except Exception as e:
        # Fall back to inlining if native fails
        return await self._execute_many_inline_fallback(sql, params_list)
```

**Benchmark Target**: 10,000 rows in ≤30 seconds (≥333 rows/sec)

---

## Decision 3: Recursive JSON Path Builder

**Decision**: Implement `JsonPathBuilder` class that accumulates operators into JSONPath string

**Rationale**:
- Current `document_filters.py` only handles single-level `->>`
- PostgreSQL allows arbitrary nesting: `col->'a'->'b'->>'c'`
- IRIS `JSON_VALUE` accepts dot-notation paths

**Alternatives Considered**:
- Recursive regex replacement → Error-prone, hard to debug
- Full JSON path parser library → Dependency overhead for simple use case

**Implementation**:
```python
class JsonPathBuilder:
    """Accumulate PostgreSQL JSON operators into IRIS JSONPath."""
    
    def parse(self, sql: str) -> str:
        """Convert col->'a'->'b'->>'c' to JSON_VALUE(col, '$.a.b.c')"""
        # Track operator chain
        # Build path incrementally
        # Handle array indices: col->'items'->0 → $.items[0]
```

**Test Cases**:
| Input | Output |
|-------|--------|
| `col->>'key'` | `JSON_VALUE(col, '$.key')` |
| `col->'a'->>'b'` | `JSON_VALUE(col, '$.a.b')` |
| `col->'a'->'b'->>'c'` | `JSON_VALUE(col, '$.a.b.c')` |
| `col->'items'->0->>'name'` | `JSON_VALUE(col, '$.items[0].name')` |

---

## Decision 4: DDL Idempotency Handler

**Decision**: Create `DdlErrorHandler` class that classifies errors and checks for `IF NOT EXISTS`

**Rationale**:
- Current implementation swallows all duplicate-object errors silently
- No distinction between intentional idempotency and unexpected errors
- No logging of skipped operations

**Alternatives Considered**:
- Check object existence before DDL → Extra round-trip, race conditions
- Always use IF NOT EXISTS internally → Masks real errors

**Implementation**:
```python
class DdlErrorHandler:
    DUPLICATE_OBJECT_CODES = {"42P07", "42710"}  # PostgreSQL error codes
    
    def handle(self, sql: str, error: Exception) -> DdlResult:
        if self._is_duplicate_error(error):
            if self._has_if_not_exists(sql):
                logger.warning(f"Object already exists, skipping: {self._extract_object_name(sql)}")
                return DdlResult(success=True, skipped=True)
            else:
                raise error  # Real error, propagate
        raise error
```

---

## Decision 5: Conversion Utilities Package

**Decision**: Create `src/iris_pgwire/conversions/` package to centralize duplicated utilities

**Rationale**:
- Date/horolog conversions duplicated in 6+ files across sim project
- Violates constitution "no code duplication" principle
- Makes maintenance error-prone

**Package Structure**:
```
conversions/
├── __init__.py          # Public API exports
├── date_horolog.py      # horolog_to_pg(), pg_to_horolog()
├── json_path.py         # JsonPathBuilder, parse_json_operators()
├── vector_syntax.py     # translate_hnsw_index(), normalize_vector()
└── ddl_idempotency.py   # DdlErrorHandler, wrap_if_not_exists()
```

**Design Principles**:
- All functions are pure (no side effects)
- Full type annotations
- Docstrings with examples
- 100% unit test coverage

---

## Performance Targets (from Constitution)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Translation latency | <5ms p95 | `PerformanceTimer` in translator |
| Bulk insert throughput | ≥333 rows/sec | Integration test benchmark |
| Memory overhead | <50MB for batches | Docker container metrics |

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `intersystems-irispython` | ≥3.0 | IRIS Python driver |
| `psycopg[binary]` | ≥3.0 | PostgreSQL compatibility layer |
| `structlog` | existing | Structured logging |
| `pytest-benchmark` | new | Performance testing |

---

## Open Items Resolved

All technical decisions documented. No remaining `NEEDS CLARIFICATION` markers.

---

*Research completed based on sim project production integration experience.*
