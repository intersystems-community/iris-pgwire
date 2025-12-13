# Async SQLAlchemy Quick Reference

**One-page guide for developers using async SQLAlchemy with IRIS**

---

## Installation

```bash
pip install sqlalchemy[asyncio] sqlalchemy-iris psycopg[binary]
```

---

## Basic Usage

### Create Engine

```python
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine("iris+psycopg://localhost:5432/USER")
```

### Simple Query

```python
from sqlalchemy import text

async with engine.connect() as conn:
    result = await conn.execute(text("SELECT 1"))
    print(result.scalar())
```

### Transaction

```python
async with engine.begin() as conn:
    await conn.execute(text("INSERT INTO users VALUES (1, 'alice')"))
    await conn.execute(text("UPDATE users SET status='active'"))
    # Auto-commits
```

---

## FastAPI Integration

```python
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

app = FastAPI()
engine = create_async_engine("iris+psycopg://localhost:5432/USER")
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session

@app.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
    return result.fetchone()
```

---

## Common Patterns

### Bulk Insert

```python
# Good: Batch operations
async with engine.begin() as conn:
    await conn.execute(table.insert(), list_of_dicts)

# Avoid: 1000s of individual inserts
for item in items:  # Don't do this
    await conn.execute(table.insert(), item)
```

### Table Creation

```python
from sqlalchemy import MetaData

metadata = MetaData()
# Define tables...

# Use checkfirst=False (IRIS/PGWire workaround)
async with engine.begin() as conn:
    await conn.run_sync(metadata.create_all, checkfirst=False)
```

### Connection Pooling

```python
engine = create_async_engine(
    "iris+psycopg://host:5432/namespace",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True
)
```

---

## IRIS Vector Operations

```python
# Create vector table
await conn.execute(text("""
    CREATE TABLE embeddings (
        id INT PRIMARY KEY,
        vec VECTOR(FLOAT, 128)
    )
"""))

# Vector similarity search
result = await conn.execute(text("""
    SELECT id, VECTOR_COSINE(vec, TO_VECTOR(:query, FLOAT)) as score
    FROM embeddings
    ORDER BY score DESC
    LIMIT 10
"""), {"query": '[0.1,0.2,...]'})
```

---

## Workarounds

### INFORMATION_SCHEMA

```python
# Instead of checkfirst=True
await conn.run_sync(metadata.create_all, checkfirst=False)

# Or manual DDL
await conn.execute(text("DROP TABLE IF EXISTS mytable"))
await conn.execute(text("CREATE TABLE mytable (...)"))
```

### Type Compatibility

```python
# IRIS may return '1' (string) or 1 (int)
result = await conn.execute(text("SELECT 1"))
value = result.scalar()
assert value in (1, '1')  # Accept both
```

---

## Troubleshooting

### Connection Refused
```bash
# Start PGWire server
docker-compose up -d pgwire-server
```

### Table Doesn't Exist Error
```python
# Use checkfirst=False
await conn.run_sync(metadata.create_all, checkfirst=False)
```

### Slow Performance
```python
# Use batch operations instead of loops
await conn.execute(table.insert(), batch_data)
```

---

## Production Config

```python
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    "iris+psycopg://user:pass@prod-host:5432/namespace",
    echo=False,  # No query logging
    pool_size=20,  # Based on load
    max_overflow=10,
    pool_pre_ping=True,  # Health checks
    pool_recycle=3600  # Recycle connections hourly
)
```

---

## Key Points

✅ **Works**: Queries, transactions, FastAPI, VECTOR operations, connection pooling
⚠️ **Workaround**: Use `checkfirst=False` for table creation
⚠️ **Best Practice**: Use batch operations for bulk inserts

**See `KNOWN_LIMITATIONS.md` for details**
