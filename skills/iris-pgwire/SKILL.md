# iris-pgwire Skill

## What it is

iris-pgwire is a PostgreSQL wire protocol server for InterSystems IRIS. It lets
any PostgreSQL-compatible client (psycopg3, asyncpg, pgx, Npgsql, node-postgres,
JDBC, Prisma, SQLAlchemy, BI tools) connect to IRIS without IRIS-specific drivers.

The server translates PostgreSQL SQL syntax to IRIS SQL in-flight, handles
authentication (SCRAM-SHA-256, OAuth 2.0, IRIS Wallet), and supports parameterized
queries, COPY bulk load, and pgvector operators.

## When to Use

Use iris-pgwire when:

- Client requires a `postgresql://` connection string
- Tooling uses pgvector operators (`<=>`, `<#>`, `<->`)
- Standard connection poolers are in the stack (PgBouncer, pgpool-II)
- BI tools connect via standard PostgreSQL driver
- ORM migration tooling (Prisma, Alembic, Flyway) needs DDL compatibility

Skip iris-pgwire when the client can connect to IRIS natively via IRIS DBAPI, JDBC,
or ODBC — those paths have lower latency and no translation layer.

## Connection String Format

```text
postgresql://<username>:<password>@<host>:<port>/<namespace>
```

Default dev setup:

```text
postgresql://_SYSTEM:SYS@localhost:5432/USER
```

psycopg3 example:

```python
import psycopg

conn = psycopg.connect(
    "host=localhost port=5432 dbname=USER user=_SYSTEM password=SYS"
)
```

asyncpg example:

```python
import asyncpg

conn = await asyncpg.connect(
    "postgresql://_SYSTEM:SYS@localhost:5432/USER"
)
```

SQLAlchemy async:

```python
from sqlalchemy.ext.asyncio import create_async_engine
engine = create_async_engine("postgresql+psycopg://_SYSTEM:SYS@localhost:5432/USER")
```

## Parameter Style

iris-pgwire uses **PostgreSQL positional parameters** (`$1`, `$2`, …) in the wire
protocol. Internally, these are translated to IRIS DBAPI `?` placeholders before
execution.

```python
# psycopg3 — use %s (pyformat); driver converts to $N on the wire
cur.execute("SELECT * FROM MyTable WHERE id = %s AND name = %s", (42, "Alice"))

# asyncpg — use $1, $2 directly
await conn.fetch("SELECT * FROM MyTable WHERE id = $1", 42)
```

Type mapping (PostgreSQL → IRIS):

| PostgreSQL type | IRIS type        | Notes                              |
| --------------- | ---------------- | ---------------------------------- |
| `integer`       | `INTEGER`        |                                    |
| `bigint`        | `BIGINT`         |                                    |
| `float8`        | `DOUBLE`         |                                    |
| `text`          | `VARCHAR`        |                                    |
| `boolean`       | `BIT`            | `TRUE`/`FALSE` → `1`/`0`           |
| `date`          | `DATE`           | ISO format rewritten to ODBC `{d}` |
| `timestamp`     | `TIMESTAMP`      |                                    |
| `vector`        | `VECTOR(DOUBLE)` | Dimension required                 |
| `jsonb`         | `VARCHAR` (JSON) | `->` / `->>` → `JSON_EXTRACT()`    |

## SQL Translation Differences from PostgreSQL

### What is auto-translated

- `pg_catalog.*` → `INFORMATION_SCHEMA` equivalents
- `RETURNING` clause → emulated via identity query after INSERT/UPDATE
- `ON CONFLICT DO NOTHING` → wrapped try/catch
- Boolean literals (`TRUE`, `FALSE`) → `1`, `0`
- `public.` schema prefix → `SQLUser.`
- pgvector operators (`<=>`, `<#>`, `<->`) → `VECTOR_COSINE()`, `VECTOR_DOT_PRODUCT()`, `VECTOR_L2()`
- JSON operators (`->`, `->>`) → `JSON_EXTRACT()`
- `HNSW` index DDL → IRIS `%VECTOR_HNSW_INDEX`
- `CREATE TABLE IF NOT EXISTS` → intercept error, skip gracefully
- Trailing semicolons → stripped

### Known gaps / limitations

