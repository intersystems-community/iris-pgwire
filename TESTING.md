# Testing Guide for iris-pgwire

## Constitutional Requirement

**Principle II: Test-First Development**
> All protocol features MUST be validated with end-to-end tests using real PostgreSQL clients before implementation begins. Mock testing is forbidden for database connectivity and protocol validation - only real IRIS instances and real clients provide sufficient validation.

## Test Categories

### 1. Contract Tests
Tests that validate API contracts and component behavior **without requiring IRIS**.

**Location**: `tests/contract/`
**Examples**:
- `test_backend_selector_contract.py` - Backend selection logic
- `test_dbapi_executor_contract.py` - DBAPI executor interface

**Run**:
```bash
# Local pytest
pytest tests/contract/ -v

# Docker (isolated environment)
docker compose --profile test run --rm pytest-contract
```

### 2. Integration Tests
Tests that validate **real behavior against real IRIS instances**. These are **REQUIRED** per constitutional mandate.

**Location**: `tests/integration/`
**Markers**: `@pytest.mark.requires_iris`
**Examples**:
- `test_dbapi_large_vectors.py` - Vector operations >1000 dimensions
- `test_backend_selection.py` - Backend switching E2E
- `test_connection_pooling.py` - 1000 concurrent connections

**Requirements**:
- IRIS instance running on `localhost:1972` (or via Docker)
- IRIS credentials: `_SYSTEM` / `SYS`
- IRIS namespace: `USER`

**Run**:
```bash
# Start IRIS first
docker compose up -d iris

# Wait for IRIS to be healthy
docker compose ps iris

# Run integration tests against real IRIS
docker compose --profile test run --rm pytest-integration
```

### 3. Feature 018: DBAPI Backend Tests

Feature 018 adds DBAPI backend support with the following test coverage:

**Contract Tests** (2):
- Backend selector contract (5 test cases)
- DBAPI executor contract (7 test cases)

**Integration Tests** (4):
- IPM installation validation
- Large vector operations (>1000 dimensions)
- Backend selection (DBAPI vs Embedded)
- Connection pooling under load (1000 connections)

**Total**: 6 test files, 12+ test cases

## Running Tests

### Quick Start (All Tests)

```bash
# 1. Start IRIS
docker compose up -d iris

# 2. Wait for healthy status
docker compose ps

# 3. Run all tests
docker compose --profile test up --abort-on-container-exit

# 4. View results
cat test-results/contract-results.xml
cat test-results/integration-results.xml
```

### Individual Test Suites

```bash
# Contract tests only (no IRIS required)
docker compose --profile test run --rm pytest-contract

# Integration tests only (IRIS required)
docker compose up -d iris
docker compose --profile test run --rm pytest-integration

# Specific test file
docker compose --profile test run --rm pytest-integration \
  pytest tests/integration/test_dbapi_large_vectors.py -v

# Specific test function
docker compose --profile test run --rm pytest-integration \
  pytest tests/integration/test_dbapi_large_vectors.py::test_vector_1024_dimensions -v
```

### Local Development (Without Docker)

```bash
# Install dependencies
uv sync --all-extras

# Start IRIS via Docker
docker compose up -d iris

# Run tests locally
export IRIS_HOSTNAME=localhost
export IRIS_PORT=1972
export IRIS_USERNAME=_SYSTEM
export IRIS_PASSWORD=SYS
export IRIS_NAMESPACE=USER

# Contract tests
pytest tests/contract/ -v

# Integration tests (requires IRIS running)
pytest tests/integration/ -v -m requires_iris

# All tests
pytest tests/ -v
```

## Test Environment Variables

### IRIS Connection
```bash
IRIS_HOSTNAME=localhost    # IRIS host (default: localhost)
IRIS_PORT=1972            # IRIS SuperServer port (default: 1972)
IRIS_NAMESPACE=USER       # IRIS namespace (default: USER)
IRIS_USERNAME=_SYSTEM     # IRIS username (default: _SYSTEM)
IRIS_PASSWORD=SYS         # IRIS password (default: SYS)
```

