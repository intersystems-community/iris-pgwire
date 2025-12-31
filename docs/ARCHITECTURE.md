# Architecture: IRIS PGWire System Design

**Last Updated**: 2025-12-27
**Related**: [Dual-Path Architecture](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/architecture/DUAL_PATH_ARCHITECTURE.md), [Performance](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PERFORMANCE.md), [Deployment](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md)

---

## Overview

IRIS PGWire is a PostgreSQL wire protocol implementation that enables any PostgreSQL-compatible client to connect to InterSystems IRIS databases without custom drivers or code changes.

**Design Goal**: ~4ms protocol translation overhead while preserving 100% IRIS native performance characteristics.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     PostgreSQL Clients                          │
│  (psql, DBeaver, Superset, psycopg3, JDBC, node-postgres, ...)  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ Port 5432 (PostgreSQL Protocol)
┌─────────────────────────────────────────────────────────────────┐
│                      IRIS PGWire Server                         │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Wire Proto   │  │   Query      │  │   Vector Translation   │ │
│  │ Handler      │──│   Parser     │──│ <=> → VECTOR_COSINE    │ │
│  └──────────────┘  └──────────────┘  │ <#> → VECTOR_DOT_PROD  │ │
│                                      └────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ IRIS DBAPI / Embedded Python
┌─────────────────────────────────────────────────────────────────┐
│                    InterSystems IRIS                            │
│                   (SQL Engine, Vector Support)                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Components

### 1. Protocol Layer

**Responsibility**: Implement PostgreSQL wire protocol v3 specification

**Components**:
- **Message Parser**: Decode PostgreSQL protocol messages (Query, Parse, Bind, Execute, Sync)
- **Message Encoder**: Encode PostgreSQL responses (RowDescription, DataRow, CommandComplete)
- **Authentication Handler**: SCRAM-SHA-256, OAuth 2.0, IRIS Wallet integration
- **Session Manager**: Track client connection state, prepared statements, portals

**Implementation**: `src/iris_pgwire/protocol.py` (asyncio-based TCP server)

**Key Features**:
- Full extended query protocol (prepared statements, parameter binding)
- Simple query protocol (direct SQL execution)
- COPY protocol (bulk import/export with 600+ rows/sec)
- Transaction support (BEGIN/COMMIT/ROLLBACK with savepoints)

### 2. Query Translation Layer

**Responsibility**: Translate PostgreSQL SQL to IRIS SQL

**Translation Rules**:

| PostgreSQL Syntax | IRIS Translation | Use Case |
|-------------------|------------------|----------|
| `embedding <=> $1` | `VECTOR_COSINE(embedding, TO_VECTOR($1))` | Cosine similarity |
| `embedding <#> $1` | `VECTOR_DOT_PRODUCT(embedding, TO_VECTOR($1))` | Dot product |
| `'tablename'::regclass` | Table OID lookup | ORM introspection |
| `= ANY($1)` | `IN (value1, value2, ...)` | Array parameters |
| `public.tablename` | `SQLUser.tablename` | Schema mapping |

**Implementation**: `src/iris_pgwire/sql_translator/` module

**Performance**: <1ms translation overhead per query (measured)

### 3. Catalog Emulation Layer

**Responsibility**: Emulate PostgreSQL system catalogs for ORM introspection

**Supported Catalogs**:
- `pg_class` - Table/view catalog
- `pg_attribute` - Column catalog
- `pg_constraint` - Constraint catalog (PK, FK, unique, check)
- `pg_index` - Index catalog
- `pg_namespace` - Schema catalog
- `pg_attrdef` - Default value catalog

**Supported Functions**:
- `format_type()` - Type name formatting
- `pg_get_constraintdef()` - Constraint SQL
- `pg_get_serial_sequence()` - Sequence lookup
- `pg_get_viewdef()` - View definition
- `pg_get_indexdef()` - Index DDL

**Implementation**: `src/iris_pgwire/catalog/` module

**How It Works**:
1. Detect `pg_catalog.*` or `pg_*` table references in queries
2. Route to appropriate catalog emulator
3. Query IRIS `INFORMATION_SCHEMA` for metadata
4. Format results to match PostgreSQL structure
5. Generate deterministic OIDs for stable object IDs

