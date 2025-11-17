# Quick Start: Package Hygiene Validation

**Feature**: 025-comprehensive-code-and
**Purpose**: Step-by-step guide to validate iris-pgwire package quality

---

## Prerequisites

- Python 3.11+
- iris-pgwire repository cloned
- Virtual environment activated

---

## Installation

```bash
# Install validation tools
pip install pyroma check-manifest black ruff mypy bandit pip-audit interrogate trove-classifiers

# Or with uv (faster)
uv pip install pyroma check-manifest black ruff mypy bandit pip-audit interrogate trove-classifiers
```

---

## Validation Workflow (5 Steps)

### Step 1: Package Metadata Validation

```bash
# Run pyroma quality checker
pyroma .

# Expected output:
# Checking .
# Found iris-pgwire
# --------------
# Your package scores 9 out of 10
# --------------------------

# Target: Score ≥9/10 ✅

# Validate source distribution
check-manifest

# Expected output:
# lists of files in version control: X
# lists of files in sdist: X
# OK

# Target: "OK" output ✅
```

**Fix Issues**:
- Low score: Add missing classifiers, keywords, or documentation links to pyproject.toml
- Missing files: Run `check-manifest --update` to regenerate MANIFEST.in

---

### Step 2: Code Quality Validation

```bash
# Check code formatting
black --check src/ tests/

# Expected output:
# All done! ✨ 🍰 ✨
# X files would be left unchanged.

# Target: All files unchanged ✅

# Run linter
ruff check src/ tests/

# Expected output:
# All checks passed!

# Target: Zero errors/warnings ✅

# Check type annotations (gradual adoption)
mypy src/iris_pgwire/server.py src/iris_pgwire/protocol.py

# Expected output:
# Success: no issues found in X source files

# Target: No type errors for public APIs ✅
```

**Fix Issues**:
- Formatting: Run `black src/ tests/` to auto-format
- Linting: Run `ruff check --fix src/ tests/` to auto-fix
- Type errors: Add type hints or `# type: ignore` with justification

---

### Step 3: Security Validation

```bash
# Scan code for security issues
bandit -r src/iris_pgwire/

# Expected output:
# Test results:
#     No issues identified.
# Code scanned: X lines
# Total issues: 0

# Target: Zero security issues ✅

# Scan dependencies for vulnerabilities
pip-audit

# Expected output:
# No known vulnerabilities found

# Target: Zero critical/high CVEs ✅
```

**Fix Issues**:
- Security issues: Review bandit output, refactor code to eliminate vulnerabilities
- CVE found: Update dependency versions or document exception

---

### Step 4: Documentation Validation

```bash
# Check docstring coverage
interrogate -vv src/iris_pgwire/

# Expected output:
# ================== Coverage for src/iris_pgwire/ ===================
# --------------------------------- Summary ----------------------------------
# | Name                     | Total | Miss | Cover |
# |--------------------------|-------|------|-------|
# | src/iris_pgwire/         |   X   |  X   |  X%   |
# ------------------------------------------------------------------------
# RESULT: PASSED (minimum: 80.0%, actual: X%)

# Target: Coverage ≥80% ✅

# Generate coverage badge
interrogate --generate-badge interrogate_badge.svg src/iris_pgwire/
```

**Fix Issues**:
- Low coverage: Add docstrings to public modules, functions, classes
- Use Google-style docstrings for consistency

---

### Step 5: Repository Hygiene Validation

```bash
# Check for committed bytecode
git ls-files | grep -E '\.pyc$|__pycache__'

# Expected output:
# (empty - no results)

# Target: Zero bytecode files ✅

# Clean up bytecode (if found)
find . -type f -name "*.pyc" -delete
find . -type d -name "__pycache__" -exec rm -rf {} +

# Verify CHANGELOG.md format
cat CHANGELOG.md | head -20

# Expected sections:
# # Changelog
# ## [Unreleased]
# ## [X.Y.Z] - YYYY-MM-DD

# Target: Keep a Changelog format ✅
```

**Fix Issues**:
- Bytecode found: Add to .gitignore, run cleanup commands above
- CHANGELOG missing: Add version entry with Added/Changed/Fixed sections

---

## Complete Validation Script

Save as `scripts/validate_package.sh`:

