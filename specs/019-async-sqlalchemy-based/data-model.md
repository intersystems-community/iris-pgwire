# Data Model: Async SQLAlchemy Support

**Feature**: 019-async-sqlalchemy-based
**Created**: 2025-10-08

---

## Overview

This feature does NOT introduce new data entities or database schema changes. It extends the existing SQLAlchemy dialect architecture to support async operations.

**Scope**: Software architecture data model (dialect classes, connection objects, session management), not database schema.

---

## Core Entities

### 1. IRISDialectAsync_psycopg (New Class)

**Type**: SQLAlchemy Dialect Class
**Location**: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py`

**Purpose**: Async variant of IRIS dialect combining IRIS-specific features with PostgreSQL async wire protocol transport.

**Attributes**:
```python
driver: str = "psycopg"                    # DBAPI driver name
is_async: bool = True                      # Async operation flag
supports_statement_cache: bool = True      # Prepared statement caching
supports_native_boolean: bool = True       # Boolean type support
```

**Methods**:
```python
@classmethod
def import_dbapi(cls) -> ModuleType:
    """Returns psycopg module for async connections."""

@classmethod
def get_pool_class(cls, url) -> Type:
    """Returns AsyncAdaptedQueuePool for async engine."""

def create_connect_args(self, url) -> Tuple[List, Dict]:
    """Converts SQLAlchemy URL to psycopg async connection args."""

def on_connect(self) -> Callable:
    """Returns connection initialization callback."""

def do_executemany(self, cursor, query, params, context=None) -> None:
    """Executes parameterized query multiple times asynchronously."""
```

**Inheritance**:
- Parent 1: `IRISDialect` (IRIS-specific features)
- Parent 2: `PGDialectAsync_psycopg` (PostgreSQL async transport)
- MRO Priority: IRIS-specific methods override PostgreSQL defaults

**Lifecycle**:
1. Instantiated by SQLAlchemy when `create_async_engine("iris+psycopg://")` is called
2. Configured via `create_connect_args()` method
3. Manages async connection pool via `get_pool_class()`
4. Disposed when engine is closed

---

### 2. AsyncEngine (SQLAlchemy Built-in)

**Type**: SQLAlchemy Engine Instance
**Location**: Created by `sqlalchemy.ext.asyncio.create_async_engine()`

**Purpose**: Async connection pool and engine for database operations.

**Attributes**:
```python
url: URL                                   # Connection URL (iris+psycopg://...)
dialect: IRISDialectAsync_psycopg         # Dialect instance
pool: AsyncAdaptedQueuePool               # Async connection pool
```

**Methods**:
```python
async def connect() -> AsyncConnection:
    """Returns async connection from pool."""

async def begin() -> AsyncTransaction:
    """Returns async transaction context."""

async def dispose() -> None:
    """Closes all pool connections."""
```

**Lifecycle**:
1. Created via `create_async_engine("iris+psycopg://localhost:5432/USER")`
2. Maintains pool of async connections to PGWire server
3. Disposed explicitly via `await engine.dispose()` or at application shutdown

**Relationships**:
- **Has-one** `IRISDialectAsync_psycopg` (dialect instance)
- **Has-many** `AsyncConnection` (via pool)

---

### 3. AsyncConnection (SQLAlchemy Built-in)

**Type**: SQLAlchemy Connection Instance
**Location**: Created by `AsyncEngine.connect()`

**Purpose**: Async database connection wrapping psycopg `AsyncConnection`.

**Attributes**:
```python
engine: AsyncEngine                        # Parent engine
_dbapi_connection: psycopg.AsyncConnection # Underlying psycopg connection
```

**Methods**:
```python
async def execute(statement, params=None) -> CursorResult:
    """Executes async query and returns result."""

async def commit() -> None:
    """Commits current transaction."""

async def rollback() -> None:
    """Rolls back current transaction."""

async def close() -> None:
    """Returns connection to pool."""
```

**Lifecycle**:
1. Acquired from pool via `async with engine.connect() as conn:`
2. Used for query execution within async context
3. Returned to pool when context exits

**Relationships**:
- **Belongs-to** `AsyncEngine` (parent engine)
- **Wraps** `psycopg.AsyncConnection` (DBAPI connection)

---

### 4. AsyncSession (SQLAlchemy ORM Built-in)

**Type**: SQLAlchemy ORM Session Instance
**Location**: Created by `sessionmaker(engine, class_=AsyncSession)`

**Purpose**: Async ORM session for model-based database operations.

**Attributes**:
```python
bind: AsyncEngine                          # Bound engine
_connection: AsyncConnection               # Current connection (if in transaction)
```

**Methods**:
```python
async def execute(statement, params=None) -> Result:
    """Executes async ORM query."""

async def commit() -> None:
    """Commits ORM transaction."""

async def rollback() -> None:
    """Rolls back ORM transaction."""

async def close() -> None:
    """Closes session and releases connection."""
