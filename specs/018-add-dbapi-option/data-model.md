# Data Model: DBAPI Backend Option with IPM Packaging

**Feature**: 018-add-dbapi-option
**Date**: 2025-10-05

## Entity Overview

This feature introduces configuration and state management entities for dual backend architecture with IPM packaging. The data model focuses on runtime configuration, connection lifecycle, and observability metadata.

---

## 1. Backend Configuration

**Entity**: `BackendConfig`

**Purpose**: Represents the choice between DBAPI and embedded Python execution paths, including connection parameters and performance settings.

### Fields

| Field | Type | Constraints | Default | Description |
|-------|------|-------------|---------|-------------|
| `backend_type` | Enum | `DBAPIBackend`, `EmbeddedBackend` | `EmbeddedBackend` | Active backend selection |
| `iris_hostname` | String | Valid hostname/IP | `localhost` | IRIS instance hostname |
| `iris_port` | Integer | 1-65535 | `1972` | IRIS SuperServer port |
| `iris_namespace` | String | Valid IRIS namespace | `USER` | Target namespace |
| `iris_username` | String | Non-empty | `_SYSTEM` | Authentication username |
| `iris_password` | String | Non-empty | Required | Authentication password |
| `pool_size` | Integer | 1-200 | `50` | Base connection pool size |
| `pool_max_overflow` | Integer | 0-100 | `20` | Overflow connections |
| `pool_timeout` | Integer | 1-300 (seconds) | `30` | Max wait for connection |
| `pool_recycle` | Integer | 60-86400 (seconds) | `3600` | Connection lifetime |
| `enable_otel` | Boolean | true/false | `true` | OpenTelemetry enabled |
| `otel_endpoint` | String | Valid URL | `http://localhost:4318` | OTLP endpoint |

### Validation Rules

- If `backend_type == DBAPIBackend`: All connection fields required
- `pool_size + pool_max_overflow <= 200` (total connection limit)
- `pool_timeout >= 1` (prevent instant failures)
- `otel_endpoint` must be valid HTTP/HTTPS URL if `enable_otel == true`

### State Transitions

```
Initial State: Uninitialized
    ↓
Load Configuration → Validated
    ↓
Backend Selection → Active (DBAPIBackend | EmbeddedBackend)
    ↓
Connection Pool Created → Ready
    ↓
Shutdown Request → Draining
    ↓
All Connections Closed → Stopped
```

### Relationships

- **Used by**: `BackendSelector` (reads configuration)
- **Configures**: `DBAPIConnectionPool` (when backend_type == DBAPIBackend)
- **Affects**: `PerformanceMonitor` (observability settings)

---

## 2. DBAPI Connection Pool State

**Entity**: `ConnectionPoolState`

**Purpose**: Runtime state of the DBAPI connection pool, including active connections and health metrics.

### Fields

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `pool_id` | String | UUID | Unique pool identifier |
| `connections_created` | Integer | >= 0 | Total connections created |
| `connections_available` | Integer | >= 0 | Idle connections in pool |
| `connections_in_use` | Integer | >= 0 | Active connections |
| `connections_failed` | Integer | >= 0 | Failed connection attempts |
| `total_acquisitions` | Integer | >= 0 | Total acquire() calls |
| `total_releases` | Integer | >= 0 | Total release() calls |
| `avg_acquisition_time_ms` | Float | >= 0 | Average time to acquire connection |
| `last_health_check` | Timestamp | ISO 8601 | Last health check time |
| `health_status` | Enum | `Healthy`, `Degraded`, `Unhealthy` | Current health |

### Invariants

- `connections_in_use + connections_available <= pool_size + pool_max_overflow`
- `total_acquisitions >= total_releases` (pending releases)
- `connections_created >= connections_in_use + connections_available`

### Relationships

- **Owned by**: `DBAPIConnectionPool`
- **Monitored by**: `HealthChecker`
- **Exported to**: OpenTelemetry metrics

---

## 3. IPM Module Metadata

**Entity**: `IPMModuleMetadata`

