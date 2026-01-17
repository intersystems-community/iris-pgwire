# Quickstart: PostgreSQL DDL Compatibility (ENUM, RLS, Boolean Defaults)

**Feature**: 035-number-1-short  
**Date**: 2026-01-17

## Overview

This quickstart validates that the DDL compatibility feature works correctly by running representative migration statements through pgwire.

---

## Prerequisites

1. iris-pgwire server running (Docker or local)
2. psycopg3 installed (`pip install psycopg[binary]`)
3. iris-devtester available for E2E tests

---

## Quick Validation

### Step 1: Connect to pgwire

```python
import psycopg

conn = psycopg.connect(
    host="localhost",
    port=5432,
    dbname="USER",
    user="_SYSTEM",
    password="SYS"
)
```

### Step 2: Test ENUM Handling

```python
with conn.cursor() as cur:
    # Should succeed (skipped)
    cur.execute("""
        CREATE TYPE "public"."test_status" AS ENUM('active', 'pending', 'closed')
    """)
    print("✓ CREATE TYPE AS ENUM: Skipped successfully")
    
    # Should succeed (enum → VARCHAR(64))
    cur.execute("""
        CREATE TABLE test_enum_table (
            id INT PRIMARY KEY,
            status "test_status" NOT NULL
        )
    """)
    print("✓ Column with enum type: Created as VARCHAR(64)")
    
    # Clean up
    cur.execute("DROP TABLE IF EXISTS test_enum_table")
    cur.execute("DROP TYPE IF EXISTS test_status")
    print("✓ Cleanup complete")
```

### Step 3: Test RLS Handling

```python
with conn.cursor() as cur:
    # Create a test table first
    cur.execute("CREATE TABLE test_rls_table (id INT PRIMARY KEY)")
    
    # Should succeed (skipped)
    cur.execute("ALTER TABLE test_rls_table ENABLE ROW LEVEL SECURITY")
    print("✓ ENABLE ROW LEVEL SECURITY: Skipped successfully")
    
    cur.execute("ALTER TABLE test_rls_table DISABLE ROW LEVEL SECURITY")
    print("✓ DISABLE ROW LEVEL SECURITY: Skipped successfully")
    
    # Clean up
    cur.execute("DROP TABLE IF EXISTS test_rls_table")
    print("✓ Cleanup complete")
```

### Step 4: Test Boolean Default Translation

```python
with conn.cursor() as cur:
    # Should succeed (true → 1, false → 0)
    cur.execute("""
        CREATE TABLE test_bool_table (
            id INT PRIMARY KEY,
            is_active boolean DEFAULT true NOT NULL,
            is_deleted boolean DEFAULT false NOT NULL
        )
    """)
    print("✓ Boolean defaults: Translated to 1/0")
    
    # Verify defaults work
    cur.execute("INSERT INTO test_bool_table (id) VALUES (1)")
    cur.execute("SELECT is_active, is_deleted FROM test_bool_table WHERE id = 1")
    row = cur.fetchone()
    assert row[0] == 1, "is_active should be 1"
    assert row[0] == 0 or row[1] == 0, "is_deleted should be 0"
    print("✓ Default values applied correctly")
    
    # Clean up
    cur.execute("DROP TABLE IF EXISTS test_bool_table")
    print("✓ Cleanup complete")
```

---

## Full Validation Test Suite

Run the complete test suite:

```bash
# Run all feature tests
pytest tests/integration/test_enum_e2e.py -v
pytest tests/integration/test_rls_e2e.py -v
pytest tests/integration/test_boolean_e2e.py -v

# Run contract tests
pytest tests/contract/test_enum_translation.py -v
pytest tests/contract/test_rls_handling.py -v
pytest tests/contract/test_boolean_defaults.py -v

# Run full regression suite
pytest tests/ -v --ignore=tests/archive
```

---

## Drizzle Migration Test

Test with actual Drizzle-style migration patterns:

```python
# Representative Drizzle migration statements
drizzle_statements = [
    # ENUM creation
    'CREATE TYPE "public"."permission_type" AS ENUM(\'admin\', \'write\', \'read\')',
    
    # Table with enum column
    '''CREATE TABLE "permissions" (
        "id" uuid PRIMARY KEY,
        "permission_type" "permission_type" NOT NULL
    )''',
    
    # RLS
    'ALTER TABLE "logs" DISABLE ROW LEVEL SECURITY',
    
    # Boolean defaults
    'ALTER TABLE "settings" ADD COLUMN "debug_mode" boolean DEFAULT false NOT NULL',
    'ALTER TABLE "settings" ADD COLUMN "auto_connect" boolean DEFAULT true NOT NULL',
]

with conn.cursor() as cur:
    for stmt in drizzle_statements:
        try:
            cur.execute(stmt)
            print(f"✓ {stmt[:60]}...")
        except Exception as e:
            print(f"✗ {stmt[:60]}... ERROR: {e}")
```

---

## Success Criteria Verification

| Criterion | Validation Method |
|-----------|-------------------|
| 64 failing statements now pass | Run migration test suite |
| No regression in 171 client tests | `pytest tests/` full suite |
| Performance <5ms overhead | Check test timing assertions |
| sim_sql_patch.py code removable | After upstream, remove and re-test |

---

## Troubleshooting

### Statement Still Fails

1. Check if pattern matches expected regex
2. Verify container has latest code (`docker restart iris-pgwire-db`)
3. Check logs for translation output

### Enum Type Not Translated

1. Verify CREATE TYPE was processed first
2. Check enum registry contains the type name
3. Ensure type name matches (case-insensitive)

### Boolean Default Unchanged

1. Check for word boundary issues
2. Verify not inside string literal or comment
3. Check case sensitivity of pattern

---

## Next Steps

After validation:
1. Remove duplicate handling from `sim/iris/sim_sql_patch.py`
2. Test sim project migrations with updated iris-pgwire
3. Release new iris-pgwire version
