# Features Overview: IRIS PGWire

**Last Updated**: 2025-12-27
**Related**: [Vector Operations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md), [PG Catalog](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md), [Authentication](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md#authentication)

---

## Overview

IRIS PGWire provides four major feature categories that enable InterSystems IRIS to integrate seamlessly with the PostgreSQL ecosystem.

---

## pgvector-Compatible Vector Operations

**Use Case**: Your existing pgvector similarity search code works with IRIS - just change the connection string.

### Key Capabilities

- **Drop-in Syntax**: Use familiar `<=>` operator - auto-translated to IRIS VECTOR_COSINE
- **HNSW Indexes**: 5× speedup on 100K+ vector datasets
- **RAG-Ready**: Compatible with LangChain, LlamaIndex embedding pipelines (1024D-4096D)
- **Binary Parameter Encoding**: 40% more compact than text for high-dimensional vectors

### Example

```python
# pgvector syntax works unchanged with IRIS PGWire
import psycopg

with psycopg.connect("host=localhost port=5432 dbname=USER") as conn:
    with conn.cursor() as cur:
        # Similarity search with pgvector <=> operator
        cur.execute(
            "SELECT id, content FROM documents ORDER BY embedding <=> %s LIMIT 5",
            (query_embedding,)  # Python list - auto-converted
        )
        results = cur.fetchall()
```

### Supported Vector Operations

| Operation | PostgreSQL Syntax | IRIS Translation | Status |
|-----------|-------------------|------------------|--------|
| Cosine similarity | `<=>` | `VECTOR_COSINE()` | ✅ Supported |
| Dot product | `<#>` | `VECTOR_DOT_PRODUCT()` | ✅ Supported |
| L2/Euclidean distance | `<->` | - | ❌ Not implemented |

### Performance

- **Query overhead**: ~4ms protocol translation
- **Vector dimensions**: 128D-4096D tested
- **HNSW indexes**: 5.14× speedup on 100K+ vectors
- **Binary encoding**: 40% more compact than text format

**Learn More**: [Vector Parameter Binding Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md)

---

## ORM & Schema Compatibility

**Use Case**: Run Prisma, SQLAlchemy, Drizzle, Sequelize, Hibernate, and other ORMs against IRIS without configuration.

### Schema Mapping

PostgreSQL ORMs expect tables in the `public` schema, but IRIS uses `SQLUser`. PGWire automatically maps between them:

```python
# Prisma/SQLAlchemy queries work unchanged
# "SELECT * FROM public.users" → executes against SQLUser.users
# Results show table_schema='public' for ORM compatibility

import psycopg
with psycopg.connect("host=localhost port=5432 dbname=USER") as conn:
    # This query returns IRIS SQLUser tables as 'public' schema
    cur = conn.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
    """)
    tables = cur.fetchall()  # Your IRIS tables!
```

### Configuration

**Default**: Maps PostgreSQL `public` schema to IRIS `SQLUser` schema.

**Custom schema** (optional):
```bash
# For non-standard IRIS schema names
export PGWIRE_IRIS_SCHEMA=MyAppSchema
```

```python
# Or configure programmatically
from iris_pgwire.schema_mapper import configure_schema
configure_schema(iris_schema="MyAppSchema")
```

### pg_catalog Support

IRIS PGWire emulates **6 core PostgreSQL catalog tables** and **5 catalog functions** to enable ORM introspection:

**Catalog Tables**:
- `pg_class` - Table/view catalog
- `pg_attribute` - Column catalog
- `pg_constraint` - Constraint catalog (PK, FK, unique, check)
- `pg_index` - Index catalog
- `pg_namespace` - Schema catalog
- `pg_attrdef` - Default value catalog

**Catalog Functions**:
- `format_type()` - Type name formatting
- `pg_get_constraintdef()` - Constraint SQL
- `pg_get_serial_sequence()` - Sequence lookup (returns NULL for IRIS)
- `pg_get_viewdef()` - View definition (returns NULL for security)
- `pg_get_indexdef()` - Index DDL

**Learn More**: [PG_CATALOG Documentation](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md)

### Supported ORMs

| ORM | Language | Introspection | Migrations | CRUD | Notes |
|-----|----------|---------------|------------|------|-------|
| **Prisma** | Node.js/TypeScript | ✅ `prisma db pull` | ✅ `prisma migrate` | ✅ Full | Enums → VARCHAR |
| **SQLAlchemy** | Python | ✅ `autoload_with` | ✅ Alembic | ✅ Full | Async supported |
| **Drizzle** | Node.js/TypeScript | ✅ `drizzle-kit introspect` | ✅ `drizzle-kit push` | ✅ Full | Serial → identity |
| **Sequelize** | Node.js | ✅ Sync | ✅ Migrations | ✅ Full | Explicit FK config |
| **Hibernate** | Java | ✅ Schema validation | ✅ Auto-DDL | ✅ Full | Use IDENTITY strategy |
| **GORM** | Go | ✅ Auto-migrate | ✅ Migrations | ✅ Full | Standard PostgreSQL driver |
| **Entity Framework** | .NET | ✅ Scaffold-DbContext | ✅ Migrations | ✅ Full | Npgsql provider |
| **ActiveRecord** | Ruby | ✅ Schema dump | ✅ Migrations | ✅ Full | pg gem |

---

## Enterprise Authentication

**Industry-standard security** matching PgBouncer, YugabyteDB, Google Cloud PGAdapter - no plain-text passwords, enterprise-grade protection.

### Supported Methods

#### 1. SCRAM-SHA-256 (Recommended)
Industry best practice for password authentication - replaces deprecated MD5.

```python
import psycopg
conn = psycopg.connect(
    "host=localhost port=5432 user=_SYSTEM password=SYS dbname=USER"
)
```

**Security**: Passwords never transmitted in plain text, salted hashing, replay attack protection.

#### 2. OAuth 2.0
Token-based authentication for BI tools and applications - cloud-native IAM pattern.

**Use Case**: Enterprise SSO, temporary access tokens, audit trail.

#### 3. IRIS Wallet
Encrypted credential storage with audit trail - zero plain-text passwords in code.

**Use Case**: Production deployments, credential rotation, compliance.

**Learn More**: [Authentication Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md#authentication)

---

## Performance & Architecture

### Minimal Protocol Overhead

- **~4ms translation layer**: Preserves IRIS native performance
- **Binary parameter encoding**: Efficient for vectors and bulk data
- **100% success rate**: All dimensions and execution paths tested

### Dual Backend Architecture

| Feature | DBAPI Backend | Embedded Python Backend |
|---------|---------------|-------------------------|
| **Deployment** | External Python process | Inside IRIS via `irispython` |
| **Connection** | TCP to IRIS:1972 | Direct in-process calls |
| **Latency** | +1-3ms network overhead | Near-zero overhead |
| **Connection Pooling** | ✅ 50+20 async pool | ❌ Not applicable |
| **Best For** | Development, multi-IRIS | Production, max performance |

### Async Python Support

Full async/await support for modern Python frameworks:

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from fastapi import FastAPI, Depends

# Async SQLAlchemy with FastAPI
engine = create_async_engine("postgresql+psycopg://localhost:5432/USER")
SessionLocal = async_sessionmaker(engine, class_=AsyncSession)

@app.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM users WHERE id = :id"),
        {"id": user_id}
    )
    return result.fetchone()
```

### Connection Pooling

**DBAPI Backend**:
- **Max connections**: 50 concurrent + 20 overflow
- **Acquisition time**: <1ms average
- **Pool strategy**: QueuePool with pre-ping health checks
- **Timeout handling**: Configurable connection timeout

**Learn More**: [DBAPI Backend Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DBAPI_BACKEND.md)

---

## Client Compatibility

IRIS PGWire works with **any PostgreSQL-compatible client** - no custom drivers required.

### Programming Languages

| Language | Clients | Features | Tests |
|----------|---------|----------|-------|
| **Python** | psycopg3, asyncpg, SQLAlchemy, pandas | Async/await, ORM, vector ops | ✅ 100% |
| **Node.js** | pg, Prisma, Sequelize | Promises, ORM introspection | ✅ 100% |
| **Java** | PostgreSQL JDBC, Spring Data, Hibernate | Connection pooling, ORM | ✅ 100% |
| **.NET** | Npgsql, Entity Framework Core, Dapper | Async, LINQ, ORM | ✅ 100% |
| **Go** | pgx, lib/pq, GORM | High performance, migrations | ✅ 100% |
| **Ruby** | pg gem, ActiveRecord, Sequel | Rails integration, ORM | ✅ 100% |
| **Rust** | tokio-postgres, sqlx, diesel | Async, compile-time checking | ✅ 100% |
| **PHP** | PDO PostgreSQL, Laravel, Doctrine | Web frameworks, ORM | ✅ 100% |

### BI Tools

Zero-configuration setup - all tools connect using standard PostgreSQL drivers:

- **Apache Superset** - Modern data exploration and visualization
- **Metabase** - User-friendly business intelligence with visual query builder
- **Grafana** - Real-time monitoring and time-series visualization
- **Tableau** - Enterprise analytics (PostgreSQL connector)
- **Power BI** - Microsoft business analytics (PostgreSQL connector)

**Learn More**: [BI Tools Setup](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/BI_TOOLS_SETUP.md)

---

## See Also

- [Vector Parameter Binding](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md) - High-dimensional vector support
- [PG_CATALOG Documentation](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md) - ORM introspection details
- [Authentication Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md#authentication) - Enterprise security setup
- [Architecture Overview](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ARCHITECTURE.md) - System design
- [Client Recommendations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/CLIENT_RECOMMENDATIONS.md) - Client compatibility matrix
