# Pytest Fixtures Contract

## Overview
This contract defines the interface, behavior, and guarantees for pytest fixtures in the IRIS PGWire testing framework.

## Session-Scoped Fixtures

### `embedded_iris`
**Purpose**: Provide shared IRIS connection for test session

**Signature**:
```python
@pytest.fixture(scope="session")
def embedded_iris() -> iris.Connection:
    """Returns connected IRIS instance for test session"""
```

**Guarantees**:
- ✅ CallIn service enabled via merge.cpf
- ✅ Connection to USER namespace active
- ✅ Connection pool initialized (max 10 connections)
- ✅ Setup completes in < 10 seconds

**Cleanup Behavior**:
- Closes all pooled connections
- Does NOT drop tables or reset data (function-scoped fixtures handle isolation)
- Releases resources cleanly

**Timeout**:
- Setup: 10 seconds max
- Teardown: 5 seconds max

**Error Handling**:
- `IRIS_ACCESSDENIED`: Fail with message "CallIn service not enabled - check merge.cpf"
- Connection timeout: Fail with diagnostic output showing IRIS container status
- Port conflict: Fail with message indicating port 1972 unavailable

**Contract Tests**: `tests/contract/test_fixture_contract.py::test_embedded_iris_fixture_*`

---

### `iris_config`
**Purpose**: Provide IRIS connection configuration dictionary

**Signature**:
```python
@pytest.fixture(scope="session")
def iris_config() -> dict:
    """Returns IRIS connection parameters"""
```

**Returns**:
```python
{
    "host": "localhost",
    "port": 1972,
    "namespace": "USER",
    "username": "_SYSTEM",
    "password": "SYS"
}
```

**Guarantees**:
- ✅ All fields present and non-empty
- ✅ Port is valid integer in range [1024, 65535]
- ✅ Configuration matches embedded IRIS setup

**Contract Tests**: `tests/contract/test_fixture_contract.py::test_iris_config_fixture_*`

---

## Function-Scoped Fixtures

### `iris_clean_namespace`
**Purpose**: Provide isolated IRIS namespace for each test

**Signature**:
```python
@pytest.fixture(scope="function")
def iris_clean_namespace(embedded_iris) -> iris.Connection:
    """Returns IRIS connection with clean namespace state"""
```

**Guarantees**:
- ✅ No conflicting test data from previous tests
- ✅ Transaction-based isolation OR namespace cleanup
- ✅ IRIS connection valid and connected
- ✅ Setup completes in < 2 seconds

**Cleanup Behavior**:
- **Option 1 (Transaction-based)**: Rollback transaction after test
- **Option 2 (Table-based)**: Drop all tables created during test
- Cleanup must complete in < 2 seconds

**Usage Example**:
```python
def test_insert_data(iris_clean_namespace):
    cursor = iris_clean_namespace.cursor()
    cursor.execute("CREATE TABLE test_users (id INT, name VARCHAR(50))")
    cursor.execute("INSERT INTO test_users VALUES (1, 'Alice')")
    # After test: table automatically dropped or transaction rolled back
```

**Timeout**:
- Setup: 2 seconds max
- Teardown: 2 seconds max

**Error Handling**:
- Table drop failure: Log warning, continue (don't fail test)
- Connection lost: Attempt reconnect from pool, fail if exhausted

**Contract Tests**: `tests/contract/test_fixture_contract.py::test_iris_clean_namespace_*`

---

### `pgwire_client`
**Purpose**: Provide PostgreSQL wire protocol client for E2E tests

**Signature**:
```python
@pytest.fixture(scope="function")
def pgwire_client(embedded_iris) -> psycopg.Connection:
    """Returns connected psycopg client to PGWire server"""
```

**Guarantees**:
- ✅ PGWire server running on port 5434 (or configured port)
- ✅ psycopg connection established
- ✅ Connection ready for query execution
- ✅ Setup completes in < 5 seconds (includes server start if needed)

**Cleanup Behavior**:
- Close psycopg connection
- Leave PGWire server running (shared across tests)
- Cleanup completes in < 1 second

**Usage Example**:
```python
def test_simple_query(pgwire_client):
    cursor = pgwire_client.cursor()
    cursor.execute("SELECT 1")
    assert cursor.fetchone()[0] == 1
```

**Timeout**:
- Setup: 5 seconds max
- Teardown: 1 second max

**Error Handling**:
- PGWire server not running: Attempt to start, fail after 5s if unsuccessful
- Connection refused: Retry 3 times with 1s delay, then fail
- Port conflict: Fail with diagnostic showing port 5434 usage

**Contract Tests**: `tests/contract/test_fixture_contract.py::test_pgwire_client_*`

---

## Fixture Dependency Graph

```
iris_config (session)
    ↓
embedded_iris (session)
    ↓
    ├─→ iris_clean_namespace (function)
    └─→ pgwire_client (function)
```

## Performance Requirements

| Fixture | Scope | Setup Time | Teardown Time |
|---------|-------|------------|---------------|
| `iris_config` | session | < 1ms | N/A |
| `embedded_iris` | session | < 10s | < 5s |
| `iris_clean_namespace` | function | < 2s | < 2s |
| `pgwire_client` | function | < 5s | < 1s |

**Total Test Overhead**: ~5-7 seconds for first test (session setup), ~2-3 seconds per subsequent test

## Resource Limits

- **IRIS Connections**: Max 10 pooled connections
- **Memory**: < 50MB per test process
- **File Descriptors**: < 100 per test process

## Contract Validation

All contracts are validated via contract tests in `tests/contract/test_fixture_contract.py`:

```python
def test_embedded_iris_fixture_provides_connection(embedded_iris):
    """Verify embedded_iris fixture returns valid IRIS connection"""
    assert embedded_iris is not None
    cursor = embedded_iris.cursor()
    cursor.execute("SELECT 1")
    assert cursor.fetchone()[0] == 1

def test_embedded_iris_fixture_cleanup_releases_resources(embedded_iris):
    """Verify fixture cleanup releases IRIS resources"""
    # Implementation TBD

def test_iris_clean_namespace_isolates_test_data(iris_clean_namespace):
    """Verify namespace isolation between tests"""
    # Create table in first test
    # Verify it doesn't exist in second test
    # Implementation TBD

def test_pgwire_client_connects_successfully(pgwire_client):
    """Verify PGWire client fixture establishes connection"""
    assert pgwire_client.status == psycopg.Connection.OK
    cursor = pgwire_client.cursor()
    cursor.execute("SELECT 1")
    assert cursor.fetchone()[0] == 1
```

These tests MUST pass before the testing framework is considered functional.
