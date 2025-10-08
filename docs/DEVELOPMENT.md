# Development Guide

## Optional Development Dependencies

### iris-devtools

The `iris-devtools` package provides helpful utilities for IRIS development:
- Connection helpers (DBAPI, JDBC)
- IRISConfig for configuration management
- Retry logic and connection managers
- Testing utilities

**Installation** (development only):

```bash
# Option 1: Install from local clone
pip install -e '.[dev]'

# Option 2: Install iris-devtools separately
pip install /path/to/iris-devtools

# Option 3: Use without installation (add to PYTHONPATH)
export PYTHONPATH=/path/to/iris-devtools:$PYTHONPATH
```

**Usage Example**:

```python
# Only available if iris-devtools is installed (development environments)
try:
    from iris_devtools.connections import create_dbapi_connection
    from iris_devtools.config import IRISConfig
    
    config = IRISConfig(host="localhost", port=1972)
    conn = create_dbapi_connection(config)
except ImportError:
    # iris-devtools not available - use alternative approach
    import iris.dbapi
    conn = iris.dbapi.connect(hostname="localhost", port=1972, namespace="USER")
```

**Why optional?**

- Not needed for production PGWire server (only uses `intersystems-irispython`)
- Only useful for development, testing, and benchmarking
- Keeps production dependencies minimal

## Async SQLAlchemy Status

**Sync SQLAlchemy**: ✅ Working via `iris+psycopg://` connection string

**Async SQLAlchemy**: ⚠️ Known limitation - psycopg async mode not compatible with SQLAlchemy's greenlet wrapper

For async database access, use raw `psycopg.AsyncConnection` directly:

```python
import psycopg

async with await psycopg.AsyncConnection.connect(
    "host=localhost port=5432 dbname=USER"
) as conn:
    result = await conn.execute("SELECT 1")
```

Future work: Investigate asyncpg-compatible wrapper or SQLAlchemy 2.0 async improvements.
