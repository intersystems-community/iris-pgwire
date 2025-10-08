# Async SQLAlchemy Quickstart

**TL;DR**: Use `iris+psycopg://` to connect SQLAlchemy async to IRIS via PGWire

---

## Installation

```bash
# Install modified sqlalchemy-iris with async support
pip install -e /Users/tdyar/ws/sqlalchemy-iris

# Or from your fork (when pushed)
pip install git+https://github.com/isc-tdyar/sqlalchemy-iris.git
```

---

## Basic Usage

```python
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Connect to IRIS via PGWire
engine = create_async_engine(
    'iris+psycopg://localhost:5432/USER',
    echo=True  # Show SQL
)

# Execute query
async with engine.begin() as conn:
    result = await conn.execute(text("SELECT 1"))
    print(result.fetchone())  # (1,)

await engine.dispose()
```

---

## Why This Works

**Magic**: Uses **IRIS dialect** with **psycopg transport**

```
SQLAlchemy → IRISDialect_psycopg → psycopg → PGWire → IRIS
              └─ INFORMATION_SCHEMA        └─ PostgreSQL
                 VECTOR types                 wire protocol
```

**NOT**:
```
❌ SQLAlchemy → PostgreSQL dialect → PGWire
                 └─ pg_catalog queries (we don't have these)
                    VECTOR types not supported
```

---

## Vector Queries

```python
# Create table with VECTOR column
await conn.execute(text("""
    CREATE TABLE vectors (
        id INTEGER,
        embedding VECTOR(FLOAT, 128)
    )
"""))

# Insert with parameter binding
await conn.execute(
    text("INSERT INTO vectors VALUES (:id, TO_VECTOR(:vec, FLOAT))"),
    {"id": 1, "vec": "[0.1, 0.2, ...]"}
)

# Similarity search
result = await conn.execute(text("""
    SELECT id, VECTOR_COSINE(embedding, TO_VECTOR(:query, FLOAT)) as score
    FROM vectors
    ORDER BY score DESC
    LIMIT 5
"""), {"query": "[0.1, 0.2, ...]"})
```

---

## Async ORM

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, select

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String(50))

# Create async session
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Insert
async with async_session() as session:
    async with session.begin():
        session.add(User(id=1, name='Alice'))

# Query
async with async_session() as session:
    result = await session.execute(select(User).where(User.id == 1))
    user = result.scalar_one()
    print(user.name)  # Alice
```

---

## FastAPI Example

```python
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

app = FastAPI()

# Setup
engine = create_async_engine('iris+psycopg://localhost:5432/USER')
async_session = sessionmaker(engine, class_=AsyncSession)

async def get_session():
    async with async_session() as session:
        yield session

# Endpoint
@app.get("/users/{user_id}")
async def get_user(user_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    return {"id": user.id, "name": user.name}
```

---

## What You Get

**IRIS Features** (inherited from IRISDialect):
- ✅ INFORMATION_SCHEMA metadata queries
- ✅ IRIS VECTOR types
- ✅ Date/time handling (Horolog format)
- ✅ Boolean conversion (1/0 → true/false)
- ✅ IRIS-specific SQL constructs

**PostgreSQL Ecosystem** (via psycopg):
- ✅ Async operations
- ✅ Connection pooling
- ✅ Wire protocol compatibility
- ✅ Universal tool support

**SQLAlchemy Features**:
- ✅ Async ORM
- ✅ Async Core
- ✅ Table reflection
- ✅ Alembic migrations (async)

---

## Requirements

1. **PGWire server running** on port 5432
2. **IRIS instance** accessible to PGWire
3. **psycopg[binary]** installed
4. **Modified sqlalchemy-iris** with psycopg dialect

---

## Testing

```bash
# Start PGWire server
docker-compose up -d pgwire-server

# Run tests
pytest tests/test_sqlalchemy_async.py -v

# Expected results
test_async_engine_creation PASSED
test_async_simple_query PASSED
test_async_table_reflection PASSED
test_async_vector_operations PASSED
test_async_orm_session PASSED
```

---

## Troubleshooting

**Import Error**:
```python
ImportError: cannot import name 'psycopg'
```
→ Make sure you installed from modified fork: `pip install -e /Users/tdyar/ws/sqlalchemy-iris`

**Connection Error**:
```
sqlalchemy.exc.OperationalError: connection refused
```
→ Start PGWire server: `docker-compose up -d pgwire-server`

**Wrong Dialect**:
```
NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:iris.psycopg
```
→ Check entry point is registered: `python -c "import sqlalchemy_iris.psycopg"`

---

## Full Documentation

- **Implementation Details**: `docs/SQLALCHEMY_ASYNC_SUPPORT.md`
- **REST API Strategy**: `docs/REST_API_STRATEGY.md`
- **Recent Developments**: `docs/RECENT_DEVELOPMENTS.md`
- **Test Suite**: `tests/test_sqlalchemy_async.py`

---

**Status**: Implementation complete ✅ | E2E testing pending ⏸️ (requires PGWire server)

**Next Step**: Start PGWire server and run `pytest tests/test_sqlalchemy_async.py -v`
