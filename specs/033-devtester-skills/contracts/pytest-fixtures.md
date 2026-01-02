# Contract: IRIS DevTester Pytest Fixtures

## Purpose
This contract defines the public interface for the `pytest` fixtures provided by the `iris-devtester` integration.

## Fixtures

### 1. `iris_container`
High-level fixture that ensures a healthy IRIS instance is available.

- **Scope**: Session or Module
- **Returns**: `iris_devtester.IRISContainer` object
- **Responsibilities**:
  - Pull image if missing.
  - Start container.
  - Wait for port 1972 to be ready.
  - Disable password expiry.
  - Enable CallIn service.
  - Cleanup on teardown.

### 2. `iris_connection`
Provides a DBAPI connection with auto-remediation.

- **Scope**: Function
- **Depends on**: `iris_container`
- **Returns**: `iris.dbapi.Connection`
- **Responsibilities**:
  - Auto-retry on transient failures.
  - Handle "ChangePassword" requirement.
  - Switch to requested namespace.

### 3. `iris_fixture`
Helper to load specific test data sets.

- **Scope**: Function
- **Usage**:
  ```python
  def test_vectors(iris_fixture):
      iris_fixture.load("vectors_1024d.dat")
      # ...
  ```
- **Responsibilities**:
  - Load `.DAT` files via `FixtureCreator`.
  - Validate schema before loading.
  - Teardown (optional) - drop tables if requested.

## Hooks

### `pytest_runtest_makereport` (Failure Hook)
- On `call.failed`, triggers the `/troubleshooting` skill logic.
- Captures:
  - IRIS connection status.
  - Container health.
  - Last few IRIS system log entries.
- Outputs to: `test_failures.jsonl`

## Configuration
Controlled via `pytest` CLI or `pyproject.toml`:
- `--iris-image`: Specify custom IRIS image.
- `--iris-namespace`: Default namespace for connections.
- `--iris-persist`: If True, don't stop container on teardown (for debugging).
