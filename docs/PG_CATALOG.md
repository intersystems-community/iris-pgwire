# PostgreSQL Catalog Support in IRIS PGWire

**Last Updated**: 2025-12-27
**Related**: [Client Recommendations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/CLIENT_RECOMMENDATIONS.md), [Known Limitations](https://github.com/intersystems-community/iris-pgwire/blob/main/KNOWN_LIMITATIONS.md)

---

## Overview

IRIS PGWire implements **partial PostgreSQL catalog support** to enable ORM introspection tools (Prisma, Drizzle, SQLAlchemy, Sequelize, Hibernate, etc.) to discover IRIS database schema through the PostgreSQL wire protocol.

**Purpose**: ORMs need to query `pg_catalog` system tables to:
- Discover tables, columns, and relationships
- Generate migration files
- Reflect database schema into ORM models
- Validate schema matches application expectations

**Implementation**: IRIS PGWire emulates key `pg_catalog` tables and functions by translating PostgreSQL catalog queries into IRIS `INFORMATION_SCHEMA` queries, then formatting results to match PostgreSQL's expected structure.

---

## Supported Catalog Tables

IRIS PGWire provides emulation for **6 core catalog tables** used by ORM introspection:

### 1. `pg_class`
**Purpose**: Table and view catalog

**Use Case**: ORMs query `pg_class` to list all tables and views in a database.

**Columns Provided**:
- `oid` (integer) - Unique object ID for the table
- `relname` (varchar) - Table/view name
- `relnamespace` (integer) - Schema OID (from `pg_namespace`)
- `relkind` (char) - Object type: `'r'` (table), `'v'` (view), `'i'` (index)
- `relam` (integer) - Access method (0 for heap tables)
- `reltablespace` (integer) - Tablespace (always 0 in IRIS)

**Example Query**:
```sql
-- Prisma: List all tables in the public schema
SELECT c.oid, c.relname
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r';
```

### 2. `pg_attribute`
**Purpose**: Column catalog

**Use Case**: ORMs query `pg_attribute` to discover columns, data types, and nullability.

**Columns Provided**:
- `attrelid` (integer) - Table OID (foreign key to `pg_class.oid`)
- `attname` (varchar) - Column name
- `atttypid` (integer) - Type OID (foreign key to `pg_type.oid`)
- `attnum` (integer) - Column number (1-indexed)
- `attnotnull` (boolean) - NOT NULL constraint
- `atthasdef` (boolean) - Has DEFAULT value
- `atttypmod` (integer) - Type modifier (e.g., varchar length)

**Example Query**:
```sql
-- SQLAlchemy: Get columns for a specific table
SELECT a.attname, a.atttypid, a.attnotnull, a.attnum
FROM pg_catalog.pg_attribute a
WHERE a.attrelid = 'my_table'::regclass
  AND a.attnum > 0  -- Exclude system columns
ORDER BY a.attnum;
```

### 3. `pg_constraint`
**Purpose**: Constraint catalog (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK)

**Use Case**: ORMs query `pg_constraint` to discover primary keys, foreign keys, and unique constraints for relationship mapping.

**Columns Provided**:
- `oid` (integer) - Constraint OID
- `conname` (varchar) - Constraint name
- `connamespace` (integer) - Schema OID
- `contype` (char) - Constraint type: `'p'` (PK), `'f'` (FK), `'u'` (unique), `'c'` (check)
- `conrelid` (integer) - Table OID
- `confrelid` (integer) - Referenced table OID (for foreign keys)
- `conkey` (integer[]) - Array of constrained column numbers
- `confkey` (integer[]) - Array of referenced column numbers (for foreign keys)

**Example Query**:
```sql
-- Prisma: Find primary key for a table
SELECT conname, conkey
FROM pg_catalog.pg_constraint
WHERE conrelid = 'users'::regclass AND contype = 'p';
```

### 4. `pg_index`
**Purpose**: Index catalog

**Use Case**: ORMs query `pg_index` to discover indexes for query optimization hints.

**Columns Provided**:
- `indexrelid` (integer) - Index OID (from `pg_class`)
- `indrelid` (integer) - Table OID
- `indkey` (integer[]) - Array of indexed column numbers
- `indisunique` (boolean) - Is unique index
- `indisprimary` (boolean) - Is primary key index
- `indisvalid` (boolean) - Is valid/usable (always true)

**Example Query**:
```sql
-- Drizzle: List all indexes on a table
SELECT i.indexrelid, i.indkey, i.indisunique, c.relname AS index_name
FROM pg_catalog.pg_index i
JOIN pg_catalog.pg_class c ON c.oid = i.indexrelid
WHERE i.indrelid = 'products'::regclass;
```

### 5. `pg_namespace`
**Purpose**: Schema catalog

**Use Case**: ORMs query `pg_namespace` to discover available schemas and filter results by schema.

**Columns Provided**:
- `oid` (integer) - Schema OID
- `nspname` (varchar) - Schema name

**IRIS Mapping**: IRIS schemas (e.g., `SQLUser`) are mapped to PostgreSQL's `public` schema for ORM compatibility.

**Example Query**:
```sql
-- SQLAlchemy: List all schemas
SELECT oid, nspname FROM pg_catalog.pg_namespace;
```

### 6. `pg_attrdef`
**Purpose**: Column default value catalog

**Use Case**: ORMs query `pg_attrdef` to discover DEFAULT expressions for columns.

**Columns Provided**:
- `oid` (integer) - Default OID
- `adrelid` (integer) - Table OID
- `adnum` (integer) - Column number
- `adbin` (text) - Binary representation (nodeToString format)
- `adsrc` (text) - Human-readable default expression

**Example Query**:
```sql
-- Sequelize: Get default values for table columns
SELECT a.attname, d.adsrc
FROM pg_catalog.pg_attrdef d
JOIN pg_catalog.pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
WHERE d.adrelid = 'orders'::regclass;
```

---

## Supported Catalog Functions

IRIS PGWire implements **5 catalog functions** that ORMs and introspection tools call to format metadata:

### 1. `format_type(type_oid, typmod)`
**Purpose**: Convert type OID and modifier to human-readable type name

**Signature**: `format_type(integer, integer) → text`

**Example**:
```sql
-- Prisma: Get formatted column types
SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS data_type
FROM pg_catalog.pg_attribute a
WHERE a.attrelid = 'users'::regclass AND a.attnum > 0;

-- Results:
-- id         | integer
-- email      | character varying(255)
-- balance    | numeric(10,2)
-- created_at | timestamp without time zone
```

### 2. `pg_get_constraintdef(constraint_oid, pretty?)`
**Purpose**: Get SQL definition of a constraint

**Signature**: `pg_get_constraintdef(integer [, boolean]) → text`

**Example**:
```sql
-- SQLAlchemy: Get primary key definition
SELECT pg_get_constraintdef(oid) AS definition
FROM pg_catalog.pg_constraint
WHERE conname = 'users_pkey';

-- Result: "PRIMARY KEY (id)"
```

### 3. `pg_get_serial_sequence(table_name, column_name)`
**Purpose**: Get sequence name for SERIAL column (auto-increment)

**Signature**: `pg_get_serial_sequence(text, text) → text`

**IRIS Note**: IRIS uses identity columns, not sequences. This function returns `NULL` (no sequences exist).

**Example**:
```sql
-- Drizzle: Check if column is auto-increment
SELECT pg_get_serial_sequence('users', 'id') AS sequence_name;

-- Result: NULL (IRIS doesn't use PostgreSQL sequences)
```

### 4. `pg_get_viewdef(view_oid, pretty?)`
**Purpose**: Get SQL definition of a view

**Signature**: `pg_get_viewdef(integer [, boolean]) → text`

**IRIS Note**: Returns `NULL` for security reasons (view definitions may contain sensitive logic).

**Example**:
```sql
-- Prisma: Attempt to get view definition
SELECT pg_get_viewdef('user_summary_view'::regclass);

-- Result: NULL (view definitions not exposed)
```

### 5. `pg_get_indexdef(index_oid, column?, pretty?)`
**Purpose**: Get CREATE INDEX statement for an index

**Signature**: `pg_get_indexdef(integer [, integer, boolean]) → text`

**Example**:
```sql
-- Hibernate: Get index DDL
SELECT pg_get_indexdef(indexrelid) AS index_ddl
FROM pg_catalog.pg_index
WHERE indrelid = 'products'::regclass;

-- Result: "CREATE INDEX idx_products_category ON products USING btree (category_id)"
```

---

## Limitations

### What's NOT Supported

**Missing Catalog Tables**:
- `pg_type` - Type system catalog (partial support only for common types)
- `pg_proc` - Function/procedure catalog
- `pg_description` - Object comments/descriptions
- `pg_depend` - Object dependency tracking
- `pg_enum` - Enum type values
- `pg_trigger` - Trigger definitions
- Many others (50+ PostgreSQL catalog tables)

**Missing Functions**:
- `pg_get_expr()` - Expression decompiler
- `pg_table_is_visible()` - Schema visibility checks
- `pg_get_userbyid()` - User name resolution
- `pg_encoding_to_char()` - Encoding name lookup
- Many others (100+ PostgreSQL catalog functions)

**Query Pattern Limitations**:
- **Complex Joins**: Queries joining 4+ catalog tables may fail
- **Subqueries**: Nested catalog queries may not resolve correctly
- **CTEs**: Recursive CTEs on catalog tables unsupported
- **Window Functions**: Over catalog tables may return incorrect results

**Type System Gaps**:
- **Custom Types**: PostgreSQL domains, composite types, enums not supported
- **Array Types**: Array type introspection incomplete
- **Range Types**: PostgreSQL range types (int4range, tstzrange) not mapped

### ORM-Specific Considerations

#### Prisma
- ✅ **Schema introspection works**: `prisma db pull` succeeds
- ✅ **Migrations work**: `prisma migrate dev` creates tables
- ⚠️ **Enum types**: Falls back to VARCHAR (no native enum support in IRIS)

#### SQLAlchemy
- ✅ **Reflection works**: `Table(..., autoload_with=engine)` succeeds
- ✅ **Inspector works**: `inspect(engine).get_columns('table')` succeeds
- ⚠️ **Custom types**: May not reflect correctly (use explicit type mapping)

#### Drizzle ORM
- ✅ **Introspection works**: `drizzle-kit introspect` generates schema
- ✅ **Push works**: `drizzle-kit push` syncs schema to IRIS
- ⚠️ **Serial columns**: Detected as integers (IRIS uses identity, not sequences)

#### Sequelize
- ✅ **Sync works**: `sequelize.sync()` creates tables
- ✅ **Migrations work**: Sequelize CLI generates migrations
- ⚠️ **Foreign keys**: May require explicit `references` configuration

#### Hibernate (Java)
- ✅ **Schema validation works**: `hbm2ddl.auto=validate` succeeds
- ✅ **Auto-DDL works**: `hbm2ddl.auto=update` creates missing tables
- ⚠️ **Sequences**: Use `IDENTITY` strategy, not `SEQUENCE`

---

## Usage Examples

### Example 1: Prisma Introspection Flow

When you run `prisma db pull`, Prisma executes these catalog queries:

```sql
-- Step 1: List all tables
SELECT c.oid, c.relname AS table_name
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r';

-- Step 2: Get columns for each table
SELECT a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       a.attnotnull AS is_required,
       d.adsrc AS default_value
FROM pg_catalog.pg_attribute a
LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attrelid = 'users'::regclass AND a.attnum > 0
ORDER BY a.attnum;

-- Step 3: Get primary keys
SELECT conname, conkey
FROM pg_catalog.pg_constraint
WHERE conrelid = 'users'::regclass AND contype = 'p';

-- Step 4: Get foreign keys
SELECT conname, conkey, confrelid, confkey, pg_get_constraintdef(oid)
FROM pg_catalog.pg_constraint
WHERE conrelid = 'users'::regclass AND contype = 'f';

-- Step 5: Get unique constraints
SELECT conname, conkey
FROM pg_catalog.pg_constraint
WHERE conrelid = 'users'::regclass AND contype = 'u';

-- Step 6: Get indexes
SELECT i.indexrelid, i.indkey, i.indisunique, c.relname AS index_name
FROM pg_catalog.pg_index i
JOIN pg_catalog.pg_class c ON c.oid = i.indexrelid
WHERE i.indrelid = 'users'::regclass AND NOT i.indisprimary;
```

**Result**: Prisma generates `schema.prisma` with all tables, columns, relationships, and indexes.

### Example 2: SQLAlchemy Reflection

When you use SQLAlchemy's autoload feature:

```python
from sqlalchemy import create_engine, Table, MetaData

# Connect via PGWire
engine = create_engine("postgresql://localhost:5432/USER")
metadata = MetaData()

# Reflect table from IRIS
users_table = Table("users", metadata, autoload_with=engine)

# SQLAlchemy runs these catalog queries:
# 1. pg_class: Check table exists
# 2. pg_attribute: Get columns and types
# 3. pg_constraint: Get primary key and foreign keys
# 4. pg_index: Get indexes

# Now you can query using the reflected table
from sqlalchemy import select
with engine.connect() as conn:
    result = conn.execute(select(users_table))
    for row in result:
        print(row)
```

### Example 3: Drizzle Schema Introspection

When you run `drizzle-kit introspect`:

```bash
# Drizzle runs similar catalog queries to Prisma
npx drizzle-kit introspect --out ./drizzle --config drizzle.config.ts
```

Drizzle queries:
```sql
-- Tables
SELECT c.relname FROM pg_class c WHERE c.relkind = 'r';

-- Columns
SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
FROM pg_attribute a WHERE a.attrelid = 'products'::regclass;

-- Constraints
SELECT conname, contype, pg_get_constraintdef(oid)
FROM pg_constraint WHERE conrelid = 'products'::regclass;
```

**Result**: Drizzle generates TypeScript schema definition files.

---

## Troubleshooting

### Issue: Prisma says "database is empty" after introspection

**Cause**: Your tables are in a schema other than `SQLUser`, and PGWire's schema mapping is misconfigured.

**Solution**:
```bash
# Set IRIS schema to map to PostgreSQL 'public' schema
export PGWIRE_IRIS_SCHEMA=YourSchemaName

# Or configure in Python
from iris_pgwire.schema_mapper import configure_schema
configure_schema(iris_schema="YourSchemaName")
```

### Issue: SQLAlchemy reflection fails with "relation does not exist"

**Cause**: Table name case sensitivity mismatch. IRIS uses case-sensitive identifiers, PostgreSQL defaults to lowercase.

**Solution**:
```python
# Use exact IRIS table name (case-sensitive)
Table("MyTable", metadata, autoload_with=engine)

# Or explicitly quote the name
from sqlalchemy import quoted_name
Table(quoted_name("MyTable", quote=True), metadata, autoload_with=engine)
```

### Issue: Drizzle introspection hangs

**Cause**: Query timeout on catalog queries with large schemas (100+ tables).

**Solution**:
```typescript
// drizzle.config.ts
export default {
  dialect: "postgresql",
  dbCredentials: {
    url: "postgresql://localhost:5432/USER",
  },
  // Increase timeout for introspection
  connectionTimeoutMillis: 30000,
}
```

### Issue: Foreign keys not detected by ORM

**Cause**: IRIS foreign key constraints may not be visible to `pg_constraint` if defined outside `SQLUser` schema.

**Solution**: Verify foreign keys exist in IRIS:
```sql
-- Query IRIS INFORMATION_SCHEMA directly
SELECT * FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = 'SQLUser';
```

---

## Implementation Details

### How PGWire Emulates pg_catalog

**Query Detection**: PGWire's `CatalogRouter` detects queries targeting `pg_catalog.*` or `pg_*` tables and routes them to emulators.

**OID Generation**: Deterministic OID generation ensures stable object IDs across sessions:
```python
# Example: Generate table OID from schema + table name
from iris_pgwire.catalog import OIDGenerator
oid_gen = OIDGenerator()
table_oid = oid_gen.get_table_oid("SQLUser", "users")
# → Consistent OID like 16432
```

**INFORMATION_SCHEMA Translation**: Emulators translate catalog queries into IRIS INFORMATION_SCHEMA queries:
```sql
-- Prisma query:
SELECT relname FROM pg_class WHERE relkind = 'r';

-- Translated to IRIS:
SELECT TABLE_NAME AS relname
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = 'SQLUser';
```

**Result Formatting**: IRIS results are reformatted to match PostgreSQL's expected column names and data types.

---

## See Also

- [Client Recommendations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/CLIENT_RECOMMENDATIONS.md) - ORM compatibility matrix
- [Known Limitations](https://github.com/intersystems-community/iris-pgwire/blob/main/KNOWN_LIMITATIONS.md) - Full list of unsupported features
- [Schema Mapping Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md#schema-mapping) - Configure `public` ↔ IRIS schema mapping
- [Prisma Example](https://github.com/intersystems-community/iris-pgwire/tree/main/examples/prisma-iris-demo) - Complete Prisma + IRIS demo
- [Drizzle Example](https://github.com/intersystems-community/iris-pgwire/tree/main/examples/drizzle-iris-demo) - Drizzle ORM integration
