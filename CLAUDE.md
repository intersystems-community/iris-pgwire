# CLAUDE.md - Development Guidelines for IRIS PGWire

This file provides guidance to Claude Code when working with the IRIS PostgreSQL wire protocol implementation.

## 🚨 CRITICAL PROJECT UNDERSTANDING

**PRIMARY GOAL**: Implement PostgreSQL wire protocol server for InterSystems IRIS using embedded Python track
**ARCHITECTURE**: asyncio-based server with IRIS embedded Python integration
**DOCKER INTEGRATION**: Reuse kg-ticket-resolver IRIS build 127 setup
**DEVELOPMENT APPROACH**: Phased implementation (P0-P6) with TDD methodology

## 🏗️ Architecture Overview

### Core Technology Stack
- **Python 3.11+**: Matching kg-ticket-resolver environment
- **asyncio**: Single-process, coroutine-per-connection model
- **IRIS Embedded Python**: Native `iris` module for SQL execution
- **Docker**: Integration with existing kg-ticket-resolver network
- **TLS**: ssl.SSLContext for secure connections

### Implementation Pattern: Embedded Python Track
```python
# Core execution pattern
async def execute_query(sql: str) -> ResultSet:
    # Use asyncio.to_thread() to avoid blocking event loop
    def iris_exec():
        import iris
        return iris.sql.exec(sql)

    return await asyncio.to_thread(iris_exec)
```

## 🐳 Docker Integration Strategy

### IRIS Build 127 Setup (from kg-ticket-resolver)
```yaml
# Reuse existing configuration
image: containers.intersystems.com/intersystems/iris:latest-preview
ports:
  - "127.0.0.1:1975:1972"    # SuperServer port
  - "127.0.0.1:52777:52773"  # Management portal
environment:
  - IRIS_USERNAME=_SYSTEM
  - IRIS_PASSWORD=SYS
  - IRIS_NAMESPACE=USER
```

### PGWire Server Integration
```yaml
# New service in iris-pgwire project
pgwire-server:
  build: .
  ports:
    - "5432:5432"  # PostgreSQL wire protocol
  networks:
    - kg-ticket-resolver_default  # Connect to existing network
  depends_on:
    - iris  # From kg-ticket-resolver
```

## 📋 Development Methodology

### Phased Implementation (P0-P6)
**ALWAYS follow the phase sequence defined in TODO.md**

1. **P0 - Handshake Skeleton**: SSL probe, StartupMessage, ParameterStatus, ReadyForQuery
2. **P1 - Simple Query**: Basic SQL execution via IRIS embedded Python
3. **P2 - Extended Protocol**: Prepared statements, parameter binding
4. **P3 - Authentication**: SCRAM-SHA-256 security implementation
5. **P4 - Cancel & Timeouts**: Query cancellation and timeout handling
6. **P5 - Types & Vectors**: Type system + IRIS VECTOR integration
7. **P6 - COPY & Performance**: Bulk operations and optimization

### TDD Requirements - E2E FOCUSED
**MANDATORY**: Write E2E tests first, then implement to make them pass

```python
# E2E Test-First Example: P0 Handshake
def test_p0_client_can_connect():
    """E2E: Client should reach ReadyForQuery state"""
    # GIVEN: IRIS is running and PGWire server is started
    # WHEN: Client attempts connection
    # THEN: Connection succeeds and client is ready
    with psycopg.connect("host=localhost port=5432") as conn:
        # If we get here without exception, P0 handshake worked
        assert conn.status == psycopg.Connection.OK

def test_p1_simple_query_execution():
    """E2E: Simple queries should execute against IRIS"""
    # GIVEN: Connected client
    # WHEN: Executing simple query
    # THEN: Results returned from IRIS
    with psycopg.connect("host=localhost port=5432") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 'hello from iris'")
            result = cur.fetchone()[0]
            assert result == "hello from iris"

def test_p5_vector_query_execution():
    """E2E: Vector queries should work with pgvector syntax"""
    # GIVEN: IRIS with vector data
    # WHEN: Executing vector similarity query
    # THEN: Results use IRIS vector functions
    with psycopg.connect("host=localhost port=5432") as conn:
        with conn.cursor() as cur:
            # This should be rewritten to use IRIS vector functions
            cur.execute("SELECT * FROM vectors ORDER BY embedding <-> '[0.1,0.2]' LIMIT 1")
            result = cur.fetchone()
            assert result is not None
```