**Purpose**: Defines how the PGWire server integrates with IRIS via IPM, including package version, dependencies, and installation hooks.

### Fields

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `module_name` | String | `^[a-z][a-z0-9-]*$` | Package identifier (`iris-pgwire`) |
| `version` | String | Semantic version | Package version (e.g., `0.1.0`) |
| `iris_min_version` | String | Version string | Minimum IRIS version (`2024.1`) |
| `ipm_min_version` | String | Version string | Minimum IPM version (`0.7.2`) |
| `python_dependencies` | List[String] | Valid package names | Required Python packages |
| `installation_hooks` | List[Hook] | Ordered sequence | Installation lifecycle hooks |
| `service_lifecycle` | ServiceConfig | Non-null | Start/stop configuration |

### Hook Structure

```typescript
interface Hook {
    class_name: string;      // ObjectScript class
    method_name: string;     // Class method to invoke
    phase: "Activate" | "Clean" | "Compile";
    when: "Before" | "After";
}
```

### ServiceConfig Structure

```typescript
interface ServiceConfig {
    start_command: string;   // Server startup command
    stop_command: string;    // Server shutdown command
    pid_file: string;        // Process ID file path
    log_file: string;        // Server log file path
}
```

### Validation Rules

- `module_name` must be lowercase with hyphens only
- `version` must follow semver (MAJOR.MINOR.PATCH)
- `installation_hooks` must be ordered by (phase, when)
- All `python_dependencies` must be installable via pip

### Relationships

- **Defines**: Installation process for iris-pgwire
- **Requires**: IRIS system services (CallIn, OTEL)
- **Creates**: ObjectScript installer classes

---

## 4. Vector Query Request

**Entity**: `VectorQueryRequest`

**Purpose**: Represents a PostgreSQL wire protocol query containing vector similarity operations that must be translated to IRIS VECTOR functions.

### Fields

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `request_id` | String | UUID | Unique request identifier |
| `original_sql` | String | Valid SQL | Original pgvector query |
| `vector_operator` | Enum | `<->`, `<#>`, `<=>` | Similarity operator |
| `vector_column` | String | Valid identifier | Column name |
| `query_vector` | List[Float] | 1-2048 dimensions | Query vector values |
| `limit_clause` | Integer | >= 1 | Result limit (TOP N) |
| `translated_sql` | String | Valid IRIS SQL | Translated query |
| `translation_time_ms` | Float | >= 0 | Translation duration |
| `backend_type` | Enum | `DBAPI`, `Embedded` | Execution backend |

### Vector Operator Mapping

| pgvector Operator | IRIS Function | Description |
|-------------------|---------------|-------------|
| `<->` | `VECTOR_COSINE` | Cosine distance |
| `<#>` | `VECTOR_DOT_PRODUCT` | Inner product (negative for max) |
| `<=>` | `VECTOR_L2` | L2/Euclidean distance |

### Translation Rules

**Original pgvector query**:
```sql
SELECT * FROM vectors
ORDER BY embedding <-> '[0.1,0.2,0.3]'
LIMIT 5
```

**Translated IRIS query**:
```sql
SELECT TOP 5 * FROM vectors
ORDER BY VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]', 'DECIMAL'))
```

### Validation Rules

- `query_vector` dimensions must match schema (1-2048)
- `vector_operator` must be one of three supported operators
- `translation_time_ms < 5.0` (constitutional SLA)
- `translated_sql` must be valid IRIS SQL

### Relationships

- **Created by**: Protocol message parser
- **Transformed by**: Vector query optimizer
- **Executed by**: Backend executor (DBAPI or Embedded)
- **Monitored by**: Performance monitor (SLA compliance)

---

## 5. DBAPI Connection

**Entity**: `DBAPIConnection`

**Purpose**: Represents an active connection established using the intersystems-irispython DBAPI interface.