```

**Lifecycle**:
1. Created via `async_session_factory()` (sessionmaker pattern)
2. Used within `async with session:` context
3. Closed when context exits

**Relationships**:
- **Uses** `AsyncConnection` (via bound engine)
- **Manages** ORM model instances

---

### 5. psycopg.AsyncConnection (DBAPI Object)

**Type**: psycopg3 Async Connection
**Location**: Created by `psycopg.AsyncConnection.connect()`

**Purpose**: PostgreSQL wire protocol async connection to PGWire server.

**Attributes**:
```python
pgconn: psycopg.pq.PGconn                  # Underlying PostgreSQL connection
status: int                                # Connection status (OK, BAD, etc.)
```

**Methods**:
```python
async def cursor() -> AsyncCursor:
    """Returns async cursor for query execution."""

async def commit() -> None:
    """Commits transaction."""

async def rollback() -> None:
    """Rolls back transaction."""

async def close() -> None:
    """Closes connection."""
```

**Lifecycle**:
1. Created by `IRISDialectAsync_psycopg.create_connect_args()`
2. Wrapped by `AsyncConnection` (SQLAlchemy)
3. Closed when SQLAlchemy connection is disposed

**Relationships**:
- **Wrapped-by** `AsyncConnection` (SQLAlchemy)
- **Connects-to** PGWire Server (TCP socket on port 5432)

---

## Class Relationships

```
┌─────────────────────────────────────────────────────────────────┐
│ Application Layer (FastAPI, etc.)                               │
└─────────────────────────┬───────────────────────────────────────┘
                          │ creates
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ AsyncEngine                                                      │
│ - url: "iris+psycopg://localhost:5432/USER"                     │
│ - dialect: IRISDialectAsync_psycopg ◄────────────────┐          │
│ - pool: AsyncAdaptedQueuePool                        │          │
└─────────────────────────┬───────────────────────────────────────┘
                          │ provides                   │
                          ▼                            │ instance of
┌─────────────────────────────────────────────────────────────────┐
│ AsyncConnection                                      │          │
│ - engine: AsyncEngine                                │          │
│ - _dbapi_connection: psycopg.AsyncConnection         │          │
└─────────────────────────┬───────────────────────────────────────┘
                          │ wraps                      │
                          ▼                            │
┌─────────────────────────────────────────────────────────────────┐
│ psycopg.AsyncConnection                              │          │
│ - pgconn: PGconn                                     │          │
│ - status: OK                                         │          │
└─────────────────────────┬───────────────────────────────────────┘
                          │ connects to                │
                          ▼                            │
┌─────────────────────────────────────────────────────────────────┐
│ PGWire Server (iris-pgwire)                          │          │
│ - Protocol: PostgreSQL Wire Protocol                 │          │
│ - Port: 5432                                         │          │
└─────────────────────────┬───────────────────────────────────────┘
                          │ queries                    │
                          ▼                            │
┌─────────────────────────────────────────────────────────────────┐
│ IRIS Database                                        │          │
│ - Namespace: USER                                    │          │
│ - Vector Functions: VECTOR_COSINE, VECTOR_DOT_PRODUCT          │
└─────────────────────────────────────────────────────────────────┘
                                                       │
                                                       │ inherits from
                                                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ IRISDialect (Base Class)                                         │
│ - VECTOR type support                                            │
│ - INFORMATION_SCHEMA metadata                                    │
│ - IRIS function mapping                                          │
└──────────────────────────────────────────────────────────────────┘
                                                       ▲
                                                       │ also inherits from
                                                       │
┌─────────────────────────────────────────────────────────────────┐
│ PGDialectAsync_psycopg (SQLAlchemy Built-in)                    │
│ - Async transport layer                                          │
│ - AsyncAdaptedQueuePool support                                 │
│ - psycopg async DBAPI handling                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## State Transitions

### Async Engine Lifecycle

```
[Created] ──create_async_engine()──> [Initialized]
                                             │
                                             │ connect()
                                             ▼
                                      [Connected]
                                             │
                                             │ dispose()
                                             ▼
                                      [Disposed]
```

### Async Connection Lifecycle

```
[Pool] ──acquire()──> [Active] ──begin()──> [InTransaction]
                         │                         │
                         │                         │ commit()/rollback()
                         ▼                         ▼
                    [Idle] <───────────────── [Active]
                         │
                         │ close()
                         ▼
                    [Returned to Pool]
```

### Async Session Lifecycle (ORM)

```
[Created] ──sessionmaker()──> [New]
                                 │
                                 │ execute()
                                 ▼
                            [Active]
                                 │
                                 │ commit()/rollback()
                                 ▼
                            [Flushed]
                                 │
                                 │ close()
                                 ▼
                            [Closed]
```

---

## Configuration Data Model

### Connection URL Structure

**Format**: `iris+psycopg://[user[:password]@][host][:port]/dbname[?param=value]`

**Examples**:
```
iris+psycopg://localhost:5432/USER
iris+psycopg://_SYSTEM:SYS@localhost:5432/USER
iris+psycopg://localhost:5432/USER?connect_timeout=10
```