**Learn More**: [PG_CATALOG Documentation](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md)

### 4. Type Mapping System

**Responsibility**: Map PostgreSQL types ↔ IRIS types

**Common Mappings**:

| PostgreSQL Type | IRIS Type | Notes |
|-----------------|-----------|-------|
| `integer` | `INT` | 32-bit signed |
| `bigint` | `BIGINT` | 64-bit signed |
| `varchar(n)` | `VARCHAR(n)` | Variable-length string |
| `timestamp` | `TIMESTAMP` | Without timezone |
| `numeric(p,s)` | `NUMERIC(p,s)` | Fixed-precision decimal |
| `boolean` | `BIT` | True/false |
| `vector(n)` | `VECTOR(DOUBLE, n)` | pgvector compatibility |

**Type Modifier Handling**:
- `varchar(255)` → typmod encoding for length
- `numeric(10,2)` → precision + scale encoding
- Preserved through `format_type()` function

**Implementation**: `src/iris_pgwire/type_mapping.py`

### 5. Parameter Binding System

**Responsibility**: Bind PostgreSQL parameters to IRIS SQL

**Binary Format Support**:
- Integers (2/4/8 byte)
- Floats (4/8 byte IEEE 754)
- Strings (UTF-8)
- Vectors (binary array of doubles)
- Arrays (PostgreSQL array format)

**Vector Parameter Binding**:
- Text format: `[0.1, 0.2, 0.3]` → IRIS list
- Binary format: 40% more compact, faster parsing
- Dimensions: 128D-4096D tested
- Automatic `TO_VECTOR()` wrapping

**Learn More**: [Vector Parameter Binding](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md)

---

## Dual Backend Execution Paths

IRIS PGWire supports **two distinct SQL execution methods**, providing deployment flexibility and performance optimization.

### Comparison Matrix

| Feature | DBAPI Backend | Embedded Python Backend |
|---------|---------------|-------------------------|
| **Deployment** | External Python process | Inside IRIS via `irispython` |
| **Connection** | TCP to IRIS:1972 | Direct in-process calls |
| **Latency** | +1-3ms network overhead | Near-zero overhead |
| **Connection Pooling** | ✅ 50+20 async pool | ❌ Not applicable |
| **Best For** | Development, multi-IRIS | Production, max performance |
| **Type System** | DBAPI type mapping | Native IRIS types |
| **VECTOR Handling** | May show as VARCHAR | True VECTOR type |

### DBAPI Backend (Development Mode)

**Use Case**: External development, connecting to remote IRIS instances, connection pooling.

**Deployment**:
```bash
# External Python process connects to IRIS
python -m iris_pgwire.server
# PGWire listens on port 5432
# Connects to IRIS on port 1972 via DBAPI
```

**Advantages**:
- Connection pooling (50 concurrent + 20 overflow)
- Works with any IRIS instance (local or remote)
- Standard Python deployment (pip install)
- Hot-reload for development

**Disadvantages**:
- Network latency (+1-3ms per query)
- DBAPI type mapping layer
- Requires separate Python environment

**Configuration**:
```bash
export IRIS_HOST=localhost
export IRIS_PORT=1972
export IRIS_USERNAME=_SYSTEM
export IRIS_PASSWORD=SYS
export IRIS_NAMESPACE=USER
export BACKEND_TYPE=dbapi
```

### Embedded Python Backend (Production Mode)

**Use Case**: Production deployment, maximum performance, single-container deployment.

**Deployment**:
```bash
# PGWire runs INSIDE IRIS process
export BACKEND_TYPE=embedded
irispython -m iris_pgwire.server
# Zero network overhead between PGWire and IRIS
```

**Advantages**:
- Zero network latency (in-process calls)
- Native IRIS type system
- True VECTOR type handling
- Single process deployment

**Disadvantages**:
- Must run on same machine as IRIS
- No connection pooling (not needed)
- Requires IRIS Embedded Python