## 🔗 IRIS Integration Patterns

### Embedded Python Connection
```python
# Connection pattern
import iris

class IrisExecutor:
    def __init__(self):
        # Initialize IRIS connection
        self.connection = iris.createConnection()

    def execute_sql(self, sql: str, params=None):
        """Execute SQL against IRIS with proper error handling"""
        try:
            cursor = self.connection.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            return cursor.fetchall()
        except iris.Error as e:
            # Convert IRIS errors to PostgreSQL-compatible errors
            raise PostgreSQLError(f"IRIS Error: {e}")
```

### Thread Safety for asyncio
```python
# Avoid blocking the event loop
async def safe_iris_call(query: str):
    """Execute IRIS operations in thread pool"""
    executor = ThreadPoolExecutor(max_workers=10)
    return await asyncio.get_event_loop().run_in_executor(
        executor, iris_executor.execute_sql, query
    )
```

## 📡 Protocol Implementation Guidelines

### Message Processing Pattern
```python
class PGWireProtocol:
    async def handle_message(self, msg_type: bytes, payload: bytes):
        """Handle incoming PostgreSQL protocol messages"""
        if msg_type == b'Q':  # Simple Query
            return await self.handle_query(payload)
        elif msg_type == b'P':  # Parse (Extended Protocol)
            return await self.handle_parse(payload)
        # ... other message types
```

### State Management
```python
class SessionState:
    """Track session state for proper ReadyForQuery responses"""
    def __init__(self):
        self.transaction_status = 'I'  # I=idle, T=transaction, E=error
        self.prepared_statements = {}
        self.portals = {}
        self.backend_key = self.generate_backend_key()
```

## 🎯 Vector Support Implementation (Based on caretdev SQLAlchemy IRIS)

### IRIS Vector Integration - REAL PATTERNS
```python
# PROVEN IRIS Vector implementation from caretdev/sqlalchemy-iris
class IRISVector(UserDefinedType):
    """Based on caretdev's production SQLAlchemy IRIS vector type"""
    cache_ok = True

    def __init__(self, max_items: int = None, item_type: type = float):
        super(UserDefinedType, self).__init__()
        if item_type not in [float, int, Decimal]:
            raise TypeError(f"IRISVector expected int, float or Decimal; got {type.__name__}")

        self.max_items = max_items
        self.item_type = item_type
        # IRIS server type mapping
        self.item_type_server = (
            "decimal" if self.item_type is float
            else "float" if self.item_type is Decimal
            else "int"
        )

    def get_col_spec(self, **kw):
        """Generate IRIS VECTOR column specification"""
        if self.max_items is None and self.item_type is None:
            return "VECTOR"
        len_spec = str(self.max_items or "")
        return f"VECTOR({self.item_type_server}, {len_spec})"

    def bind_processor(self, dialect):
        """Convert Python list to IRIS vector text format"""
        def process(value):
            if not value:
                return value
            if not isinstance(value, (list, tuple)):
                raise ValueError("expected list or tuple, got '%s'" % type(value))
            # IRIS vector text format: [1.0,2.0,3.0]
            return f"[{','.join([str(v) for v in value])}]"
        return process

    def result_processor(self, dialect, coltype):
        """Parse IRIS vector result back to Python list"""
        def process(value):
            if not value:
                return value
            # Parse "[1.0,2.0,3.0]" back to [1.0, 2.0, 3.0]
            vals = value.split(",")
            vals = [self.item_type(v) for v in vals]
            return vals
        return process

    class comparator_factory(UserDefinedType.Comparator):
        """IRIS vector functions for similarity operations"""

        def max_inner_product(self, other):
            return self.func("vector_dot_product", other)

        def cosine_distance(self, other):
            return self.func("vector_cosine", other)

        def cosine(self, other):
            return 1 - self.func("vector_cosine", other)

        def func(self, funcname: str, other):
            if not isinstance(other, (list, tuple)):
                raise ValueError("expected list or tuple, got '%s'" % type(other))
            other_value = f"[{','.join([str(v) for v in other])}]"
            return getattr(func, funcname)(
                self, func.to_vector(other_value, text(self.type.item_type_server))
            )
```