### PGWire Server Connection
```bash
PGWIRE_HOST=localhost     # PGWire server host (default: localhost)
PGWIRE_PORT=5432         # PGWire server port (default: 5432)
```

### Test Configuration
```bash
PYTHONPATH=/app/src       # Python module path
PYTEST_ARGS=-v --tb=short # Additional pytest arguments
```

## Test Markers

```python
@pytest.mark.integration     # Integration test (may require IRIS)
@pytest.mark.requires_iris   # REQUIRES real IRIS instance (Constitutional)
@pytest.mark.slow           # Slow test (>10 seconds)
@pytest.mark.skipif(...)    # Conditional skip (e.g., missing implementation)
```

**Filter by marker**:
```bash
# Only tests that require IRIS
pytest -m requires_iris -v

# Only fast tests (exclude slow)
pytest -m "not slow" -v

# Integration tests that require IRIS
pytest -m "integration and requires_iris" -v
```

## Continuous Integration

### GitLab CI Example

```yaml
test:
  stage: test
  services:
    - name: containers.intersystems.com/intersystems/iris:latest-preview
      alias: iris
  variables:
    IRIS_HOSTNAME: iris
    IRIS_PORT: 1972
    IRIS_USERNAME: _SYSTEM
    IRIS_PASSWORD: SYS
    IRIS_NAMESPACE: USER
  script:
    - pip install -e ".[dev]"
    - pytest tests/contract/ -v --junitxml=contract-results.xml
    - pytest tests/integration/ -v -m requires_iris --junitxml=integration-results.xml
  artifacts:
    reports:
      junit:
        - contract-results.xml
        - integration-results.xml
```

## Troubleshooting

### "IRIS_ACCESSDENIED" errors
**Cause**: CallIn service not enabled
**Fix**: Ensure `merge.cpf` is applied during IRIS startup
```bash
docker compose down -v
docker compose up -d iris
docker compose logs iris | grep "CallIn"
```

### Integration tests skipped
**Cause**: IRIS not running or not healthy
**Fix**: Check IRIS container status
```bash
docker compose ps iris
docker compose logs iris
```

### Connection timeouts
**Cause**: IRIS not fully initialized
**Fix**: Wait for health check to pass
```bash
docker compose ps  # Check "healthy" status
docker compose up -d iris
sleep 30  # Wait for initialization
```

### ImportError for test modules
**Cause**: PYTHONPATH not set correctly
**Fix**: Set PYTHONPATH to src directory
```bash
export PYTHONPATH=/path/to/iris-pgwire/src
pytest tests/ -v
```

## Coverage Reporting

```bash
# Run tests with coverage
docker compose --profile test run --rm pytest-integration \
  pytest tests/ -v --cov=iris_pgwire --cov-report=html

# View coverage report
open htmlcov/index.html
```

## Performance Benchmarking

```bash
# Run connection pooling load test
docker compose up -d iris
docker compose --profile test run --rm pytest-integration \
  pytest tests/integration/test_connection_pooling.py::test_1000_concurrent_connections -v

# Check P95 latency (should be <1ms per Constitutional SLA)
docker compose --profile test run --rm pytest-integration \
  pytest tests/integration/test_connection_pooling.py -v --benchmark
```

## Validation Checklist

Before merging feature 018:

- [ ] Contract tests pass (2 test files, 12 test cases)
- [ ] Integration tests pass against real IRIS (4 test files)
- [ ] E2E validation script passes (8 quickstart steps)
- [ ] Coverage >80% for new DBAPI backend code
- [ ] Performance SLAs met (<1ms connection, <5ms translation)
- [ ] No mocks used for IRIS connectivity (Constitutional Principle II)

---

**Constitutional Compliance**: ✅ All integration tests run against real IRIS instances per Principle II.
