# Async SQLAlchemy Quickstart Guide

**Feature**: 019-async-sqlalchemy-based
**Audience**: Python developers using FastAPI or other async frameworks
**Prerequisites**: IRIS PGWire server running on port 5432

---

## Installation

```bash
# Install SQLAlchemy with async support and IRIS dialect
uv pip install sqlalchemy[asyncio] sqlalchemy-iris psycopg[binary]

# Or add to requirements.txt
sqlalchemy>=2.0.0
sqlalchemy-iris>=0.9.14
psycopg[binary]>=3.1.0
```

---

## Quick Start (5 Minutes)

### 1. Start PGWire Server

```bash
# From iris-pgwire project directory
docker-compose up -d pgwire-server

# Verify server is running
docker ps | grep pgwire
# Should show: pgwire-server running on port 5432
```

### 2. Create Async Engine

```python
from sqlalchemy.ext.asyncio import create_async_engine

# Connection string: iris+psycopg://[user:password@]host:port/namespace
engine = create_async_engine(
    "iris+psycopg://localhost:5432/USER",
    echo=True  # Show SQL queries (disable in production)
)
```

### 3. Execute Simple Query

```python
from sqlalchemy import text

async def test_connection():
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 'Hello from IRIS!'"))
        print(result.fetchone()[0])

# Run with asyncio
import asyncio
asyncio.run(test_connection())
```

**Expected Output**:
```
Hello from IRIS!
```

---

## FastAPI Integration

### Basic Setup

```python
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

app = FastAPI()

# Create async engine and session factory
engine = create_async_engine("iris+psycopg://localhost:5432/USER")
async_session_factory = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Dependency for route handlers
async def get_session():
    async with async_session_factory() as session:
        yield session
```

### Simple Query Route

```python
from sqlalchemy import text

@app.get("/health")
async def health_check(session: AsyncSession = Depends(get_session)):
    result = await session.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}
```

### Vector Similarity Search

```python
@app.get("/vectors/search")
async def search_vectors(
    query: str,
    limit: int = 5,
    session: AsyncSession = Depends(get_session)
):
    """Search vectors by similarity using IRIS vector functions."""
    sql = text("""
        SELECT id, name,
               VECTOR_COSINE(embedding, TO_VECTOR(:query, FLOAT)) as score
        FROM product_vectors
        ORDER BY score DESC
        LIMIT :limit
    """)

    result = await session.execute(sql, {"query": query, "limit": limit})
    return [
        {"id": row.id, "name": row.name, "score": float(row.score)}
        for row in result
    ]
```

---

## Common Patterns

### Transaction Management

```python
async def update_with_transaction():
    async with engine.begin() as conn:
        # Transaction started automatically
        await conn.execute(text("INSERT INTO users VALUES (1, 'Alice')"))
        await conn.execute(text("INSERT INTO users VALUES (2, 'Bob')"))
        # Transaction committed automatically on context exit
        # Rollback on exception
```

### ORM Models with Async Sessions

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()

# Create tables
async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)

# Insert with ORM
async with async_session_factory() as session:
    user = User(name="Charlie")
    session.add(user)
    await session.commit()

# Query with ORM
async with async_session_factory() as session:
    from sqlalchemy import select
    result = await session.execute(select(User).where(User.name == "Charlie"))
    user = result.scalar_one()
    print(user.id, user.name)
```

### Bulk Insert (Efficient)

```python
async def bulk_insert_users(users: list[dict]):
    async with engine.begin() as conn:
        # Uses do_executemany() for efficiency
        await conn.execute(
            text("INSERT INTO users (name, email) VALUES (:name, :email)"),
            users  # List of dicts: [{"name": "Alice", "email": "..."}, ...]
        )
```

---

## IRIS Vector Operations

### Create Vector Table

```python
async with engine.begin() as conn:
    await conn.execute(text("""
        CREATE TABLE product_vectors (
            id INTEGER PRIMARY KEY,
            name VARCHAR(100),
            embedding VECTOR(FLOAT, 128)
        )
    """))
```

### Insert Vectors

```python
import json

async def insert_vector(product_id: int, name: str, embedding: list[float]):
    # Convert Python list to IRIS vector format
    vector_str = json.dumps(embedding)  # "[0.1, 0.2, 0.3, ...]"

    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO product_vectors VALUES (
                :id, :name, TO_VECTOR(:embedding, FLOAT)
            )
        """), {"id": product_id, "name": name, "embedding": vector_str})
```

### Vector Similarity Query

```python
async def find_similar_products(query_embedding: list[float], top_k: int = 5):
    vector_str = json.dumps(query_embedding)

    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT id, name,
                   VECTOR_COSINE(embedding, TO_VECTOR(:query, FLOAT)) as score
            FROM product_vectors
            ORDER BY score DESC
            LIMIT :limit
        """), {"query": vector_str, "limit": top_k})

        return [
            {"id": row.id, "name": row.name, "similarity": float(row.score)}
            for row in result
        ]
