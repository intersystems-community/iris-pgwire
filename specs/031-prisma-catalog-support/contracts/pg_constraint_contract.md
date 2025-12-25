# Contract: pg_constraint Catalog Emulation

**Feature**: 031-prisma-catalog-support
**Component**: `catalog/pg_constraint.py`
**Created**: 2025-12-23

---

## Purpose

Emulate PostgreSQL `pg_catalog.pg_constraint` system table to enable Prisma constraint and relationship discovery.

---

## Input Contracts

### IC-1: Query constraints for a table

**Query Pattern**:
```sql
SELECT c.oid, c.conname, c.contype, c.conrelid, c.confrelid, c.conkey, c.confkey
FROM pg_catalog.pg_constraint c
WHERE c.conrelid = $1
```

**Expected Behavior**:
- $1 = table OID
- Return all constraints on the table
- Include PK, FK, UNIQUE constraints

### IC-2: Query foreign key constraints

**Query Pattern**:
```sql
SELECT c.conname, c.conkey, c.confkey, c.confrelid
FROM pg_catalog.pg_constraint c
WHERE c.conrelid = $1 AND c.contype = 'f'
```

**Expected Behavior**:
- Return only foreign key constraints
- Include referenced table OID (confrelid)
- Include column position arrays (conkey, confkey)

### IC-3: Query constraints referencing a table

**Query Pattern**:
```sql
SELECT * FROM pg_catalog.pg_constraint
WHERE confrelid = $1
```

**Expected Behavior**:
- Return FK constraints that reference the specified table
- Used by Prisma to discover incoming relationships

---

## Output Contracts

### OC-1: Column structure

**Required Columns** (Prisma introspection minimum):

| Column | Type | Description |
|--------|------|-------------|
| oid | int4 (OID 26) | Constraint OID |
| conname | name (OID 19) | Constraint name |
| connamespace | int4 (OID 26) | Namespace OID |
| contype | char (OID 18) | 'p'=PK, 'f'=FK, 'u'=UNIQUE, 'c'=CHECK |
| conrelid | int4 (OID 26) | Table OID |
| confrelid | int4 (OID 26) | Referenced table OID (FK only, else 0) |
| conkey | int2[] (OID 1005) | Constrained column positions |
| confkey | int2[] (OID 1005) | Referenced column positions (FK only) |
| condeferrable | bool (OID 16) | Is deferrable |
| convalidated | bool (OID 16) | Is validated |

### OC-2: Constraint type mapping

| IRIS Constraint Type | PostgreSQL contype |
|---------------------|-------------------|
| PRIMARY KEY | 'p' |
| FOREIGN KEY | 'f' |
| UNIQUE | 'u' |
| CHECK | 'c' |

### OC-3: Array column format

**conkey/confkey arrays**:
- PostgreSQL int2[] format: `{1,2}` for columns 1 and 2
- Column positions match pg_attribute.attnum
- Example: FK on columns (2, 3) → conkey = `{2, 3}`

### OC-4: Foreign key action codes

| Column | Values | Description |
|--------|--------|-------------|
| confupdtype | 'a'=no action, 'r'=restrict, 'c'=cascade, 'n'=set null, 'd'=set default | Update action |
| confdeltype | Same as above | Delete action |
| confmatchtype | 'f'=full, 'p'=partial, 's'=simple | Match type |

---

## Test Contracts

### TC-1: Primary key discovery

```python
def test_pg_constraint_primary_key():
    """
    Given: Table 'users' with primary key on 'id'
    When: Query pg_constraint for table
    Then: Return PK constraint with correct column position
    """
    create_iris_table_ddl("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name VARCHAR(100)
        )
    """)

    result = execute_pg_query("""
        SELECT conname, contype, conkey
        FROM pg_catalog.pg_constraint
        WHERE conrelid = (SELECT oid FROM pg_class WHERE relname = 'users')
          AND contype = 'p'
    """)

    assert len(result.rows) == 1
    assert result.rows[0][1] == 'p'  # contype
    assert result.rows[0][2] == [1]  # conkey (first column)
```

### TC-2: Foreign key discovery

