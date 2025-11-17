# PHP PDO_PGSQL Client Compatibility Tests

Tests for PHP PDO_PGSQL driver compatibility with IRIS PGWire server.

## Test Coverage

**Total Tests**: 25 tests across 3 suites

### Connection Tests (6 tests)
- Basic connection establishment
- Connection with DSN string
- Multiple sequential connections
- Server version query
- Error handling for invalid connections
- Multiple queries per connection

### Query Tests (12 tests)
- Simple SELECT with constants
- Multiple column selection
- CURRENT_TIMESTAMP query
- NULL value handling
- Prepared statements (single parameter)
- Prepared statements (multiple parameters)
- Prepared statements with NULL
- String escaping and special characters
- Multiple row results (UNION ALL)
- Empty result sets
- Sequential query execution
- BLOB/binary data handling

### Transaction Tests (7 tests)
- Explicit BEGIN command
- Explicit COMMIT command
- Explicit ROLLBACK command
- Queries within transactions
- Multiple queries in single transaction
- PDO's beginTransaction() method
- PDO's rollback() method

## Prerequisites

- PHP 8.0+ with PDO and PDO_PGSQL extensions
- Composer
- IRIS PGWire server running on localhost:5432

### Install PHP and Extensions (macOS)

```bash
# Install PHP via Homebrew
brew install php

# Verify pdo_pgsql is installed
php -m | grep pdo_pgsql
# If missing, install:
# brew install php@8.2
# And ensure pdo_pgsql extension is enabled in php.ini
```

### Install PHP and Extensions (Ubuntu/Debian)

```bash
# Install PHP and PDO PostgreSQL extension
sudo apt-get update
sudo apt-get install php php-pgsql php-xml php-mbstring composer

# Verify installation
php -m | grep pdo_pgsql
```

## Installation

```bash
cd tests/client_compatibility/php
composer install
```

## Running Tests

### Run All Tests

```bash
./vendor/bin/phpunit
```

### Run Specific Test Suite

```bash
# Connection tests only
./vendor/bin/phpunit --testsuite "Connection Tests"

# Query tests only
./vendor/bin/phpunit --testsuite "Query Tests"

# Transaction tests only
./vendor/bin/phpunit --testsuite "Transaction Tests"
```

### Run Single Test File

```bash
./vendor/bin/phpunit tests/ConnectionTest.php
./vendor/bin/phpunit tests/QueryTest.php
./vendor/bin/phpunit tests/TransactionTest.php
```

### Run with Verbose Output

```bash
./vendor/bin/phpunit --verbose
```

## Configuration

Environment variables can be set in `phpunit.xml` or via shell:

```bash
export PGWIRE_HOST=localhost
export PGWIRE_PORT=5432
export PGWIRE_DATABASE=USER
export PGWIRE_USERNAME=test_user
export PGWIRE_PASSWORD=test

./vendor/bin/phpunit
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
echo "PHP PDO_PGSQL Compatibility Tests"
echo "==================================="
echo ""

# Check PHP version
echo "PHP Version:"
php --version | head -1
echo ""

# Check PDO_PGSQL extension
echo "Checking PDO_PGSQL extension..."
if php -m | grep -q pdo_pgsql; then
    echo "✅ PDO_PGSQL extension found"
else
    echo "❌ PDO_PGSQL extension NOT found"
    echo "Install with: brew install php (macOS) or apt-get install php-pgsql (Linux)"
    exit 1
fi
echo ""

# Install dependencies
if [ ! -d "vendor" ]; then
    echo "Installing Composer dependencies..."
    composer install
    echo ""
fi

# Run tests
echo "Running tests..."
./vendor/bin/phpunit --verbose

echo ""
echo "==================================="
echo "Test execution complete"
echo "==================================="
```

## Troubleshooting

### PDO_PGSQL Extension Not Found

```bash
# macOS
brew install php
brew link php

# Ubuntu/Debian
sudo apt-get install php-pgsql

# Verify
php -m | grep pdo_pgsql
```

### Connection Refused

Ensure IRIS PGWire server is running:

```bash
docker compose ps
docker logs iris-pgwire-db
```

### Composer Not Found

```bash
# macOS
brew install composer

# Ubuntu/Debian
sudo apt-get install composer

# Or download directly
curl -sS https://getcomposer.org/installer | php
mv composer.phar /usr/local/bin/composer
```

## Features Tested

### ✅ Implemented and Validated
- PDO connection establishment
- PDO_PGSQL driver compatibility
- Simple queries (SELECT constants)
- Prepared statements with named parameters
- Parameter binding (integers, strings, NULL, binary data)
- Transaction management (BEGIN/COMMIT/ROLLBACK)
- PDO transaction methods (beginTransaction, commit, rollback)
- Error handling (exceptions, invalid connections)
- Multiple queries per connection
- CURRENT_TIMESTAMP queries
- NULL handling (IS NULL comparisons)
- Special character escaping (quotes, backslashes)
- UNION ALL queries (multi-row results)
- Empty result sets
- BLOB/binary data handling
- Sequential query execution

### PHP-Specific Features
- **PDO::ATTR_ERRMODE**: Exception mode for error handling
- **PDO::ATTR_DEFAULT_FETCH_MODE**: Associative array fetching
- **PDO::PARAM_LOB**: Binary data parameter binding
- **Named parameters**: `:parameter` syntax for prepared statements
- **DSN strings**: Standard PostgreSQL DSN format
- **Server version**: PDO::ATTR_SERVER_VERSION attribute

## Performance Notes

- PHP PDO uses **text format** (0) by default (unlike Go pgx or Rust tokio-postgres)
- Performance characteristics similar to Node.js pg driver
- Prepared statements use server-side statement caching
- PDO persistent connections supported (`PDO::ATTR_PERSISTENT`)

## Compatibility Notes

### Transaction Translation (Feature 022)
- PHP `BEGIN` automatically translated to IRIS `START TRANSACTION`
- PDO's `beginTransaction()` method works seamlessly
- All standard PostgreSQL transaction commands supported

### Binary Format Support (Fix 1)
- PHP PDO uses text format by default
- Binary format not commonly used in PHP ecosystem
- Text format fully validated and working

### TIMESTAMP Handling (Fix 3)
- CURRENT_TIMESTAMP returns string format
- PHP can parse timestamp strings natively
- No special binary format handling needed

## References

- **PHP PDO Documentation**: https://www.php.net/manual/en/book.pdo.php
- **PDO_PGSQL Driver**: https://www.php.net/manual/en/ref.pdo-pgsql.php
- **Client Compatibility Summary**: `../CLIENT_COMPATIBILITY_SUMMARY.md`
- **Protocol Completeness Audit**: `../../docs/PROTOCOL_COMPLETENESS_AUDIT.md`
