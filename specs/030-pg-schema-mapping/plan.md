# Implementation Plan: PostgreSQL Schema Mapping

**Branch**: `030-pg-schema-mapping` | **Date**: 2024-12-23 | **Spec**: [spec.md](./spec.md)

## Summary

Map PostgreSQL `public` schema to IRIS `SQLUser` schema bidirectionally to enable ORM introspection tools (Prisma, SQLAlchemy) to discover and query IRIS tables without configuration. Implementation requires two translation points: input queries (public→SQLUser) and output results (SQLUser→public).

## Technical Context

**Language/Version**: Python 3.11 (existing PGWire codebase)
**Primary Dependencies**: Existing SQL translator, vector_optimizer.py patterns
**Storage**: N/A (schema mapping only, no data storage)
**Testing**: pytest with psycopg3, Prisma CLI, SQLAlchemy
**Target Platform**: Linux/macOS (Docker deployment)
**Project Type**: Single project (extend existing iris_pgwire module)
**Performance Goals**: <1ms overhead per query (per NFR-001)
**Constraints**: Must not break existing SQLUser schema queries
**Scale/Scope**: ~50 lines of translation code, ~200 lines of tests

## Constitution Check

*GATE: Must pass before Phase 0 research.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Protocol Fidelity | ✅ PASS | PostgreSQL clients expect `public` schema - this improves compliance |
| II. Test-First Development | ✅ PLANNED | Prisma, SQLAlchemy, psycopg3 tests specified |
| III. Phased Implementation | ✅ PASS | Extends P1 query translation (already complete) |
| IV. IRIS Integration | ✅ PASS | Uses existing embedded Python patterns |
| V. Production Readiness | ✅ PASS | Transparent operation, no new security surface |
| VI. Vector Performance | N/A | Not a vector feature |
| VII. Dev Environment Sync | ✅ AWARE | Will restart container after code changes |

**Initial Constitution Check: PASS** - No violations requiring justification.

## Project Structure

### Documentation (this feature)
```
specs/030-pg-schema-mapping/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (minimal - no data entities)
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/tasks command)
```

### Source Code (repository root)
```
src/iris_pgwire/
├── schema_mapper.py     # NEW: Schema translation logic (~50 lines)
├── sql_translator/      # Existing: Will import schema_mapper
└── protocol.py          # Existing: May need minor integration

tests/
├── contract/
│   └── test_schema_mapping_contract.py  # NEW: Schema translation tests
├── integration/
│   └── test_schema_mapping_e2e.py       # NEW: ORM compatibility tests
└── e2e/
    └── test_prisma_introspection.py     # NEW: Prisma db pull test
```

**Structure Decision**: Single project - extends existing iris_pgwire module with new schema_mapper.py module.

## Phase 0: Research

### Token Usage Optimization Opportunities

Based on user request to minimize token usage:

1. **Single-file implementation**: All schema mapping logic in one ~50 line file
2. **Regex-based translation**: Simple string replacement vs AST parsing
3. **Inline mapping**: Hardcoded `public`↔`SQLUser` vs configurable mappings
4. **Extend existing patterns**: Reuse vector_optimizer.py approach for SQL rewriting

### Research Tasks

| Topic | Decision | Rationale |
|-------|----------|-----------|
| Translation approach | Regex substitution | Simpler than SQL AST parsing, sufficient for schema name replacement |
| Integration point | SQL translator layer | Existing translation pipeline, consistent with vector optimizer |
| Result transformation | Modify query results | Replace `SQLUser` with `public` in information_schema output |
| Case handling | Case-insensitive match | PostgreSQL schema names are case-insensitive |

### Implementation Strategy (Minimal Token Approach)

```python
# schema_mapper.py - Entire implementation (~50 lines)

SCHEMA_MAP = {"public": "SQLUser"}
REVERSE_MAP = {"SQLUser": "public"}

def translate_input_schema(sql: str) -> str:
    """Replace 'public' with 'SQLUser' in incoming queries."""
    # Case-insensitive replacement for schema references
    pass

def translate_output_schema(rows: list, columns: list) -> list:
    """Replace 'SQLUser' with 'public' in result sets."""
    # Only for columns named 'table_schema', 'schema_name', etc.
    pass
```

