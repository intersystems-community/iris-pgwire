# Feature Specification: irispython Server Deployment

**Feature ID**: 014-irispython-deployment
**Status**: Draft
**Created**: 2025-10-01
**Owner**: IRIS PGWire Team
**Priority**: CRITICAL (Blocking HNSW performance)

## Overview

Deploy the PostgreSQL Wire Protocol server INSIDE the IRIS process using the `irispython` command, enabling direct IRIS process access and proper VECTOR type handling.

**CONSTITUTIONAL REQUIREMENT**: "we SHOULD be running the server-side pgwire server IN python as irispython"

## Background

### Current Architecture (INCORRECT)
- PGWire server runs as **external Python process**
- Connects to IRIS via DBAPI (external connection)
- VECTOR columns show as `varchar` in INFORMATION_SCHEMA
- HNSW index provides 0% performance improvement
- Performance: 37.4 qps (12× slower than 433.9 qps target)

### Required Architecture (CORRECT)
- PGWire server runs **INSIDE IRIS process** via `irispython`
- Uses IRIS Embedded Python for direct process access
- VECTOR columns properly typed (not varchar)
- HNSW index expected to engage correctly
- Target performance: 433.9 qps (from IRIS performance report)

### Root Cause Analysis
**User Assertion**: "this IRIS version DOES HAVE A WORKING HNSW INDEX so we are screwing up somehow!"

**Investigation Finding**: The issue is NOT the code (both DBAPI and Embedded SQL paths are correctly implemented in `iris_executor.py`), but the **deployment architecture**. Running the server externally prevents proper VECTOR type handling and HNSW engagement.

## Functional Requirements

### FR-001: irispython Deployment
**Priority**: CRITICAL
**Description**: PGWire server MUST run inside IRIS using `irispython` command

**Acceptance Criteria**:
- Server executable via: `irispython /path/to/server.py`
- Runs within IRIS process space, not as external process
- Environment variables configured: IRISUSERNAME, IRISPASSWORD, IRISNAMESPACE
- Server starts successfully and accepts PostgreSQL wire protocol connections

### FR-002: Environment Configuration
**Priority**: CRITICAL
**Description**: Proper environment variables for embedded Python authentication

**Required Variables**:
```bash
export IRISUSERNAME=_SYSTEM
export IRISPASSWORD=SYS
export IRISNAMESPACE=USER
```

**Acceptance Criteria**:
- Variables set before `irispython` invocation
- Embedded Python can access IRIS without additional authentication
- iris.sql.exec() functions without connection setup

### FR-003: Docker Integration
**Priority**: CRITICAL
**Description**: docker-compose.yml configured for embedded deployment

**Current docker-compose.yml** (INCORRECT):
```yaml
services:
  pgwire:
    build: .
    command: python -m iris_pgwire.server  # WRONG: external process
    ports:
      - "5432:5432"
```

**Required docker-compose.yml** (CORRECT):
```yaml
services:
  iris:
    image: containers.intersystems.com/intersystems/iris:latest-preview
    ports:
      - "5432:5432"  # PGWire port
      - "1972:1972"  # SuperServer port
    environment:
      - IRISUSERNAME=_SYSTEM
      - IRISPASSWORD=SYS
      - IRISNAMESPACE=USER
    volumes:
      - ./src:/app/src
      - ./iris.key:/usr/irissys/mgr/iris.key  # Vector licensing
    command: >
      sh -c "irispython /app/src/iris_pgwire/server.py"
```

**Acceptance Criteria**:
- Server runs inside IRIS container
- No separate Python container needed
- irispython command used for server startup
- Vector licensing (iris.key) properly mounted

### FR-004: VECTOR Type Validation
**Priority**: CRITICAL
**Description**: Verify VECTOR columns created correctly when running embedded

**Test Query**:
```sql
CREATE TABLE test_embedded (
    id INTEGER PRIMARY KEY,
    vec VECTOR(FLOAT, 1024)
);

SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'test_embedded';
```

**Expected Result**: `('vec', 'VECTOR')` NOT `('vec', 'varchar')`

**Acceptance Criteria**:
- VECTOR columns show as 'VECTOR' type in INFORMATION_SCHEMA
- No varchar conversion when using embedded deployment
- HNSW index creation succeeds on VECTOR columns
- TO_VECTOR() function works correctly

### FR-005: HNSW Performance Validation
**Priority**: CRITICAL
**Description**: HNSW index provides expected performance improvement with embedded deployment

**Performance Test**:
```python
# Create HNSW index with ACORN-1
CREATE INDEX idx_hnsw_vec ON test_embedded(vec) AS HNSW
SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1

# Benchmark vector similarity queries
SELECT id FROM test_embedded
ORDER BY VECTOR_COSINE(vec, TO_VECTOR('[...]'))
LIMIT 5
```

**Acceptance Criteria**:
- HNSW index provides >4.5× improvement over linear scan
- Average latency <5ms for 1024-dimensional vectors
- Throughput >433.9 qps at 16 clients
- Zero SLA violations in performance monitoring

## Performance Requirements

