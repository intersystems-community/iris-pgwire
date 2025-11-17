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

### Vector Operations (Up to 188K Dimensions!)

- **Massive Scale**: Support for vectors up to **188,962 dimensions** (1.44 MB)
- **pgvector Syntax**: Use familiar `<=>`, `<->`, `<#>` operators - auto-translated to IRIS functions
- **HNSW Indexes**: 5× speedup on 100K+ vector datasets
- **RAG Integration**: Works with LangChain, LlamaIndex, and other pgvector-based tools

```python
# pgvector syntax - works transparently
cur.execute("""
    SELECT id, embedding <=> %s AS distance
    FROM vectors
    ORDER BY distance
    LIMIT 5
""", (query_vector,))
```

### Enterprise Authentication

**Industry-Standard Security** (matches PgBouncer, YugabyteDB, PGAdapter approach):

- **OAuth 2.0**: Token-based authentication for BI tools and API integrations (cloud-native IAM pattern)
- **IRIS Wallet**: Encrypted credential storage with audit trail (no plain-text passwords)
- **SCRAM-SHA-256**: Secure password authentication (industry best practice, replaces deprecated MD5)
- **Password Fallback**: 100% backward compatible with standard password authentication

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
    query_vector = [0.1, 0.2, 0.3]  # Up to 188,962D supported
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

**Production-Ready Security**: IRIS PGWire implements authentication patterns matching industry leaders (PgBouncer, YugabyteDB, Google Cloud PGAdapter). No plain-text passwords, enterprise-grade credential protection.

### OAuth 2.0 Token Authentication

**Use Case**: BI tools, data science notebooks, API integrations

```bash
# Environment configuration
export OAUTH_CLIENT_ID=pgwire-server
export OAUTH_CLIENT_SECRET=your-secret-here

# Clients connect normally - OAuth happens transparently
psql -h localhost -p 5432 -U john.doe -d USER
# Password is exchanged for OAuth token automatically
# Token cached in session (5-minute TTL) - no re-authentication
```

### IRIS Wallet Integration

**Use Case**: Zero plain-text passwords, encrypted credential storage, audit compliance

```python
# Store user passwords in IRIS Wallet (admin operation)
import iris
wallet = iris.cls('%IRIS.Wallet')
wallet.SetSecret('pgwire-user-john.doe', 'secure_password_123')

# Client connects without password in code
conn = psycopg.connect("host=localhost port=5432 user=john.doe dbname=USER")
# Password retrieved from Wallet automatically
# Audit log: credential access recorded
```

**Benefits**:
- ✅ Zero plain-text passwords in code or configuration
- ✅ Automatic password rotation via Wallet API
- ✅ Audit trail of all credential access
- ✅ Encrypted storage in IRISSECURITY database

### Password Authentication (SCRAM-SHA-256)

**Industry Best Practice**: SCRAM-SHA-256 secure password authentication (replaces deprecated MD5, matches YugabyteDB recommendation):

```python
# SCRAM-SHA-256 authentication (secure challenge-response, no plain-text transmission)
conn = psycopg.connect("host=localhost port=5432 user=_SYSTEM password=SYS dbname=USER")
```

**Security Benefits**:
- ✅ Challenge-response authentication (never transmits plain-text passwords)
- ✅ Cryptographically secure password storage
- ✅ Resistant to replay attacks
- ✅ 100% backward compatible with PostgreSQL clients

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
| **Max Vector Dimensions** | **188,962D (1.44 MB)** | **1,465× more than text literals** |
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

## 🌐 Industry Comparison

IRIS PGWire follows proven architectural patterns from the PostgreSQL wire protocol ecosystem:

