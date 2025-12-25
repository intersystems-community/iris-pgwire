# Phase 0 Research: Prisma Catalog Support

**Feature Branch**: `031-prisma-catalog-support`
**Created**: 2025-12-23
**Status**: Complete

---

## Research Task 1: Prisma Catalog Query Patterns

### Summary

Prisma's `db pull` (introspection) command queries PostgreSQL system catalogs to discover database schema. The queries target `pg_catalog` schema tables rather than `information_schema` views for more detailed metadata.

### Key Findings

#### 1.1 Primary Catalog Tables Used

Based on PostgreSQL introspection documentation and Prisma ORM behavior:

| Catalog Table | Purpose | Prisma Usage |
|--------------|---------|--------------|
| `pg_class` | Tables, views, indexes, sequences | Enumerate all relations |
| `pg_attribute` | Column definitions | Get column names, types, positions |
| `pg_constraint` | Constraints (PK, FK, UNIQUE, CHECK) | Discover relationships |
| `pg_index` | Index definitions | Identify indexes |
| `pg_namespace` | Schema/namespace info | Map schemas to names |
| `pg_type` | Data type definitions | Resolve type OIDs |
| `pg_attrdef` | Default values | Get column defaults |
| `pg_depend` | Object dependencies | Track FK relationships |

#### 1.2 Typical Query Patterns

**Pattern 1: Get all tables in a namespace**
```sql
SELECT c.oid, c.relname, c.relkind, c.relnamespace
FROM pg_catalog.pg_class c
LEFT JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'v', 'p')  -- tables, views, partitioned
  AND n.nspname = 'public'
```

**Pattern 2: Get columns for a table**
```sql
SELECT a.attnum, a.attname, a.atttypid, a.attnotnull, a.atthasdef
FROM pg_catalog.pg_attribute a
WHERE a.attrelid = $1::oid
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum
```

**Pattern 3: Get constraints (including foreign keys)**
```sql
SELECT c.oid, c.conname, c.contype, c.conrelid, c.confrelid, c.conkey, c.confkey
FROM pg_catalog.pg_constraint c
WHERE c.conrelid = $1::oid
  OR c.confrelid = $1::oid
```

**Pattern 4: Get indexes**
```sql
SELECT i.indexrelid, i.indrelid, i.indkey, i.indisunique, i.indisprimary
FROM pg_catalog.pg_index i
WHERE i.indrelid = $1::oid
```

#### 1.3 Array Parameter Usage

Prisma often sends queries with array parameters (e.g., `WHERE oid = ANY($1)`):

```sql
SELECT oid, typname, typnamespace, typlen
FROM pg_catalog.pg_type
WHERE oid = ANY($1)  -- $1 is array of OIDs like {23, 25, 1043}
```

**IRIS Challenge**: IRIS doesn't natively support PostgreSQL array syntax. Need to translate `ANY($1)` to `IN (...)` or use IRIS list functions.

#### 1.4 OID Resolution with `::regclass`

Prisma uses PostgreSQL's regclass cast for table name → OID conversion:

```sql
SELECT oid FROM pg_class WHERE oid = 'public.users'::regclass
```

**Implementation**: Need to intercept `::regclass` casts and resolve via INFORMATION_SCHEMA lookup.

---

## Research Task 2: IRIS INFORMATION_SCHEMA Coverage

### Summary

IRIS INFORMATION_SCHEMA provides the core metadata needed to populate PostgreSQL catalog responses.

### 2.1 Available IRIS Metadata Tables

| IRIS Table | Maps To PostgreSQL | Notes |
|-----------|-------------------|-------|
| `INFORMATION_SCHEMA.TABLES` | `pg_class` (relkind='r','v') | Has TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE |
| `INFORMATION_SCHEMA.COLUMNS` | `pg_attribute` | Has COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION |
| `INFORMATION_SCHEMA.TABLE_CONSTRAINTS` | `pg_constraint` (partial) | Has CONSTRAINT_TYPE, CONSTRAINT_NAME |
| `INFORMATION_SCHEMA.KEY_COLUMN_USAGE` | `pg_constraint` (conkey) | Has COLUMN_NAME, POSITION_IN_UNIQUE_CONSTRAINT |
| `INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS` | `pg_constraint` (FK) | Has referenced table info |
| N/A | `pg_index` | Need alternative approach |

### 2.2 Metadata Query Examples

**Get tables:**
```sql
SELECT TABLE_NAME, TABLE_TYPE
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'SQLUser'
```

**Get columns:**
```sql
SELECT COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION, IS_NULLABLE, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'SQLUser' AND TABLE_NAME = 'users'
ORDER BY ORDINAL_POSITION
```

