# IRIS PostgreSQL Wire Protocol

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)
[![InterSystems IRIS](https://img.shields.io/badge/IRIS-Compatible-green.svg)](https://www.intersystems.com/products/intersystems-iris/)

PostgreSQL wire protocol server for InterSystems IRIS, enabling PostgreSQL client connectivity to IRIS databases.

**Status**: Active development. Basic queries and vector operations work. Many PostgreSQL features not yet implemented.

---

## 🚀 Quick Start

```bash
# Clone and start services
git clone https://gitlab.iscinternal.com/tdyar/iris-pgwire.git
cd iris-pgwire
docker-compose up -d

# Test connection
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 1;"
```

---

## ✅ What Works

- **Basic Queries**: Simple SELECT, INSERT, UPDATE, DELETE
- **Vector Operations**: pgvector syntax → IRIS VECTOR functions
- **Parameter Binding**: Up to 188,962D vectors (1.44 MB per vector)
- **Binary Encoding**: PostgreSQL binary array format (float4/float8/int4/int8)
- **DBAPI Backend**: Connection pooling (50+20 connections)
- **Docker Deployment**: docker-compose setup with IRIS integration

### Vector Parameter Binding (Verified)

**Achievement**: 1,465× more capacity than text literals

| Method | Max Dimensions | Capacity vs Text |
|--------|----------------|------------------|
| Text Literal | 129D | Baseline |
| Parameter Binding | **188,962D** | **1,465×** |

**Usage** (verified with `tests/test_all_vector_sizes.py`):
```python
import psycopg

with psycopg.connect('host=localhost port=5434 dbname=USER') as conn:
    cur = conn.cursor()
    query_vector = [0.1, 0.2, 0.3]  # Up to 188,962D supported

    cur.execute("""
        SELECT id, embedding <=> %s as distance
        FROM vectors ORDER BY distance LIMIT 5
    """, (query_vector,))

    results = cur.fetchall()
```

**Documentation**: `docs/VECTOR_PARAMETER_BINDING.md`, `tests/README.md`

---

## 📊 Performance (Verified)

**Benchmark**: 128D vectors, 50 iterations, 100% success rate

### Vector Similarity Queries (pgvector `<=>` operator)

| Path | P50 Latency | P95 Latency | vs PostgreSQL |
|------|-------------|-------------|---------------|
| PostgreSQL + pgvector | 0.43 ms | 1.21 ms | Baseline |
| IRIS DBAPI Direct | 2.13 ms | 4.74 ms | 5.0× slower |
| PGWire → DBAPI → IRIS | 6.94 ms | 8.05 ms | 16.1× slower |

### Simple SELECT Queries

| Path | P50 Latency | P95 Latency | vs PostgreSQL |
|------|-------------|-------------|---------------|
| PostgreSQL | 0.29 ms | 0.39 ms | Baseline |
| IRIS DBAPI Direct | 0.20 ms | 0.25 ms | **1.5× faster** ✅ |
| PGWire → DBAPI → IRIS | 3.99 ms | 4.29 ms | 13.8× slower |
| PGWire → Embedded IRIS | 4.33 ms | 7.01 ms | 14.9× slower |

**Source**: `benchmarks/results/benchmark_4way_results.json` (2025-10-05)

**Key Findings**:
- IRIS DBAPI faster than PostgreSQL for simple queries
- PGWire protocol overhead: ~4ms per query
- All execution paths: 100% success rate

---

## 🔧 Installation

### Docker (Recommended)

```bash
docker-compose up -d
```

**Services**:
- PostgreSQL Protocol: `localhost:5432`
- IRIS Management Portal: `localhost:52773`

### Manual Installation

```bash
# Install dependencies
uv sync --frozen

# Configure IRIS connection
export IRIS_HOST=localhost
export IRIS_PORT=1972
export IRIS_USERNAME=_SYSTEM
export IRIS_PASSWORD=SYS
export IRIS_NAMESPACE=USER

# Start server
python -m src.iris_pgwire.server
```

---

## 🧪 Testing

### Run Tests

```bash
# All tests (30-second timeout detection)
pytest -v

# Specific test categories
pytest tests/contract/ -v         # Framework validation
pytest tests/integration/ -v      # E2E workflows

# Vector parameter binding tests
python3 tests/test_all_vector_sizes.py      # 128D-1024D validation
python3 tests/test_vector_limits.py         # Max dimension tests
```

### Test Framework Features

- ✅ 30-second timeout detection with diagnostics
- ✅ Sequential execution (IRIS stability)
- ✅ Coverage tracking (informational)
- ✅ Flaky test detection and retry

**Documentation**: `docs/testing.md`, `tests/flaky_tests.md`

---

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   PostgreSQL    │    │   IRIS PGWire    │    │ InterSystems    │
│     Clients     │◄──►│     Server       │◄──►│      IRIS       │
│                 │    │                  │    │                 │
│ • psql          │    │ • Protocol v3    │    │ • SQL Engine    │
│ • psycopg       │    │ • Vector Support │    │ • Vector Store  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

### Backend Options

**DBAPI Backend** (External Connection):
- External Python applications
- Connection pooling (50+20 connections)
- <1ms connection acquisition
- Network overhead: ~4ms per query

**Embedded Backend** (Internal Execution):
- Running inside IRIS via `irispython`
- Zero connection overhead
- Direct `iris.sql.exec()` access
- Best for IPM deployments

---

## ⚠️ Known Limitations

- **No Extended Protocol**: Prepared statements not implemented (P2)
- **Basic Type System**: Limited PostgreSQL type mapping
- **No Authentication**: SCRAM-SHA-256 placeholder only (P3)
- **No SSL/TLS**: Encryption not implemented
- **Simple Queries Only**: Extended protocol features missing
- **No Transaction Support**: Multi-statement transactions incomplete

---

## 📚 Documentation

- **[Vector Parameter Binding](docs/VECTOR_PARAMETER_BINDING.md)** - Implementation guide (P5)
- **[Test Suite](tests/README.md)** - Testing framework and validation
- **[Testing Guide](docs/testing.md)** - Framework documentation

---

## 🔗 Links

- **Repository**: https://gitlab.iscinternal.com/tdyar/iris-pgwire
- **IRIS Docs**: https://docs.intersystems.com/iris/
- **PostgreSQL Protocol**: https://www.postgresql.org/docs/current/protocol.html

---

**License**: MIT | **Status**: Development (not production-ready)
