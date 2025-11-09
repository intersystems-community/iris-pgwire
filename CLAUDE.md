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

### Implementation Pattern: Embedded Python Track (VALIDATED)
**Official Pattern from intersystems-community/iris-embedded-python-template**

```python
# CRITICAL: Run via `irispython` command, NOT system python
# Core execution pattern (from official template)
import iris  # NO authentication needed when run via irispython!

async def execute_query(sql: str) -> ResultSet:
    # Use asyncio.to_thread() to avoid blocking event loop
    def iris_exec():
        # Direct execution - NO connection creation required
        result = iris.sql.exec(sql)
        # Iterate results: for row in result: print(row)
        return result

    return await asyncio.to_thread(iris_exec)

# Additional patterns from official template:
# - Switch namespace: iris.system.Process.SetNamespace("USER")
# - Set credentials: iris.cls('Security.Users').UnExpireUserPasswords("*")
# - Direct class calls: iris.cls('%SYSTEM.License').KeyCustomerName()
```

### ⚠️ CRITICAL: InterSystems Python Package Naming (NON-STANDARD)

**IMPORTANT**: The `intersystems-irispython` package uses **highly unusual** naming that violates standard Python conventions:

```python
# PyPI package name (pip install)
pip install intersystems-irispython>=5.1.2

# Module names (Python import) - COMPLETELY DIFFERENT!
import iris                    # ✅ CORRECT - Main module
import iris.dbapi             # ✅ CORRECT - DBAPI interface
import irisnative             # ✅ CORRECT - Native globals access

# WRONG imports that will fail:
import intersystems_irispython        # ❌ WRONG - module doesn't exist!
import intersystems_iris              # ❌ WRONG - old package name
import intersystems_irispython.dbapi  # ❌ WRONG - no such module
```

**Why This Matters**:
- **Package name**: `intersystems-irispython` (PyPI/pip)
- **Module names**: `iris` and `irisnative` (completely different!)
- **Violates PEP 8**: Standard convention is package name ≈ module name
- **Legacy reasons**: InterSystems wanted short import (`iris`) but descriptive package name

**DBAPI Connection Pattern** (Feature 018):
```python
# CORRECT: External DBAPI connection (from outside IRIS)
import iris.dbapi as dbapi

connection = dbapi.connect(
    hostname="localhost",
    port=1972,
    namespace="USER",
    username="_SYSTEM",
    password="SYS"
)
cursor = connection.cursor()
cursor.execute("SELECT 1")
```

**Key Differences**:
1. **Embedded Python** (`irispython` command): `import iris` → NO connection needed
2. **External DBAPI** (standard Python): `import iris.dbapi` → Connection required
3. Both use the SAME package (`intersystems-irispython`) but different import paths!

**CRITICAL REQUIREMENTS** (from official template):
1. **merge.cpf REQUIRED**: Must enable CallIn service for embedded Python
   ```
   [Actions]
   ModifyService:Name=%Service_CallIn,Enabled=1,AutheEnabled=48
   ```
2. **Run via irispython**: `/usr/irissys/bin/irispython -m your_module`
3. **NO external authentication**: iris module works directly inside IRIS process

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

## 🔍 IRIS-Specific Quirks and Learnings

**Purpose**: This section documents IRIS-specific behaviors discovered during development that differ from standard PostgreSQL. These learnings are critical for MCP tool development and troubleshooting.

### 1. Semicolon Handling - CRITICAL DISCOVERY

**Issue**: PostgreSQL clients send queries with trailing semicolons (`;`), but IRIS rejects them during SQL parsing.

**Root Cause**: The SQL translator bypass in `protocol.py` (lines 897-910) passes queries directly to IRIS without translation, bypassing the v0.2.0 fix in `translator.py`.

**Error Message**:
```
ERROR: Input (;) encountered after end of query^CREATE TABLE test (id INT PRIMARY KEY);
```

**Execution Path** (Critical Understanding):
```
PostgreSQL Client → protocol.py → vector_optimizer.py → IRIS Executor
                                   ↑
                              (translator.py BYPASSED!)
```

**Fix Location**: `src/iris_pgwire/vector_optimizer.py:112-116`
```python
# STEP 0: Strip trailing semicolons from incoming SQL
# PostgreSQL clients send queries with semicolons, but IRIS expects them without
# This is critical since protocol.py bypasses the translator where this was fixed
sql = sql.rstrip(';').strip()
logger.debug(f"Stripped semicolons from SQL", sql_preview=sql[:150])
```

**Testing Reference**: See `tests/test_ddl_semicolon_fix.sh` for comprehensive validation framework.

### 2. Date Format Validation Issues

**Issue**: IRIS DATE columns reject PostgreSQL ISO date format (`'1990-01-01'`) during INSERT operations.

**Error Message**:
```
ERROR: Field 'SQLUser.Patients.DateOfBirth' (value '1990-01-01') failed validation
ERROR: Field 'SQLUser.Patients.AdmissionDate' (value '2024-01-01') failed validation
```