### pgvector Compatibility - REAL IRIS Functions
```python
# SQL rewriter using ACTUAL IRIS vector functions (from caretdev analysis)
PGVECTOR_OPERATOR_MAP = {
    '<->': 'VECTOR_L2',           # L2 distance
    '<#>': 'VECTOR_DOT_PRODUCT',  # Inner product (negative for max)
    '<=>': 'VECTOR_COSINE',       # Cosine distance
}

def rewrite_vector_query(sql: str) -> str:
    """Convert pgvector syntax to IRIS vector functions"""
    # Replace operators with IRIS function calls
    for pg_op, iris_func in PGVECTOR_OPERATOR_MAP.items():
        sql = sql.replace(pg_op, iris_func)

    # Handle ORDER BY distance patterns
    sql = re.sub(
        r'ORDER BY\s+(\w+)\s+<->\s+(.+?)\s+LIMIT',
        r'ORDER BY VECTOR_L2(\1, TO_VECTOR(\2)) LIMIT',
        sql
    )
    return sql

# PostgreSQL OID for vector type (custom assignment)
VECTOR_OID = 16388  # Avoid conflicts with standard PostgreSQL OIDs
```

## 🔍 Testing Strategy - PRAGMATIC E2E APPROACH

### Core Testing Philosophy
**NO MOCKS FOR DATABASE CONNECTIONS** - Test against real IRIS instance
**E2E FIRST** - Prove the system works end-to-end, then optimize
**REAL CLIENT TESTING** - Use actual PostgreSQL clients (psql, psycopg) for validation

### Test Categories (Priority Order)
1. **E2E Protocol Tests**: Real clients against running IRIS+PGWire
2. **IRIS Integration Tests**: Direct embedded Python execution
3. **Unit Tests**: Only for pure protocol message parsing (no DB involved)
4. **Performance Tests**: Real load against real database

### Real IRIS Testing Setup
```python
# pytest fixtures for REAL database testing
@pytest.fixture(scope="session")
def iris_container():
    """Ensure IRIS container is running (from kg-ticket-resolver)"""
    # Verify IRIS is accessible at localhost:1975
    import iris
    try:
        conn = iris.createConnection("127.0.0.1", 1975, "USER", "_SYSTEM", "SYS")
        yield conn
    except Exception as e:
        pytest.skip(f"IRIS not available: {e}")

@pytest.fixture(scope="session")
def pgwire_server(iris_container):
    """Start PGWire server against real IRIS"""
    # Start server in subprocess, return when port 5432 is ready
    server_process = start_pgwire_server()
    wait_for_port(5432)
    yield server_process
    server_process.terminate()

# E2E tests with real clients
def test_psql_connection(pgwire_server):
    """Test with real psql client"""
    result = subprocess.run([
        "psql", "-h", "localhost", "-p", "5432",
        "-c", "SELECT 1"
    ], capture_output=True, text=True)
    assert result.returncode == 0
    assert "1" in result.stdout

def test_psycopg_prepared_statement(pgwire_server):
    """Test with real psycopg driver"""
    import psycopg
    with psycopg.connect("host=localhost port=5432") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT %s", (42,))
            assert cur.fetchone()[0] == 42
```

## 📝 Code Quality Standards

### File Organization
```
src/iris_pgwire/
├── __init__.py
├── server.py           # Main asyncio server
├── protocol.py         # PGWire protocol implementation
├── auth.py            # SCRAM authentication
├── iris_executor.py   # IRIS SQL execution
├── types.py          # Type system and OID mapping
├── catalog.py        # pg_catalog shims
└── vector.py         # Vector type support
```

### Error Handling Pattern
```python
class PGWireError(Exception):
    """Base exception for protocol errors"""
    def __init__(self, message: str, severity: str = 'ERROR'):
        self.message = message
        self.severity = severity

    def to_error_response(self) -> bytes:
        """Convert to PostgreSQL ErrorResponse message"""
        # Format according to protocol spec
        pass
```

## 🔧 Development Tools Configuration

### Required Dependencies
```txt
# Core requirements (NO MOCKS)
asyncio>=3.11.0         # Core async server
cryptography>=41.0.0    # For SCRAM authentication
structlog>=23.0.0       # Structured logging

# E2E Testing (REAL clients)
pytest>=7.0.0           # Testing framework
psycopg>=3.1.0          # Real PostgreSQL Python driver
subprocess32>=3.5.0     # For psql command testing

# Development Tools
black>=23.0.0           # Code formatting
ruff>=0.1.0            # Linting
docker>=6.0.0          # Docker client for container management

# IRIS Integration (from caretdev patterns)
intersystems-iris       # IRIS embedded Python (if available)
```