**Get constraints:**
```sql
SELECT tc.CONSTRAINT_NAME, tc.CONSTRAINT_TYPE, kcu.COLUMN_NAME
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
  ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
WHERE tc.TABLE_SCHEMA = 'SQLUser' AND tc.TABLE_NAME = 'users'
```

### 2.3 Coverage Gaps

| Required | IRIS Coverage | Workaround |
|----------|--------------|------------|
| Index metadata | Not in INFORMATION_SCHEMA | Use `%Dictionary.CompiledIndex` or SQL system tables |
| OID values | Not available | Generate deterministic OIDs via hashing |
| Array columns | Not directly indicated | Infer from data type |
| Type modifiers | Partial | Parse from DATA_TYPE column |

---

## Research Task 3: OID Generation Strategy

### Summary

PostgreSQL catalogs use OID (Object Identifier) values extensively. IRIS doesn't have OIDs, so we must generate stable, deterministic values.

### 3.1 OID Requirements

1. **Stability**: Same object must return same OID across queries
2. **Uniqueness**: Different objects must have different OIDs
3. **Determinism**: OID must be reproducible (no random generation)
4. **Range**: PostgreSQL OIDs are 32-bit unsigned integers (0 to 4294967295)

### 3.2 Recommended Approach: Deterministic Hashing

```python
import hashlib

def generate_oid(namespace: str, object_type: str, object_name: str) -> int:
    """
    Generate a stable OID from object identity.

    Args:
        namespace: Schema name (e.g., 'SQLUser')
        object_type: Object type ('table', 'column', 'constraint', 'index')
        object_name: Object name (e.g., 'users', 'users.id')

    Returns:
        32-bit unsigned integer OID
    """
    # Create deterministic string
    identity = f"{namespace}:{object_type}:{object_name}"

    # Hash to get stable bytes
    hash_bytes = hashlib.sha256(identity.encode()).digest()

    # Extract 32-bit value (use first 4 bytes)
    oid = int.from_bytes(hash_bytes[:4], byteorder='big')

    # PostgreSQL reserves OIDs below 16384 for system use
    # Map to range 16384 - 4294967295
    if oid < 16384:
        oid += 16384

    return oid
```

### 3.3 OID Namespaces

| Object Type | Identity Format | Example |
|------------|-----------------|---------|
| Table | `{schema}:table:{table_name}` | `SQLUser:table:users` |
| Column | `{schema}:column:{table}.{column}` | `SQLUser:column:users.id` |
| Constraint | `{schema}:constraint:{constraint_name}` | `SQLUser:constraint:users_pkey` |
| Index | `{schema}:index:{index_name}` | `SQLUser:index:users_pk_idx` |
| Namespace | `namespace:{schema}` | `namespace:SQLUser` |

### 3.4 Caching Strategy

Cache OIDs per session to ensure consistency:

```python
class OIDCache:
    def __init__(self):
        self._cache = {}

    def get_or_create(self, namespace: str, obj_type: str, name: str) -> int:
        key = (namespace, obj_type, name)
        if key not in self._cache:
            self._cache[key] = generate_oid(namespace, obj_type, name)
        return self._cache[key]
```

---

## Research Task 4: Array Parameter Handling

### Summary

PostgreSQL clients (including Prisma) send array parameters using PostgreSQL array syntax. IRIS doesn't support this natively.

### 4.1 PostgreSQL Array Syntax

```sql
-- Array literal
SELECT * FROM pg_type WHERE oid = ANY(ARRAY[23, 25, 1043])

-- Parameter binding
SELECT * FROM pg_type WHERE oid = ANY($1)
-- Where $1 = '{23,25,1043}'::int[]
```

### 4.2 IRIS Translation

**Approach 1: Expand to IN clause**
```sql
-- PostgreSQL
SELECT * FROM pg_type WHERE oid = ANY($1)

-- IRIS (translated)
SELECT * FROM pg_type WHERE oid IN (23, 25, 1043)
```

**Approach 2: Use IRIS list functions**
```sql
-- IRIS alternative
SELECT * FROM pg_type WHERE $LISTFIND($LISTFROMSTRING('23,25,1043'), oid) > 0
```

### 4.3 Detection Patterns

```python
import re

def translate_array_parameter(sql: str, params: list) -> tuple[str, list]:
    """
    Translate PostgreSQL array parameters to IRIS-compatible format.
    """
    # Pattern: ANY($N) where N is parameter index
    pattern = r'ANY\s*\(\s*\$(\d+)\s*\)'

    def replace_any(match):
        param_idx = int(match.group(1)) - 1  # PostgreSQL params are 1-indexed
        if param_idx < len(params):
            array_value = params[param_idx]
            if isinstance(array_value, (list, tuple)):
                # Expand array to IN clause
                values = ', '.join(str(v) for v in array_value)
                return f'IN ({values})'
        return match.group(0)  # Return unchanged if not an array

    translated_sql = re.sub(pattern, replace_any, sql, flags=re.IGNORECASE)
    return translated_sql, params
```