**Investigation Status**: 🚧 **ONGOING**

**Attempted Solutions**:
```sql
-- ❌ FAILED: Direct ISO format
INSERT INTO Patients VALUES (1, 'John', 'Doe', '1990-01-01', 'M', 'Active', '2024-01-01', NULL);

-- ❓ UNCLEAR: TO_DATE() conversion (error visibility issue hides result)
INSERT INTO Patients VALUES (999, 'Test', 'Patient', TO_DATE('1990-01-01', 'YYYY-MM-DD'), 'M', 'Active', TO_DATE('2024-01-01', 'YYYY-MM-DD'), NULL);
```

**Potential Solutions** (Not Yet Validated):
1. Use IRIS Horolog format: `datetime.date(1840, 12, 31).toordinal()` conversion
2. Use `iris-devtester` DAT fixture loading (bypasses SQL INSERT entirely)
3. Investigate IRIS-specific date literal syntax

**Reference**: See `examples/superset-iris-healthcare/data/patients-data.sql` for blocked dataset (250 patient records).

### 3. DROP TABLE Syntax Limitations

**Issue**: IRIS does NOT support PostgreSQL's comma-separated DROP TABLE syntax.

**PostgreSQL Syntax** (doesn't work):
```sql
DROP TABLE IF EXISTS table1, table2, table3 CASCADE;
```

**Error Message**:
```
ERROR: Input (,) encountered after end of query^DROP TABLE IF EXISTS test1,
```

**Workaround** (use individual statements):
```bash
# In bash scripts
for table in test1 test2 test3; do
    psql -c "DROP TABLE IF EXISTS $table"
done
```

**Or in SQL**:
```sql
DROP TABLE IF EXISTS table1;
DROP TABLE IF EXISTS table2;
DROP TABLE IF EXISTS table3;
```

**Impact**: Test cleanup scripts must loop over individual DROP statements instead of bulk operations.

### 4. Error Visibility Challenges

**Issue**: IRIS query failures sometimes return "SELECT 0" with exit code 0, hiding actual errors from shell scripts.

**Example** (demonstrating the problem):
```bash
# This command may return "SELECT 0" even if it fails
psql -c "CREATE TABLE ..."
echo $?  # Returns 0 even on failure!
```

**Workaround** - Comprehensive Error Capture:
```bash
# Capture both stdout and stderr
if output=$(docker run ... psql ... -c "$sql" 2>&1); then
    # Command succeeded - verify actual result
    if [ "$expect_success" = "true" ]; then
        echo "✅ PASS: Command succeeded as expected"
        echo "Output: $output"
    else
        echo "❌ FAIL: Command succeeded but was expected to fail"
    fi
else
    # Command failed - capture exit code and logs
    exit_code=$?
    echo "❌ FAIL: Command failed unexpectedly (exit code: $exit_code)"
    echo "Error output: $output"

    # Tail PGWire logs for additional context
    docker exec iris-pgwire-db tail -30 /tmp/pgwire.log 2>/dev/null
fi
```

**Best Practice**: Always use `2>&1` redirection and check actual output content, not just exit codes.

**Reference**: `tests/test_ddl_semicolon_fix.sh` implements this pattern throughout.

### 5. Mixed Case Column Names

**Issue**: IRIS stores column names with their original case (e.g., `PatientID`, `LastName`, `DateOfBirth`), unlike PostgreSQL which lowercases unquoted identifiers.

**INFORMATION_SCHEMA Behavior**:
```sql
-- PostgreSQL expectation: columns lowercase
SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS WHERE table_name = 'patients';
-- Expected (PostgreSQL): patientid, lastname, dateofbirth

-- IRIS reality: columns preserve original case
SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS WHERE LOWER(table_name) = 'patients';
-- Actual (IRIS): PatientID, LastName, DateOfBirth
```

**Workaround for Case-Insensitive Queries**:
```sql
-- Use LOWER() for case-insensitive table name matching
SELECT column_name
FROM INFORMATION_SCHEMA.COLUMNS
WHERE LOWER(table_name) = LOWER('Patients')
ORDER BY ordinal_position;
```

**Impact**:
- Schema introspection queries must account for mixed case
- Column references in queries are case-sensitive
- PostgreSQL clients expecting lowercase may fail

### 6. Protocol Translator Bypass (Architecture Critical)

**Critical Discovery**: `src/iris_pgwire/protocol.py` lines 897-910 contain a **hardcoded bypass** of the SQL translator:

```python
# For now, bypass SQL translation to test core query execution
# TODO: Fix SQL translation issue with TranslationResult
translation_result = {
    'success': True,
    'original_sql': query,
    'translated_sql': query,  # ❌ PASSTHROUGH - no translation!
    'translation_used': False,
    'construct_mappings': [],
    'performance_stats': {'translation_time_ms': 0.0},
    'warnings': []
}

# Use original SQL for execution (no translation for now)
final_sql = query
```

**Implications**:
- ALL SQL fixes must be applied in `vector_optimizer.py`, NOT `translator.py`
- The v0.2.0 semicolon fix in `translator.py` was ineffective due to this bypass
- Vector query optimization is the ACTUAL entry point for SQL preprocessing

**Why It Matters**: When debugging SQL issues:
1. ❌ DON'T add fixes to `translator.py` (it's bypassed!)
2. ✅ DO add fixes to `vector_optimizer.py` (actual execution path)
3. ✅ DO verify fixes with real psql client testing

