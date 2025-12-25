# Contract: pg_class Catalog Emulation

**Feature**: 031-prisma-catalog-support
**Component**: `catalog/pg_class.py`
**Created**: 2025-12-23

---

## Purpose

Emulate PostgreSQL `pg_catalog.pg_class` system table to enable Prisma introspection of IRIS tables.

---

## Input Contracts

### IC-1: Query for all tables in public schema

**Query Pattern**:
```sql
SELECT c.oid, c.relname, c.relkind, c.relnamespace, c.relowner
FROM pg_catalog.pg_class c
LEFT JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'v')
  AND n.nspname = 'public'
```

**Expected Behavior**:
- Query IRIS `INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'SQLUser'`
- Translate SQLUser → public in output
- Return all BASE TABLEs (relkind='r') and VIEWs (relkind='v')

### IC-2: Query for specific table by name

**Query Pattern**:
```sql
SELECT * FROM pg_catalog.pg_class
WHERE relname = $1 AND relnamespace = $2
```

**Expected Behavior**:
- $1 = table name (lowercase)
- $2 = namespace OID (2200 for public)
- Return single row or empty result

### IC-3: Query for table by OID

**Query Pattern**:
```sql
SELECT * FROM pg_catalog.pg_class WHERE oid = $1
```

**Expected Behavior**:
- Resolve OID via OIDGenerator reverse lookup
- Return table metadata if found

### IC-4: regclass cast

**Query Pattern**:
```sql
SELECT oid FROM pg_class WHERE oid = 'public.users'::regclass
```

**Expected Behavior**:
- Parse 'schema.table' from regclass literal
- Generate OID for the table
- Return matching row

---

## Output Contracts

### OC-1: Column structure

**Required Columns** (Prisma introspection minimum):

| Column | Type | Description |
|--------|------|-------------|
| oid | int4 (OID 26) | Table OID (generated) |
| relname | name (OID 19) | Table name (lowercase) |
| relnamespace | int4 (OID 26) | Namespace OID |
| relkind | char (OID 18) | 'r'=table, 'v'=view, 'i'=index |
| relowner | int4 (OID 26) | Owner OID (10 = postgres) |
| relhasindex | bool (OID 16) | Has indexes |
| relnatts | int2 (OID 21) | Number of columns |

### OC-2: OID stability

**Invariant**: Same table must return same OID across:
- Multiple queries in same session
- Different sessions
- Server restarts

**Implementation**: Deterministic hash of `{schema}:table:{table_name}`

### OC-3: Schema mapping

**Input→Output Translation**:
- Input `nspname = 'public'` → Query `TABLE_SCHEMA = 'SQLUser'`
- Output `relnamespace` → OID 2200 (public namespace)

---

## Test Contracts

### TC-1: Basic table enumeration

```python
def test_pg_class_enumerate_tables():
    """
    Given: IRIS database with tables: users, orders, products
    When: Query pg_class for all tables in public schema
    Then: Return 3 rows with correct relname values
    """
    # Setup
    create_iris_tables(['users', 'orders', 'products'])

    # Execute
    result = execute_pg_query("""
        SELECT relname FROM pg_catalog.pg_class
        WHERE relkind = 'r' AND relnamespace = 2200
    """)

    # Assert
    assert len(result.rows) == 3
    names = {row[0] for row in result.rows}
    assert names == {'users', 'orders', 'products'}
```

### TC-2: OID consistency

```python
def test_pg_class_oid_stability():
    """
    Given: Table 'users' in IRIS
    When: Query pg_class OID twice
    Then: Same OID returned both times
    """
    result1 = execute_pg_query("SELECT oid FROM pg_class WHERE relname = 'users'")
    result2 = execute_pg_query("SELECT oid FROM pg_class WHERE relname = 'users'")

    assert result1.rows[0][0] == result2.rows[0][0]
```

### TC-3: regclass resolution

```python
def test_regclass_cast():
    """
    Given: Table 'public.users' exists
    When: Use ::regclass cast
    Then: Return valid OID
    """
    result = execute_pg_query("SELECT 'public.users'::regclass::oid")

    assert result.rows[0][0] >= 16384  # User OID range
```

### TC-4: Empty schema

```python
def test_pg_class_empty_schema():
    """
    Given: No tables in SQLUser schema
    When: Query pg_class
    Then: Return empty result set (not error)
    """
    result = execute_pg_query("""
        SELECT * FROM pg_catalog.pg_class
        WHERE relkind = 'r' AND relnamespace = 2200
    """)

    assert result.success is True
    assert len(result.rows) == 0
```

---

## Performance Contract

- Query response time: <5ms for schema with ≤50 tables
- Memory: O(n) where n = number of tables
- Caching: OID cache per session
