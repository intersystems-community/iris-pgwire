#!/bin/bash
# run-tests.sh - Automated PHP test execution

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
./vendor/bin/phpunit --verbose 2>&1 | tee test-output.log

echo ""
echo "==================================="
echo "Test execution complete"
echo "==================================="
