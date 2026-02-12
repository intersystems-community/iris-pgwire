# Client Compatibility Test Refactoring - Complete

## Summary

Successfully refactored the client compatibility test suite to use pytest fixtures instead of hardcoded connections to localhost:5432.

## Changes Made

### 1. Infrastructure Setup
- ✅ Created persistent IRIS container (`iris-pgwire-test` on port 21972)
- ✅ Created `test_user` in IRIS with password `test` and role `%All`
- ✅ Fixed `conftest.py` to attach to persistent container
- ✅ Created deployment scripts in `scripts/`

### 2. Test Refactoring (@fixer)
Refactored 5 test files to use `pgwire_server` and `pgwire_connection_params` fixtures:

#### ✅ test_psycopg_basic.py
- Removed hardcoded `PGWIRE_CONFIG`
- Added autouse fixture to build connection string from `pgwire_connection_params`
- All tests now request `pgwire_server` fixture (starts PGWire on port 5434)
- Added null guards on fetched rows
- **Status**: 3/3 connection tests passing

#### ✅ test_asyncpg_basic.py
- Removed static config
- Added helper to normalize `pgwire_connection_params` for asyncpg
- Both fixtures depend on `pgwire_server`/`pgwire_connection_params`

#### ✅ test_psycopg_parameters.py
- Converted standalone scripts to pytest tests
- Use `pgwire_connection_params` fixture
- Added guards against empty fetches
- Removed `__main__` runner

#### ✅ test_postgres_with_casts.py
- Converted to pytest async tests
- Built connections via `pgwire_connection_params`
- Kept informative prints while raising on failures

#### ✅ test_postgres_parameter_types.py
- Converted PostgreSQL diagnostics to pytest async tests
- Uses fixture-managed connections
- Logs same protocol metadata as before

## Test Architecture

### Before (Manual Infrastructure)
```
tests/client_compatibility/python/
├── PGWIRE_CONFIG = {"host": "localhost", "port": 5432, ...}
└── Tests connect directly to hardcoded port
    ❌ Requires docker-compose up separately
    ❌ Fails in normal pytest runs
```

### After (Fixture Infrastructure)
```
tests/conftest.py
├── iris_container → Attaches to iris-pgwire-test (port 21972)
├── pgwire_server → Starts PGWire on port 5434
└── pgwire_connection_params → Dynamic connection info

tests/client_compatibility/python/
└── Tests request pgwire_server fixture
    ✅ Auto-starts PGWire server
    ✅ Works in normal pytest runs
    ✅ No manual docker-compose needed
```

## Verification

```bash
# Single test
pytest tests/client_compatibility/python/test_psycopg_basic.py::TestPsycopgBasicConnection::test_connection_establishment -v
# ✅ PASSED

# Connection test class
pytest tests/client_compatibility/python/test_psycopg_basic.py::TestPsycopgBasicConnection -v
# ✅ 3 passed

# All client compatibility tests
pytest tests/client_compatibility/python/ -v
# (Full suite - run with timeout, some tests may be slow)
```

## Key Implementation Details

### Credentials
- **IRIS Container**: `_SYSTEM` / `SYS` (admin)
- **PGWire Test User**: `test_user` / `test` (created via ObjectScript)
- **PGWire Server**: Connects to IRIS as `_SYSTEM`, authenticates clients as `test_user`

### Ports
- **IRIS SuperServer**: 21972 (host) → 1972 (container)
- **IRIS Web Portal**: 22972 (host) → 52773 (container)
- **PGWire Server**: 5434 (from `PGWIRE_PORT` env or default)

### Fixture Flow
```
Test requests pgwire_server
  ↓
pgwire_server depends on iris_container + iris_config + pgwire_namespace
  ↓
iris_container attaches to iris-pgwire-test
  ↓
pgwire_server starts on port 5434
  ↓
pgwire_connection_params provides connection info
  ↓
Test connects to PGWire on 5434
  ↓
PGWire connects to IRIS on 21972
```

## Benefits

1. **No Manual Setup**: Tests start PGWire server automatically
2. **Isolated**: Each test module gets its own PGWire server instance
3. **Portable**: Works on any machine with Docker (no localhost:5432 dependency)
4. **CI-Ready**: Tests run in standard pytest without docker-compose
5. **Unified**: All tests use same fixture infrastructure

## Remaining Work

- [ ] Run full test suite to identify slow/hanging tests
- [ ] Add timeout markers for long-running tests
- [ ] Update `tests/client_compatibility/README.md` to reflect new approach
- [ ] Verify async tests work correctly
- [ ] Consider adding test markers for categorization

## Related Files

- `tests/conftest.py` - Fixture definitions
- `scripts/create_persistent_container.sh` - Container setup
- `docs/container-setup-summary.md` - Container management guide
- `tests/client_compatibility/README.md` - Test documentation (needs update)

## Commands Reference

```bash
# Create container (one-time)
./scripts/create_persistent_container.sh

# Create test_user (one-time)
python3 << 'EOF'
import iris
conn = iris.connect("localhost", 21972, "%SYS", "_SYSTEM", "SYS")
iris_obj = iris.createIRIS(conn)
status = iris_obj.classMethodValue("Security.Users", "Create", "test_user", "%All", "test")
print(f"Created test_user: {status == 1}")
conn.close()
EOF

# Run tests
pytest tests/client_compatibility/python/test_psycopg_basic.py -v
```

---

**Refactoring completed**: 2026-02-12  
**Status**: ✅ Core tests passing, full suite needs validation