```python
def test_pg_constraint_foreign_key():
    """
    Given: Tables 'orders' and 'users' with FK relationship
    When: Query pg_constraint for FK
    Then: Return FK with correct referenced table and columns
    """
    create_iris_tables_ddl("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name VARCHAR(100)
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)

    result = execute_pg_query("""
        SELECT contype, conrelid, confrelid, conkey, confkey
        FROM pg_catalog.pg_constraint
        WHERE conrelid = (SELECT oid FROM pg_class WHERE relname = 'orders')
          AND contype = 'f'
    """)

    assert len(result.rows) == 1
    fk = result.rows[0]
    assert fk[0] == 'f'  # contype
    assert fk[3] == [2]  # conkey (user_id is 2nd column)
    assert fk[4] == [1]  # confkey (id is 1st column in users)

    # Verify confrelid points to users table
    users_oid = execute_pg_query("SELECT oid FROM pg_class WHERE relname = 'users'").rows[0][0]
    assert fk[2] == users_oid
```

### TC-3: Unique constraint

```python
def test_pg_constraint_unique():
    """
    Given: Table with UNIQUE constraint
    When: Query pg_constraint
    Then: Return UNIQUE constraint
    """
    create_iris_table_ddl("""
        CREATE TABLE emails (
            id INTEGER PRIMARY KEY,
            email VARCHAR(255) UNIQUE
        )
    """)

    result = execute_pg_query("""
        SELECT conname, contype, conkey
        FROM pg_catalog.pg_constraint
        WHERE conrelid = (SELECT oid FROM pg_class WHERE relname = 'emails')
          AND contype = 'u'
    """)

    assert len(result.rows) == 1
    assert result.rows[0][1] == 'u'  # contype
```

### TC-4: Composite key

```python
def test_pg_constraint_composite_key():
    """
    Given: Table with composite primary key
    When: Query pg_constraint
    Then: conkey contains multiple column positions
    """
    create_iris_table_ddl("""
        CREATE TABLE order_items (
            order_id INTEGER,
            product_id INTEGER,
            quantity INTEGER,
            PRIMARY KEY (order_id, product_id)
        )
    """)

    result = execute_pg_query("""
        SELECT conkey
        FROM pg_catalog.pg_constraint
        WHERE conrelid = (SELECT oid FROM pg_class WHERE relname = 'order_items')
          AND contype = 'p'
    """)

    assert result.rows[0][0] == [1, 2]  # Both columns
```

### TC-5: Incoming foreign keys

```python
def test_pg_constraint_incoming_fk():
    """
    Given: Table referenced by FK from another table
    When: Query constraints by confrelid
    Then: Return incoming FK relationships
    """
    # Setup: orders.user_id -> users.id
    users_oid = get_table_oid('users')

    result = execute_pg_query(f"""
        SELECT conname, conrelid
        FROM pg_catalog.pg_constraint
        WHERE confrelid = {users_oid}
    """)

    # Should find the FK from orders table
    assert len(result.rows) >= 1
```

---

## IRIS Source Mapping

### Primary/Unique Key Source

```sql
SELECT tc.CONSTRAINT_NAME, tc.CONSTRAINT_TYPE, kcu.COLUMN_NAME, kcu.ORDINAL_POSITION
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
  ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
  AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
  AND tc.TABLE_NAME = kcu.TABLE_NAME
WHERE tc.TABLE_SCHEMA = 'SQLUser'
  AND tc.TABLE_NAME = ?
  AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'UNIQUE')
ORDER BY kcu.ORDINAL_POSITION
```

### Foreign Key Source

```sql
SELECT
    tc.CONSTRAINT_NAME,
    kcu.COLUMN_NAME,
    rc.UNIQUE_CONSTRAINT_SCHEMA,
    rc.UNIQUE_CONSTRAINT_NAME,
    kcu.REFERENCED_TABLE_NAME,
    kcu.REFERENCED_COLUMN_NAME
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
  ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
  ON tc.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
WHERE tc.TABLE_SCHEMA = 'SQLUser'
  AND tc.TABLE_NAME = ?
  AND tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
```

---

## Performance Contract

- Query response time: <5ms per table
- Support for tables with up to 20 constraints
- Batch support for multiple table OIDs
