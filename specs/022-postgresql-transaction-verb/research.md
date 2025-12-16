# Research: PostgreSQL Transaction Verb Compatibility

**Feature**: 022-postgresql-transaction-verb
**Date**: 2025-11-08
**Status**: Research Phase Skipped - No Unknowns

## Executive Summary

Research phase skipped per Phase 0 assessment in plan.md. Feature scope is well-defined with no technical unknowns, dependency unknowns, or integration unknowns. This document serves as a record of that decision and provides reference information for implementation.

## Decision: Skip Research Phase

**Rationale**: All technical requirements are known from:
1. **PostgreSQL Documentation**: Transaction control syntax is well-documented standard
2. **IRIS Documentation**: Transaction syntax documented in SQL reference
3. **Feature 021 Pattern**: SQL transformation pattern already established and validated
4. **Specification Completeness**: spec.md contains 10 functional requirements with no [NEEDS CLARIFICATION] markers

## Known Technical Details

### PostgreSQL Transaction Syntax (Source)

```sql
-- Standard PostgreSQL transaction commands (from PostgreSQL 16 documentation)
BEGIN [WORK | TRANSACTION] [transaction_mode [, ...]]
START TRANSACTION [transaction_mode [, ...]]
COMMIT [WORK | TRANSACTION]
ROLLBACK [WORK | TRANSACTION]

-- Where transaction_mode can be:
ISOLATION LEVEL { SERIALIZABLE | REPEATABLE READ | READ COMMITTED | READ UNCOMMITTED }
READ WRITE | READ ONLY
[NOT] DEFERRABLE
```

**Key Insights**:
- `BEGIN` and `START TRANSACTION` are synonymous in PostgreSQL
- Optional modifiers must be preserved during translation
- Case-insensitive: `BEGIN`, `begin`, `Begin` all valid

### IRIS Transaction Syntax (Target)

```sql
-- IRIS transaction commands (from IRIS SQL Reference)
START TRANSACTION [transaction_mode]
COMMIT [WORK]
ROLLBACK [WORK]

-- IRIS does NOT support:
BEGIN  -- ❌ Not recognized as transaction start
BEGIN TRANSACTION  -- ❌ Not recognized

-- IRIS session-level transaction modes:
SET TRANSACTION %COMMITMODE=0  -- IMPLICIT (auto-commit)
SET TRANSACTION %COMMITMODE=1  -- EXPLICIT (manual commit/rollback)
SET TRANSACTION %COMMITMODE=2  -- OBJECTSCRIPT (advanced)
```

**Key Insights**:
- `BEGIN` is not a valid IRIS transaction command
- `START TRANSACTION` is the only supported transaction start syntax
- `COMMIT` and `ROLLBACK` work identically to PostgreSQL
- Isolation levels supported via modifiers (same syntax as PostgreSQL)

### Translation Requirements

**Simple Mapping**:
```
PostgreSQL → IRIS
----------    ----
BEGIN         → START TRANSACTION
BEGIN TRANSACTION → START TRANSACTION
BEGIN WORK    → START TRANSACTION
BEGIN <modifiers> → START TRANSACTION <modifiers>
COMMIT        → COMMIT (unchanged)
ROLLBACK      → ROLLBACK (unchanged)
```

**Edge Cases to Handle**:
1. **String Literals**: `SELECT 'BEGIN'` must NOT be translated
2. **Case Insensitivity**: `begin`, `Begin`, `BEGIN` all must translate
3. **Modifier Preservation**: `BEGIN ISOLATION LEVEL READ COMMITTED` → `START TRANSACTION ISOLATION LEVEL READ COMMITTED`
4. **Nested Transactions**: IRIS limitation - server should pass through and let IRIS error
5. **Comments**: `-- BEGIN` inside comment must NOT be translated

## Integration Pattern (From Feature 021)

Feature 021 established the SQL normalization pattern that this feature will follow:

```python
# Pattern: Intercept SQL before execution, apply transformation, pass to IRIS

class IRISExecutor:
    async def _execute_embedded_async(self, sql, params):
        # Step 1: Apply transaction verb translation (NEW - Feature 022)
        sql = translate_transaction_verbs(sql)

        # Step 2: Apply SQL normalization (EXISTING - Feature 021)
        sql = normalize_sql(sql)

        # Step 3: Execute against IRIS
        result = await asyncio.to_thread(iris.sql.exec, sql)
        return result
```

