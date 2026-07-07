# iris-pgwire

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Coverage: 92%](https://img.shields.io/badge/coverage-92%25-brightgreen.svg)](https://github.com/intersystems-community/iris-pgwire)

PostgreSQL wire protocol server for InterSystems IRIS. Connects BI tools, Python frameworks, data pipelines, and any PostgreSQL-compatible client to IRIS databases — no IRIS-specific drivers needed.

**Connection string**: `postgresql://user:pass@localhost:5432/USER`

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/intersystems-community/iris-pgwire.git
cd iris-pgwire
docker compose up -d

# Test it (PGWire runs on port 5432 inside the IRIS container)
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Hello from IRIS!'"
```

### Python package

```bash
pip install iris-pgwire psycopg[binary]

export IRIS_HOST=localhost IRIS_PORT=1972 \
       IRIS_USERNAME=_SYSTEM IRIS_PASSWORD=SYS IRIS_NAMESPACE=USER

python -m iris_pgwire.server
```

### First query

```python
import psycopg

with psycopg.connect("host=localhost port=5432 dbname=USER user=_SYSTEM password=SYS") as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM MyTable")
        print(cur.fetchone()[0])
```

---

## Verified Client Compatibility

Tested against real IRIS instances via the wire protocol:

| Language | Clients                                      |
| -------- | -------------------------------------------- |
| Python   | psycopg3, asyncpg, SQLAlchemy (sync + async) |
| Node.js  | pg (node-postgres)                           |
| Java     | PostgreSQL JDBC                              |
| .NET     | Npgsql                                       |
| Go       | pgx v5                                       |
| Ruby     | pg gem                                       |
| Rust     | tokio-postgres                               |
| PHP      | PDO PostgreSQL                               |

**ORMs**: SQLAlchemy, Prisma, Drizzle, Sequelize, Hibernate  
**BI tools**: Apache Superset, Metabase, Grafana (standard PostgreSQL driver)

See [Client Compatibility Guide](docs/CLIENT_RECOMMENDATIONS.md) for setup examples.

---

## Key Features

**pgvector operators** — `<=>` (cosine), `<#>` (dot product), `<->` (L2) auto-translate to IRIS `VECTOR_COSINE`/`VECTOR_DOT_PRODUCT`. HNSW indexes give 5× speedup at 100K+ vectors. See [Vector Operations](docs/VECTOR_PARAMETER_BINDING.md).

**DDL compatibility** — Automatic `public` ↔ `SQLUser` schema mapping; strips `fillfactor`, `GENERATED` columns, `USING btree`, `IF NOT EXISTS` guards, and other PostgreSQL-specific DDL so ORM migrations run cleanly. See [DDL Compatibility](docs/DDL_COMPATIBILITY.md).

**SQL translation** — `RETURNING` emulation, `ON CONFLICT`, boolean literals, `pg_catalog` → `INFORMATION_SCHEMA` rewrites, JSON operators (`->` / `->>` → `JSON_EXTRACT`), parameterized queries.

**Authentication** — SCRAM-SHA-256, OAuth 2.0 (RFC 6749), IRIS Wallet credentials.

**Dual backend** — Embedded Python (irispython, lowest latency) or external DBAPI (standard TCP connection). Selectable via `IRIS_BACKEND` env var.

**COPY protocol** — Bulk load via `COPY … FROM STDIN` (~600 rows/sec on DBAPI path).

---

## Usage Examples

### Parameterized queries (psycopg3)

```python
import psycopg

with psycopg.connect("host=localhost port=5432 dbname=USER user=_SYSTEM password=SYS") as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM MyTable WHERE id = %s", (42,))
        row = cur.fetchone()
```

### Vector similarity search

```python
query_vector = [0.1, 0.2, 0.3]
with conn.cursor() as cur:
    cur.execute("""
        SELECT id, embedding <=> %s::vector AS score
        FROM vectors
        ORDER BY score
        LIMIT 5
    """, (query_vector,))
    results = cur.fetchall()
```

### Async SQLAlchemy

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text

engine = create_async_engine("postgresql+psycopg://localhost:5432/USER")
SessionLocal = async_sessionmaker(engine, class_=AsyncSession)

async def query():
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT * FROM MyTable"))
        return result.fetchall()
```

### COPY bulk load

```python
with conn.cursor() as cur:
    with cur.copy("COPY MyTable (col1, col2) FROM STDIN") as copy:
        for row in data:
            copy.write_row(row)
```

---

## Documentation

| Guide                                                  | Description                                |
| ------------------------------------------------------ | ------------------------------------------ |
| [Installation](docs/INSTALLATION.md)                   | Docker, PyPI, Embedded Python deployment   |
| [Architecture](docs/ARCHITECTURE.md)                   | System design, dual backend, request flow  |
| [DDL Compatibility](docs/DDL_COMPATIBILITY.md)         | PostgreSQL DDL transformations             |
| [Vector Operations](docs/VECTOR_PARAMETER_BINDING.md)  | pgvector syntax, HNSW indexes              |
| [Client Compatibility](docs/CLIENT_RECOMMENDATIONS.md) | Per-language setup and caveats             |
| [Deployment](docs/DEPLOYMENT.md)                       | Production setup, SSL/TLS, auth            |
| [Performance](docs/PERFORMANCE.md)                     | Benchmarks, tuning                         |
| [Developer Guide](docs/developer_guide.md)             | Development setup, contribution guidelines |

---

## Development

```bash
# Install dependencies
uv sync --frozen

# Run unit + contract tests (no IRIS needed)
pytest tests/unit/ tests/contract/ -v

# Run with live IRIS (container must be up)
docker compose up -d
PGWIRE_BACKEND_TYPE=dbapi PGWIRE_POOL_SIZE=1 pytest tests/ -v

# Code quality check
python -m iris_pgwire.quality
```

**Test coverage**: 92% (5349 tests)  
**Code quality**: black (formatter), ruff (linter), bandit (security)

---

## Known Limitations

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) for the full list. Key items:

- IRIS Community Edition: 5-user connection limit — use `PGWIRE_POOL_SIZE=1` for dev
- No native SSL termination — use nginx/HAProxy in front for TLS
- Kerberos/GSSAPI auth wiring deferred (OAuth 2.0 is the recommended enterprise auth)
- `INFORMATION_SCHEMA` only, no `pg_catalog` tables (translated automatically)

---

## Contributing

```bash
git clone https://github.com/intersystems-community/iris-pgwire.git
cd iris-pgwire
uv sync --frozen
docker compose up -d
pytest tests/unit/ tests/contract/ -v
```

Open an issue or PR on [GitHub](https://github.com/intersystems-community/iris-pgwire/issues).

---

## Links

- [InterSystems IRIS](https://www.intersystems.com/products/intersystems-iris/)
- [IRIS Documentation](https://docs.intersystems.com/iris/)
- [PostgreSQL Protocol Spec](https://www.postgresql.org/docs/current/protocol.html)
- [pgvector](https://github.com/pgvector/pgvector)

---

MIT License — see [LICENSE](LICENSE)
