#!/bin/bash
# run-tests.sh - Automated Ruby test execution

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