- **RETURNING with complex expressions** — emulation may not cover all cases
- **Kerberos/GSSAPI auth** — wired but deferred; OAuth 2.0 is the recommended
  enterprise auth path
- **No pg_catalog tables** — only `INFORMATION_SCHEMA` exists in IRIS; ORM
  introspection that hits `pg_catalog` directly may fail even after translation
- **COPY throughput** — ~600 rows/sec on DBAPI path; executemany() path
  theoretically ~4× faster but not yet wired
- **Community Edition limit** — 5-user connection limit; use `PGWIRE_POOL_SIZE=1`
  for dev against Community IRIS
- **No native SSL termination** — put nginx/HAProxy in front for TLS
- **DDL**: `ALTER TABLE ADD COLUMN` on existing columns → IRIS error (not silently
  skipped); `DROP TABLE` must be one table per statement

## Common Integration Test Patterns

### Attach to container (never hardcode ports)

```python
from iris_devtester import IRISContainer

@pytest.fixture
def iris_conn():
    container = IRISContainer.attach("iris-pgwire-db")
    conn = psycopg.connect(
        host=container.host,
        port=5432,          # pgwire port, not IRIS DBAPI port
        dbname="USER",
        user="_SYSTEM",
        password="SYS",
    )
    yield conn
    conn.close()
```

### Skip when container is unavailable

```python
import pytest
from iris_devtester import IRISContainer

@pytest.fixture(scope="session")
def iris_available():
    try:
        IRISContainer.attach("iris-pgwire-db")
        return True
    except Exception:
        return False

@pytest.mark.integration
def test_basic_query(iris_available, iris_conn):
    if not iris_available:
        pytest.skip("iris-pgwire-db not running")
    ...
```

### Pure translation tests (no IRIS required)

```python
from iris_pgwire.vector_optimizer import VectorQueryOptimizer

def test_pg_catalog_rewrite():
    opt = VectorQueryOptimizer()
    result = opt.translate("SELECT * FROM pg_catalog.pg_tables")
    assert "INFORMATION_SCHEMA" in result
    assert "pg_catalog" not in result
```

## Transaction Semantics

- `BEGIN` → `START TRANSACTION` (translated before SQL normalization)
- `COMMIT`, `ROLLBACK` → passed through as-is
- Autocommit is on by default; clients that call `BEGIN` explicitly get a
  transaction block
- Savepoints are not translated — avoid them

## Environment Variables

| Variable           | Default     | Purpose                                           |
| ------------------ | ----------- | ------------------------------------------------- |
| `IRIS_HOST`        | `localhost` | IRIS DBAPI host                                   |
| `IRIS_PORT`        | `1972`      | IRIS DBAPI port                                   |
| `IRIS_USERNAME`    | `_SYSTEM`   | IRIS username                                     |
| `IRIS_PASSWORD`    | `SYS`       | IRIS password                                     |
| `IRIS_NAMESPACE`   | `USER`      | IRIS namespace                                    |
| `IRIS_BACKEND`     | `embedded`  | `embedded` or `dbapi`                             |
| `PGWIRE_POOL_SIZE` | `5`         | Connection pool size (use `1` for Community)      |
| `PGWIRE_LOG_LEVEL` | `INFO`      | `DEBUG` or `TRACE` for translation/packet logging |

## Gotchas

1. **Bytecode caching** — `.pyc` files persist across Docker container restarts.
   Always delete before testing a fix:
   `docker exec iris-pgwire bash -c 'find /app/src -name "*.pyc" -delete'`

2. **Container name** — The IRIS container for this project is `iris-pgwire-db`
   (IRIS DBAPI on host port 2972). Do not confuse with the `iris-pgwire` service
   container (the Python server itself).

3. **Port 5432 vs 2972** — psycopg3/pgwire clients connect to port `5432`
   (inside the iris-pgwire service). Direct IRIS DBAPI connections use port `2972`
   (host-mapped from the iris-pgwire-db container).

4. **`iris_pgwire` vs `intersystems_iris`** — The PyPI package name is
   `iris-pgwire`; it depends on `intersystems-irispython` (not `iris` standalone).

5. **`IRISContainer.attach("iris-pgwire")` in older tests** — The correct name is
   `"iris-pgwire-db"`. Tests using the old name will fail port resolution.
