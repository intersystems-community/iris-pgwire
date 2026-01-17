# iris-pgwire: PostgreSQL Wire Protocol for InterSystems IRIS

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)
[![InterSystems IRIS](https://img.shields.io/badge/IRIS-Compatible-green.svg)](https://www.intersystems.com/products/intersystems-iris/)

**Access IRIS through the entire PostgreSQL ecosystem** - Connect BI tools, Python frameworks, data pipelines, and thousands of PostgreSQL-compatible clients to InterSystems IRIS databases with zero code changes.

---

## 📊 Why This Matters

**Verified compatibility** with PostgreSQL clients across 8 languages - no IRIS-specific drivers needed:

- **Tested & Working**: Python (psycopg3, asyncpg), Node.js (pg), Java (JDBC), .NET (Npgsql), Go (pgx), Ruby (pg gem), Rust (tokio-postgres), PHP (PDO)
- **BI Tools**: Apache Superset, Metabase, Grafana (use standard PostgreSQL driver)
- **ORMs**: SQLAlchemy, Prisma, Sequelize, Hibernate, Drizzle

**Connection**: `postgresql://localhost:5432/USER` - that's it!

---

## 🚀 Quick Start

### Docker (Fastest - 60 seconds)

```bash
git clone https://github.com/intersystems-community/iris-pgwire.git
cd iris-pgwire
docker-compose up -d

# Test it works
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Hello from IRIS!'"
```

### Python Package

```bash
pip install iris-pgwire psycopg[binary]

# Configure IRIS connection
export IRIS_HOST=localhost IRIS_PORT=1972 IRIS_USERNAME=_SYSTEM IRIS_PASSWORD=SYS IRIS_NAMESPACE=USER

# Start server
python -m iris_pgwire.server
```

### ZPM Installation (Existing IRIS)

For InterSystems IRIS 2024.1+ with ZPM package manager:

```objectscript
// Install the package
zpm "install iris-pgwire"

// Start the server manually
do ##class(IrisPGWire.Service).Start()

// Check server status
do ##class(IrisPGWire.Service).ShowStatus()
```

**From terminal**:
```bash
# Install
iris session IRIS -U USER 'zpm "install iris-pgwire"'

# Start server
iris session IRIS -U USER 'do ##class(IrisPGWire.Service).Start()'
```

### First Query

```python
import psycopg

with psycopg.connect('host=localhost port=5432 dbname=USER') as conn:
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM YourTable')
    print(f'Rows: {cur.fetchone()[0]}')
```

---

## ✅ Client Compatibility

**171/171 tests passing** across 8 programming languages:

| Language | Verified Clients | Test Coverage |
|----------|------------------|---------------|
| **Python** | psycopg3, asyncpg, SQLAlchemy | 100% (21 tests) |
| **Node.js** | pg (node-postgres) | 100% (17 tests) |
| **Java** | PostgreSQL JDBC | 100% (27 tests) |
| **.NET** | Npgsql | 100% (15 tests) |
| **Go** | pgx v5 | 100% (19 tests) |
| **Ruby** | pg gem | 100% (25 tests) |
| **Rust** | tokio-postgres | 100% (22 tests) |
| **PHP** | PDO PostgreSQL | 100% (25 tests) |

**ORMs & BI Tools**: Prisma, Sequelize, Hibernate, Drizzle, Apache Superset, Metabase, Grafana

See [Client Compatibility Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/CLIENT_RECOMMENDATIONS.md) for detailed testing results and ORM setup examples.

---

## 🎯 Key Features

- **pgvector Syntax**: Use familiar `<=>` and `<#>` operators - auto-translated to IRIS VECTOR_COSINE/DOT_PRODUCT. HNSW indexes provide 5× speedup on 100K+ vectors. See [Vector Operations Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md)

- **ORM & DDL Compatibility**: Automatic `public` ↔ `SQLUser` schema mapping and PostgreSQL DDL transformations (stripping `fillfactor`, `GENERATED` columns, `USING btree`, etc.) for seamless migrations. See [DDL Compatibility Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DDL_COMPATIBILITY.md)

- **Enterprise Security**: SCRAM-SHA-256, OAuth 2.0, IRIS Wallet authentication. Industry-standard security matching PgBouncer, YugabyteDB. See [Deployment Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md)

- **Performance**: ~4ms protocol overhead, dual backend (DBAPI/Embedded), async SQLAlchemy support. See [Performance Benchmarks](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PERFORMANCE.md)

---

## 💻 Usage Examples

### Command-Line (psql)

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

### Python (psycopg3)

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

### Async SQLAlchemy with FastAPI

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

## 📚 Documentation Index

**📖 [Complete Documentation →](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/README.md)** - Full navigation hub with all guides, architecture docs, and troubleshooting

### Getting Started
- **[Installation Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/INSTALLATION.md)** - Docker, PyPI, ZPM, Embedded Python deployment
- **[Quick Start Examples](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/QUICKSTART_EXAMPLES.md)** - First queries with psql, Python, FastAPI
- **[BI Tools Setup](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/BI_TOOLS.md)** - Superset, Metabase, Grafana integration

### Features & Capabilities
- **[Features Overview](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/FEATURES_OVERVIEW.md)** - pgvector, ORM compatibility, DDL transformations, authentication
- **[DDL Compatibility](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DDL_COMPATIBILITY.md)** - Automatic handling of PostgreSQL-specific DDL (fillfactor, generated columns, enums)
- **[pg_catalog Support](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md)** - 6 catalog tables + 5 functions for ORM introspection
- **[Vector Operations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md)** - High-dimensional vectors, parameter binding
- **[Client Compatibility](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/CLIENT_RECOMMENDATIONS.md)** - 171 tests across 8 languages

### Architecture & Performance
- **[Architecture Overview](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ARCHITECTURE.md)** - System design, dual backend, components
- **[Performance Benchmarks](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PERFORMANCE.md)** - ~4ms overhead, HNSW indexes
- **[Deployment Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md)** - Production setup, authentication, SSL/TLS

### Development & Reference
- **[Roadmap & Limitations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ROADMAP.md)** - Current status, future enhancements
- **[Developer Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/developer_guide.md)** - Development setup, contribution guidelines
- **[Testing Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/testing.md)** - Test framework, validation

---

## ⚡ Production Ready

**171/171 tests passing** - Verified compatibility with Python, Node.js, Java, .NET, Go, Ruby, Rust, PHP PostgreSQL clients

**What Works**: Core protocol (queries, transactions, COPY), Enterprise auth (SCRAM-SHA-256, OAuth 2.0), pgvector operators, ORM introspection

**Architecture**: SSL/TLS via reverse proxy (nginx/HAProxy), OAuth 2.0 instead of Kerberos - industry patterns matching PgBouncer, YugabyteDB

See [Roadmap & Limitations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ROADMAP.md) for details

---

## 🤝 Contributing

```bash
# Clone repository
git clone https://github.com/intersystems-community/iris-pgwire.git
cd iris-pgwire

# Install development dependencies
uv sync --frozen

# Start development environment
docker-compose up -d

# Run tests
pytest -v
```

**Code Quality**: black (formatter), ruff (linter), pytest (testing)

---

## 🔗 Links

- **Repository**: https://github.com/intersystems-community/iris-pgwire
- **IRIS Documentation**: https://docs.intersystems.com/iris/
- **PostgreSQL Protocol**: https://www.postgresql.org/docs/current/protocol.html
- **pgvector**: https://github.com/pgvector/pgvector

---

## 📄 License

MIT License - See [LICENSE](https://github.com/intersystems-community/iris-pgwire/blob/main/LICENSE) for details

---

**Questions?** Open an issue on [GitHub](https://github.com/intersystems-community/iris-pgwire/issues)
