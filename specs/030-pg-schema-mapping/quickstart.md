# Quickstart: PostgreSQL Schema Mapping

**Feature**: 030-pg-schema-mapping
**Purpose**: Validate schema mapping works for ORM introspection

## Prerequisites

- IRIS PGWire running on port 5432
- Node.js 18+ (for Prisma)
- Python 3.11+ (for SQLAlchemy)

## Validation Steps

### 1. Basic Schema Query Test (psycopg3)

```python
import psycopg

conn = psycopg.connect("host=localhost port=5432 user=_SYSTEM password=SYS dbname=USER")
cur = conn.cursor()

# This should return SQLUser tables (mapped from 'public')
cur.execute("""
    SELECT table_name, table_schema
    FROM information_schema.tables
    WHERE table_schema = 'public'
    LIMIT 5
""")

rows = cur.fetchall()
assert len(rows) > 0, "Should find tables in 'public' schema"
for row in rows:
    assert row[1] == 'public', f"table_schema should be 'public', got {row[1]}"
    print(f"Found table: {row[0]}")

conn.close()
print("✓ Basic schema mapping works")
```

### 2. Prisma Introspection Test

```bash
# Create test directory
mkdir -p /tmp/prisma-test && cd /tmp/prisma-test

# Initialize Prisma
npm init -y
npm install prisma --save-dev
npx prisma init

# Configure datasource (edit prisma/schema.prisma)
cat > prisma/schema.prisma << 'EOF'
datasource db {
  provider = "postgresql"
  url      = "postgresql://_SYSTEM:SYS@localhost:5432/USER"
}

generator client {
  provider = "prisma-client-js"
}
EOF

# Run introspection
npx prisma db pull

# Verify models generated
grep -c "model" prisma/schema.prisma
# Should return > 0
```

### 3. SQLAlchemy Reflection Test

```python
from sqlalchemy import create_engine, MetaData

engine = create_engine("postgresql://_SYSTEM:SYS@localhost:5432/USER")
metadata = MetaData()

# Reflect tables from 'public' schema
metadata.reflect(bind=engine, schema='public')

assert len(metadata.tables) > 0, "Should discover tables"
for table_name in metadata.tables:
    print(f"Discovered: {table_name}")

print("✓ SQLAlchemy reflection works")
```

### 4. Schema-Qualified Query Test

```python
import psycopg

conn = psycopg.connect("host=localhost port=5432 user=_SYSTEM password=SYS dbname=USER")
cur = conn.cursor()

# Query using public.tablename syntax
cur.execute("SELECT COUNT(*) FROM public.test_table")  # Replace with actual table
count = cur.fetchone()[0]
print(f"Row count: {count}")

conn.close()
print("✓ Schema-qualified queries work")
```

## Expected Results

| Test | Expected Outcome |
|------|------------------|
| Basic schema query | Returns SQLUser tables with `table_schema = 'public'` |
| Prisma db pull | Generates schema.prisma with model definitions |
| SQLAlchemy reflect | Discovers all user tables |
| Schema-qualified query | `public.tablename` resolves to `SQLUser.tablename` |

## Troubleshooting

**Empty results from information_schema?**
- Verify tables exist in SQLUser schema: `SELECT * FROM information_schema.tables WHERE table_schema = 'SQLUser'`
- Check PGWire is running with schema mapping enabled

**Prisma serialization errors?**
- Ensure all information_schema columns return expected types
- Check for NULL handling in schema mapping output
