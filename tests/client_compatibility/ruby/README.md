# Ruby pg Gem Client Compatibility Tests

Tests for Ruby pg gem (ruby-pg) compatibility with IRIS PGWire server.

## Test Coverage

**Total Tests**: 25 tests across 3 suites

### Connection Tests (6 tests)
- Basic connection establishment
- Connection with connection string
- Multiple sequential connections
- Server version query
- Error handling for invalid connections
- Multiple queries per connection

### Query Tests (12 tests)
- Simple SELECT with constants
- Multiple column selection
- CURRENT_TIMESTAMP query
- NULL value handling
- Prepared statements (single parameter with `$1` syntax)
- Prepared statements (multiple parameters)
- Prepared statements with NULL
- String escaping and special characters
- Multiple row results (UNION ALL)
- Empty result sets
- Sequential query execution
- Binary data handling

### Transaction Tests (7 tests)
- Explicit BEGIN command
- Explicit COMMIT command
- Explicit ROLLBACK command
- Queries within transactions
- Multiple queries in single transaction
- Transaction block method (`conn.transaction do ... end`)
- Transaction rollback on error

## Prerequisites

- Ruby 3.0+ with bundler
- IRIS PGWire server running on localhost:5432

### Install Ruby and Bundler (macOS)

```bash
# Install Ruby via Homebrew
brew install ruby

# Add Ruby to PATH (add to ~/.zshrc or ~/.bash_profile)
export PATH="/opt/homebrew/opt/ruby/bin:$PATH"

# Install Bundler
gem install bundler

# Verify installation
ruby --version
bundle --version
```

### Install Ruby and Bundler (Ubuntu/Debian)

```bash
# Install Ruby and development tools
sudo apt-get update
sudo apt-get install ruby ruby-dev build-essential libpq-dev

# Install Bundler
gem install bundler

# Verify installation
ruby --version
bundle --version
```

## Installation

```bash
cd tests/client_compatibility/ruby
bundle install
```

## Running Tests

### Run All Tests

```bash
bundle exec rake test
```

### Run Specific Test File

```bash
bundle exec ruby test/connection_test.rb
bundle exec ruby test/query_test.rb
bundle exec ruby test/transaction_test.rb
```

### Run with Verbose Output

```bash
bundle exec rake test TESTOPTS="-v"
```

## Configuration

Environment variables can be set via shell:

```bash
export PGWIRE_HOST=localhost
export PGWIRE_PORT=5432
export PGWIRE_DATABASE=USER
export PGWIRE_USERNAME=test_user
export PGWIRE_PASSWORD=test

bundle exec rake test
```

## Expected Results

All tests should pass (25/25):
- ✅ Connection Tests: 6/6
- ✅ Query Tests: 12/12
- ✅ Transaction Tests: 7/7

## Test Execution Script

```bash
#!/bin/bash
# run-tests.sh - Automated test execution

cd "$(dirname "$0")"

echo "==================================="
echo "Ruby pg Gem Compatibility Tests"
echo "==================================="
echo ""

# Check Ruby version
echo "Ruby Version:"
ruby --version
echo ""

# Check pg gem
echo "Checking pg gem..."
if gem list | grep -q "^pg "; then
    echo "✅ pg gem found"
else
    echo "⚠️  pg gem not found - will install via bundler"
fi
echo ""

# Install dependencies
if [ ! -d "vendor/bundle" ]; then
    echo "Installing gem dependencies..."
    bundle install
    echo ""
fi

# Run tests
echo "Running tests..."
bundle exec rake test TESTOPTS="-v" 2>&1 | tee test-output.log

echo ""
echo "==================================="
echo "Test execution complete"
echo "==================================="
```

## Troubleshooting

### pg Gem Installation Fails

The pg gem requires libpq development headers:

```bash
# macOS
brew install postgresql

# Ubuntu/Debian
sudo apt-get install libpq-dev

# Then retry bundle install
bundle install
```

### Connection Refused

Ensure IRIS PGWire server is running:

```bash
docker compose ps
docker logs iris-pgwire-db
```

### Bundler Not Found

```bash
gem install bundler

# If permission denied
sudo gem install bundler
```

## Features Tested

### ✅ Implemented and Validated
- PG connection establishment
- ruby-pg (pg gem) driver compatibility
- Simple queries (SELECT constants)
- Prepared statements with positional parameters (`$1`, `$2`)
- Parameter binding (integers, strings, NULL, binary data)
- Transaction management (BEGIN/COMMIT/ROLLBACK)
- Transaction block method (`conn.transaction do ... end`)
- Error handling (exceptions, invalid connections)
- Multiple queries per connection
- CURRENT_TIMESTAMP queries
- NULL handling (IS NULL comparisons, empty result sets)
- Special character escaping (quotes, backslashes)
- UNION ALL queries (multi-row results)
- Empty result sets
- Binary data handling
- Sequential query execution

### Ruby-Specific Features
- **PG::Connection**: Standard PostgreSQL connection object
- **exec_params**: Prepared statement execution with parameters
- **transaction block**: Automatic BEGIN/COMMIT/ROLLBACK handling
- **server_version**: Server version query method
- **ntuples**: Row count for result sets
- **Connection string**: PostgreSQL-style connection strings

## Performance Notes

- Ruby pg gem uses **text format** (0) by default (like Node.js pg and PHP PDO)
- Built on libpq C library (same foundation as PHP PDO_PGSQL and Perl DBD::Pg)
- Performance characteristics similar to other libpq-based drivers
- Transaction block method provides automatic rollback on exceptions

## Compatibility Notes

### Transaction Translation (Feature 022)
- Ruby `BEGIN` automatically translated to IRIS `START TRANSACTION`
- `conn.transaction do ... end` method works seamlessly
- All standard PostgreSQL transaction commands supported

### Binary Format Support (Fix 1)
- Ruby pg gem uses text format by default
- Binary format available via `exec_params` with format parameter
- Text format fully validated and working

### TIMESTAMP Handling (Fix 3)
- CURRENT_TIMESTAMP returns string format
- Ruby can parse timestamp strings with `Time.parse()`
- No special binary format handling needed

### ActiveRecord Compatibility
- Tests focus on low-level pg gem API
- ActiveRecord ORM should work on top of pg gem
- Further testing recommended for full Rails integration

## References

- **Ruby pg Gem Documentation**: https://rubygems.org/gems/pg
- **GitHub Repository**: https://github.com/ged/ruby-pg
- **Client Compatibility Summary**: `../CLIENT_COMPATIBILITY_SUMMARY.md`
- **Protocol Completeness Audit**: `../../docs/PROTOCOL_COMPLETENESS_AUDIT.md`