**Reference Files**:
- `src/iris_pgwire/protocol.py:897-910` - Bypass location
- `src/iris_pgwire/vector_optimizer.py:112-116` - Where semicolon fix was actually needed
- `src/iris_pgwire/sql_translator/translator.py:240-244` - Ineffective fix location

### 7. INFORMATION_SCHEMA Compatibility Notes

**IRIS Uses INFORMATION_SCHEMA, NOT pg_catalog**:
```python
# ✅ CORRECT: Query IRIS metadata
cursor.execute("""
    SELECT column_name, data_type
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE table_name = 'MyTable'
""")

# ❌ WRONG: PostgreSQL catalog queries
cursor.execute("""
    SELECT column_name, data_type
    FROM pg_catalog.pg_attribute
    WHERE relname = 'MyTable'
""")
```

**Key INFORMATION_SCHEMA Tables**:
- `INFORMATION_SCHEMA.TABLES` - Table metadata
- `INFORMATION_SCHEMA.COLUMNS` - Column metadata
- `INFORMATION_SCHEMA.INDEXES` - Index metadata
- `INFORMATION_SCHEMA.TABLE_CONSTRAINTS` - Constraint metadata

**Case Sensitivity**: Use `LOWER()` for case-insensitive matching:
```sql
WHERE LOWER(table_name) = LOWER('MyTable')
```

### 8. Testing Best Practices for IRIS Integration

**Pattern 1: Comprehensive Error Capture**
```bash
# From tests/test_ddl_semicolon_fix.sh
run_test() {
    local test_name="$1"
    local test_sql="$2"
    local expect_success="${3:-true}"

    # Capture stdout AND stderr (2>&1)
    if output=$(psql ... -c "$test_sql" 2>&1); then
        # Verify actual success
        if [ "$expect_success" = "true" ]; then
            echo "✅ PASS"
        else
            echo "❌ FAIL: Should have failed"
        fi
    else
        # On failure, show logs for debugging
        exit_code=$?
        echo "❌ FAIL: exit_code=$exit_code"
        echo "Output: $output"
        docker exec iris-pgwire-db tail -30 /tmp/pgwire.log
    fi
}
```

**Pattern 2: Column Count Validation**
```bash
# Validate CREATE TABLE preserved all columns
validate_columns() {
    local table_name="$1"
    local expected_count="$2"

    actual_count=$(psql ... -t -c "
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE LOWER(table_name) = LOWER('$table_name')
    " | tr -d ' ')

    if [ "$actual_count" = "$expected_count" ]; then
        echo "✅ PASS: $expected_count columns preserved"
    else
        echo "❌ FAIL: Expected $expected_count, got $actual_count"
        # Show actual columns for debugging
        psql ... -c "
            SELECT column_name, data_type
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE LOWER(table_name) = LOWER('$table_name')
        "
    fi
}
```

**Pattern 3: PGWire Log Inspection**
```bash
# Always check PGWire logs when debugging
docker exec iris-pgwire-db tail -50 /tmp/pgwire.log

# Look for specific error patterns
docker exec iris-pgwire-db grep "ERROR" /tmp/pgwire.log | tail -20
```

### 9. iris-devtester Integration Recommendations

**Tool Capabilities** (from `/Users/tdyar/ws/iris-devtester/`):
- **Automatic Password Management**: Detects and fixes "Password change required" errors
- **Testcontainers Integration**: Isolated IRIS instances per test suite
- **DBAPI-First Performance**: 3× faster than JDBC connections
- **DAT Fixture Loading**: 10-100× faster than programmatic INSERT statements
- **Zero Configuration**: No manual setup required
- **Medical-Grade Reliability**: 94%+ test coverage

**Zero-Config Example**:
```python
from iris_devtools.containers import IRISContainer

# That's it - no configuration needed!
with IRISContainer.community() as iris:
    conn = iris.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT $ZVERSION")
    print(cursor.fetchone())
```

**Potential Solutions for Current Blockers**:
1. **Date Format Issues**: Use DAT fixtures instead of SQL INSERT
2. **Container State Management**: Automatic cleanup and isolation
3. **Performance Testing**: Built-in benchmarking utilities

**Next Steps**: Integrate `iris-devtester` into PGWire test framework to leverage DAT fixture loading and container management.

### 10. DDL Statement Quirks Summary

