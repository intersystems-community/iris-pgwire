# Dual-Path IRIS Integration Architecture

## Constitutional Requirement

**MANDATE**: The IRIS PostgreSQL Wire Protocol implementation MUST support TWO distinct SQL execution paths:

1. **DBAPI Path**: SQL execution via cursor (intersystems-iris package)
2. **Embedded Python Path**: SQL execution via iris.sql.exec() (native IRIS API)

**CRITICAL SERVER DEPLOYMENT REQUIREMENT**: The PGWire server itself MUST run INSIDE IRIS using the `irispython` command, not as an external Python process.

**Constitutional Principle**: "We are supposed to have 2 IRIS paths - DBAPI AND iris.sql.exec() which is Embedded Python - and compare both of those to postgresql"

**Deployment Principle**: "we SHOULD be running the server-side pgwire server IN python as irispython"

## Architecture Overview

```
DEPLOYMENT: irispython server.py
           │
           ▼
PostgreSQL Wire Protocol Server (RUNNING INSIDE IRIS PROCESS)
           │
           ├─→ SQL Execution Path 1: DBAPI (iris.createConnection)
           │   ├─ External-style connection (but same process)
           │   ├─ Cursor-based execution
           │   ├─ Type mapping via DBAPI layer
           │   └─ May show VECTOR → varchar in INFORMATION_SCHEMA
           │
           └─→ SQL Execution Path 2: Embedded (iris.sql.exec)
               ├─ Direct IRIS API access
               ├─ Native IRIS type system
               ├─ No DBAPI translation layer
               └─ Proper VECTOR type handling
```

**KEY INSIGHT**: Both paths are SQL execution methods, NOT server deployment methods. The server itself runs inside IRIS via `irispython`, and from there can execute SQL using either DBAPI or Embedded APIs.

## Path Comparison Matrix

| Feature | DBAPI Path | Embedded Python Path | PostgreSQL (Reference) |
|---------|-----------|---------------------|------------------------|
| **Connection** | `iris.createConnection()` | Native IRIS API | `psycopg2.connect()` |
| **Execution** | `cursor.execute(sql)` | `iris.sql.exec(sql)` | `cursor.execute(sql)` |
| **Type System** | DBAPI type mapping | Native IRIS types | PostgreSQL native |
| **VECTOR Type** | Shows as varchar ❌ | True VECTOR ✅ | vector (pgvector) |
| **HNSW Support** | Unknown (blocked) | Expected ✅ | pgvector HNSW ✅ |
| **Performance** | 37.4 qps (measured) | TBD | 934.9 qps (measured) |

## Implementation Requirements

### 1. DBAPI Path (Current - Partial Implementation)

**Status**: ✅ Implemented but VECTOR type issue blocking HNSW

**Implementation**:
```python
# src/iris_pgwire/iris_executor.py (current)
class IRISExecutor:
    def __init__(self):
        self.connection = iris.createConnection('localhost', 1972, 'USER', '_SYSTEM', 'SYS')

    def execute_query(self, sql: str, params=None):
        cursor = self.connection.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        return cursor.fetchall()
```

**Known Limitations**:
- VECTOR columns appear as varchar in INFORMATION_SCHEMA
- May prevent HNSW index optimization
- Type mapping inconsistencies

### 2. Embedded Python Path (REQUIRED - Not Yet Implemented)

**Status**: ❌ NOT IMPLEMENTED (blocking HNSW validation)

**Required Research**:
```python
# Pattern from CLAUDE.md (doesn't work - no iris.sql attribute)
def iris_exec():
    import iris
    return iris.sql.exec(sql)  # AttributeError: module 'iris' has no attribute 'sql'

# Available iris module attributes (confirmed)
# ['connect', 'createConnection', 'createIRIS', 'IRIS', 'IRISConnection', ...]

# TODO: Research correct IRIS Embedded Python API
```

**Required Implementation**:
```python
# src/iris_pgwire/iris_executor_embedded.py (NEW FILE)
class IRISEmbeddedExecutor:
    """Execute IRIS operations via Embedded Python (native IRIS API)"""

    def __init__(self):
        # TODO: Research correct initialization
        pass

    def execute_ddl(self, ddl: str):
        """Execute DDL with proper VECTOR type support"""
        # TODO: Find correct API for DDL execution
        pass

    def execute_query(self, sql: str, params=None):
        """Execute query using native IRIS API"""
        # TODO: Find correct API for query execution
        pass

    def create_vector_table(self, table_name: str, dimension: int):
        """Create table with TRUE VECTOR column type"""
        # TODO: Implement using Embedded Python to avoid varchar issue
        pass
```