**Performance**: Embedded backend eliminates 1-3ms network overhead present in DBAPI mode.

**Learn More**: [Dual-Path Architecture Details](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/architecture/DUAL_PATH_ARCHITECTURE.md)

---

## Request Flow

### Simple Query Flow

```
Client: "SELECT * FROM users WHERE id = 123"
  │
  ▼ PostgreSQL wire protocol (Query message)
Protocol Layer: Parse message, extract SQL
  │
  ▼ SQL string
Query Translator: No translation needed (standard SQL)
  │
  ▼ IRIS SQL
Executor: Execute via DBAPI or Embedded backend
  │
  ▼ Result rows
Protocol Layer: Encode as DataRow messages
  │
  ▼ PostgreSQL wire protocol
Client: Receives result set
```

### Extended Query Flow (Prepared Statement)

```
Client: Prepare "SELECT * FROM docs WHERE embedding <=> $1 LIMIT 5"
  │
  ▼ Parse message
Protocol Layer: Store prepared statement, parse SQL
  │
  ▼ SQL with placeholders
Query Translator: Translate pgvector operator
  "... WHERE VECTOR_COSINE(embedding, TO_VECTOR($1)) ..."
  │
  ▼ Translated SQL stored
Client: Bind [0.1, 0.2, 0.3] to $1
  │
  ▼ Bind message
Protocol Layer: Extract binary parameter
  │
  ▼ Binary float array
Parameter Binder: Convert to IRIS list
  │
  ▼ Execute
Executor: Run query with bound parameter
  │
  ▼ Result rows
Protocol Layer: Encode and send DataRow messages
```

### Catalog Query Flow

```
Client: "SELECT relname FROM pg_class WHERE relkind = 'r'"
  │
  ▼ Query message
Protocol Layer: Parse SQL
  │
  ▼ SQL string
Catalog Router: Detect pg_class reference
  │
  ▼ Catalog query
Catalog Emulator: Translate to INFORMATION_SCHEMA query
  "SELECT TABLE_NAME AS relname FROM INFORMATION_SCHEMA.TABLES
   WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = 'SQLUser'"
  │
  ▼ IRIS SQL
Executor: Execute INFORMATION_SCHEMA query
  │
  ▼ IRIS result rows
Catalog Emulator: Format as pg_class structure
  │
  ▼ PostgreSQL-compatible rows
Protocol Layer: Encode and send
```

---

## Performance Characteristics

### Latency Breakdown

**Simple SELECT** (no parameters):
- Protocol parsing: ~0.5ms
- Query translation: ~0.3ms
- IRIS execution: 0.2ms (DBAPI baseline)
- Network (DBAPI only): +1-3ms
- Protocol encoding: ~0.5ms
- **Total**: 3.82ms (DBAPI), ~1.5ms (Embedded)

**Vector Similarity Query** (binary parameter):
- Protocol parsing: ~0.8ms
- Vector parameter decode: ~0.4ms
- Query translation: ~0.5ms
- IRIS VECTOR_COSINE: 2.35ms
- Network (DBAPI only): +1-3ms
- Protocol encoding: ~0.6ms
- **Total**: 6.76ms (DBAPI), ~4.5ms (Embedded)

**Catalog Query** (pg_class):
- Catalog detection: ~0.2ms
- INFORMATION_SCHEMA translation: ~0.3ms
- IRIS execution: 0.5ms
- OID generation: ~0.1ms
- Result formatting: ~0.2ms
- **Total**: ~1.3ms

### Throughput

**DBAPI Backend**:
- Simple queries: ~250 qps per connection
- Vector queries: ~150 qps per connection
- Connection pool: 50 concurrent connections
- **Aggregate**: ~12,500 simple qps

**Embedded Backend**:
- Simple queries: ~600 qps (estimated, no network)
- Vector queries: ~220 qps (estimated)

**Comparison to PostgreSQL**:
- PostgreSQL native: ~930 qps (psycopg3)
- IRIS DBAPI direct: ~4,760 qps (bypassing PGWire)
- **Overhead**: ~4ms for PostgreSQL compatibility

**Learn More**: [Performance Benchmarks](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PERFORMANCE.md)