### PR-001: Constitutional 5ms SLA
**Requirement**: All SQL transformations MUST complete within 5ms (constitutional mandate)

**Validation**:
- Vector Query Optimizer already compliant: 0.36ms P95 (14× faster than SLA)
- Total query latency target: <5ms for HNSW-optimized queries
- Monitoring: Real-time SLA violation tracking

### PR-002: HNSW Throughput Target
**Requirement**: Vector similarity queries MUST achieve ≥433.9 ops/sec at 16 clients

**Baseline** (from IRIS performance report):
- Target: 433.9 ops/sec @ 16 clients
- HNSW improvement factor: 4.5× over linear scan
- Current (external deployment): 37.4 qps (12× slower)

**Expected** (embedded deployment):
- Throughput: ≥433.9 qps
- Latency: <5ms P95 for 1024-dimensional vectors
- HNSW engagement: >90% of vector queries

## Technical Implementation

### Implementation Path 1: Update docker-compose.yml

**File**: `/Users/tdyar/ws/iris-pgwire/docker-compose.yml`

**Changes Required**:
1. Remove separate pgwire service
2. Run server inside IRIS container using irispython
3. Configure environment variables for authentication
4. Mount source code into IRIS container
5. Expose port 5432 from IRIS container

### Implementation Path 2: Startup Script

**Create**: `/Users/tdyar/ws/iris-pgwire/scripts/start_embedded_server.sh`

```bash
#!/bin/bash
# Start PGWire server inside IRIS using embedded Python

export IRISUSERNAME=${IRISUSERNAME:-_SYSTEM}
export IRISPASSWORD=${IRISPASSWORD:-SYS}
export IRISNAMESPACE=${IRISNAMESPACE:-USER}

# Run server via irispython
irispython /app/src/iris_pgwire/server.py
```

**Acceptance Criteria**:
- Script executable from IRIS container
- Environment variables properly set
- Server starts and accepts connections
- Logging indicates embedded mode active

### Implementation Path 3: Code Validation

**File**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/iris_executor.py`

**Verification**:
- Lines 104, 165, 260-262: iris.sql.exec() usage ✅ CORRECT
- Lines 519-541: Transaction management via iris.sql.exec() ✅ CORRECT
- Embedded mode detection working ✅ CORRECT

**No code changes required** - implementation already correct, just needs embedded deployment.

## Testing & Validation

### Test 1: Embedded Deployment Verification
**File**: `tests/deployment/test_embedded_deployment.py`

```python
def test_server_runs_via_irispython():
    """GIVEN: IRIS container with PGWire source
    WHEN: Starting server via irispython command
    THEN: Server accepts PostgreSQL connections"""

    # Start server
    subprocess.Popen([
        'docker', 'exec', 'iris-container',
        'irispython', '/app/src/iris_pgwire/server.py'
    ])

    # Wait for startup
    time.sleep(2)

    # Test connection
    import psycopg
    with psycopg.connect("host=localhost port=5432") as conn:
        assert conn.status == psycopg.Connection.OK
```

### Test 2: VECTOR Type Validation
**File**: `tests/deployment/test_vector_type_embedded.py`

```python
def test_vector_type_correct_when_embedded():
    """GIVEN: Server running via irispython
    WHEN: Creating table with VECTOR column
    THEN: INFORMATION_SCHEMA shows 'VECTOR', not 'varchar'"""

    with psycopg.connect("host=localhost port=5432") as conn:
        cur = conn.cursor()

        # Create table
        cur.execute("""
            CREATE TABLE test_vector_embedded (
                id INTEGER PRIMARY KEY,
                vec VECTOR(FLOAT, 1024)
            )
        """)

        # Query type
        cur.execute("""
            SELECT DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'test_vector_embedded'
            AND COLUMN_NAME = 'vec'
        """)

        data_type = cur.fetchone()[0]
        assert data_type == 'VECTOR', f"Expected VECTOR, got {data_type}"
```

### Test 3: HNSW Performance Benchmark
**File**: `tests/deployment/test_hnsw_performance_embedded.py`

```python
def test_hnsw_performance_with_embedded_deployment():
    """GIVEN: Server running via irispython with HNSW index
    WHEN: Executing vector similarity queries
    THEN: Performance meets 433.9 qps target"""

    # Create HNSW index
    with psycopg.connect("host=localhost port=5432") as conn:
        cur = conn.cursor()
        cur.execute("SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1")
        cur.execute("CREATE INDEX idx_hnsw ON test_1024(vec) AS HNSW")

    # Benchmark performance
    times = []
    for i in range(100):
        vec = generate_random_vector(1024)
        start = time.perf_counter()

        cur.execute("""
            SELECT id FROM test_1024
            ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))
            LIMIT 5
        """, (vec,))
        cur.fetchall()

        times.append((time.perf_counter() - start) * 1000)

    avg_ms = sum(times) / len(times)
    qps = 100 / (sum(times) / 1000)

    assert avg_ms < 5.0, f"Latency {avg_ms:.2f}ms exceeds 5ms SLA"
    assert qps >= 433.9, f"Throughput {qps:.1f} below 433.9 qps target"