### Fields

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `connection_id` | String | UUID | Unique connection identifier |
| `created_at` | Timestamp | ISO 8601 | Connection creation time |
| `last_used_at` | Timestamp | ISO 8601 | Last query execution time |
| `query_count` | Integer | >= 0 | Queries executed on this connection |
| `transaction_active` | Boolean | true/false | Transaction in progress |
| `isolation_level` | Enum | `READ_COMMITTED`, etc. | Transaction isolation |
| `cursor_count` | Integer | >= 0 | Active cursors |
| `health_status` | Enum | `Alive`, `Stale`, `Dead` | Connection health |

### Lifecycle States

```
Created → Idle
    ↓
Acquire from Pool → Active
    ↓
Execute Query → Active (query_count++)
    ↓
Release to Pool → Idle
    ↓
Recycle (age > pool_recycle) → Closed
```

### Health Check Algorithm

```python
def validate_connection(conn: DBAPIConnection) -> bool:
    if conn.created_at + pool_recycle < now():
        return False  # Too old, recycle

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        return True  # Alive
    except Exception:
        return False  # Dead
```

### Relationships

- **Managed by**: `ConnectionPool`
- **Uses**: IRIS DBAPI driver (`intersystems-irispython`)
- **Executes**: Vector query requests
- **Reports to**: OpenTelemetry traces

---

## Entity Relationship Diagram

```
┌─────────────────────┐
│ BackendConfig       │
│ - backend_type      │
│ - pool_size         │
│ - enable_otel       │
└──────────┬──────────┘
           │ configures
           ↓
┌─────────────────────┐
│ ConnectionPoolState │
│ - connections_available │
│ - health_status     │
└──────────┬──────────┘
           │ monitors
           ↓
┌─────────────────────┐       ┌──────────────────┐
│ DBAPIConnection     │←──────│ VectorQueryRequest│
│ - connection_id     │ executes│ - query_vector   │
│ - health_status     │       │ - translation_ms │
└─────────────────────┘       └──────────────────┘
           ↑
           │ defined by
┌─────────────────────┐
│ IPMModuleMetadata   │
│ - module_name       │
│ - installation_hooks│
└─────────────────────┘
```

---

## Configuration File Schema

**File**: `config.yaml` (or environment variables)

```yaml
backend:
  type: "dbapi"  # or "embedded"

iris:
  hostname: "localhost"
  port: 1972
  namespace: "USER"
  username: "_SYSTEM"
  password: "SYS"

connection_pool:
  size: 50
  max_overflow: 20
  timeout: 30
  recycle: 3600

observability:
  enable_otel: true
  otel_endpoint: "http://otel-collector:4318"
  log_level: "INFO"

server:
  host: "0.0.0.0"
  port: 5432
  max_connections: 1000
```

---

## Performance Constraints

| Entity | Constraint | Value | Rationale |
|--------|-----------|-------|-----------|
| `VectorQueryRequest` | translation_time_ms | <5ms | Constitutional SLA |
| `ConnectionPoolState` | avg_acquisition_time_ms | <1ms | Minimize overhead |
| `DBAPIConnection` | pool_recycle | 3600s | Balance stability/overhead |
| `BackendConfig` | pool_size + overflow | <=200 | IRIS connection limits |

---

## Validation Test Scenarios

### Scenario 1: Backend Selection
```python
config = BackendConfig(backend_type="dbapi")
assert config.validate() == True
assert config.requires_pool() == True
```

### Scenario 2: Connection Pool Limits
```python
config = BackendConfig(pool_size=50, pool_max_overflow=20)
assert config.total_connections() == 70
assert config.total_connections() <= 200  # Hard limit
```

### Scenario 3: Vector Query Translation
```python
request = VectorQueryRequest(
    original_sql="SELECT * FROM v ORDER BY e <-> '[0.1,0.2]' LIMIT 5",
    vector_operator="<->",
    query_vector=[0.1, 0.2]
)
translated = request.translate()
assert "VECTOR_COSINE" in translated.translated_sql
assert translated.translation_time_ms < 5.0  # Constitutional SLA
```

---

**Data Model Complete**: ✅ All entities defined with validation rules and relationships
