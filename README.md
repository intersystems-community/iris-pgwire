# IRIS PostgreSQL Wire Protocol Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)
[![InterSystems IRIS](https://img.shields.io/badge/IRIS-Compatible-green.svg)](https://www.intersystems.com/products/intersystems-iris/)

**Access IRIS through the entire PostgreSQL ecosystem** - Connect BI tools, Python frameworks, data pipelines, and thousands of PostgreSQL-compatible clients to InterSystems IRIS databases with zero code changes.

---

## 📊 Why This Matters

### The Ecosystem Advantage

Connect **any PostgreSQL-compatible tool** to InterSystems IRIS without custom drivers:

- **BI Tools**: Apache Superset, Metabase, Grafana - zero configuration needed
- **Python**: psycopg3, pandas, Jupyter notebooks, FastAPI applications
- **Data Engineering**: DBT, Apache Airflow, Kafka Connect (JDBC)
- **Programming Languages**: Python, Node.js, Go, Java, .NET, Ruby, Rust, PHP
- **pgvector Tools**: LangChain, LlamaIndex, and other RAG frameworks

**Connection String**: `postgresql://localhost:5432/USER` - that's it!

---

## 🚀 Quick Start

### Docker (Fastest - 60 seconds)

```bash
git clone https://github.com/isc-tdyar/iris-pgwire.git
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

Tested and verified with popular PostgreSQL clients:

| Language | Clients | Features |
|----------|---------|----------|
| **Python** | psycopg3, asyncpg, SQLAlchemy (sync + async), pandas | Full CRUD, transactions, async/await, vector ops |
| **Node.js** | pg (node-postgres), Prisma, Sequelize | Prepared statements, connection pooling, ORM support |
| **Java** | PostgreSQL JDBC, Spring Data JPA, Hibernate | Enterprise ORM, connection pooling, batch operations |
| **.NET** | Npgsql, Entity Framework Core, Dapper | Async operations, LINQ queries, ORM support |
| **Go** | pgx, lib/pq, GORM | High performance, connection pooling, migrations |
| **Ruby** | pg gem, ActiveRecord, Sequel | Rails integration, migrations, ORM support |
| **Rust** | tokio-postgres, sqlx, diesel | Async operations, compile-time query checking |
| **PHP** | PDO PostgreSQL, Laravel, Doctrine | Web framework integration, ORM support |
| **BI Tools** | Apache Superset, Metabase, Grafana | Zero-config PostgreSQL connection |

**Note**: InterSystems is developing an official `sqlalchemy-iris` package that will be available in the `intersystems-iris` PyPI package, providing native IRIS SQLAlchemy support alongside PGWire compatibility.

---

## 🎯 Key Features

### pgvector-Compatible Vector Operations

**Use Case**: You have a LangChain RAG application using PostgreSQL + pgvector. Now you want IRIS capabilities (healthcare FHIR, analytics, ObjectScript). Just change the connection string - your pgvector code works unchanged.

- **Drop-in Syntax**: Use familiar `<=>`, `<->`, `<#>` operators - auto-translated to IRIS
- **HNSW Indexes**: 5× speedup on 100K+ vector datasets
- **RAG-Ready**: Works with LangChain, LlamaIndex, and embedding models (1024D-4096D)

```python
# LangChain pgvector code - works with IRIS PGWire unchanged
from langchain_community.vectorstores import PGVector

vectorstore = PGVector(
    connection_string="postgresql://localhost:5432/USER",  # IRIS PGWire
    embedding_function=embeddings,
    collection_name="documents"
)
retriever = vectorstore.as_retriever()  # Semantic search over IRIS data
```

### Enterprise Authentication

Industry-standard security matching PgBouncer, YugabyteDB, Google Cloud PGAdapter:

- **OAuth 2.0**: Token-based authentication (cloud-native IAM)
- **IRIS Wallet**: Encrypted credential storage (zero plain-text passwords)
- **SCRAM-SHA-256**: Secure password authentication (industry best practice)

### Performance & Architecture

- **Minimal Overhead**: ~4ms protocol translation layer preserves IRIS native performance
- **Dual Backend**: External DBAPI (connection pooling) or Embedded Python (zero overhead)
- **Async Python**: Full async/await support with FastAPI and async SQLAlchemy
- **Connection Pooling**: 50+20 async connections, <1ms acquisition time

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

## 🔐 Authentication

**Industry-Standard Security** - No plain-text passwords, enterprise-grade protection matching PgBouncer, YugabyteDB, Google Cloud PGAdapter.

### Quick Start

```python
# Standard PostgreSQL connection (SCRAM-SHA-256 secure authentication)
import psycopg
conn = psycopg.connect("host=localhost port=5432 user=_SYSTEM password=SYS dbname=USER")
```

### Enterprise Options

**OAuth 2.0**: Token-based authentication for BI tools and applications (cloud-native IAM pattern)
**IRIS Wallet**: Encrypted credential storage with audit trail (zero plain-text passwords in code)
**SCRAM-SHA-256**: Industry best practice for password authentication (replaces deprecated MD5)

See [Authentication Guide](docs/DEPLOYMENT.md#authentication) for detailed configuration

---

## 📊 BI & Analytics Integration

### Zero-Configuration Setup

All BI tools connect using standard PostgreSQL drivers - no IRIS-specific plugins required:

**Connection Configuration**:
```yaml
Host:     localhost
Port:     5432
Database: USER
Username: _SYSTEM
Password: SYS
Driver:   PostgreSQL (standard)
```

### Supported BI Tools

#### Apache Superset
Modern data exploration and visualization platform.

```bash
docker-compose --profile bi-tools up superset
# Access: http://localhost:8088 (admin / admin)
```

**Try the Healthcare Demo**: Complete working example with 250 patient records and 400 lab results - see [Superset Healthcare Example](examples/superset-iris-healthcare/README.md) for <10 minute setup.

#### Metabase
User-friendly business intelligence tool with visual query builder.

```bash
docker-compose --profile bi-tools up metabase
# Access: http://localhost:3001
```

#### Grafana
Real-time monitoring and time-series visualization.

```bash
docker-compose up grafana
# Access: http://localhost:3000 (admin / admin)
```

### IRIS Vector Analytics in BI Tools

```sql
-- Semantic search directly in Superset/Metabase
SELECT id, title,
       VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,...]', DOUBLE)) AS similarity
FROM documents
ORDER BY similarity DESC
LIMIT 10
```

---

## 📊 Performance

### Benchmarked Results

**Protocol Translation Overhead**: ~4ms (preserves IRIS native performance)

| Metric | Result | Notes |
|--------|--------|-------|
| Simple Query Latency | 3.99ms avg, 4.29ms P95 | IRIS DBAPI baseline: 0.20ms |
| Vector Similarity (1024D) | 6.94ms avg, 8.05ms P95 | Binary parameter encoding |
| Binary Vector Encoding | 40% more compact | Efficient for high-dimensional embeddings |
| Connection Pool | 50+20 async connections | <1ms acquisition time |
| HNSW Index Speedup | 5.14× at 100K+ vectors | Requires ≥100K dataset |

**Key Findings**:
- ✅ ~4ms protocol overhead enables entire PostgreSQL ecosystem
- ✅ Binary parameter encoding (40% more compact than text)
- ✅ 100% success rate across all dimensions and execution paths

**Detailed Benchmarks**: See [benchmarks/README_4WAY.md](benchmarks/README_4WAY.md) and [Vector Parameter Binding](docs/VECTOR_PARAMETER_BINDING.md)

---

## 🏗️ Architecture

### High-Level Flow

```
PostgreSQL Client → PGWire Server (Port 5432) → IRIS Database
```

### Dual Backend Execution Paths

| Feature | DBAPI Backend | Embedded Python Backend |
|---------|---------------|-------------------------|
| **Deployment** | External Python process | Inside IRIS via `irispython` |
| **Connection** | TCP to IRIS:1972 | Direct in-process calls |
| **Latency** | +1-3ms network overhead | Near-zero overhead |
| **Best For** | Development, multi-IRIS | Production, max performance |

### Key Components

- **Protocol Layer**: PostgreSQL wire protocol v3 (message parsing, encoding)
- **Query Translation**: SQL rewriting, pgvector → IRIS vector functions
- **Connection Pooling**: Async pool with configurable limits (DBAPI backend)

**Detailed Architecture**: See [Dual-Path Architecture](docs/DUAL_PATH_ARCHITECTURE.md)

---


## 🔧 Installation

### Prerequisites

- **IRIS Database**: InterSystems IRIS 2024.1+ with vector support
- **Python**: 3.11+ (for development) or IRIS embedded Python
- **Docker** (optional): For containerized deployment

### Docker Deployment

```bash
# Clone repository
git clone https://github.com/isc-tdyar/iris-pgwire.git
cd iris-pgwire

# Start services
docker-compose up -d

# Verify services
docker-compose ps
```

**Ports**:
- `5432` - PGWire server (PostgreSQL protocol)
- `1972` - IRIS SuperServer
- `52773` - IRIS Management Portal

### Manual Installation

```bash
# Install dependencies
pip install iris-pgwire intersystems-irispython psycopg[binary]

# Or with uv (recommended)
uv pip install iris-pgwire intersystems-irispython psycopg[binary]

# Configure IRIS connection
export IRIS_HOST=localhost
export IRIS_PORT=1972
export IRIS_USERNAME=_SYSTEM
export IRIS_PASSWORD=SYS
export IRIS_NAMESPACE=USER

# Start server
python -m iris_pgwire.server
```

### Embedded Python Deployment (Production)

```bash
# From IRIS container/instance
export IRISUSERNAME=_SYSTEM
export IRISPASSWORD=SYS
export IRISNAMESPACE=USER
export BACKEND_TYPE=embedded

# Start embedded server
irispython -m iris_pgwire.server
```

**Benefits**: Zero network overhead, true VECTOR types, maximum performance

---

## 📚 Documentation

### Getting Started
- **[Installation Guide](docs/DEPLOYMENT.md)** - Detailed deployment instructions
- **[BI Tools Setup](examples/BI_TOOLS_SETUP.md)** - Superset, Metabase, Grafana integration
- **[Developer Guide](docs/developer_guide.md)** - Development setup and contribution

### Core Features
- **[Vector Parameter Binding](docs/VECTOR_PARAMETER_BINDING.md)** - High-dimensional vector support
- **[DBAPI Backend Guide](docs/DBAPI_BACKEND.md)** - Connection pooling configuration
- **[Testing Guide](docs/testing.md)** - Test framework and validation

### Architecture
- **[Dual-Path Architecture](docs/DUAL_PATH_ARCHITECTURE.md)** - DBAPI vs Embedded execution
- **[Embedded Python Servers](docs/EMBEDDED_PYTHON_SERVERS_HOWTO.md)** - Running inside IRIS
- **[Client Compatibility](docs/CLIENT_RECOMMENDATIONS.md)** - PostgreSQL client matrix

---

## ⚡ Production Ready

**171/171 tests passing** across 8 languages (Python, Node.js, Java, .NET, Go, Ruby, Rust, PHP)

### What Works

✅ **Core Protocol**: Simple queries, prepared statements, transactions, bulk operations (COPY)
✅ **Authentication**: OAuth 2.0, IRIS Wallet, SCRAM-SHA-256 (no plain-text passwords)
✅ **Vectors**: pgvector syntax (`<=>`, `<->`, `<#>`), HNSW indexes
✅ **Clients**: Full compatibility with PostgreSQL drivers and ORMs

### Architecture Decisions

**SSL/TLS**: Delegated to reverse proxy (nginx/HAProxy) - industry-standard pattern matching QuestDB, Tailscale pgproxy
**Kerberos**: Not implemented - matches PgBouncer, YugabyteDB, PGAdapter (use OAuth 2.0 instead)

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) for detailed deployment guidance and industry comparison

---

## 🧪 Testing

```bash
# All tests (contract + integration)
pytest -v

# Specific categories
pytest tests/contract/ -v         # Framework validation
pytest tests/integration/ -v      # E2E workflows

# Vector parameter binding tests
python3 tests/test_all_vector_sizes.py      # 128D-1024D validation
python3 tests/test_vector_limits.py         # Maximum dimension tests
```

### Performance Benchmarks

```bash
# 4-way architecture comparison
./benchmarks/run_4way_benchmark.sh

# Custom parameters
python3 benchmarks/4way_comparison.py \
    --iterations 100 \
    --dimensions 1024 \
    --output results.json
```

---

## 🤝 Contributing

```bash
# Clone repository
git clone https://github.com/isc-tdyar/iris-pgwire.git
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

- **Repository**: https://github.com/isc-tdyar/iris-pgwire
- **IRIS Documentation**: https://docs.intersystems.com/iris/
- **PostgreSQL Protocol**: https://www.postgresql.org/docs/current/protocol.html
- **pgvector**: https://github.com/pgvector/pgvector

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details

---

## 🎯 Roadmap

### ✅ Implemented (Production-Ready)
- PostgreSQL wire protocol v3 (handshake, simple & extended query protocols)
- Authentication (SCRAM-SHA-256, OAuth 2.0, IRIS Wallet)
- Vector operations (pgvector syntax, HNSW indexes)
- COPY protocol (bulk import/export with CSV format, 600+ rows/sec)
- Transactions (BEGIN/COMMIT/ROLLBACK with savepoints)
- Async SQLAlchemy support (FastAPI integration, connection pooling)
- Dual backend architecture (DBAPI + Embedded Python)
- Multi-language client compatibility (8 drivers at 100%: Python, Node.js, Java, .NET, Go, Ruby, Rust, PHP)

### 🚧 Known Limitations

**Note**: These limitations are common across PostgreSQL wire protocol implementations. For example, PgBouncer (the most widely deployed connection pooler) also omits GSSAPI support, and QuestDB explicitly does not support SSL/TLS.

- **SSL/TLS wire protocol**: Not implemented - use reverse proxy (nginx/HAProxy) for transport encryption (industry-standard approach)
- **Kerberos/GSSAPI**: Not implemented - use OAuth 2.0 or IRIS Wallet authentication instead (matches PgBouncer, YugabyteDB, PGAdapter)
- **L2 distance operator** (`<->`): Not supported by IRIS - use cosine (`<=>`) or dot product (`<#>`) instead

### 📋 Future Enhancements
- SSL/TLS wire protocol encryption
- Kerberos/GSSAPI authentication
- Connection limits & rate limiting
- Performance optimization (executemany() for bulk operations)
- Advanced PostgreSQL features (CTEs, window functions)

---

**Questions?** File an issue on [GitHub](https://github.com/isc-tdyar/iris-pgwire/issues)