| Feature | IRIS PGWire | PgBouncer | YugabyteDB | PGAdapter | QuestDB | Pattern |
|---------|-------------|-----------|------------|-----------|---------|---------|
| **Wire Protocol** | ✅ v3.0 | ✅ v3.0 | ✅ v3.0 | ✅ v3.0 | ✅ v3.0 | Universal |
| **SSL/TLS** | Proxy | ✅ Native | ✅ Native | ✅ Native | ❌ None | Mixed (3/5 native) |
| **SCRAM-SHA-256** | ✅ | ✅ | ✅ | ✅ | ❌ | Standard (4/5) |
| **OAuth/IAM** | ✅ | ❌ | ❌ | ✅ | ❌ | Cloud-native (2/5) |
| **Kerberos/GSSAPI** | ❌ | ❌ | ❌ | ❌ | ❌ | **Rare (0/5)** |
| **Connection Pooling** | ✅ | ✅ | ✅ | ✅ | ❌ | Common (4/5) |
| **Binary Format** | ✅ | ✅ | ✅ | ✅ | ✅ | Universal |

**Key Insights**:
- **GSSAPI**: Only CockroachDB + PostgreSQL core implement (2 of 9 surveyed implementations)
- **SSL/TLS**: Mixed - QuestDB has none, Tailscale pgproxy uses network-layer security
- **Cloud Auth**: OAuth/IAM increasingly preferred over Kerberos for cloud-native deployments
- **Pattern**: IRIS PGWire matches 6 of 9 major implementations in security profile

**References**: Industry analysis via Perplexity research (November 2025)

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

## 🏆 Production Readiness

### Protocol Implementation Status

| Feature | Status | Implementation Quality |
|---------|--------|----------------------|
| **Simple Queries** | ✅ Complete | SELECT, INSERT, UPDATE, DELETE - 100% |
| **DDL Statements** | ✅ Complete | CREATE/DROP/ALTER TABLE - full compatibility |
| **Extended Protocol** | ✅ Complete | Prepared statements, binary/text formats - 8 drivers validated |
| **Authentication** | ✅ Complete | OAuth 2.0, IRIS Wallet, SCRAM-SHA-256 - enterprise-grade |
| **Transactions** | ✅ Complete | BEGIN/COMMIT/ROLLBACK, savepoints - full ACID support |
| **COPY Protocol** | ✅ Complete | Bulk CSV import/export - 600+ rows/sec |
| **Client Compatibility** | ✅ **100%** | **171/171 tests passing** across 8 languages |

### Architecture Decisions (Industry-Standard)

**SSL/TLS Transport Encryption**:
- **Status**: Delegated to reverse proxy (industry-standard pattern)
- **Examples**: QuestDB (no SSL), Tailscale pgproxy (network-layer security)
- **Workaround**: nginx/HAProxy TLS termination (see [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md))
- **Authentication Security**: OAuth 2.0, IRIS Wallet, SCRAM-SHA-256 (no plain-text passwords)

**Kerberos/GSSAPI Authentication**:
- **Status**: Not implemented (matches PgBouncer, YugabyteDB, PGAdapter, ClickHouse, QuestDB)
- **Technical Reason**: "Inherently stateful, interactive protocol - difficult for connection poolers" (industry research)
- **Alternative**: OAuth 2.0 token authentication (cloud-native IAM pattern like Google Cloud PGAdapter)
- **Enterprise**: Only CockroachDB + PostgreSQL core implement GSSAPI (2 of 9 major implementations)

### IRIS-Specific Optimizations

1. **HNSW Vector Indexes**: 5× speedup at 100K+ vectors (empirically validated). Below 10K vectors, sequential scan is competitive. See [HNSW Investigation](docs/HNSW_FINDINGS_2025_10_02.md).

2. **VECTOR Type Display (DBAPI Backend)**: INFORMATION_SCHEMA shows VARCHAR for VECTOR columns, but all vector operations work correctly (188K dimensions validated). Use embedded backend for accurate type introspection.

**Complete Details**: See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) for deployment guidance

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
- Vector operations (pgvector syntax, HNSW indexes, up to 188K dimensions)
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
