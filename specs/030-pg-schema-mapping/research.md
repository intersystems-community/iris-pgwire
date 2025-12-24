# Research: PostgreSQL Schema Mapping

## Decision Summary

| Topic | Decision | Alternatives Rejected |
|-------|----------|----------------------|
| Translation approach | Regex substitution | SQL AST parsing (overkill for schema names) |
| Integration point | vector_optimizer.py | New middleware layer (unnecessary complexity) |
| Output transformation | Column-aware replacement | Global string replace (too aggressive) |
| Case handling | Case-insensitive input | Strict case match (breaks PostgreSQL compatibility) |

## Research Findings

### 1. Prisma Introspection Query Analysis

Prisma sends these queries during `db pull`:

```sql
-- Schema discovery (fails on IRIS due to 'public')
SELECT table_schema, table_name, table_type
FROM information_schema.tables
WHERE table_schema = 'public'

-- Column discovery
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = ?
```

**Finding**: Simple `WHERE table_schema = 'public'` replacement sufficient for Prisma.

### 2. SQLAlchemy Reflection Analysis

SQLAlchemy uses:
```python
metadata.reflect(schema='public')  # Passed to information_schema queries
```

**Finding**: Same pattern as Prisma - schema name in WHERE clause.

### 3. IRIS information_schema Structure

IRIS returns `table_schema = 'SQLUser'` for user tables:
```sql
SELECT DISTINCT table_schema FROM information_schema.tables LIMIT 5;
-- Returns: SQLUser, %SYS, %Library, etc.
```

**Finding**: Only `SQLUser` needs mapping. System schemas (`%*`) untouched.

### 4. Token Optimization Strategy

Per user request, minimize implementation:

1. **No new module**: Add functions to existing `sql_translator/` or `vector_optimizer.py`
2. **No configuration**: Hardcode `public` ↔ `SQLUser` mapping
3. **Regex over AST**: Simple pattern matching for schema names
4. **Targeted output transform**: Only modify `table_schema` columns, not all strings

**Estimated implementation**: ~50 lines of code + ~150 lines of tests