## 📊 pg_catalog Implementation (Based on caretdev INFORMATION_SCHEMA)

### IRIS Information Schema Mapping
The caretdev SQLAlchemy implementation provides proven patterns for mapping IRIS metadata to PostgreSQL expectations:

```python
# PROVEN pg_catalog shims based on IRIS INFORMATION_SCHEMA
class PGCatalogShims:
    """PostgreSQL catalog tables implemented using IRIS INFORMATION_SCHEMA"""

    @staticmethod
    def get_pg_type_data():
        """Map IRIS data types to PostgreSQL OIDs (from caretdev patterns)"""
        return {
            # Standard PostgreSQL types
            'BIGINT': {'oid': 20, 'typname': 'int8'},
            'BIT': {'oid': 1560, 'typname': 'bit'},
            'DATE': {'oid': 1082, 'typname': 'date'},
            'DOUBLE': {'oid': 701, 'typname': 'float8'},
            'INTEGER': {'oid': 23, 'typname': 'int4'},
            'NUMERIC': {'oid': 1700, 'typname': 'numeric'},
            'SMALLINT': {'oid': 21, 'typname': 'int2'},
            'TIME': {'oid': 1083, 'typname': 'time'},
            'TIMESTAMP': {'oid': 1114, 'typname': 'timestamp'},
            'TINYINT': {'oid': 21, 'typname': 'int2'},  # Map to smallint
            'VARBINARY': {'oid': 17, 'typname': 'bytea'},
            'VARCHAR': {'oid': 1043, 'typname': 'varchar'},
            'LONGVARCHAR': {'oid': 25, 'typname': 'text'},
            'LONGVARBINARY': {'oid': 17, 'typname': 'bytea'},

            # IRIS-specific types
            'VECTOR': {'oid': 16388, 'typname': 'vector'},  # Custom OID for vector
        }

    @staticmethod
    def get_version_info():
        """Return version string compatible with PostgreSQL clients"""
        return "InterSystems IRIS (pgwire-compatible) based on PostgreSQL 16 semantics"

    @staticmethod
    def handle_show_commands(command: str):
        """Handle PostgreSQL SHOW commands using IRIS patterns"""
        show_responses = {
            'server_version': '16.0 (InterSystems IRIS)',
            'server_version_num': '160000',
            'client_encoding': 'UTF8',
            'DateStyle': 'ISO, MDY',
            'TimeZone': 'UTC',
            'standard_conforming_strings': 'on',
            'integer_datetimes': 'on',
            'IntervalStyle': 'postgres',
            'is_superuser': 'off',
            'server_encoding': 'UTF8',
            'application_name': '',  # Echo from startup
        }

        # Handle "SHOW ALL" or specific parameter
        if command.upper() in ['SHOW ALL', 'SHOW *']:
            return show_responses

        # Extract parameter name from "SHOW parameter"
        param = command.upper().replace('SHOW ', '').strip()
        return {param.lower(): show_responses.get(param.lower(), 'unknown')}

# IRIS metadata introspection patterns (from caretdev)
IRIS_METADATA_QUERIES = {
    'tables': """
        SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, DESCRIPTION
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = ?
    """,

    'columns': """
        SELECT
            TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE,
            CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE,
            COLUMN_DEFAULT, IS_IDENTITY, DESCRIPTION
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """,

    'indexes': """
        SELECT
            TABLE_NAME, INDEX_NAME, COLUMN_NAME, NON_UNIQUE, PRIMARY_KEY
        FROM INFORMATION_SCHEMA.INDEXES
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY INDEX_NAME, ORDINAL_POSITION
    """,

    'constraints': """
        SELECT
            TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
    """,
}
```

### Critical IRIS-Specific Behaviors (from caretdev)
```python
# IRIS-specific type handling patterns discovered from caretdev
class IRISTypeMapping:
    """Handle IRIS-specific type behaviors for PostgreSQL compatibility"""

    @staticmethod
    def handle_iris_date_formats():
        """IRIS uses Horolog date format - conversion required"""
        # HOROLOG_ORDINAL = datetime.date(1840, 12, 31).toordinal()
        pass

    @staticmethod
    def handle_iris_boolean():
        """IRIS uses 1/0 for boolean, PostgreSQL expects true/false"""
        # Convert 1/0 to 't'/'f' for PostgreSQL clients
        pass

    @staticmethod
    def handle_iris_varchar():
        """IRIS VARCHAR defaults to 50 if no length specified"""
        # Default length handling for compatibility
        pass

    @staticmethod
    def handle_iris_vector_detection():
        """Test for IRIS vector support availability"""
        test_query = "SELECT vector_cosine(to_vector('1'), to_vector('1'))"
        # This query succeeds if vector support is licensed/enabled
        pass
```