### 3. Dual-Path Integration Layer

**Status**: ❌ NOT IMPLEMENTED

**Required Implementation**:
```python
# src/iris_pgwire/dual_path_manager.py (NEW FILE)
class DualPathManager:
    """Manage both DBAPI and Embedded Python execution paths"""

    def __init__(self):
        self.dbapi_executor = IRISExecutor()
        self.embedded_executor = IRISEmbeddedExecutor()
        self.preferred_path = 'embedded'  # Default to Embedded Python

    def execute_ddl(self, ddl: str, path: str = None):
        """Execute DDL using specified or preferred path"""
        executor = self._select_executor(path)
        return executor.execute_ddl(ddl)

    def execute_query(self, sql: str, params=None, path: str = None):
        """Execute query using specified or preferred path"""
        executor = self._select_executor(path)
        return executor.execute_query(sql, params)

    def _select_executor(self, path: str = None):
        """Select executor based on path preference"""
        if path == 'dbapi':
            return self.dbapi_executor
        elif path == 'embedded':
            return self.embedded_executor
        else:
            return self.embedded_executor if self.preferred_path == 'embedded' else self.dbapi_executor
```

## DDL Procedures: Strong Table Creation

### DBAPI Path (Current - Known Issues)

```python
# DBAPI table creation (creates varchar, not VECTOR)
def create_vector_table_dbapi(table_name: str, dimension: int):
    """Create vector table via DBAPI (has varchar limitation)"""
    conn = iris.createConnection('localhost', 1972, 'USER', '_SYSTEM', 'SYS')
    cur = conn.cursor()

    ddl = f"""
    CREATE TABLE {table_name} (
        id INTEGER PRIMARY KEY,
        vec VECTOR(FLOAT, {dimension})
    )
    """
    cur.execute(ddl)

    # HNSW index creation
    cur.execute('SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1')
    cur.execute(f'CREATE INDEX idx_hnsw_vec ON {table_name}(vec) AS HNSW')

    # Verify column type
    cur.execute(f"""
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = '{table_name}'
    """)
    result = cur.fetchall()
    # Expected: [('id', 'INTEGER'), ('vec', 'VECTOR')]
    # Actual:   [('id', 'INTEGER'), ('vec', 'varchar')]  ← PROBLEM
```

### Embedded Python Path (REQUIRED - To Be Implemented)

```python
# Embedded Python table creation (expected to create true VECTOR)
def create_vector_table_embedded(table_name: str, dimension: int):
    """Create vector table via Embedded Python (proper VECTOR type)"""
    # TODO: Research and implement correct API

    # Expected DDL execution (correct API TBD)
    ddl = f"""
    CREATE TABLE {table_name} (
        id INTEGER PRIMARY KEY,
        vec VECTOR(FLOAT, {dimension})
    )
    """
    # embedded_executor.execute_ddl(ddl)

    # HNSW index creation
    # embedded_executor.execute_ddl('SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1')
    # embedded_executor.execute_ddl(f'CREATE INDEX idx_hnsw_vec ON {table_name}(vec) AS HNSW')

    # Verify column type
    # result = embedded_executor.execute_query(f"""
    #     SELECT COLUMN_NAME, DATA_TYPE
    #     FROM INFORMATION_SCHEMA.COLUMNS
    #     WHERE TABLE_NAME = '{table_name}'
    # """)
    # Expected: [('id', 'INTEGER'), ('vec', 'VECTOR')]  ← Should be correct
```

## Testing Requirements

### Path Comparison Tests