```

---

## Performance Tips

### 1. Connection Pooling

```python
# Configure pool size for high concurrency
engine = create_async_engine(
    "iris+psycopg://localhost:5432/USER",
    pool_size=20,        # Default: 5
    max_overflow=10,     # Additional connections beyond pool_size
    pool_timeout=30,     # Timeout waiting for connection
    pool_pre_ping=True,  # Verify connections before use
)
```

### 2. Prepared Statements

```python
# Reuse queries with bound parameters (automatic caching)
stmt = text("SELECT * FROM users WHERE id = :user_id")

async with engine.connect() as conn:
    # Statement prepared once, reused for all executions
    for user_id in range(1, 100):
        result = await conn.execute(stmt, {"user_id": user_id})
```

### 3. Batch Operations

```python
# Use executemany for bulk inserts (not individual execute calls)
async with engine.begin() as conn:
    await conn.execute(
        text("INSERT INTO logs (message) VALUES (:msg)"),
        [{"msg": f"Log {i}"} for i in range(1000)]
    )
```

---

## Troubleshooting

### AwaitRequired Error

**Problem**: `sqlalchemy.exc.AwaitRequired: The current operation requires an async execution env`

**Cause**: Using `create_engine()` instead of `create_async_engine()`

**Solution**:
```python
# ❌ Wrong: sync engine
engine = create_engine("iris+psycopg://localhost:5432/USER")

# ✅ Correct: async engine
from sqlalchemy.ext.asyncio import create_async_engine
engine = create_async_engine("iris+psycopg://localhost:5432/USER")
```

### Connection Refused

**Problem**: `psycopg.OperationalError: connection refused`

**Cause**: PGWire server not running

**Solution**:
```bash
# Check if PGWire server is running
docker ps | grep pgwire

# If not running, start it
cd /path/to/iris-pgwire
docker-compose up -d pgwire-server

# Verify port 5432 is listening
nc -zv localhost 5432
```

### Module Not Found: psycopg

**Problem**: `ModuleNotFoundError: No module named 'psycopg'`

**Cause**: psycopg not installed or missing binary extras

**Solution**:
```bash
# Install with binary extras (recommended)
uv pip install psycopg[binary]

# Or compile from source (slower, but smaller)
uv pip install psycopg
```

### Slow Bulk Inserts

**Problem**: Bulk insert takes minutes for 1000 records

**Cause**: Using individual `execute()` calls instead of `executemany` pattern

**Solution**:
```python
# ❌ Slow: 1000 separate execute() calls
for record in records:
    await conn.execute(text("INSERT INTO table VALUES (:val)"), record)

# ✅ Fast: Single executemany() call
await conn.execute(
    text("INSERT INTO table VALUES (:val)"),
    records  # List of dicts
)
```

### Vector Query Fails

**Problem**: `SQLCODE: -400 Message: Cannot perform vector operation on vectors of different datatypes`

**Cause**: Vector table uses DOUBLE but query uses TO_VECTOR(..., FLOAT)

**Solution**: Match data types:
```python
# Check table definition
await conn.execute(text("SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE COLUMN_NAME = 'embedding'"))
# Result: "VECTOR(DOUBLE, 128)"

# Use matching type in query
await conn.execute(text("""
    SELECT * FROM vectors
    ORDER BY VECTOR_COSINE(embedding, TO_VECTOR(:query, DOUBLE))  -- DOUBLE not FLOAT
"""), {"query": vector_str})
```

---

## Example Project Structure

```
my_fastapi_app/
├── main.py                 # FastAPI app with async routes
├── database.py             # Engine and session factory
├── models.py               # SQLAlchemy ORM models
├── routers/
│   ├── users.py           # User CRUD routes
│   └── vectors.py         # Vector search routes
├── requirements.txt        # Dependencies
└── docker-compose.yml      # PGWire server config
```

**database.py**:
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine("iris+psycopg://localhost:5432/USER", echo=False)
async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session():
    async with async_session_factory() as session:
        yield session
```

**main.py**:
```python
from fastapi import FastAPI
from routers import users, vectors

app = FastAPI(title="IRIS Vector Search API")
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(vectors.router, prefix="/vectors", tags=["vectors"])

@app.on_event("startup")
async def startup():
    # Initialize database tables if needed
    pass

@app.on_event("shutdown")
async def shutdown():
    await engine.dispose()
```

---

## Next Steps

1. **Read Full Documentation**: `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/spec.md`
2. **Review Benchmarks**: Compare async vs sync performance in `benchmarks/`
3. **Explore Vector Use Cases**: IRIS vector functions for semantic search
4. **Join Community**: Report issues at https://github.com/iris-pgwire/issues

---

## Performance Expectations

**Baseline** (from sync SQLAlchemy testing):
- Simple SELECT: 1-2ms per query
- Vector similarity (128D): 5-10ms per query
- Bulk insert (1000 records): Sub-second

**Async Target** (within 10% of sync):
- Simple SELECT: ≤2.2ms per query
- Vector similarity: ≤11ms per query
- Bulk insert: Within 10% of sync baseline

**When to Use Async**:
- High concurrency (100+ concurrent requests)
- I/O-bound workloads (long queries, vector searches)
- FastAPI async routes
- Streaming results

**When to Use Sync**:
- Simple scripts
- Low concurrency
- CPU-bound workloads
- Existing sync codebases

---

**Questions?** See troubleshooting section above or open an issue.
