#!/bin/bash
# Package Quality Validation Script (Feature 025)
# Comprehensive 5-step validation workflow for iris-pgwire
#
# Usage: ./scripts/validate_package.sh [--verbose] [--fail-fast]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
VERBOSE=""
FAIL_FAST=""
for arg in "$@"; do
    case $arg in
        --verbose|-v)
            VERBOSE="--verbose"
            shift
            ;;
        --fail-fast|-f)
            FAIL_FAST="--fail-fast"
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --verbose, -v     Show detailed validation output"
            echo "  --fail-fast, -f   Stop on first validation failure"
            echo "  --help, -h        Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                      # Run all validations"
            echo "  $0 --verbose            # Show detailed output"
            echo "  $0 --fail-fast          # Stop on first failure"
            exit 0
            ;;
    esac
done

# Print header
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}iris-pgwire Package Quality Validation${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Step 1: Check prerequisites
echo -e "${BLUE}Step 1: Checking prerequisites...${NC}"
if ! command -v python &> /dev/null; then
    echo -e "${RED}✗ Python not found${NC}"
    exit 1
fi

python_version=$(python --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}✓ Python $python_version${NC}"

# Check for required packages
if ! python -c "import pyroma" 2>/dev/null; then
    echo -e "${YELLOW}⚠ pyroma not installed - installing validation tools...${NC}"
    pip install -q pyroma check-manifest black ruff interrogate bandit pip-audit trove-classifiers
fi

echo -e "${GREEN}✓ All validation tools available${NC}"
echo ""

# Step 2: Run comprehensive validation
echo -e "${BLUE}Step 2: Running comprehensive validation...${NC}"
echo ""

# Build validation command
CMD="python -m iris_pgwire.quality"
if [ -n "$VERBOSE" ]; then
    CMD="$CMD $VERBOSE"
fi
if [ -n "$FAIL_FAST" ]; then
    CMD="$CMD $FAIL_FAST"
fi

# Run validation
if eval $CMD; then
    VALIDATION_EXIT_CODE=0
else
    VALIDATION_EXIT_CODE=$?
fi

echo ""

# Step 3: Display results
echo -e "${BLUE}Step 3: Validation results${NC}"
echo ""

if [ $VALIDATION_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ Package validation PASSED${NC}"
    echo -e "${GREEN}✅ Package is ready for PyPI distribution${NC}"
    echo ""

    # Step 4: Show optional next steps
    echo -e "${BLUE}Step 4: Optional next steps${NC}"
    echo ""
    echo "  • Create git tag: bump2version patch|minor|major"
    echo "  • Build distribution: python -m build"
    echo "  • Upload to PyPI: twine upload dist/*"
    echo ""

    exit 0
else
    echo -e "${RED}❌ Package validation FAILED${NC}"
    echo -e "${YELLOW}Please fix the issues above and run validation again${NC}"
    echo ""

    # Step 4: Troubleshooting tips
    echo -e "${BLUE}Step 4: Troubleshooting tips${NC}"
    echo ""
    echo "  • Package metadata: Run 'pyroma .' for detailed scoring"
    echo "  • Code quality: Run 'black src/ tests/' to fix formatting"
    echo "  • Security: Run 'pip-audit' to see vulnerability details"
    echo "  • Documentation: Run 'interrogate -vv src/iris_pgwire/' for coverage"
    echo ""
    echo "  For more help: python -m iris_pgwire.quality --help"
    echo ""

    exit 1
fi
