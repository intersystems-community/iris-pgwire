# Go Client Compatibility Tests for IRIS PGWire

PostgreSQL wire protocol compatibility tests using the **pgx v5** driver.

## Prerequisites

- Go 1.21 or higher
- IRIS PGWire server running on localhost:5432
- Docker (for IRIS container)

## Setup

```bash
# Install dependencies
cd tests/client_compatibility/go
go mod download
```

## Running Tests

```bash
# Run all tests
go test -v ./...

# Run specific test
go test -v -run TestBasicConnection

# Run with environment variables
PGWIRE_HOST=localhost PGWIRE_PORT=5432 go test -v ./...

# Run with timeout
go test -v -timeout 30s ./...

# Generate coverage report
go test -v -coverprofile=coverage.out ./...
go tool cover -html=coverage.out
```

## Environment Variables

- `PGWIRE_HOST` - Server host (default: localhost)
- `PGWIRE_PORT` - Server port (default: 5432)
- `PGWIRE_DATABASE` - Database name (default: USER)
- `PGWIRE_USERNAME` - Username (default: test_user)
- `PGWIRE_PASSWORD` - Password (default: test)

## Test Coverage

### Connection Tests (connection_test.go)
- ✅ Basic connection establishment
- ✅ Connection string format
- ✅ Connection pooling (max/min connections)
- ✅ Multiple sequential connections
- ✅ Server information (version query)
- ✅ Connection error handling (invalid port)
- ✅ Connection timeout configuration

### Query Tests (query_test.go)
- ✅ SELECT constant values
- ✅ Multi-column SELECT queries
- ✅ NULL value handling
- ✅ Multiple sequential queries
- ✅ Empty result sets
- ✅ Result metadata (field descriptions)
- ✅ String with special characters (escaping)
- ✅ Parameterized queries ($1, $2 syntax)
- ✅ UNION ALL queries (multiple rows)
- ✅ Transaction COMMIT
- ✅ Transaction ROLLBACK
- ✅ Batch query execution

## pgx Driver Features Tested

- **Standard Protocol**: P0 Handshake, P1 Simple Query
- **Extended Protocol**: Prepared statements, parameter binding
- **Connection Pooling**: pgxpool with min/max connections
- **Transactions**: BEGIN, COMMIT, ROLLBACK
- **Batch Operations**: Multiple queries in single round trip
- **Result Metadata**: Field names, types, row counts
- **Error Handling**: Connection errors, query errors

## Notes

### pgx vs lib/pq

This test suite uses **pgx v5** because:
- Modern driver with active development
- Native PostgreSQL protocol implementation
- Better performance and memory efficiency
- Connection pooling built-in (pgxpool)
- Batch query support
- Context-aware API (proper cancellation)

**lib/pq** is now in maintenance mode (minimal updates).

### IRIS-Specific Compatibility

All tests validate that IRIS PGWire behaves like PostgreSQL:
- Column name normalization (lowercase, ?column? for unnamed)
- Type OID mapping (int4, text, float8)
- Transaction state management
- NULL handling
- Error message format

## Troubleshooting

### Connection Refused
```bash
# Ensure IRIS container is running
docker ps | grep iris

# Check PGWire server logs
docker exec iris-pgwire-db tail -50 /tmp/pgwire.log
```

### Test Timeouts
```bash
# Increase timeout
go test -v -timeout 60s ./...

# Check server is ready
docker exec iris-pgwire-db tail -1 /tmp/pgwire.log | grep Ready
```

### Module Download Issues
```bash
# Clear module cache
go clean -modcache

# Re-download
go mod download
```

## References

- **pgx Documentation**: https://pkg.go.dev/github.com/jackc/pgx/v5
- **PostgreSQL Protocol**: https://www.postgresql.org/docs/current/protocol.html
- **IRIS PGWire Project**: ../../..