**Working** (after v0.2.0 semicolon fix):
- ✅ CREATE TABLE with semicolons
- ✅ DROP TABLE (individual statements)
- ✅ ALTER TABLE operations
- ✅ CREATE INDEX with semicolons
- ✅ Multiple columns, constraints, data types

**Not Working** / Requires Workarounds:
- ❌ Comma-separated DROP TABLE statements
- ❌ Direct ISO date format in DATE columns
- ⚠️ Error visibility (requires stderr redirection)

**Testing Coverage**:
- 15 comprehensive E2E tests in `tests/test_ddl_semicolon_fix.sh`
- Validates column preservation, error handling, edge cases
- Full PGWire log integration for debugging

### References

**Primary Files**:
- `src/iris_pgwire/vector_optimizer.py:112-116` - Semicolon fix (ACTUAL execution path)
- `src/iris_pgwire/protocol.py:897-910` - Translator bypass (why translator.py doesn't work)
- `tests/test_ddl_semicolon_fix.sh` - Comprehensive testing framework
- `BUG_FIX_SUMMARY.md` - Complete DDL semicolon bug documentation
- `KNOWN_LIMITATIONS.md` - Production-ready limitation catalog

**Integration Examples**:
- `examples/superset-iris-healthcare/data/init-healthcare-schema.sql` - Working DDL
- `examples/superset-iris-healthcare/data/patients-data.sql` - Blocked by date issue

**External Tools**:
- `/Users/tdyar/ws/iris-devtester/` - Container and state management tool
- `/Users/tdyar/ws/iris-devtester/docs/examples/sql_vs_objectscript_examples.py` - DBAPI patterns

**Constitutional References**:
- Translation SLA: <5ms (maintained for DDL operations)
- PostgreSQL Compatibility: Full DDL support required
- Test Coverage: E2E validation mandatory

---

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
# CONSTITUTIONAL REQUIREMENT: L2 distance NOT SUPPORTED - REJECT with error
PGVECTOR_OPERATOR_MAP = {
    '<=>': 'VECTOR_COSINE',       # Cosine distance - ✅ SUPPORTED
    '<#>': 'VECTOR_DOT_PRODUCT',  # Inner product (negative for max) - ✅ SUPPORTED
    # '<->': REJECTED - L2 distance NOT supported by IRIS (Constitution v1.2.4)
}

def rewrite_vector_query(sql: str) -> str:
    """Convert pgvector syntax to IRIS vector functions

    Raises:
        NotImplementedError: If L2 distance operator (<->) is found
    """
    # REJECT L2 distance queries (Constitutional requirement)
    if '<->' in sql:
        raise NotImplementedError(
            "L2 distance operator (<->) is not supported by IRIS. "
            "Use <=> (cosine) or <#> (dot product) instead."
        )

    # Replace supported operators with IRIS function calls
    for pg_op, iris_func in PGVECTOR_OPERATOR_MAP.items():
        sql = sql.replace(pg_op, iris_func)

    return sql

# PostgreSQL OID for vector type (custom assignment)
VECTOR_OID = 16388  # Avoid conflicts with standard PostgreSQL OIDs
```

## 🚀 HNSW Vector Performance Requirements (Constitutional v1.2.0)

### Constitutional Compliance - Principle VI

**MANDATORY**: All vector similarity operations MUST follow Constitutional Principle VI: Vector Performance Requirements established in constitution v1.2.0.

### HNSW Index Requirements

**Required Syntax** (Distance parameter MANDATORY):
```sql
-- CORRECT: Distance parameter specified
CREATE INDEX idx_vector ON table_name(vector_column) AS HNSW(Distance='Cosine')
CREATE INDEX idx_vector ON table_name(vector_column) AS HNSW(Distance='DotProduct')

-- INCORRECT: Missing Distance parameter (will fail)
CREATE INDEX idx_vector ON table_name(vector_column) AS HNSW
```

### Dataset Scale Thresholds (Empirically Validated)

Based on comprehensive testing with 1024-dimensional vectors across 1K, 10K, and 100K scales:

| Vector Count | HNSW Performance | Recommendation |
|--------------|------------------|----------------|
| **< 10,000** | 0.98-1.02× (overhead ≈ benefits) | Sequential scan preferred |
| **10,000-99,999** | 1.0-2.0× improvement | Consider HNSW with testing |
| **≥ 100,000** | **5.14× improvement** ✅ | **HNSW strongly recommended** |

**Production Guidance**:
- Target ≥100K vectors for meaningful HNSW benefits
- Benchmark your specific dataset and query patterns
- Use EXPLAIN to verify index usage
- Monitor P95 latency against constitutional 5ms SLA

### HNSW Index Creation Pattern

```python
def create_hnsw_index_constitutional(table_name: str, column_name: str,
                                     index_name: str, distance_metric: str = 'Cosine'):
    """
    Create HNSW index following constitutional requirements.

    Constitutional Requirements:
    - Distance parameter MUST be specified
    - Dataset SHOULD be ≥100K vectors for optimal performance
    - EXPLAIN verification SHOULD confirm index usage
    """
    ddl = f"""
    CREATE INDEX {index_name}
    ON {table_name}({column_name})
    AS HNSW(Distance='{distance_metric}')
    """

    try:
        cursor.execute(ddl)
        logger.info(f"✅ HNSW index created: {index_name} (Distance={distance_metric})")

        # Constitutional validation: Verify index usage
        explain_sql = f"""
        EXPLAIN
        SELECT TOP 5 id FROM {table_name}
        ORDER BY VECTOR_COSINE({column_name}, TO_VECTOR('[0.1,0.2,...]'))
        """
        explain_result = cursor.execute(explain_sql)

        # Check for "Read index map" in EXPLAIN output
        plan_text = str(explain_result)
        if "Read index map" in plan_text and index_name in plan_text:
            logger.info(f"✅ EXPLAIN confirms HNSW index usage: {index_name}")
        else:
            logger.warning(f"⚠️ EXPLAIN shows sequential scan - dataset may be too small")

        return True

    except Exception as e:
        logger.error(f"❌ HNSW index creation failed: {e}")
        return False
```

### ACORN-1 Algorithm Reference (DEPRECATED)

**⚠️ ACORN-1 IS NOT RECOMMENDED FOR PRODUCTION USE**

Empirical testing shows consistent performance degradation (20-72% slower) at all dataset scales.

**Historical Syntax** (for reference only):
```python
# DO NOT USE IN PRODUCTION
cursor.execute('SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1')

# ACORN-1 requires WHERE clauses to engage
sql = """
SELECT TOP 5 id, VECTOR_COSINE(vec, TO_VECTOR('[...]')) AS score
FROM table_name
WHERE id >= 0  -- Required for ACORN-1 engagement
ORDER BY score DESC
"""
```

**Empirical Performance** (100K vectors):
- HNSW alone: 10.85ms avg ✅
- ACORN-1 + WHERE id >= 0: 13.60ms avg (25% slower) ❌
- ACORN-1 + WHERE id < 5000: 17.97ms avg (62% slower) ❌

**Constitutional Status**: Deprecated in constitution v1.2.0 based on comprehensive investigation findings documented in `docs/HNSW_FINDINGS_2025_10_02.md`.

### Performance Benchmarking Requirements

**Constitutional Mandate**: All vector operations MUST be validated against performance requirements.

```python
class ConstitutionalVectorPerformance:
    """Validate vector operations against constitutional requirements"""

    def __init__(self):
        self.constitutional_sla_ms = 5.0  # Translation SLA
        self.hnsw_target_improvement = 5.0  # Minimum at 100K+ scale

    def validate_hnsw_performance(self, dataset_size: int,
                                  with_hnsw_ms: float,
                                  without_hnsw_ms: float):
        """
        Validate HNSW performance against constitutional requirements.

        Constitutional Requirements (Principle VI):
        - ≥100K vectors: 4-10× improvement expected
        - <100K vectors: Sequential scan may be faster
        """
        improvement_factor = without_hnsw_ms / with_hnsw_ms

        if dataset_size >= 100000:
            # Constitutional expectation: 4-10× improvement
            if improvement_factor >= 4.0:
                return {
                    'constitutional_compliant': True,
                    'improvement': f'{improvement_factor:.2f}×',
                    'status': '✅ HNSW performing as expected'
                }
            else:
                return {
                    'constitutional_compliant': False,
                    'improvement': f'{improvement_factor:.2f}×',
                    'status': '⚠️ HNSW underperforming - investigate dataset/index'
                }
        else:
            # Dataset too small for meaningful HNSW benefits
            return {
                'constitutional_compliant': True,  # No requirement at this scale
                'improvement': f'{improvement_factor:.2f}×',
                'status': f'ℹ️ Dataset ({dataset_size}) below 100K threshold'
            }
```

### EXPLAIN Query Plan Validation

**Required Practice**: Always verify HNSW index usage with EXPLAIN.

```python
def verify_hnsw_index_usage(table_name: str, vector_column: str, index_name: str):
    """Verify HNSW index is being used by query optimizer"""

    explain_sql = f"""
    EXPLAIN
    SELECT TOP 5 id, VECTOR_COSINE({vector_column}, TO_VECTOR('[0.1,0.2,...]')) AS score
    FROM {table_name}
    ORDER BY score DESC
    """

    result = cursor.execute(explain_sql)
    plan_text = str(result)

    # Check for index usage indicators
    if "Read index map" in plan_text and index_name in plan_text:
        logger.info(f"✅ HNSW index {index_name} IS being used")
        return True
    elif "Read master map" in plan_text:
        logger.warning(f"⚠️ Sequential scan detected - HNSW index NOT used")
        logger.warning(f"   Possible causes: dataset too small (<10K vectors)")
        return False
    else:
        logger.error(f"❌ Unexpected EXPLAIN output: {plan_text[:200]}")
        return False
```

### References

- **Constitution**: `.specify/memory/constitution.md` - Principle VI (Vector Performance Requirements)
- **Investigation Report**: `docs/HNSW_FINDINGS_2025_10_02.md` - Comprehensive 100K scale testing
- **IRIS Documentation**: https://docs.intersystems.com/iris20252/csp/docbook/Doc.View.cls?KEY=GSQL_vecsearch#GSQL_vecsearch_index

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

## 🔌 Async SQLAlchemy Integration (Feature 019)

### Overview

**Feature**: 019-async-sqlalchemy-based
**Status**: Specification and planning complete (2025-10-08)
**Scope**: Enable async SQLAlchemy ORM usage with IRIS via PGWire protocol

**Connection String**: `iris+psycopg://localhost:5432/USER`

**Key Innovation**: Combines IRIS-specific features (VECTOR types, INFORMATION_SCHEMA) with PostgreSQL async wire protocol via SQLAlchemy's `get_async_dialect_cls()` resolution mechanism.

### Problem Statement

**Current State**: Sync SQLAlchemy works perfectly with IRIS via PGWire:
```python
# ✅ Sync works (existing implementation)
from sqlalchemy import create_engine, text
engine = create_engine("iris+psycopg://localhost:5432/USER")
with engine.connect() as conn:
    result = conn.execute(text("SELECT 1"))
```

**Broken State**: Async SQLAlchemy fails with AwaitRequired errors:
```python
# ❌ Async fails (current problem)
from sqlalchemy.ext.asyncio import create_async_engine
engine = create_async_engine("iris+psycopg://localhost:5432/USER")
async with engine.connect() as conn:
    result = await conn.execute(text("SELECT 1"))
    # Raises: sqlalchemy.exc.AwaitRequired
```

**Root Cause** (confirmed via Perplexity research):
- psycopg3 driver supports both sync and async modes through same module
- SQLAlchemy defaults to sync dialect unless `get_async_dialect_cls()` method exists
- Setting `is_async = True` alone is **insufficient** for async operation

### Solution Architecture

**Implementation Pattern** (from SQLAlchemy PostgreSQL dialect):
```python
# Sync dialect (current - in sqlalchemy_iris/psycopg.py)
class IRISDialect_psycopg(IRISDialect):
    driver = "psycopg"
    is_async = True  # ⚠️ Not enough!

    # KEY METHOD: Enables async resolution
    @classmethod
    def get_async_dialect_cls(cls, url):
        """Return async variant for create_async_engine()."""
        return IRISDialectAsync_psycopg

# Async variant (to be implemented)
from sqlalchemy.dialects.postgresql.psycopg import PGDialectAsync_psycopg

class IRISDialectAsync_psycopg(IRISDialect, PGDialectAsync_psycopg):
    """
    Multiple inheritance combines:
    - IRISDialect: VECTOR types, INFORMATION_SCHEMA, IRIS functions
    - PGDialectAsync_psycopg: Async psycopg transport, async pooling
    """
    driver = "psycopg"
    is_async = True
    supports_statement_cache = True
    supports_native_boolean = True

    @classmethod
    def import_dbapi(cls):
        import psycopg
        return psycopg  # Same module, async mode handled by parent

    @classmethod
    def get_pool_class(cls, url):
        from sqlalchemy.pool import AsyncAdaptedQueuePool
        return AsyncAdaptedQueuePool

    # Override IRIS-specific methods to skip IRIS DBAPI checks
    def on_connect(self):
        def on_connect_impl(conn):
            self._dictionary_access = False
            self.vector_cosine_similarity = None
        return on_connect_impl

    def do_executemany(self, cursor, query, params, context=None):
        # Use loop-based execution for IRIS compatibility
        if query.endswith(";"):
            query = query[:-1]
        for param_set in params:
            cursor.execute(query, param_set)
```

### IRIS Feature Preservation

**Critical Requirement**: Async variant MUST maintain all IRIS-specific features:

1. **VECTOR Types**:
   - `VECTOR(FLOAT, n)` column type
   - `VECTOR_COSINE()` and `VECTOR_DOT_PRODUCT()` functions
   - `TO_VECTOR()` conversion function

2. **INFORMATION_SCHEMA Queries**:
   - Table metadata via `INFORMATION_SCHEMA.TABLES`
   - Column metadata via `INFORMATION_SCHEMA.COLUMNS`
   - Index metadata via `INFORMATION_SCHEMA.INDEXES`
   - NOT PostgreSQL's `pg_catalog`

3. **Transaction Management**:
   - Async commit/rollback
   - Proper isolation level handling
   - NO two-phase commit (not supported via PGWire)

### Performance Requirements

**Constitutional Compliance** (from clarifications):
- Async query latency MUST be within **10% of sync SQLAlchemy** performance
- Measured for single-query operations (not bulk/concurrent)

**Baseline Metrics** (from sync benchmark):
- Simple SELECT: 1-2ms per query
- Vector similarity (128D): 5-10ms per query
- **10% Threshold**: Async ≤2.2ms (simple), ≤11ms (vector)

### FastAPI Integration Requirement

**Validation Scope** (from clarifications):
- MUST validate compatibility with **FastAPI only**
- Other frameworks (Django async, aiohttp) excluded

**FastAPI Use Case**:
```python
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

app = FastAPI()
engine = create_async_engine("iris+psycopg://localhost:5432/USER")
async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session():
    async with async_session_factory() as session:
        yield session

@app.get("/vectors/search")
async def search_vectors(query: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(text("""
        SELECT id, VECTOR_COSINE(embedding, TO_VECTOR(:query, FLOAT)) as score
        FROM vectors ORDER BY score DESC LIMIT 5
    """), {"query": query})
    return [{"id": r.id, "score": r.score} for r in result]
```

### Implementation Artifacts

**Location**: `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/`

**Generated Documentation**:
1. **spec.md** - Feature specification (14 functional requirements, 5 acceptance scenarios)
2. **plan.md** - Implementation plan with constitutional compliance checks
3. **tasks.md** - 33 detailed tasks following TDD principles
4. **research.md** - Research findings and solution patterns
5. **data-model.md** - Class relationships and state transitions
6. **contracts/async_dialect_interface.py** - Interface contracts for TDD
7. **quickstart.md** - Developer usage guide

**Implementation Target**:
- File: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py`
- Location: Separate project (sqlalchemy-iris)
- Changes: Add `get_async_dialect_cls()` and `IRISDialectAsync_psycopg` class

### TDD Workflow

**Phase Sequence** (from tasks.md):
1. **T001-T002**: Verify sync baseline and document async failures (parallel)
2. **T003-T009**: Write contract and integration tests (MUST fail initially)
3. **T010-T018**: Implement async dialect class to make tests pass
4. **T019-T021**: FastAPI integration testing
5. **T022-T024**: Performance validation (10% threshold)
6. **T025-T029**: IRIS feature validation (VECTOR, INFORMATION_SCHEMA)
7. **T030-T033**: Edge cases and error handling

**Critical Testing Requirements**:
- Tests MUST be written BEFORE implementation
- Tests MUST fail initially (no async dialect exists)
- Implement to make tests pass (Red-Green-Refactor)

### Known Risks

1. **DBAPI Configuration** (Medium Risk)
   - Ensuring psycopg module properly configured for async mode
   - Mitigation: Follow `PGDialectAsync_psycopg` patterns exactly

2. **Bulk Insert Performance** (High Risk - Known Issue)
   - 5-minute bulk insert observed in previous testing
   - Root cause: Likely connection establishment overhead
   - Mitigation: T017 validates `do_executemany()` in async mode

3. **Transaction Management** (Medium Risk)
   - IRIS transaction semantics may differ from PostgreSQL
   - Mitigation: Extensive transaction testing (T027-T028)

### References

- **Specification**: `specs/019-async-sqlalchemy-based/spec.md`
- **Implementation Plan**: `specs/019-async-sqlalchemy-based/plan.md`
- **Task List**: `specs/019-async-sqlalchemy-based/tasks.md` (33 tasks)
- **Quickstart Guide**: `specs/019-async-sqlalchemy-based/quickstart.md`
- **Contract Interface**: `specs/019-async-sqlalchemy-based/contracts/async_dialect_interface.py`

### Next Steps

**Implementation Status**: Planning complete, implementation NOT started

**To Begin Implementation**:
1. Run T001: Verify sync SQLAlchemy benchmark passes (baseline)
2. Run T002: Document current async failure modes
3. Execute T003-T033 following TDD principles (tests first, then implementation)

**Expected Outcome**: Async SQLAlchemy working with IRIS via PGWire, within 10% performance of sync baseline, validated with FastAPI integration.

---

**Remember**: This is a foundational infrastructure project. Focus on correctness, security, and PostgreSQL compatibility over premature optimization. The embedded Python approach provides the fastest path to a working system while maintaining the flexibility to optimize hot paths later.
- use uv for package management

## 🔄 PostgreSQL→IRIS SQL Translation (Features 021-022)

### Feature 022: Transaction Verb Compatibility

**Status**: ✅ Implemented (2025-11-08)
**Location**: `src/iris_pgwire/sql_translator/transaction_translator.py`

**Problem**: PostgreSQL clients send `BEGIN` to start transactions, but IRIS SQL uses `START TRANSACTION`. Without translation, PostgreSQL clients cannot use standard transaction syntax.

**Solution**: Translate PostgreSQL transaction commands to IRIS equivalents before SQL execution.

#### Translation Rules

```python
# PostgreSQL → IRIS translations
BEGIN                     → START TRANSACTION
BEGIN TRANSACTION         → START TRANSACTION
BEGIN WORK               → START TRANSACTION
BEGIN [modifiers]        → START TRANSACTION [modifiers]

# Normalized (unchanged)
COMMIT                   → COMMIT
COMMIT WORK              → COMMIT
ROLLBACK                 → ROLLBACK
```

#### Integration Point (FR-010: Critical Ordering)

**Execution Pipeline Order** (in `iris_executor.py`):
```python
# 1. Transaction Translation (Feature 022) - MUST occur FIRST
transaction_translator = TransactionTranslator()
transaction_translated_sql = transaction_translator.translate_transaction_command(sql)

# 2. SQL Normalization (Feature 021) - Identifiers, DATE literals
translator = SQLTranslator()
normalized_sql = translator.normalize_sql(transaction_translated_sql, execution_path="direct")

# 3. Vector Optimization - Parameter optimization
optimized_sql, optimized_params = optimize_vector_query(normalized_sql, params)
```

**Why This Order Matters**:
- Transaction translation happens on original SQL before normalization
- Normalization applies to transaction-translated SQL
- Vector optimizer receives fully normalized SQL

#### Performance Requirements

**Constitutional SLA**: <0.1ms translation overhead per query (PR-001)

```python
# Example usage with performance tracking
translator = TransactionTranslator()

# Translate transaction command
result = translator.translate_transaction_command("BEGIN ISOLATION LEVEL READ COMMITTED")
# Returns: "START TRANSACTION ISOLATION LEVEL READ COMMITTED"

# Get performance metrics
metrics = translator.get_translation_metrics()
# {
#     'total_translations': 1,
#     'avg_translation_time_ms': 0.02,  # < 0.1ms requirement
#     'sla_violations': 0,
#     'sla_compliance_rate': 100.0
# }
```

#### Usage Examples

```python
# Direct usage
from iris_pgwire.sql_translator import TransactionTranslator

translator = TransactionTranslator()

# Basic translation
assert translator.translate_transaction_command("BEGIN") == "START TRANSACTION"
assert translator.translate_transaction_command("BEGIN WORK") == "START TRANSACTION"

# Modifier preservation
result = translator.translate_transaction_command("BEGIN ISOLATION LEVEL SERIALIZABLE READ ONLY")
assert result == "START TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY"

# Detection
assert translator.is_transaction_command("BEGIN") is True
assert translator.is_transaction_command("SELECT 1") is False

# Parsing
cmd = translator.parse_transaction_command("BEGIN READ ONLY")
assert cmd.command_type == CommandType.BEGIN
assert cmd.modifiers == "READ ONLY"
assert cmd.translated_text == "START TRANSACTION READ ONLY"
```

#### E2E Testing with PostgreSQL Clients

**psql client validation**:
```bash
# PostgreSQL client sends BEGIN - should work transparently
psql -h localhost -p 5432 -U test_user -d USER -c "
BEGIN;
INSERT INTO Patients VALUES (1, 'John', 'Smith', '1985-03-15');
COMMIT;
SELECT * FROM Patients WHERE PatientID = 1;
"
# ✅ Works because PGWire translates BEGIN → START TRANSACTION
```

**psycopg driver validation**:
```python
import psycopg

with psycopg.connect("host=localhost port=5432 user=test_user dbname=USER") as conn:
    with conn.cursor() as cur:
        cur.execute("BEGIN")  # Translated to START TRANSACTION
        cur.execute("INSERT INTO Patients VALUES (%s, %s, %s)", (1, 'John', 'Smith'))
        cur.execute("COMMIT")
        # ✅ Transaction succeeds
```

#### Implementation Files

- **Core**: `src/iris_pgwire/sql_translator/transaction_translator.py` (237 lines)
- **Integration**: `src/iris_pgwire/iris_executor.py` (lines 379-408, 647-676)
- **Tests**: 
  - `tests/unit/test_transaction_translator.py` (38 unit tests)
  - `tests/unit/test_transaction_edge_cases.py` (40 edge case tests)
  - `tests/integration/test_transaction_e2e.py` (E2E with psql/psycopg)
  - `tests/contract/test_transaction_translator_contract.py` (11 contract tests)

#### Edge Cases Handled

1. **String Literals**: `SELECT 'BEGIN'` → unchanged (BEGIN not translated inside strings)
2. **Comments**: `-- BEGIN transaction\nSELECT 1` → unchanged
3. **Whitespace**: `   BEGIN   ` → `START TRANSACTION`
4. **Case Sensitivity**: `begin`, `BEGIN`, `BeGiN` all work
5. **COMMIT/ROLLBACK variants**: `COMMIT WORK` → `COMMIT`, `ROLLBACK TRANSACTION` → `ROLLBACK`
6. **Empty inputs**: `""` → `""` (no crash)

#### References

- **Specification**: `specs/022-postgresql-transaction-verb/spec.md`
- **Implementation Plan**: `specs/022-postgresql-transaction-verb/plan.md`
- **Task List**: `specs/022-postgresql-transaction-verb/tasks.md` (54 tasks, 49 complete)
- **Contract Interface**: `specs/022-postgresql-transaction-verb/contracts/transaction_translator_interface.py`

---

