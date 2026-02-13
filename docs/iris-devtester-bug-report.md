# Bug Report: IRIS Connection "Access Denied" in Fixture Context

## Environment
- **iris-devtester version**: 1.12.0
- **IRIS version**: Community 2025.1
- **Container**: `iris-pgwire-test` (created via Docker, registered with iris-devtester)
- **Platform**: macOS 15.5 (arm64)
- **Python**: 3.12.9

## Summary
When using iris-devtester in pytest fixtures, IRIS connections fail with "Access Denied" even though:
1. Direct connections to the same IRIS instance work fine
2. The container is running and healthy
3. The same credentials work outside the fixture context

## Reproduction

### Container Setup
```bash
# Container created via Docker
docker run -d \
    --name iris-pgwire-test \
    -p 21972:1972 \
    -p 22972:52773 \
    -e IRIS_PASSWORD=SYS \
    -e IRIS_USERNAME=_SYSTEM \
    intersystemsdc/iris-community:latest

# Registered with iris-devtester port registry
python3 << 'PYEOF'
import json
from pathlib import Path
registry_file = Path.home() / ".iris-devtester" / "port-registry.json"
data = json.loads(registry_file.read_text()) if registry_file.exists() else {}
data["/path/to/project"] = {"port": 21972, "container": "iris-pgwire-test"}
registry_file.write_text(json.dumps(data, indent=2))
PYEOF
```

### Direct Connection (WORKS ✅)
```python
import iris
conn = iris.connect("localhost", 21972, "%SYS", "_SYSTEM", "SYS")
iris_obj = iris.createIRIS(conn)
exists = iris_obj.classMethodValue("Security.Users", "Exists", "test_user")
print(f"User exists: {exists}")  # ✅ Works fine
conn.close()
```

### Fixture Connection (FAILS ❌)
```python
# tests/conftest.py
@pytest.fixture(scope="session")
def iris_container(pytestconfig):
    from iris_devtester import IRISContainer
    iris = IRISContainer.attach("iris-pgwire-test")
    yield iris

@pytest.fixture(scope="session")
def iris_config(iris_container):
    config = iris_container.get_config()
    return {
        "host": config.host,
        "port": config.port,
        "username": config.username,
        "password": config.password,
        "namespace": config.namespace,
    }

@pytest.fixture(scope="module")
def provision_test_user(iris_config, pgwire_namespace):
    import iris
    conn = iris.connect(
        iris_config["host"],
        iris_config["port"],
        "%SYS",
        iris_config.get("username", "_SYSTEM"),
        iris_config.get("password", "SYS"),
    )
    # ❌ FAILS HERE with:
    # <COMMUNICATION LINK ERROR> Failed to connect to server;
    # Details: <COMMUNICATION ERROR> Invalid Message received;
    # Details: Access Denied
```

## Error Details

### Full Error Message
```
<COMMUNICATION LINK ERROR> Failed to connect to server;
Details: <COMMUNICATION ERROR> Invalid Message received;
Details: Access Denied
```

### When It Occurs
- During fixture setup in `provision_test_user`
- After `iris_container.attach()` succeeds
- After `iris_container.get_config()` returns valid config
- When trying to use that config to create a new `iris.connect()` connection

### What Works
1. ✅ Direct `iris.connect("localhost", 21972, "%SYS", "_SYSTEM", "SYS")` outside fixtures
2. ✅ `IRISContainer.attach("iris-pgwire-test")` succeeds
3. ✅ `iris_container.get_config()` returns valid configuration

### What Fails
❌ Using the config from `get_config()` to create a new connection within a fixture

## Suspected Issue

**Hypothesis**: The `IRISConfig` object returned by `get_config()` might contain additional metadata or connection parameters that cause authentication to fail when passed to `iris.connect()`.

### Config Values Observed
```python
config = iris_container.get_config()
print(config.host)      # localhost
print(config.port)      # 21972
print(config.username)  # _SYSTEM (or SuperUser?)
print(config.password)  # SYS
print(config.namespace) # USER or TEST_xxxxx
```

**Question**: Are there other attributes in `IRISConfig` that affect connection behavior?

## Expected Behavior
Connection using `iris_config` values should work the same as direct connection with the same parameters.

## Actual Behavior
Connection fails with "Access Denied" only when using config from iris-devtester fixture.

## Workaround
None found. Direct hardcoded values work, but defeat the purpose of using iris-devtester for container management.

## Request
1. Clarify what `get_config()` returns and if there are hidden connection parameters
2. Provide example of correct way to create additional IRIS connections from fixture config
3. Debug why same credentials work directly but not through `IRISConfig`

## Minimal Reproduction
```python
# test_iris_devtester_connection.py
import pytest
import iris
from iris_devtester import IRISContainer

def test_direct_connection():
    """This works"""
    conn = iris.connect("localhost", 21972, "%SYS", "_SYSTEM", "SYS")
    iris_obj = iris.createIRIS(conn)
    result = iris_obj.classMethodValue("Security.Users", "Exists", "test_user")
    assert result in [0, 1]
    conn.close()

def test_devtester_config_connection():
    """This fails"""
    container = IRISContainer.attach("iris-pgwire-test")
    config = container.get_config()
    
    conn = iris.connect(
        config.host,
        config.port,
        "%SYS",
        config.username,
        config.password,
    )
    # ❌ Access Denied here
    iris_obj = iris.createIRIS(conn)
    result = iris_obj.classMethodValue("Security.Users", "Exists", "test_user")
    assert result in [0, 1]
    conn.close()
```

## Related Code
- Project: https://github.com/isc-tdyar/iris-pgwire
- Commit: 9edf152
- File: `tests/conftest.py` lines 401-460 (provision_test_user fixture)

## Questions for iris-devtester Maintainers
1. Is `IRISContainer.attach()` intended for containers created outside iris-devtester?
2. Does `get_config()` work correctly for attached (vs created) containers?
3. Are there known authentication quirks when mixing iris-devtester with manual containers?
4. Should we use a different API pattern for this use case?