```

## Deployment Procedure

### Step 1: Update docker-compose.yml
```bash
# Edit docker-compose.yml to use embedded deployment
vim docker-compose.yml

# Verify configuration
docker-compose config
```

### Step 2: Rebuild and Start
```bash
# Stop current deployment (if running)
docker-compose down

# Start with embedded deployment
docker-compose up -d iris

# Verify server running inside IRIS
docker logs iris-container | grep "PGWire server started"
```

### Step 3: Validate VECTOR Type
```bash
# Connect and test
psql -h localhost -p 5432 -c "
CREATE TABLE test_embedded (id INTEGER, vec VECTOR(FLOAT, 1024));
SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'test_embedded' AND COLUMN_NAME = 'vec';
"
# Expected output: VECTOR (not varchar)
```

### Step 4: Benchmark HNSW Performance
```bash
# Run performance tests
uv run python tests/deployment/test_hnsw_performance_embedded.py

# Expected results:
# - Avg latency: <5ms
# - Throughput: >433.9 qps
# - HNSW improvement: >4.5×
```

## Success Criteria

### SC-001: Deployment Architecture
- ✅ PGWire server runs inside IRIS via irispython
- ✅ No external Python process required
- ✅ Environment variables configured correctly
- ✅ Vector licensing (iris.key) mounted and active

### SC-002: Type System Correctness
- ✅ VECTOR columns show as 'VECTOR' in INFORMATION_SCHEMA
- ✅ No varchar conversion
- ✅ HNSW index creation succeeds
- ✅ TO_VECTOR() function works correctly

### SC-003: HNSW Performance
- ✅ Average latency <5ms for 1024-dimensional vectors
- ✅ Throughput ≥433.9 qps at 16 clients
- ✅ HNSW provides >4.5× improvement over linear scan
- ✅ Zero SLA violations in constitutional monitoring

### SC-004: Constitutional Compliance
- ✅ Translation SLA: <5ms (already 0.36ms P95)
- ✅ Performance monitoring active
- ✅ SLA violation tracking functional
- ✅ Governance compliance reporting operational

## Dependencies

### Prerequisite Features
- ✅ 013-vector-query-optimizer (implemented, 100% SLA compliant)
- ✅ DBAPI and Embedded SQL paths in iris_executor.py
- ✅ ACORN-1 configuration syntax validated
- ✅ Vector licensing (iris.key) available

### External Dependencies
- IRIS Build: 2025.3.0EHAT.127.0-linux-arm64v8 or later
- Docker: docker-compose v2.0+
- Python: 3.11+ (embedded in IRIS)
- irispython: Available in IRIS bin directory

## Risks & Mitigation

### Risk 1: Port Conflicts
**Risk**: Port 5432 already in use by external PostgreSQL
**Mitigation**: Use different port or stop conflicting service
**Severity**: LOW (configuration issue)

### Risk 2: Permission Issues
**Risk**: irispython may lack permissions for network binding
**Mitigation**: Run IRIS container with appropriate capabilities
**Severity**: MEDIUM (deployment blocker)

### Risk 3: Performance Assumptions
**Risk**: Embedded deployment may not fix HNSW issue
**Mitigation**: Have fallback investigation plan
**Severity**: MEDIUM (requires deeper investigation)

## References

- HNSW Investigation: [docs/HNSW_INVESTIGATION.md](../../docs/HNSW_INVESTIGATION.md)
- Dual-Path Architecture: [docs/DUAL_PATH_ARCHITECTURE.md](../../docs/DUAL_PATH_ARCHITECTURE.md)
- Vector Query Optimizer: [specs/013-vector-query-optimizer/](../013-vector-query-optimizer/)
- IRIS Embedded Python Docs: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=AEPYTHON
- Constitutional Governance: [.specify/memory/constitution.md](../../.specify/memory/constitution.md)

## Appendix: irispython Command Reference

### Basic Usage
```bash
# Run Python script inside IRIS
irispython /path/to/script.py

# With environment variables
export IRISUSERNAME=_SYSTEM
export IRISPASSWORD=SYS
export IRISNAMESPACE=USER
irispython /path/to/script.py
```

### Docker Execution
```bash
# From docker-compose.yml
command: >
  sh -c "
    export IRISUSERNAME=_SYSTEM && \
    export IRISPASSWORD=SYS && \
    export IRISNAMESPACE=USER && \
    irispython /app/src/iris_pgwire/server.py
  "

# Manual docker exec
docker exec -it iris-container \
  env IRISUSERNAME=_SYSTEM IRISPASSWORD=SYS IRISNAMESPACE=USER \
  irispython /app/src/iris_pgwire/server.py
```

### Debugging
```bash
# Check if irispython available
docker exec iris-container which irispython

# Test embedded Python
docker exec iris-container irispython -c "import iris; print(iris.sql.exec('SELECT 1'))"

# View server logs
docker logs -f iris-container
```

---

**Document Status**: DRAFT - Ready for implementation
**Next Step**: Update docker-compose.yml and deploy
**Priority**: CRITICAL (blocks HNSW performance validation)
