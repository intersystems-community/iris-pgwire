# Rust PostgreSQL Client Compatibility Tests

Tests PostgreSQL wire protocol compatibility using **tokio-postgres** (the most popular async PostgreSQL client for Rust).

## Overview

**Driver**: tokio-postgres 0.7
**Protocol**: PostgreSQL wire protocol via async I/O
**Format**: Binary format by default (like Go pgx and Python asyncpg)
**Test Coverage**: 24 tests across 3 categories

## Test Categories

### Connection Tests (7 tests)
- `test_basic_connection` - Basic connection establishment
- `test_connection_string_parsing` - Connection string format
- `test_multiple_sequential_connections` - Sequential connection handling
- `test_server_version` - Server version query
- `test_connection_error_handling` - Error handling for invalid connections
- `test_query_after_connection` - Multiple queries on single connection

### Query Tests (12 tests)
- `test_select_constant` - Simple SELECT with constant
- `test_select_multiple_columns` - Multiple column selection
- `test_select_current_timestamp` - TIMESTAMP binary format (CRITICAL)
- `test_select_with_null` - NULL value handling
- `test_prepared_statement_single_param` - Single parameter binding
- `test_prepared_statement_multiple_params` - Multiple parameters
- `test_prepared_statement_with_null` - NULL as parameter
- `test_string_with_special_characters` - Special character escaping
- `test_multiple_rows_result` - Multiple row results (UNION ALL)
- `test_empty_result_set` - Empty result sets
- `test_sequential_queries` - Sequential query execution

### Transaction Tests (5 tests)
- `test_basic_transaction_commit` - Transaction commit
- `test_basic_transaction_rollback` - Transaction rollback
- `test_transaction_with_multiple_operations` - Multiple operations in transaction
- `test_explicit_begin_commit` - Explicit BEGIN/COMMIT syntax
- `test_explicit_begin_rollback` - Explicit BEGIN/ROLLBACK syntax

## Prerequisites

1. **Rust toolchain** (1.70+):
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```

2. **PGWire server running**:
   ```bash
   cd /Users/tdyar/ws/iris-pgwire
   docker compose up -d
   ```

## Running Tests

### All Tests
```bash
cd /Users/tdyar/ws/iris-pgwire/tests/client_compatibility/rust
cargo test
```

### Specific Test Suite
```bash
cargo test --test connection_tests
cargo test --test query_tests
cargo test --test transaction_tests
```

### Single Test
```bash
cargo test test_select_current_timestamp -- --exact --nocapture
```

### With Output
```bash
cargo test -- --nocapture
```

## Environment Variables

Configure connection via environment variables:

```bash
export PGWIRE_HOST=localhost      # Default: localhost
export PGWIRE_PORT=5432           # Default: 5432
export PGWIRE_DATABASE=USER       # Default: USER
export PGWIRE_USERNAME=test_user  # Default: test_user
export PGWIRE_PASSWORD=test       # Default: test
```

## Expected Results

**Target**: 24/24 tests passing (100% compatibility)

### Critical Features Tested

✅ **Binary Format Support**: tokio-postgres uses binary format by default (like Go pgx)
✅ **TIMESTAMP Binary Format**: CURRENT_TIMESTAMP returned as NaiveDateTime (8-byte int64)
✅ **Transaction Management**: BEGIN/COMMIT/ROLLBACK with Feature 022 translation
✅ **Prepared Statements**: Parameter binding with $1, $2, etc.
✅ **NULL Handling**: Option<T> for nullable values
✅ **Special Characters**: String escaping and UTF-8 support

## Known Compatibility Notes

1. **Binary Format**: tokio-postgres prefers binary format for performance (like pgx and asyncpg)
2. **Transaction Syntax**: Uses Feature 022 translation (BEGIN → START TRANSACTION)
3. **TIMESTAMP Format**: Relies on Fix 3 (TIMESTAMP binary encoding from Npgsql work)
4. **Type System**: Rust's type safety requires explicit type annotations in some cases

## Performance Characteristics

**Binary Format Benefits** (vs text format):
- Network bandwidth: 30-50% reduction for numeric workloads
- CPU overhead: 2-4× faster for numeric types (no string parsing)
- Precision: No floating-point rounding errors

**Async I/O Benefits**:
- Non-blocking operations via tokio runtime
- Efficient connection pooling
- High concurrency without thread overhead

## Dependencies

```toml
tokio = { version = "1.40", features = ["full"] }
tokio-postgres = "0.7"
chrono = "0.4"
tokio-test = "0.4"
```

## References

- **tokio-postgres**: https://docs.rs/tokio-postgres/
- **PostgreSQL Protocol**: https://www.postgresql.org/docs/current/protocol.html
- **Rust async book**: https://rust-lang.github.io/async-book/
- **TIMESTAMP Binary Format**: See protocol.py:1564-1585 (Fix 3 implementation)
