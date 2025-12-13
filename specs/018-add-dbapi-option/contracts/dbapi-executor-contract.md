# Contract: DBAPI Executor

**Component**: `dbapi_executor.py`
**Purpose**: Execute SQL queries against IRIS using intersystems-irispython DBAPI with connection pooling

## Interface Contract

### `DBAPIExecutor`

**Responsibilities**:
- Manage DBAPI connection pool (50 base + 20 overflow)
- Execute SQL queries via pooled connections
- Support large vector operations (>1000 dimensions)
- Maintain constitutional <5ms translation overhead
- Handle connection failures with retry logic

### Methods

#### `__init__(config: BackendConfig)`

**Contract**:
- **Input**: Valid `BackendConfig` with DBAPI settings
- **Output**: Initialized executor with connection pool
- **Postconditions**:
  - Connection pool created with specified size
  - Initial connections established and validated
  - Health checker initialized
- **Exceptions**:
  - `ConnectionError`: Cannot connect to IRIS

**Example**:
```python
config = BackendConfig(
    backend_type="dbapi",
    iris_hostname="localhost",
    iris_port=1972,
    pool_size=50
)
executor = DBAPIExecutor(config)
assert executor.pool.connections_available == 50
```

#### `async execute_query(sql: str, params: Optional[list] = None) -> list[tuple]`

**Contract**:
- **Input**:
  - `sql`: Valid IRIS SQL query (already translated from PostgreSQL)
  - `params`: Optional query parameters
- **Output**: List of result tuples
- **Preconditions**:
  - Pool initialized and healthy
  - `sql` is valid IRIS SQL (not PostgreSQL)
- **Postconditions**:
  - Query executed successfully
  - Connection returned to pool
  - Metrics recorded (execution time, row count)
- **Performance**:
  - Query execution overhead <5ms (constitutional SLA)
  - Connection acquisition <1ms
- **Exceptions**:
  - `TimeoutError`: Pool exhausted (no connections available)
  - `iris.Error`: IRIS SQL error
  - `ConnectionError`: IRIS unreachable

**Example**:
```python
executor = DBAPIExecutor(config)
results = await executor.execute_query("SELECT TOP 5 * FROM vectors")
assert len(results) <= 5
assert isinstance(results[0], tuple)
```

#### `async execute_vector_query(request: VectorQueryRequest) -> list[tuple]`

**Contract**:
- **Input**: `VectorQueryRequest` with >1000 dimension vector
- **Output**: List of result tuples with similarity scores
- **Preconditions**:
  - Query already translated (pgvector → IRIS VECTOR functions)
  - Vector dimensions match schema (1-2048)
- **Postconditions**:
  - Vector query executed via DBAPI
  - Results ordered by similarity
  - Translation time <5ms (constitutional SLA)
- **Performance**:
  - Comparable to pgvector PostgreSQL (clarified requirement)
  - HNSW index used if dataset ≥100K vectors
- **Exceptions**:
  - `ValueError`: Vector dimensions mismatch
  - `iris.Error`: Invalid VECTOR function call

**Example**:
```python
request = VectorQueryRequest(
    translated_sql="SELECT TOP 5 * FROM vectors ORDER BY VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,...]', 'DECIMAL'))",
    query_vector=[0.1, 0.2, ...],  # >1000 dimensions
    limit_clause=5
)
results = await executor.execute_vector_query(request)
assert len(results) == 5
```

#### `async health_check() -> bool`

**Contract**:
- **Input**: None
- **Output**: `True` if healthy, `False` if degraded
- **Health Criteria**:
  - At least 1 connection available in pool
  - Test query (`SELECT 1`) succeeds
  - Average acquisition time <10ms
- **Side Effects**: Updates `health_status` metric

**Example**:
```python
executor = DBAPIExecutor(config)
is_healthy = await executor.health_check()
assert is_healthy == True
```

#### `async close()`

**Contract**:
- **Input**: None
- **Output**: None
- **Postconditions**:
  - All pooled connections closed
  - Pool marked as closed
  - No new connections accepted
- **Side Effects**: Drains connection pool gracefully

**Example**:
```python
executor = DBAPIExecutor(config)
await executor.close()
assert executor.pool.connections_available == 0
```

---

## Connection Pool Contract

### `IRISConnectionPool`

#### `async acquire() -> PooledConnection`

**Contract**:
- **Output**: Available connection from pool
- **Timeout**: `pool_timeout` seconds (default 30s)
- **Validation**: Connection validated before return
- **Recycling**: Connections >1 hour old are recycled
- **Exceptions**:
  - `TimeoutError`: No connections available within timeout