**Output**: research.md complete (consolidated above)

## Phase 1: Design & Contracts

### Data Model

Minimal - no new data entities. Schema mapping is a pure translation function.

**Mapping Entity** (conceptual only):
- Input: PostgreSQL schema name (`public`)
- Output: IRIS schema name (`SQLUser`)
- Direction: Bidirectional
- Case sensitivity: Case-insensitive input, preserve IRIS case in output

### API Contracts

No new API endpoints. Schema mapping is transparent middleware applied to:

1. **Input Translation** (SQL queries):
   - `WHERE table_schema = 'public'` → `WHERE table_schema = 'SQLUser'`
   - `FROM public.tablename` → `FROM SQLUser.tablename`

2. **Output Translation** (Result sets):
   - `table_schema: 'SQLUser'` → `table_schema: 'public'`

### Contract Tests

```python
# tests/contract/test_schema_mapping_contract.py

class TestSchemaInputTranslation:
    def test_public_to_sqluser_where_clause(self):
        sql = "SELECT * FROM information_schema.tables WHERE table_schema = 'public'"
        result = translate_input_schema(sql)
        assert "table_schema = 'SQLUser'" in result

    def test_public_schema_qualified_table(self):
        sql = "SELECT * FROM public.mytable"
        result = translate_input_schema(sql)
        assert "SQLUser.mytable" in result

    def test_case_insensitive_matching(self):
        sql = "WHERE table_schema = 'PUBLIC'"
        result = translate_input_schema(sql)
        assert "SQLUser" in result

    def test_sqluser_unchanged(self):
        sql = "WHERE table_schema = 'SQLUser'"
        result = translate_input_schema(sql)
        assert "SQLUser" in result  # Not double-mapped

    def test_system_schema_unchanged(self):
        sql = "WHERE table_schema = '%SYS'"
        result = translate_input_schema(sql)
        assert "%SYS" in result  # System schemas untouched

class TestSchemaOutputTranslation:
    def test_sqluser_to_public_in_results(self):
        rows = [("SQLUser", "mytable")]
        columns = ["table_schema", "table_name"]
        result = translate_output_schema(rows, columns)
        assert result[0][0] == "public"
```

### Integration Test Approach

```python
# tests/integration/test_schema_mapping_e2e.py

def test_information_schema_tables_public_filter():
    """Query information_schema.tables with public schema filter."""
    conn = psycopg.connect("host=localhost port=5432 user=_SYSTEM")
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' LIMIT 5")
    rows = cur.fetchall()
    assert len(rows) > 0  # Should find SQLUser tables

def test_prisma_db_pull():
    """Prisma introspection completes successfully."""
    # Run in /tmp/prisma-test with schema pointing to PGWire
    result = subprocess.run(["npx", "prisma", "db", "pull"], capture_output=True)
    assert result.returncode == 0
    assert "model" in Path("prisma/schema.prisma").read_text()
```

### Quickstart

See `quickstart.md` for step-by-step validation.

## Phase 2: Task Planning Approach

**Task Generation Strategy**:
- 3 contract test tasks (input, output, edge cases)
- 1 implementation task (schema_mapper.py)
- 2 integration tasks (SQL translator, protocol)
- 3 E2E test tasks (psycopg3, Prisma, SQLAlchemy)

**Ordering Strategy**:
1. Contract tests first (TDD)
2. Core implementation
3. Integration into existing pipeline
4. E2E validation

**Estimated Output**: 10-12 tasks (minimal scope feature)

## Complexity Tracking

No violations - feature is intentionally minimal scope.

## Progress Tracking

**Phase Status**:
- [x] Phase 0: Research complete
- [x] Phase 1: Design complete
- [x] Phase 2: Task planning complete
- [x] Phase 3: Tasks generated (/tasks command)
- [x] Phase 4: Implementation complete
- [x] Phase 5: Validation passed (psycopg3 E2E tests passing)

**Gate Status**:
- [x] Initial Constitution Check: PASS
- [x] Post-Design Constitution Check: PASS
- [x] All NEEDS CLARIFICATION resolved
- [x] Complexity deviations documented (none needed)

---
*Based on Constitution v1.3.1 - See `.specify/memory/constitution.md`*
