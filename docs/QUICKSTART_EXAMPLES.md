# Quick Start Examples: First Queries with IRIS PGWire

**Last Updated**: 2025-12-27
**Related**: [Installation](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/INSTALLATION.md), [Client Recommendations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/CLIENT_RECOMMENDATIONS.md)

---

## Command-Line (psql)

```bash
# Connect to IRIS via PostgreSQL protocol
psql -h localhost -p 5432 -U _SYSTEM -d USER

# Simple queries
SELECT * FROM MyTable LIMIT 10;

# Vector similarity search
SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]', DOUBLE)) AS score
FROM vectors
ORDER BY score DESC
LIMIT 5;
```

---

## Python (psycopg3)

```python
import psycopg

with psycopg.connect('host=localhost port=5432 dbname=USER user=_SYSTEM password=SYS') as conn:
    # Simple query
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM MyTable')
        count = cur.fetchone()[0]
        print(f'Total rows: {count}')

    # Parameterized query
    with conn.cursor() as cur:
        cur.execute('SELECT * FROM MyTable WHERE id = %s', (42,))
        row = cur.fetchone()

    # Vector search with parameter binding
    query_vector = [0.1, 0.2, 0.3]  # Works with any embedding model
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, VECTOR_COSINE(embedding, TO_VECTOR(%s, DOUBLE)) AS score
            FROM vectors
            ORDER BY score DESC
            LIMIT 5
        """, (query_vector,))
        results = cur.fetchall()
```

---

## Async SQLAlchemy with FastAPI

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from fastapi import FastAPI, Depends

# Setup
engine = create_async_engine("postgresql+psycopg://localhost:5432/USER")
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
app = FastAPI()

async def get_db():
    async with SessionLocal() as session:
        yield session

# FastAPI endpoint with async IRIS query
@app.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM users WHERE id = :id"),
        {"id": user_id}
    )
    return result.fetchone()
```

---

## See Also

- [Client Recommendations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/CLIENT_RECOMMENDATIONS.md) - Full compatibility matrix
- [Vector Parameter Binding](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md) - Vector operations guide
- [Features Overview](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/FEATURES_OVERVIEW.md) - All capabilities