```bash
#!/bin/bash
# Complete package hygiene validation

set -e  # Exit on first error

echo "=== Package Hygiene Validation ==="
echo

echo "Step 1: Metadata validation..."
pyroma . || exit 1
check-manifest || exit 1
echo "✅ Metadata validation passed"
echo

echo "Step 2: Code quality validation..."
black --check src/ tests/ || exit 1
ruff check src/ tests/ || exit 1
# mypy src/iris_pgwire/ || echo "⚠️  Type checking incomplete (gradual adoption)"
echo "✅ Code quality validation passed"
echo

echo "Step 3: Security validation..."
bandit -r src/iris_pgwire/ || exit 1
pip-audit || exit 1
echo "✅ Security validation passed"
echo

echo "Step 4: Documentation validation..."
interrogate -vv src/iris_pgwire/ || exit 1
echo "✅ Documentation validation passed"
echo

echo "Step 5: Repository hygiene..."
bytecode_count=$(git ls-files | grep -E '\.pyc$|__pycache__' | wc -l)
if [ "$bytecode_count" -gt 0 ]; then
    echo "❌ Found $bytecode_count bytecode files"
    exit 1
fi
echo "✅ Repository hygiene passed"
echo

echo "========================================="
echo "✅ ALL VALIDATION CHECKS PASSED"
echo "Package ready for PyPI release!"
echo "========================================="
```

**Usage**:
```bash
chmod +x scripts/validate_package.sh
./scripts/validate_package.sh
```

---

## Pre-commit Hook Setup (Optional)

Automate validation on every commit:

```bash
# Create pre-commit hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
# Pre-commit package quality checks

# Clean bytecode
find . -type f -name "*.pyc" -delete
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Format code
black src/ tests/

# Lint code
ruff check --fix src/ tests/

# Stage auto-formatted files
git add -u

echo "✅ Pre-commit checks passed"
EOF

chmod +x .git/hooks/pre-commit
```

---

## Continuous Integration (GitHub Actions)

Example workflow for automated validation:

```yaml
# .github/workflows/package-quality.yml
name: Package Quality

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install validation tools
        run: |
          pip install pyroma check-manifest black ruff bandit pip-audit interrogate

      - name: Metadata validation
        run: |
          pyroma .
          check-manifest

      - name: Code quality
        run: |
          black --check src/ tests/
          ruff check src/ tests/

      - name: Security
        run: |
          bandit -r src/
          pip-audit

      - name: Documentation
        run: |
          interrogate -vv src/iris_pgwire/
```

---

## Troubleshooting

### Issue: pyroma score <9/10

**Symptoms**: pyroma reports missing metadata fields

**Solution**:
1. Read pyroma output carefully (lists missing items)
2. Add missing fields to `[project]` section in pyproject.toml:
   - keywords = ["iris", "postgresql", ...]
   - classifiers = ["Development Status :: 4 - Beta", ...]
   - urls = {Homepage = "...", Documentation = "..."}
3. Run `pyroma .` again to verify score ≥9/10

### Issue: check-manifest fails

**Symptoms**: "lists of files in version control: X / lists of files in sdist: Y"

**Solution**:
1. Run `check-manifest --update` to regenerate MANIFEST.in
2. Review changes to ensure intentional
3. Commit updated MANIFEST.in

### Issue: black formatting conflicts

**Symptoms**: "X files would be reformatted"

**Solution**:
1. Run `black src/ tests/` to auto-format (no --check flag)
2. Review changes (usually just whitespace, line breaks)
3. Commit formatted files

### Issue: ruff reports errors

**Symptoms**: "Found X errors"

**Solution**:
1. Run `ruff check --fix src/ tests/` to auto-fix (many rules fixable)
2. For remaining errors, review ruff output and fix manually
3. Use `# noqa: <rule>` sparingly for intentional violations

### Issue: bandit reports security issues

**Symptoms**: "Issue: [security_issue] Severity: High"

**Solution**:
1. Review bandit output for details
2. Refactor code to eliminate vulnerability (e.g., use parameterized queries)
3. If false positive, add `# nosec` comment with justification

### Issue: pip-audit finds CVEs

**Symptoms**: "Found X known vulnerability in ..."

**Solution**:
1. Update dependency: `pip install --upgrade <package>`
2. Test package still works after upgrade
3. If no fix available, document exception and mitigation

### Issue: interrogate reports low coverage

**Symptoms**: "RESULT: FAILED (minimum: 80.0%, actual: X%)"

**Solution**:
1. Run `interrogate -vv src/iris_pgwire/` to see missing docstrings
2. Add docstrings to public modules, functions, classes
3. Use Google-style docstrings for consistency

### Issue: Bytecode files committed

**Symptoms**: `git ls-files` shows *.pyc or __pycache__

**Solution**:
1. Remove from git: `git rm --cached <file>`
2. Add to .gitignore: `echo "__pycache__/" >> .gitignore`
3. Clean workspace: `find . -name "*.pyc" -delete`
4. Commit .gitignore update

---

## Next Steps

After all validation checks pass:

1. ✅ **Version Update**: Use `bump2version patch` to increment version
2. ✅ **CHANGELOG Update**: Add version entry with changes
3. ✅ **Build Distribution**: `python -m build` (creates dist/iris-pgwire-X.Y.Z.tar.gz)
4. ✅ **Test Installation**: `pip install dist/iris-pgwire-X.Y.Z.tar.gz`
5. ✅ **Upload to PyPI**: `twine upload dist/*` (requires PyPI credentials)

---

**Validation complete!** Package is ready for professional PyPI distribution. 🎉