**Integration Points** (3 locations):
1. `iris_executor.py::_execute_embedded_async()` - Direct execution path
2. `iris_executor.py::_execute_external_async()` - External connection fallback
3. `vector_optimizer.py::optimize_vector_query()` - Vector query optimization

**Why 3 Integration Points?**:
- Feature 021 established that ALL SQL execution paths must apply normalization
- Transaction commands can appear in any execution context (direct, external, vector queries)
- Constitutional requirement: No SQL can bypass translation layer

## Performance Considerations

**Translation Overhead Target**: <0.1ms per command

**Complexity Analysis**:
- String pattern matching: O(n) where n = SQL length
- Regex compilation: O(1) (compiled once, reused)
- String replacement: O(n) worst case
- Typical transaction command length: 10-50 characters
- Expected overhead: <0.01ms (100× below constitutional target)

**Performance Validation**:
- Measure overhead with Python `time.perf_counter()`
- Track metrics via existing `performance_monitor.py` (Feature 021)
- Report violations if >0.1ms (constitutional requirement)

## Testing Strategy

**TDD Approach** (from constitution Principle II):
1. Write contract tests first (must fail - no implementation exists)
2. Write E2E tests with real clients (must fail - translation doesn't exist)
3. Implement translation logic to make tests pass
4. Validate performance tests (must be <0.1ms)

**Real Client Testing**:
- **psql**: `echo "BEGIN; SELECT 1; COMMIT" | psql -h localhost -p 5432`
- **psycopg**: Python driver with context manager `with conn.begin():`
- **SQLAlchemy**: `with engine.connect() as conn: with conn.begin():`

## Implementation Recommendation

**Minimal Implementation** (~100-150 lines):

```python
# src/iris_pgwire/sql_translator/transaction_translator.py
import re
import time
from typing import Dict, Any

class TransactionTranslator:
    """Translate PostgreSQL transaction verbs to IRIS equivalents"""

    # Case-insensitive regex patterns
    BEGIN_PATTERN = re.compile(
        r'^\s*BEGIN(?:\s+TRANSACTION|\s+WORK)?(?:\s+(.*))?$',
        re.IGNORECASE
    )

    def translate(self, sql: str) -> str:
        """Main translation entry point"""
        start_time = time.perf_counter()

        # Check if this is a transaction command
        if not self._is_transaction_command(sql):
            return sql

        # Apply translation
        result = self._translate_begin(sql)

        # Track performance
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        if elapsed_ms > 0.1:
            logger.warning(f"Translation SLA violation: {elapsed_ms:.2f}ms")

        return result

    def _translate_begin(self, sql: str) -> str:
        """Translate BEGIN variants to START TRANSACTION"""
        match = self.BEGIN_PATTERN.match(sql.strip())
        if match:
            modifiers = match.group(1) or ''
            return f"START TRANSACTION {modifiers}".strip()
        return sql

    def _is_transaction_command(self, sql: str) -> bool:
        """Check if SQL is a transaction control command"""
        sql_upper = sql.strip().upper()
        return sql_upper.startswith(('BEGIN', 'COMMIT', 'ROLLBACK'))
```

**Why This Implementation?**:
- Simple and maintainable (~100 lines)
- Follows Feature 021 pattern
- Performance overhead minimal (regex compile once, reuse)
- Easy to test (pure function, no side effects)

## References

1. **PostgreSQL 16 Documentation**: Transaction Control
   https://www.postgresql.org/docs/16/sql-begin.html

2. **IRIS SQL Reference**: Transaction Commands
   (InterSystems IRIS SQL Reference - Transaction Management)

3. **Feature 021 Implementation**: SQL Normalization Pattern
   `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/sql_translator/`

4. **Constitution v1.3.0**: Performance Standards (Section: Performance Standards)
   `/Users/tdyar/ws/iris-pgwire/.specify/memory/constitution.md`

5. **Specification**: Feature 022 Functional Requirements
   `/Users/tdyar/ws/iris-pgwire/specs/022-postgresql-transaction-verb/spec.md`

---

## Conclusion

Research phase skipped due to complete specification and known technical requirements. Implementation can proceed directly to Phase 1 design and Phase 2 task generation. All necessary patterns, integration points, and performance targets are documented and validated from previous features (Feature 021).

**Next Step**: Execute Phase 1 (Design & Contracts) per plan.md workflow.