### Docker Development Setup
```dockerfile
FROM python:3.11-slim

# Reuse patterns from kg-ticket-resolver
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# IRIS embedded Python integration
ENV PYTHONPATH=/app/src:$PYTHONPATH
ENV IRIS_HOST=iris-enterprise
ENV IRIS_PORT=1972

EXPOSE 5432
CMD ["python", "-m", "iris_pgwire.server"]
```

## 🚨 Critical Implementation Notes

### Threading Model
- **Main Loop**: Single asyncio event loop
- **IRIS Calls**: Execute in ThreadPoolExecutor to avoid blocking
- **Connection Limit**: Use asyncio.Semaphore for connection limits

### Memory Management
```python
# Avoid memory leaks with large result sets
class ResultStreamer:
    async def stream_rows(self, result_set):
        """Stream large results to avoid memory buildup"""
        for chunk in self.chunk_results(result_set, chunk_size=1000):
            yield chunk
            await asyncio.sleep(0)  # Yield control
```

### Security Considerations
- **TLS Required**: Enforce TLS in production
- **SCRAM-SHA-256**: No MD5 authentication
- **Input Validation**: Sanitize all client inputs
- **Error Messages**: Don't leak sensitive information

## 📊 Progress Tracking

### Update Requirements
**MANDATORY**: Update progress files after each development session
- **TODO.md**: Mark phase completions and next priorities
- **PROGRESS.md**: Log development activities and decisions
- **STATUS.md**: Update metrics and health indicators

### Commit Message Format
```
feat(P0): implement SSL probe handling

- Add SSL upgrade capability
- Handle 8-byte SSL request probe
- Return 'S' for TLS, 'N' for plain text
- Update P0 handshake progress to 40%

Tests: Added unit tests for SSL negotiation
Docs: Updated PROGRESS.md with implementation details
```

## 🎯 Success Criteria by Phase

### P0 Success: Basic Connection (E2E Test)
```bash
# REAL TEST: Actual psql client connection
psql -h localhost -p 5432 -c "\conninfo"
# EXPECTED: Connection info displayed, no errors
# PROVES: SSL negotiation, handshake, and ReadyForQuery work

# E2E Python test equivalent:
pytest tests/test_p0_handshake.py::test_psql_connection -v
```

### P1 Success: Simple Queries (E2E Test)
```bash
# REAL TEST: Execute actual SQL against IRIS via PGWire
psql -h localhost -p 5432 -c "SELECT 1"
psql -h localhost -p 5432 -c "SELECT CURRENT_TIMESTAMP"
# EXPECTED: Returns results from IRIS
# PROVES: Query parsing, IRIS execution, result encoding work

# E2E Python test equivalent:
pytest tests/test_p1_simple_query.py -v
```

### P5 Success: Vector Operations (E2E Test)
```bash
# REAL TEST: Vector similarity with actual pgvector syntax
psql -h localhost -p 5432 -c "
CREATE TABLE test_vectors (id INT, embedding VECTOR(3));
INSERT INTO test_vectors VALUES (1, '[0.1,0.2,0.3]');
SELECT * FROM test_vectors ORDER BY embedding <-> '[0.1,0.2,0.3]' LIMIT 5;
"
# EXPECTED: Query rewritten to IRIS vector functions, results returned
# PROVES: Vector type system and operator rewriting work

# E2E Python test equivalent:
pytest tests/test_p5_vector_ops.py::test_vector_similarity -v
```

## 🔄 Continuous Integration

### Automated Checks
- **Code Quality**: black, ruff, mypy
- **Security**: bandit security analysis
- **Testing**: pytest with coverage reporting
- **Protocol**: Automated client compatibility tests

### Docker Health Checks
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import socket; socket.create_connection(('localhost', 5432))"]
  interval: 30s
  timeout: 10s
  retries: 3
```

---

**Remember**: This is a foundational infrastructure project. Focus on correctness, security, and PostgreSQL compatibility over premature optimization. The embedded Python approach provides the fastest path to a working system while maintaining the flexibility to optimize hot paths later.
- use uv for package management