#### `async release(conn: PooledConnection)`

**Contract**:
- **Input**: Connection to return to pool
- **Postconditions**:
  - Connection returned to queue (if pool not full)
  - Connection closed (if pool full)
- **No Exceptions**: Always succeeds (logs errors)

---

## Test Contract

**File**: `tests/contract/test_dbapi_executor_contract.py`

### Test Cases (TDD - Must Fail Initially)

```python
def test_dbapi_executor_initializes_pool():
    """GIVEN valid DBAPI configuration
       WHEN DBAPIExecutor is created
       THEN connection pool is initialized with correct size"""
    config = BackendConfig(backend_type="dbapi", pool_size=50)
    executor = DBAPIExecutor(config)

    assert executor.pool.pool_size == 50
    assert executor.pool.connections_available > 0


@pytest.mark.asyncio
async def test_dbapi_executor_executes_simple_query(embedded_iris):
    """GIVEN initialized DBAPI executor
       WHEN execute_query is called with simple SQL
       THEN query executes and returns results"""
    executor = DBAPIExecutor(test_config)
    results = await executor.execute_query("SELECT 1 AS test")

    assert len(results) == 1
    assert results[0][0] == 1


@pytest.mark.asyncio
async def test_dbapi_executor_handles_large_vectors(embedded_iris):
    """GIVEN vector query with >1000 dimensions
       WHEN execute_vector_query is called
       THEN query executes successfully via DBAPI"""
    # Setup: Create table with 1024-dim vector
    await executor.execute_query(
        "CREATE TABLE test_vectors (id INT, embedding VECTOR(DECIMAL, 1024))"
    )

    # Execute vector similarity query
    request = VectorQueryRequest(
        translated_sql="SELECT TOP 5 * FROM test_vectors ORDER BY VECTOR_COSINE(embedding, TO_VECTOR(..., 'DECIMAL'))",
        query_vector=[0.1] * 1024,  # 1024 dimensions
        limit_clause=5
    )
    results = await executor.execute_vector_query(request)

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_dbapi_executor_pool_handles_1000_concurrent_connections(embedded_iris):
    """GIVEN 1000 concurrent client connections
       WHEN all execute queries simultaneously
       THEN pool handles load with 50 connections"""
    executor = DBAPIExecutor(BackendConfig(pool_size=50, pool_max_overflow=20))

    async def concurrent_query(i):
        return await executor.execute_query(f"SELECT {i} AS id")

    # Simulate 1000 concurrent connections
    tasks = [concurrent_query(i) for i in range(1000)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 1000
    assert executor.pool.connections_in_use <= 70  # 50 + 20 overflow


@pytest.mark.asyncio
async def test_dbapi_executor_reconnects_after_iris_restart(embedded_iris):
    """GIVEN IRIS instance restarts during operation
       WHEN execute_query is called
       THEN executor reconnects automatically"""
    executor = DBAPIExecutor(test_config)

    # Simulate IRIS restart (close all connections)
    await executor.pool.close()

    # Should reconnect automatically
    results = await executor.execute_query("SELECT 1")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_dbapi_executor_translation_time_under_5ms(embedded_iris):
    """GIVEN complex vector query
       WHEN query is executed
       THEN total overhead <5ms (constitutional SLA)"""
    executor = DBAPIExecutor(test_config)

    start = time.perf_counter()
    await executor.execute_query("SELECT TOP 5 * FROM vectors")
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Note: This tests executor overhead, not IRIS execution time
    assert elapsed_ms < 5.0, f"Executor overhead {elapsed_ms}ms exceeds 5ms SLA"
```

---

## Performance Benchmarks

| Metric | Target | Measured | Status |
|--------|--------|----------|--------|
| Connection acquisition | <1ms | TBD | ⏳ |
| Query execution overhead | <5ms | TBD | ⏳ |
| Pool exhaustion recovery | <100ms | TBD | ⏳ |
| Vector query (1024-dim) | Comparable to pgvector | TBD | ⏳ |

---

## Error Handling

### Connection Pool Exhaustion

```python
try:
    conn = await pool.acquire()
except TimeoutError:
    logger.error("Connection pool exhausted",
                 pool_size=pool.pool_size,
                 in_use=pool.connections_in_use)
    raise
```

### IRIS Restart During Query

```python
try:
    results = await executor.execute_query(sql)
except ConnectionError:
    logger.warning("IRIS connection lost, reconnecting...")
    await executor.reconnect()
    results = await executor.execute_query(sql)  # Retry once
```

---

**Contract Status**: ✅ Defined, awaiting implementation
