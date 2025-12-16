# Contract: Backend Selector

**Component**: `backend_selector.py`
**Purpose**: Configuration-driven selection between DBAPI and Embedded Python backends

## Interface Contract

### `BackendSelector`

**Responsibilities**:
- Read backend configuration from environment/file
- Instantiate correct executor based on configuration
- Validate configuration before backend creation
- Provide unified interface for both backends

### Methods

#### `select_backend(config: BackendConfig) -> Executor`

**Contract**:
- **Input**: `BackendConfig` with valid `backend_type`
- **Output**: Either `DBAPIExecutor` or `EmbeddedExecutor` instance
- **Preconditions**:
  - `config.backend_type in ["dbapi", "embedded"]`
  - If `backend_type == "dbapi"`: All IRIS connection params must be valid
- **Postconditions**:
  - Returned executor is ready to execute queries
  - Connection pool initialized (if DBAPI backend)
- **Exceptions**:
  - `ValueError`: Invalid backend_type
  - `ConnectionError`: Cannot connect to IRIS (DBAPI only)

**Example**:
```python
config = BackendConfig(backend_type="dbapi", iris_hostname="localhost")
selector = BackendSelector()
executor = selector.select_backend(config)
assert isinstance(executor, DBAPIExecutor)
```

#### `validate_config(config: BackendConfig) -> bool`

**Contract**:
- **Input**: `BackendConfig` object
- **Output**: `True` if valid, raises exception otherwise
- **Validation Rules**:
  - `backend_type` must be "dbapi" or "embedded"
  - If DBAPI: hostname, port, namespace, username, password required
  - `pool_size > 0 and pool_size <= 200`
  - `pool_max_overflow >= 0 and pool_max_overflow <= 100`
  - `pool_size + pool_max_overflow <= 200`
- **Exceptions**:
  - `ValueError`: Validation failure with specific error message

**Example**:
```python
config = BackendConfig(backend_type="invalid")
try:
    selector.validate_config(config)
    assert False, "Should have raised ValueError"
except ValueError as e:
    assert "Invalid backend_type" in str(e)
```

---

## Test Contract

**File**: `tests/contract/test_backend_selector_contract.py`

### Test Cases (TDD - Must Fail Initially)

```python
def test_backend_selector_creates_dbapi_executor():
    """GIVEN valid DBAPI configuration
       WHEN select_backend is called
       THEN DBAPIExecutor instance is returned"""
    config = BackendConfig(
        backend_type="dbapi",
        iris_hostname="localhost",
        iris_port=1972,
        iris_namespace="USER",
        iris_username="_SYSTEM",
        iris_password="SYS"
    )
    selector = BackendSelector()
    executor = selector.select_backend(config)

    assert isinstance(executor, DBAPIExecutor)
    assert executor.backend_type == "dbapi"


def test_backend_selector_creates_embedded_executor():
    """GIVEN embedded backend configuration
       WHEN select_backend is called
       THEN EmbeddedExecutor instance is returned"""
    config = BackendConfig(backend_type="embedded")
    selector = BackendSelector()
    executor = selector.select_backend(config)

    assert isinstance(executor, EmbeddedExecutor)
    assert executor.backend_type == "embedded"


def test_backend_selector_validates_pool_limits():
    """GIVEN configuration with pool_size + overflow > 200
       WHEN validate_config is called
       THEN ValueError is raised"""
    config = BackendConfig(
        backend_type="dbapi",
        pool_size=180,
        pool_max_overflow=50  # Total 230 > 200
    )
    selector = BackendSelector()

    with pytest.raises(ValueError, match="exceeds maximum"):
        selector.validate_config(config)


def test_backend_selector_requires_credentials_for_dbapi():
    """GIVEN DBAPI config without credentials
       WHEN validate_config is called
       THEN ValueError is raised"""
    config = BackendConfig(
        backend_type="dbapi",
        iris_hostname="localhost"
        # Missing username/password
    )
    selector = BackendSelector()

    with pytest.raises(ValueError, match="credentials required"):
        selector.validate_config(config)


def test_backend_selector_rejects_invalid_backend_type():
    """GIVEN invalid backend_type
       WHEN select_backend is called
       THEN ValueError is raised"""
    config = BackendConfig(backend_type="invalid")
    selector = BackendSelector()

    with pytest.raises(ValueError, match="Invalid backend_type"):
        selector.select_backend(config)
```

---

## Configuration Schema

**Environment Variables**:
```bash
PGWIRE_BACKEND_TYPE=dbapi           # or "embedded"
IRIS_HOSTNAME=localhost
IRIS_PORT=1972
IRIS_NAMESPACE=USER
IRIS_USERNAME=_SYSTEM
IRIS_PASSWORD=SYS
PGWIRE_POOL_SIZE=50
PGWIRE_POOL_MAX_OVERFLOW=20
```

**config.yaml**:
```yaml
backend:
  type: dbapi  # or embedded

iris:
  hostname: localhost
  port: 1972
  namespace: USER
  username: _SYSTEM
  password: SYS

connection_pool:
  size: 50
  max_overflow: 20
```

---

## Performance Requirements

- Configuration loading: <10ms
- Backend instantiation: <100ms
- Validation: <1ms

---

## Error Messages

| Error | Message | Resolution |
|-------|---------|------------|
| Invalid backend type | `Invalid backend_type: {type}. Must be 'dbapi' or 'embedded'` | Set valid backend_type |
| Missing credentials | `DBAPI backend requires credentials (username/password)` | Provide authentication |
| Pool limit exceeded | `Connection pool ({size} + {overflow}) exceeds maximum (200)` | Reduce pool configuration |
| Connection failed | `Cannot connect to IRIS at {host}:{port}` | Verify IRIS is running |

---

**Contract Status**: ✅ Defined, awaiting implementation
