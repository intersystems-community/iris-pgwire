# Test Development Strategy

## Overview
This document outlines the test development approach for the IRIS PostgreSQL Wire Protocol implementation, emphasizing E2E testing with real IRIS connections.

## Test Architecture

### Core Testing Philosophy
1. **E2E First**: Test against real IRIS instances, not mocks
2. **Real Client Testing**: Use actual PostgreSQL clients (psql, psycopg)
3. **Progressive Validation**: Test each protocol phase independently
4. **Infrastructure Dependencies**: Ensure proper IRIS container setup

### Test Categories (Priority Order)

#### 1. Infrastructure Tests
Test that our IRIS container and connection setup works correctly.

```python
def test_iris_container_health():
    """Test IRIS container is healthy and accessible"""

def test_iris_connection_no_password_expiry():
    """Test IRIS connection works without password change required"""

def test_iris_basic_sql_execution():
    """Test basic SQL execution through IRIS executor"""
```

#### 2. Wire Protocol Foundation Tests (P0-P2)
Test the core PostgreSQL protocol implementation.

```python
def test_p0_ssl_negotiation():
    """Test SSL probe and negotiation"""

def test_p0_startup_sequence():
    """Test complete startup handshake"""

def test_p1_simple_query_execution():
    """Test Simple Query protocol"""

def test_p2_extended_protocol():
    """Test Parse/Bind/Execute messages"""
```

#### 3. End-to-End Client Tests
Test with real PostgreSQL clients.

```python
def test_psycopg_connection():
    """Test psycopg driver connection"""

def test_psql_command_line():
    """Test psql CLI client"""

def test_real_query_execution():
    """Test actual SQL queries through wire protocol"""
```

#### 4. IRIS Integration Tests
Test IRIS-specific functionality.

```python
def test_iris_system_functions():
    """Test IRIS %UPPER, %HOROLOG functions"""

def test_iris_vector_operations():
    """Test vector similarity queries"""

def test_sql_translation_integration():
    """Test SQL translation with wire protocol"""
```

## Test Infrastructure Setup

### IRIS Container Management
```python
@pytest.fixture(scope="session")
def iris_container():
    """Ensure IRIS container is running with proper configuration"""
    # Verify container health
    # Check password expiry disabled
    # Return connection config

@pytest.fixture(scope="session")
def pgwire_server(iris_container):
    """Start PGWire server against real IRIS"""
    # Start server process
    # Wait for port readiness
    # Return server instance
```

### Test Data Management
```python
@pytest.fixture
def test_database(iris_container):
    """Create isolated test database/schema"""
    # Create test tables
    # Insert test data
    # Yield for tests
    # Cleanup after tests
```

## Implementation Priorities

### Phase 1: Infrastructure Validation
1. Fix IRIS executor bug (currently failing with "'int' object has no attribute 'upper'")
2. Validate basic IRIS SQL execution
3. Document working IRIS connection patterns

### Phase 2: Protocol Foundation
1. Test P0 handshake with real clients
2. Test P1 simple queries
3. Test P2 extended protocol

### Phase 3: Integration Testing
1. Test complete E2E flow with psycopg
2. Test SQL translation integration
3. Test IRIS-specific features

## Test Configuration

### Pytest Configuration
```ini
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "e2e: E2E tests with real PostgreSQL clients",
    "integration: Integration tests with IRIS",
    "unit: Unit tests",
    "requires_iris: Tests that require IRIS connection",
    "wire_protocol: Wire protocol specific tests"
]
```

### Environment Configuration
```python
# Test configuration
TEST_CONFIG = {
    'iris': {
        'host': 'localhost',
        'port': 1972,
        'username': '_SYSTEM',
        'password': 'SYS',
        'namespace': 'USER'
    },
    'pgwire': {
        'host': 'localhost',
        'port': 5432
    }
}
```

## Success Criteria

### Infrastructure Tests
- ✅ IRIS container starts and becomes healthy
- ✅ IRIS connection works without password errors
- ✅ Basic SQL execution succeeds

### Protocol Tests
- ✅ SSL negotiation completes successfully
- ✅ PostgreSQL handshake sequence completes
- ✅ Simple Query protocol works
- ✅ Extended protocol (Parse/Bind/Execute) works

### E2E Tests
- ✅ psycopg driver can connect and execute queries
- ✅ psql CLI can connect and execute queries
- ✅ SQL queries execute against IRIS and return results
- ✅ IRIS-specific functions work through wire protocol

## Current Status

### Completed
- IRIS container setup with rag-templates patterns
- Password expiry disabled successfully
- Container health check passing

### In Progress
- IRIS executor bug fix (Python error in result processing)
- Basic SQL execution validation

### Next Steps
1. Fix IRIS executor implementation
2. Create infrastructure test suite
3. Implement P0-P2 protocol tests
4. Build E2E test framework

## References
- Protocol specification: PostgreSQL v3.0 wire protocol
- IRIS patterns: rag-templates docker setup
- Test patterns: Real client integration approach