```python
# tests/integration/test_dual_path_comparison.py (NEW FILE)
import pytest

class TestDualPathComparison:
    """Compare DBAPI vs Embedded Python execution paths"""

    def test_table_creation_type_correctness(self):
        """GIVEN: Same DDL executed via both paths
        WHEN: Create table with VECTOR column
        THEN: Embedded Python should create true VECTOR, DBAPI may create varchar
        """
        # Create via DBAPI
        dbapi_table = create_vector_table_dbapi('test_dbapi', 1024)

        # Create via Embedded Python
        embedded_table = create_vector_table_embedded('test_embedded', 1024)

        # Verify column types
        dbapi_type = get_column_type('test_dbapi', 'vec')
        embedded_type = get_column_type('test_embedded', 'vec')

        # Assertions
        assert embedded_type == 'VECTOR', "Embedded Python should create true VECTOR"
        # Note: DBAPI may show varchar due to limitation

    def test_hnsw_performance_comparison(self):
        """GIVEN: HNSW index on both path-created tables
        WHEN: Execute vector similarity queries
        THEN: Compare performance between paths
        """
        # Test DBAPI-created table
        dbapi_performance = benchmark_vector_queries('test_dbapi', num_queries=100)

        # Test Embedded Python-created table
        embedded_performance = benchmark_vector_queries('test_embedded', num_queries=100)

        # Report comparison
        print(f"DBAPI avg: {dbapi_performance.avg_ms}ms")
        print(f"Embedded avg: {embedded_performance.avg_ms}ms")
        print(f"HNSW working: {embedded_performance.avg_ms < 5.0}")

    def test_postgresql_comparison(self):
        """GIVEN: All three systems (DBAPI, Embedded, PostgreSQL)
        WHEN: Execute identical vector similarity workload
        THEN: Compare performance and correctness
        """
        # IRIS DBAPI
        iris_dbapi_perf = benchmark_iris_dbapi(queries=100)

        # IRIS Embedded Python
        iris_embedded_perf = benchmark_iris_embedded(queries=100)

        # PostgreSQL pgvector
        postgres_perf = benchmark_postgresql(queries=100)

        # Comparison report
        report = {
            'iris_dbapi': iris_dbapi_perf.to_dict(),
            'iris_embedded': iris_embedded_perf.to_dict(),
            'postgresql': postgres_perf.to_dict(),
            'target_performance': 433.9,  # ops/sec from IRIS report
        }

        # Log comparison
        print(f"\nPerformance Comparison:")
        print(f"  IRIS DBAPI:     {iris_dbapi_perf.qps:.1f} qps")
        print(f"  IRIS Embedded:  {iris_embedded_perf.qps:.1f} qps")
        print(f"  PostgreSQL:     {postgres_perf.qps:.1f} qps")
        print(f"  Target:         433.9 qps")
```

## Action Plan

### Phase 1: Research (IMMEDIATE)
1. ✅ Document dual-path requirement (this document)
2. ⏳ Research correct IRIS Embedded Python API
3. ⏳ Find DDL execution method in Embedded Python
4. ⏳ Verify VECTOR type handling in Embedded Python

### Phase 2: Implementation (BLOCKING HNSW FIX)
5. ⏳ Implement IRISEmbeddedExecutor class
6. ⏳ Implement DualPathManager integration layer
7. ⏳ Create strong DDL procedures using Embedded Python
8. ⏳ Implement path selection logic in protocol handler

### Phase 3: Testing & Validation
9. ⏳ Create dual-path comparison tests
10. ⏳ Benchmark both paths vs PostgreSQL
11. ⏳ Validate HNSW works with Embedded Python tables
12. ⏳ Document type system differences

### Phase 4: Integration
13. ⏳ Update CLAUDE.md with correct patterns
14. ⏳ Update specs with dual-path architecture
15. ⏳ Add constitutional requirement to governance
16. ⏳ Create migration guide for DBAPI → Embedded Python

## References

- HNSW Investigation: [docs/HNSW_INVESTIGATION.md](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/HNSW_INVESTIGATION.md)
- Constitutional Governance: [src/iris_pgwire/constitutional.py](https://github.com/intersystems-community/iris-pgwire/blob/main/src/iris_pgwire/constitutional.py)
- CLAUDE.md: [CLAUDE.md](https://github.com/intersystems-community/iris-pgwire/blob/main/CLAUDE.md)
- User Requirement: "we need to put this in the specs and constitution!!!!!!!"

## Constitutional Status

**Compliance**: ❌ NON-COMPLIANT (missing Embedded Python path)

**Required for Compliance**:
1. Implement both DBAPI and Embedded Python execution paths
2. Document both paths in specifications
3. Compare both paths to PostgreSQL reference
4. Validate HNSW works with correct path

**Blocking Issue**: Unknown correct IRIS Embedded Python API for DDL/query execution

---

**Document Status**: DRAFT - Requires implementation research
**Next Step**: Research IRIS Embedded Python API documentation
**Priority**: CRITICAL (blocking HNSW validation)
