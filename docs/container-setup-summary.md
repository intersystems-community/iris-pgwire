# IRIS Container Setup Summary

## ✅ Completed

### 1. Created persistent iris-pgwire-test container
- **Container name**: `iris-pgwire-test`
- **SuperServer Port**: 21972 (host) → 1972 (container)
- **Web Portal**: 22972 (host) → 52773 (container)
- **Edition**: community (intersystemsdc/iris-community:latest)
- **Status**: Running and persistent (survives script exit and reboots)
- **Credentials**: _SYSTEM / SYS
- **Verified**: Both DBAPI and IRISContainer.attach() work

### 2. Fixed conftest.py to attach to container
- Changed from creating new containers to attaching to `iris-pgwire-test`
- Fixed indentation issues (lines 241-291 were incorrectly nested)
- Container attachment works via `IRISContainer.attach("iris-pgwire-test")`

### 3. Created helper scripts
- ✅ **`scripts/create_persistent_container.sh`** - **RECOMMENDED**
  - Uses plain Docker (no testcontainers auto-cleanup)
  - Registers port in iris-devtester port registry
  - Container persists until explicitly removed
  - Tested and verified working
- `scripts/create_test_container.py` - Alternative using iris-devtester API
  - Uses `PortRegistry` with expanded range (21972-21982)
  - ⚠️  Container may be auto-removed on script exit (testcontainers behavior)
  - Use shell script instead for persistence

## 🔍 Findings

### iris-devtester Port Management
The key to controlling ports with `iris-devtester`:

```python
from iris_devtester import IRISContainer
from iris_devtester.ports.registry import PortRegistry

# MUST expand port_range to include desired port
registry = PortRegistry(port_range=(21972, 21982))  # Default is (1972, 1981)

container = IRISContainer.community(
    project_path=str(project_path),
    port_registry=registry,
    preferred_port=21972,  # This is honored only if in port_range
    username="_SYSTEM",
    password="SYS",
)
```

### Test Infrastructure Status
Client compatibility tests (`tests/client_compatibility/python/`) have issues:
- Tests don't request `pgwire_server` fixture
- Hardcoded to connect to localhost:5432
- Require the PGWire server to be running separately

This is a separate issue from container management and needs investigation of:
1. Why tests don't use fixtures properly
2. Whether there's missing test infrastructure
3. How the PGWire server should be started for these tests

## 📋 Next Steps

To run tests successfully:
1. ✅ IRIS container is running (iris-pgwire-test on port 21972)
2. ❌ Need to start PGWire server (or fix tests to use pgwire_server fixture)
3. ❌ Tests need to use dynamic port/config instead of hardcoded values

## 🎯 Usage

### Create container (first time):
```bash
cd /Users/tdyar/ws/iris-pgwire-gh
./scripts/create_persistent_container.sh
```

### Verify container:
```bash
idt container list
idt container status iris-pgwire-test
docker ps --filter "name=iris-pgwire-test"
```

### Connect to IRIS:
```bash
# Web Portal
open http://localhost:22972/csp/sys/UtilHome.csp

# DBAPI (Python)
python3 << 'EOF'
import iris.dbapi as iris_dbapi
conn = iris_dbapi.connect("localhost", 21972, "USER", "_SYSTEM", "SYS")
cursor = conn.cursor()
cursor.execute("SELECT 1")
print(cursor.fetchone())
EOF
```

### In tests (via conftest):
```python
# conftest automatically attaches to iris-pgwire-test
iris = IRISContainer.attach("iris-pgwire-test")
port = 21972  # Known from container creation
```

### Manage container:
```bash
# Stop (preserves data)
docker stop iris-pgwire-test

# Start again
docker start iris-pgwire-test

# Remove completely
docker rm -f iris-pgwire-test
```

## 📝 Related Knowledge

See compound knowledge base:
- Port conflicts with Docker containers
- iris-devtester PortRegistry API
- Container attachment patterns