---

## Scalability Considerations

### Horizontal Scaling

**DBAPI Backend**:
- Multiple PGWire instances can connect to same IRIS database
- Load balancer distributes clients across PGWire instances
- Each instance maintains independent connection pool

```
                    ┌─→ PGWire Instance 1 ─┐
Load Balancer ──────┼─→ PGWire Instance 2 ─┼─→ IRIS Database
                    └─→ PGWire Instance 3 ─┘
```

**Embedded Backend**:
- One PGWire instance per IRIS instance
- Scale by deploying multiple IRIS instances
- Use IRIS sharding/mirroring for data distribution

### Vertical Scaling

**Connection Limits**:
- DBAPI pool: 50+20 connections (configurable)
- IRIS concurrent connections: Depends on IRIS license and resources
- Operating system: File descriptor limits (default 1024, increase for production)

**Memory Usage**:
- ~10MB per PGWire connection (protocol buffers, session state)
- ~5MB per IRIS DBAPI connection (cursor state, result caching)
- Vector operations: Temporary memory for dimension encoding

---

## Security Architecture

### Authentication Flow

```
Client: Connect with username/password
  │
  ▼ Startup message
Protocol Layer: Initiate SCRAM-SHA-256 authentication
  │
  ▼ Challenge/response exchange
Authentication Handler: Verify credentials against IRIS
  │
  ▼ Success/failure
Protocol Layer: Send Authentication OK or Error
```

**Supported Methods**:
- **SCRAM-SHA-256**: Industry standard, no plain-text passwords
- **OAuth 2.0**: Token-based, enterprise SSO
- **IRIS Wallet**: Encrypted credential storage

**Security Best Practices**:
- Use TLS/SSL reverse proxy (nginx, HAProxy) for transport encryption
- Rotate IRIS Wallet credentials regularly
- Configure OAuth 2.0 token expiration
- Audit authentication failures

**Learn More**: [Authentication Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md#authentication)

### Authorization

**IRIS SQL Privileges**: PGWire inherits IRIS user permissions
- Users see only tables they have SELECT privilege on
- INSERT/UPDATE/DELETE operations respect IRIS grants
- Catalog queries filtered by user schema access

**Row-Level Security**: Not implemented (delegated to IRIS)

---

## Monitoring & Observability

### Logging

**Structured Logging** (via structlog):
```python
logger.info(
    "query_executed",
    query=sql,
    params=params,
    duration_ms=duration,
    rows_returned=len(rows),
    backend="dbapi"
)
```

**Log Levels**:
- `DEBUG`: Protocol message details, SQL translations
- `INFO`: Query execution, connection events
- `WARNING`: Slow queries, authentication failures
- `ERROR`: Exceptions, connection errors

### Metrics

**Key Metrics** (exposed via `/metrics` endpoint - if configured):
- `pgwire_connections_active` - Current active connections
- `pgwire_queries_total` - Total queries executed (by type)
- `pgwire_query_duration_seconds` - Query latency histogram
- `pgwire_errors_total` - Errors by type (auth, protocol, SQL)
- `pgwire_vector_operations_total` - Vector query count

### Performance Monitoring

**Query Performance**:
```python
# Enable query timing
export PGWIRE_LOG_QUERY_TIMING=true

# Set slow query threshold (ms)
export PGWIRE_SLOW_QUERY_THRESHOLD=100
```

**Connection Pool Monitoring**:
```python
# DBAPI backend - pool statistics
from iris_pgwire.dbapi_backend import get_pool_stats
stats = get_pool_stats()
print(f"Active: {stats.active}, Idle: {stats.idle}, Overflow: {stats.overflow}")
```

---

## See Also

- [Dual-Path Architecture Details](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/architecture/DUAL_PATH_ARCHITECTURE.md) - DBAPI vs Embedded comparison
- [Performance Benchmarks](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PERFORMANCE.md) - Detailed performance analysis
- [Deployment Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md) - Production deployment
- [PG_CATALOG Documentation](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md) - Catalog emulation details
- [Vector Parameter Binding](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md) - Vector optimization