### 4.4 Array Serialization Formats

Prisma may send arrays in different formats:

| Format | Example | Detection |
|--------|---------|-----------|
| PostgreSQL literal | `'{1,2,3}'` | Starts with `{` |
| JSON array | `[1, 2, 3]` | Valid JSON array |
| Python tuple | `(1, 2, 3)` | Python tuple type |

---

## Research Task 5: Existing pg_type Implementation Analysis

### Summary

The codebase already has partial pg_type support in `iris_executor.py`. This provides a foundation for catalog emulation.

### 5.1 Current Implementation (from iris_executor.py)

```python
# Existing pg_type interception (lines 1239-1419)
if "PG_TYPE" in sql_upper or "PG_CATALOG" in sql_upper:
    # Returns static type data for standard PostgreSQL types
    base_types = {
        "nspname": "pg_catalog",
        "oid": [16, 17, 20, 21, 23, 25, 700, 701, ...],
        "typname": ["bool", "bytea", "int8", "int2", "int4", "text", ...],
        "typtype": "b",
        "typnotnull": False,
        "elemtypoid": 0,
    }
```

### 5.2 Extension Strategy

1. **Modularize**: Move pg_type handling to dedicated `catalog/pg_type.py` module
2. **Dynamic Discovery**: Add types from IRIS INFORMATION_SCHEMA.COLUMNS
3. **Consistent OIDs**: Use deterministic OID generation for all types

---

## Research Task 6: Schema Mapping Integration

### Summary

Feature 030 implemented schema mapping (public ↔ SQLUser). Catalog emulation must integrate with this.

### 6.1 Current Schema Mapper (from spec review)

The schema mapper translates:
- Input: `public.users` → `SQLUser.users`
- Output: `SQLUser.users` → `public.users`

### 6.2 Catalog Integration Requirements

1. **Namespace OID**: `pg_namespace` must return OID for 'public' (mapped to SQLUser)
2. **Table Lookup**: `pg_class` queries for `public.*` tables must query `SQLUser.*`
3. **Result Translation**: Column `nspname` should return 'public' not 'SQLUser'

### 6.3 Implementation Pattern

```python
# In catalog_router.py
from ..schema_mapper import get_configured_mapping

def handle_pg_namespace_query(sql: str, params: list):
    mapping = get_configured_mapping()
    iris_schema = mapping.get('public', 'SQLUser')

    # Query IRIS for iris_schema, return 'public' in results
    ...
```

---

## Research Conclusions

### Feasibility Assessment

| Requirement | Feasibility | Complexity | Notes |
|-------------|-------------|------------|-------|
| pg_class emulation | HIGH | Medium | INFORMATION_SCHEMA.TABLES provides base |
| pg_attribute emulation | HIGH | Medium | INFORMATION_SCHEMA.COLUMNS provides base |
| pg_constraint emulation | HIGH | Medium-High | Multiple IRIS tables needed |
| pg_index emulation | MEDIUM | High | No direct INFORMATION_SCHEMA support |
| OID generation | HIGH | Low | Deterministic hashing is straightforward |
| Array parameters | HIGH | Medium | Pattern translation viable |
| JOIN queries | HIGH | Medium | Route to appropriate handlers |

### Implementation Priority

1. **P0 (Critical)**: OID generator, pg_namespace, pg_class, pg_attribute
2. **P1 (Required)**: pg_constraint, pg_type (extend existing), pg_attrdef
3. **P2 (Important)**: pg_index, pg_depend
4. **P3 (Nice-to-have)**: Additional catalog tables as needed

### Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Incomplete catalog coverage | High | Start with tables Prisma actually queries |
| OID collision | Medium | Use cryptographic hash, large namespace |
| Performance overhead | Low | Cache metadata queries, <5ms target |
| Complex JOIN queries | Medium | Parse query to identify required tables |

---

## References

1. PostgreSQL System Catalogs Documentation: https://www.postgresql.org/docs/current/catalogs.html
2. pg_attribute Documentation: https://www.postgresql.org/docs/current/catalog-pg-attribute.html
3. pg_constraint Documentation: https://www.postgresql.org/docs/8.0/catalog-pg-constraint.html
4. Prisma Introspection: https://www.prisma.io/docs/orm/prisma-schema/introspection
5. IRIS INFORMATION_SCHEMA: InterSystems documentation
6. Feature 030 Schema Mapping: `/specs/030-pg-schema-mapping/`