**Components**:
- **Scheme**: `iris+psycopg` (dialect.driver format)
- **User**: Optional (defaults to current user)
- **Password**: Optional (PGWire authentication)
- **Host**: PGWire server host (default: localhost)
- **Port**: PGWire port (default: 5432)
- **Database**: IRIS namespace (e.g., USER, IRISAPP)
- **Query Params**: Connection options (timeout, SSL, etc.)

### Dialect Configuration

**Attributes**:
```python
{
    "driver": "psycopg",
    "is_async": True,
    "supports_statement_cache": True,
    "supports_native_boolean": True,
    "default_isolation_level": "READ COMMITTED",
    "max_identifier_length": 128,
    "supports_native_decimal": True,
    "supports_native_uuid": False,  # IRIS has no UUID type
}
```

### Pool Configuration

**AsyncAdaptedQueuePool Settings**:
```python
{
    "pool_size": 5,                    # Default connection pool size
    "max_overflow": 10,                # Additional connections allowed
    "pool_timeout": 30.0,              # Timeout waiting for connection
    "pool_recycle": 3600,              # Recycle connections after 1 hour
    "pool_pre_ping": True,             # Verify connections before use
}
```

---

## Error States

### Dialect Resolution Errors

**AwaitRequired Exception**:
- **Cause**: `get_async_dialect_cls()` not implemented, sync dialect used with async engine
- **State**: Engine created but operations fail on first query
- **Recovery**: Implement `get_async_dialect_cls()` method

**No DBAPI Module Error**:
- **Cause**: psycopg not installed or import failure
- **State**: Engine creation fails immediately
- **Recovery**: Install psycopg with `uv pip install psycopg[binary]`

### Connection Errors

**Connection Refused**:
- **Cause**: PGWire server not running on port 5432
- **State**: Connection acquisition fails from pool
- **Recovery**: Start PGWire server via `docker-compose up pgwire-server`

**Authentication Failed**:
- **Cause**: Invalid credentials in connection URL
- **State**: Connection attempt fails with authentication error
- **Recovery**: Verify user/password match IRIS authentication

### Transaction Errors

**Async Transaction Rollback**:
- **Cause**: Exception during async query execution
- **State**: Transaction rolled back, connection returned to pool
- **Recovery**: Automatic rollback, connection reusable

---

## Validation Checkpoints

### Dialect Registration

**Entry Point**:
```python
# setup.py
entry_points={
    "sqlalchemy.dialects": [
        "iris.psycopg = sqlalchemy_iris.psycopg:IRISDialect_psycopg",
    ]
}
```

**Verification**:
```python
from sqlalchemy import create_async_engine
engine = create_async_engine("iris+psycopg://localhost:5432/USER")
assert engine.dialect.__class__.__name__ == "IRISDialectAsync_psycopg"
```

### Async Resolver Validation

**Method Existence**:
```python
from sqlalchemy_iris.psycopg import IRISDialect_psycopg
assert hasattr(IRISDialect_psycopg, "get_async_dialect_cls")
```

**Return Type**:
```python
async_cls = IRISDialect_psycopg.get_async_dialect_cls(None)
assert async_cls.__name__ == "IRISDialectAsync_psycopg"
assert async_cls.is_async == True
```

### Connection Pool Validation

**Pool Class**:
```python
from sqlalchemy.pool import AsyncAdaptedQueuePool
pool_cls = IRISDialectAsync_psycopg.get_pool_class(None)
assert pool_cls == AsyncAdaptedQueuePool
```

---

## Performance Considerations

### Object Pooling

**Connection Reuse**:
- Async connections expensive to create (TCP handshake, authentication)
- Pool maintains 5 connections by default (configurable)
- Pre-ping ensures connections are alive before use

**Prepared Statement Cache**:
- `supports_statement_cache = True` enables statement reuse
- Reduces IRIS query compilation overhead
- Bounded cache size (default: 500 statements)

### Memory Management

**Result Streaming**:
- Large result sets streamed asynchronously
- No blocking on large fetches
- Memory bounded by fetch buffer size

**Connection Cleanup**:
- Connections auto-closed on context exit
- Pool recycles connections after 1 hour (prevent stale connections)
- Graceful disposal on engine shutdown

---

## Testing Data Model

### Test Fixtures

**Engine Fixture**:
```python
@pytest_asyncio.fixture
async def async_engine():
    engine = create_async_engine("iris+psycopg://localhost:5432/USER")
    yield engine
    await engine.dispose()
```

**Session Fixture**:
```python
@pytest_asyncio.fixture
async def async_session(async_engine):
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        yield session
```

### Test Data

**Simple Table**:
```sql
CREATE TABLE async_test (
    id INTEGER GENERATED ALWAYS AS IDENTITY,
    name VARCHAR(50) NOT NULL
)
```

**Vector Table**:
```sql
CREATE TABLE async_vectors (
    id INTEGER PRIMARY KEY,
    embedding VECTOR(FLOAT, 128)
)
```

---

## Next Steps

**Data model documentation complete** ✅ - Proceed to contract definition in `contracts/async_dialect_interface.py`.
