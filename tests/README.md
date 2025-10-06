# IRIS PGWire Test Suite

## Active Test Files

### Vector Parameter Binding Tests

**test_all_vector_sizes.py**
- **Purpose**: Validate parameter binding across all vector dimensions (128D-1024D)
- **Usage**: `python3 tests/test_all_vector_sizes.py`
- **Validates**:
  - pgvector operator rewriting (<=>, <#>)
  - Parameter placeholder detection (?, %s, $1)
  - TO_VECTOR() wrapper injection
  - Both PGWire-DBAPI and PGWire-embedded paths
- **Expected Output**: ✅ All dimensions work on both paths

**test_vector_limit_binary_search.py**
- **Purpose**: Find exact maximum vector dimension using binary search
- **Usage**: `python3 tests/test_vector_limit_binary_search.py`
- **Validates**: Maximum transport capacity (188,962D = 1.44 MB)
- **Algorithm**: Binary search between 1,024D and 100,000D
- **Expected Output**: 🎯 Maximum: 188,962D (1.44 MB per vector)

**test_vector_limits.py**
- **Purpose**: Stress test with progressively larger vectors
- **Usage**: `python3 tests/test_vector_limits.py`
- **Tests**: 1024D → 2048D → 4096D → 8192D → 16384D → 32768D
- **Expected Output**: Shows maximum working dimension and performance metrics

**test_binary_vectors.py**
- **Purpose**: Test binary parameter encoding for vectors
- **Usage**: `python3 tests/test_binary_vectors.py`
- **Validates**:
  - PostgreSQL binary array format decoding
  - OID support (float4, float8, int4, int8)
  - Binary vs text encoding comparison
- **Expected Output**: ✅ Binary encoding works, ~40% more compact

### Experimental Tests (WIP)

**test_copy_protocol.py**
- **Purpose**: COPY protocol implementation testing
- **Status**: 🚧 Partial - blocked by container filesystem isolation
- **Issues**:
  - Vector optimizer strips TO_VECTOR()
  - IRIS doesn't support multi-row VALUES syntax
  - Temp files not accessible between containers
- **Future**: Needs shared volume or LOAD DATA alternative

### Core Protocol Tests

**test_p0_handshake.py**
- **Purpose**: P0 phase - Basic connection handshake
- **Validates**: SSL negotiation, StartupMessage, ReadyForQuery
- **Status**: ✅ Complete

**test_e2e_wire_protocol.py**
- **Purpose**: End-to-end wire protocol validation
- **Validates**: Full message flow, state management
- **Status**: ✅ Complete

**test_infrastructure.py**
- **Purpose**: Test framework infrastructure validation
- **Validates**: Docker containers, IRIS connectivity, pytest fixtures
- **Status**: ✅ Complete

### Integration Tests

**test_contract_iris_translation.py**
- **Purpose**: Contract tests for SQL translation
- **Validates**: PostgreSQL → IRIS SQL dialect conversion
- **Status**: ✅ Complete

**test_integration_iris_translation.py**
- **Purpose**: Integration tests for translation layer
- **Validates**: Complex query transformations
- **Status**: ✅ Complete

**test_e2e_iris_constructs.py**
- **Purpose**: IRIS-specific construct validation
- **Validates**: VECTOR operations, TO_VECTOR(), VECTOR_COSINE()
- **Status**: ✅ Complete

---

## Test Utilities

**conftest.py**
- pytest fixtures and configuration
- Docker container management
- Database connection helpers

**timeout_handler.py**
- Timeout management for long-running tests
- Background process handling

**validate_framework.py**
- Test framework validation
- Ensures test environment is correctly configured

---

## Archived Tests

The `tests/archive/` directory contains historical test files from earlier development phases (P0-P5). These are preserved for reference but are no longer actively maintained:

- P2 Extended Protocol tests
- P3 Authentication tests
- P4 Cancellation tests
- P5 Vector operations (legacy)
- Various debugging and profiling scripts

---

## Running Tests

### Quick Validation
```bash
# Test all vector sizes (fast)
python3 tests/test_all_vector_sizes.py

# Expected output:
🎉 SUCCESS: All vector sizes work with parameter binding!
```

### Find Maximum Dimension
```bash
# Binary search for maximum (2-3 minutes)
python3 tests/test_vector_limit_binary_search.py

# Expected output:
🎯 Overall Maximum: 188,962D (1.44 MB per vector)
```

### Stress Testing
```bash
# Progressive stress test (5-10 minutes)
python3 tests/test_vector_limits.py

# Tests: 1K → 2K → 4K → 8K → 16K → 32K dimensions
```

### Full Test Suite
```bash
# Run all pytest tests
pytest tests/ -v

# Run specific test file
pytest tests/test_all_vector_sizes.py -v

# Run with coverage
pytest tests/ --cov=src/iris_pgwire --cov-report=html
```

---

## Test Data Setup

Before running vector tests, ensure benchmark data is created:

```bash
# Create multi-dimensional test data (1000 rows × 4 dimensions)
python3 benchmarks/setup_multidim_vectors.py

# Creates table with columns:
# - embedding_128 (VECTOR 128D)
# - embedding_256 (VECTOR 256D)
# - embedding_512 (VECTOR 512D)
# - embedding_1024 (VECTOR 1024D)
```

---

## Docker Environment

Tests assume the following containers are running:

| Container | Port | Purpose |
|-----------|------|---------|
| **postgres** | 5433 | PostgreSQL + pgvector baseline |
| **iris-4way** | 1974 | IRIS main instance (DBAPI) |
| **iris-4way-embedded** | 1975 | IRIS embedded instance |
| **pgwire-4way-dbapi** | 5434 | PGWire-DBAPI path |
| **iris-4way-embedded** | 5435 | PGWire-embedded path |

Start containers:
```bash
docker compose -f benchmarks/docker-compose.4way.yml up -d
```

Verify health:
```bash
docker ps | grep -E "(pgwire|iris|postgres)"
# All containers should show "healthy" status
```

---

## Test Coverage

### P0: Handshake ✅
- SSL negotiation
- StartupMessage handling
- Parameter status
- ReadyForQuery

### P1: Simple Query ✅
- Query execution
- Result encoding
- Error handling

### P2: Extended Protocol ✅
- Parse/Bind/Execute flow
- Prepared statements
- Parameter binding
- **Binary parameters** ✅

### P3: Authentication ✅
- SCRAM-SHA-256
- Password encryption

### P4: Cancellation ✅
- Query cancellation
- Backend key management

### P5: Vector Operations ✅
- **pgvector operator rewriting** ✅
- **Parameter placeholder detection** ✅
- **TO_VECTOR() injection** ✅
- **128D-1024D support** ✅
- **Maximum 188,962D (1.44 MB)** ✅
- **Binary encoding** ✅

### P6: COPY & Performance 🚧
- COPY protocol: Partial (blocked)
- Batch operations: Deferred
- Performance hints: Documented (future)

---

## Key Achievements

✅ **Vector Parameter Binding**: Full support for parameterized vector queries
✅ **Maximum Capacity**: 188,962D (1.44 MB) - 1,465× improvement over text literals
✅ **Binary Encoding**: PostgreSQL wire format support for efficient transport
✅ **Both Paths Working**: PGWire-DBAPI and PGWire-embedded identical results
✅ **pgvector Compatible**: <=> and <#> operators work with parameters

---

## Documentation

See `/docs/VECTOR_PARAMETER_BINDING.md` for comprehensive documentation including:
- Implementation details
- Performance characteristics
- Usage examples
- Known limitations
- Future enhancements
