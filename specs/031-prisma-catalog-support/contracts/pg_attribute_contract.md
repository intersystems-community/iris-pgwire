# Contract: pg_attribute Catalog Emulation

**Feature**: 031-prisma-catalog-support
**Component**: `catalog/pg_attribute.py`
**Created**: 2025-12-23

---

## Purpose

Emulate PostgreSQL `pg_catalog.pg_attribute` system table to enable Prisma column discovery.

---

## Input Contracts

### IC-1: Query columns for a table by OID

**Query Pattern**:
```sql
SELECT a.attnum, a.attname, a.atttypid, a.attnotnull, a.atthasdef
FROM pg_catalog.pg_attribute a
WHERE a.attrelid = $1
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum
```

**Expected Behavior**:
- $1 = table OID (from pg_class)
- Return all user columns (attnum > 0)
- Exclude system columns (attnum < 0)
- Exclude dropped columns

### IC-2: Query specific column

**Query Pattern**:
```sql
SELECT * FROM pg_catalog.pg_attribute
WHERE attrelid = $1 AND attname = $2
```

**Expected Behavior**:
- Return single column metadata or empty result

### IC-3: Query with array of table OIDs

**Query Pattern**:
```sql
SELECT * FROM pg_catalog.pg_attribute
WHERE attrelid = ANY($1) AND attnum > 0
```

**Expected Behavior**:
- $1 = array of OIDs (e.g., `{12345, 12346}`)
- Return columns for all specified tables

---

## Output Contracts

### OC-1: Column structure

**Required Columns** (Prisma introspection minimum):

| Column | Type | Description |
|--------|------|-------------|
| attrelid | int4 (OID 26) | Table OID |
| attname | name (OID 19) | Column name (lowercase) |
| atttypid | int4 (OID 26) | Type OID |
| attnum | int2 (OID 21) | Column number (1-indexed) |
| attnotnull | bool (OID 16) | NOT NULL constraint |
| atthasdef | bool (OID 16) | Has default value |
| attlen | int2 (OID 21) | Type length |
| atttypmod | int4 (OID 23) | Type modifier |
| attisdropped | bool (OID 16) | Always false |

### OC-2: Type OID mapping

| IRIS Data Type | PostgreSQL Type | atttypid |
|---------------|-----------------|----------|
| INTEGER | int4 | 23 |
| BIGINT | int8 | 20 |
| SMALLINT | int2 | 21 |
| VARCHAR(n) | varchar | 1043 |
| CHAR(n) | bpchar | 1042 |
| TEXT, LONGVARCHAR | text | 25 |
| DECIMAL, NUMERIC | numeric | 1700 |
| DOUBLE | float8 | 701 |
| DATE | date | 1082 |
| TIME | time | 1083 |
| TIMESTAMP | timestamp | 1114 |
| BIT | bool | 16 |
| VARBINARY | bytea | 17 |

### OC-3: Type modifier calculation

**VARCHAR(n)**:
- `atttypmod = n + 4` (PostgreSQL convention)
- Example: VARCHAR(255) → atttypmod = 259

**NUMERIC(p, s)**:
- `atttypmod = ((p + 4) << 16) | (s + 4)`
- Example: NUMERIC(10, 2) → atttypmod calculated

### OC-4: Column ordering

- Columns ordered by `attnum` (ORDINAL_POSITION from IRIS)
- attnum starts at 1 for first user column

---

## Test Contracts

### TC-1: Basic column enumeration

```python
def test_pg_attribute_enumerate_columns():
    """
    Given: Table 'users' with columns: id (INT), name (VARCHAR), email (VARCHAR)
    When: Query pg_attribute for table
    Then: Return 3 rows with correct column metadata
    """
    # Setup
    create_iris_table('users', [
        ('id', 'INTEGER'),
        ('name', 'VARCHAR(100)'),
        ('email', 'VARCHAR(255)')
    ])

    users_oid = get_table_oid('users')

    # Execute
    result = execute_pg_query(f"""
        SELECT attname, atttypid, attnum
        FROM pg_catalog.pg_attribute
        WHERE attrelid = {users_oid} AND attnum > 0
        ORDER BY attnum
    """)

    # Assert
    assert len(result.rows) == 3
    assert result.rows[0] == ('id', 23, 1)      # int4
    assert result.rows[1] == ('name', 1043, 2)  # varchar
    assert result.rows[2] == ('email', 1043, 3) # varchar
```

### TC-2: NOT NULL detection

```python
def test_pg_attribute_notnull():
    """
    Given: Table with NOT NULL columns
    When: Query pg_attribute
    Then: attnotnull reflects constraint
    """
    create_iris_table_ddl("""
        CREATE TABLE test_notnull (
            id INTEGER NOT NULL,
            name VARCHAR(100),
            required VARCHAR(50) NOT NULL
        )
    """)

    result = execute_pg_query("""
        SELECT attname, attnotnull
        FROM pg_catalog.pg_attribute
        WHERE attrelid = (SELECT oid FROM pg_class WHERE relname = 'test_notnull')
          AND attnum > 0
        ORDER BY attnum
    """)

    assert result.rows[0] == ('id', True)
    assert result.rows[1] == ('name', False)
    assert result.rows[2] == ('required', True)
```

### TC-3: Type modifier for VARCHAR

```python
def test_pg_attribute_varchar_typmod():
    """
    Given: Table with VARCHAR(255) column
    When: Query pg_attribute
    Then: atttypmod = 259 (255 + 4)
    """
    create_iris_table('test_typmod', [('name', 'VARCHAR(255)')])

    result = execute_pg_query("""
        SELECT atttypmod FROM pg_catalog.pg_attribute
        WHERE attrelid = (SELECT oid FROM pg_class WHERE relname = 'test_typmod')
          AND attname = 'name'
    """)

    assert result.rows[0][0] == 259
```

### TC-4: Array parameter handling

```python
def test_pg_attribute_array_param():
    """
    Given: Multiple tables
    When: Query with array of OIDs
    Then: Return columns from all tables
    """
    create_iris_tables(['table1', 'table2'])

    result = execute_pg_query("""
        SELECT attrelid, attname
        FROM pg_catalog.pg_attribute
        WHERE attrelid = ANY(ARRAY[
            (SELECT oid FROM pg_class WHERE relname = 'table1'),
            (SELECT oid FROM pg_class WHERE relname = 'table2')
        ])
        AND attnum > 0
    """)

    # Should return columns from both tables
    relids = {row[0] for row in result.rows}
    assert len(relids) == 2
```

---

## Performance Contract

- Query response time: <5ms per table (up to 100 columns)
- Memory: O(n) where n = total columns
- Batch support: Single query for multiple table OIDs
