# Quickstart Guide: IRIS Bridge Gaps

This guide demonstrates the four new capabilities added to iris-pgwire based on learnings from the sim project IRIS integration.

## Prerequisites

- Python 3.11+
- iris-pgwire running (see main README)
- IRIS instance with vector support enabled

---

## 1. HNSW Vector Index Creation

Create vector indexes directly from your ORM migrations:

```python
import psycopg

with psycopg.connect("host=localhost port=5432 dbname=USER") as conn:
    with conn.cursor() as cur:
        # Create table with vector column
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                content TEXT,
                embedding VECTOR(384)
            )
        """)
        
        # Create HNSW index with cosine distance
        # Bridge translates to: CREATE INDEX doc_embedding_idx ON documents (embedding) AS HNSW
        cur.execute("""
            CREATE INDEX IF NOT EXISTS doc_embedding_idx 
            ON documents USING hnsw (embedding vector_cosine_ops)
        """)
        
        conn.commit()
        print("HNSW index created successfully!")
```

**Supported Distance Metrics**:
| PostgreSQL | IRIS Equivalent | Supported |
|------------|-----------------|-----------|
| `vector_cosine_ops` | Cosine similarity | ✅ Yes |
| `vector_ip_ops` | Inner product (dot product) | ✅ Yes |
| `vector_l2_ops` | Euclidean distance | ❌ **Not supported** |

> **Note**: If you use `vector_l2_ops`, the bridge will return an error:  
> *"IRIS does not support L2/Euclidean distance for HNSW indexes. Use vector_cosine_ops or vector_ip_ops."*

---

## 2. Fast Bulk Insert

Insert thousands of rows efficiently using the native fast-insert path:

```python
import psycopg
import random

# Generate test data
rows = [
    (f"doc_{i}", [random.random() for _ in range(384)])
    for i in range(10000)
]

with psycopg.connect("host=localhost port=5432 dbname=USER") as conn:
    with conn.cursor() as cur:
        # Use executemany for bulk insert
        # Bridge uses native parameter binding (not string inlining)
        cur.executemany(
            "INSERT INTO documents (content, embedding) VALUES (%s, %s)",
            rows
        )
        conn.commit()
        print(f"Inserted {len(rows)} rows")

# Expected: ~30 seconds for 10,000 rows (≥333 rows/sec)
```

**Performance Notes**:
- Native `executemany` uses binary parameter binding
- Falls back to string inlining only if native fails
- Monitor with `iris_pgwire.bulk_insert_latency` metric

---

## 3. Nested JSON Queries

Query deeply nested JSON structures:

```python
import psycopg
import json

with psycopg.connect("host=localhost port=5432 dbname=USER") as conn:
    with conn.cursor() as cur:
        # Create table with JSON column
        cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY,
                data JSONB
            )
        """)
        
        # Insert nested JSON
        cur.execute("""
            INSERT INTO events (data) VALUES (%s)
        """, [json.dumps({
            "user": {
                "profile": {
                    "name": "Alice",
                    "settings": {"theme": "dark"}
                }
            },
            "items": [
                {"name": "Item 1", "price": 10},
                {"name": "Item 2", "price": 20}
            ]
        })])
        
        # Query nested JSON (bridge translates to JSON_VALUE)
        # Two levels: data->'user'->>'name' → JSON_VALUE(data, '$.user.name')
        cur.execute("""
            SELECT data->'user'->'profile'->>'name' AS user_name
            FROM events
        """)
        print(f"User name: {cur.fetchone()[0]}")  # Output: Alice
        
        # Three levels with array access
        # data->'items'->0->>'name' → JSON_VALUE(data, '$.items[0].name')
        cur.execute("""
            SELECT data->'items'->0->>'name' AS first_item
            FROM events
        """)
        print(f"First item: {cur.fetchone()[0]}")  # Output: Item 1
        
        conn.commit()
```

**Supported Patterns**:
| PostgreSQL | IRIS Translation |
|------------|------------------|
| `col->>'key'` | `JSON_VALUE(col, '$.key')` |
| `col->'a'->>'b'` | `JSON_VALUE(col, '$.a.b')` |
| `col->'a'->'b'->>'c'` | `JSON_VALUE(col, '$.a.b.c')` |
| `col->'items'->0->>'name'` | `JSON_VALUE(col, '$.items[0].name')` |

---

## 4. DDL Idempotency

Run migrations safely multiple times:

```python
import psycopg

def run_migration(conn):
    with conn.cursor() as cur:
        # These statements are safe to run multiple times
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE
            )
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS users_email_idx ON users (email)
        """)
        
        conn.commit()

with psycopg.connect("host=localhost port=5432 dbname=USER") as conn:
    # First run: creates objects
    run_migration(conn)
    print("First migration: objects created")
    
    # Second run: skips existing objects (logs warnings, no errors)
    run_migration(conn)
    print("Second migration: objects skipped (no errors)")
```

**Behavior**:
- `IF NOT EXISTS` + object exists → Success + warning log
- `IF NOT EXISTS` + object doesn't exist → Create object
- No `IF NOT EXISTS` + object exists → Error raised

**Log Output**:
```
WARN  Object already exists, skipping: table 'users'
WARN  Object already exists, skipping: index 'users_email_idx'
```

---

## Verifying the Integration

Run the test suite to verify all features:

```bash
# Unit tests for conversion utilities
pytest tests/unit/test_conversions.py -v

# Integration tests for all four features
pytest tests/integration/test_bridge_gaps.py -v

# Benchmark bulk insert performance
pytest tests/integration/test_bulk_insert.py --benchmark-only
```

**Expected Results**:
- All unit tests pass
- HNSW index creation succeeds
- Bulk insert completes in ≤30 seconds for 10,000 rows
- Nested JSON queries return correct values
- Re-running DDL migrations produces no errors

---

## Troubleshooting

### HNSW index creation fails
- Verify IRIS version supports `CREATE INDEX ... AS HNSW`
- Check that column type is VECTOR

### Bulk insert is slow
- Check if falling back to string inlining (look for "fallback" in logs)
- Ensure connection pool is sized appropriately

### JSON path returns NULL
- Verify the JSON structure matches the path
- Use `->` for intermediate objects, `->>` for final text value

### DDL errors despite IF NOT EXISTS
- Check for permission issues (not duplicate object errors)
- Verify IRIS user has CREATE TABLE/INDEX privileges

---

*Quickstart based on sim project integration patterns.*
