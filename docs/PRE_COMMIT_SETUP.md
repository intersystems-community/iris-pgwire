# Pre-Commit Hook Setup (Optional)

This document describes how to set up local pre-commit validation hooks for iris-pgwire development. These hooks are **optional** and not enforced - developers can choose whether to use them.

## Overview

Pre-commit hooks automatically run validation checks before each git commit, helping catch issues early in the development process. The hooks provided here focus on:

1. **Bytecode cleanup** - Remove Python .pyc files and __pycache__ directories
2. **Code formatting** - Auto-format with black
3. **Linting** - Check with ruff
4. **Auto-staging** - Stage formatted files automatically

## Prerequisites

- Python 3.11+
- Git repository initialized
- Validation tools installed: `pip install black ruff`

## Installation

### Option 1: Manual Hook Installation (Recommended)

Create a pre-commit hook file at `.git/hooks/pre-commit`:

```bash
#!/bin/bash
# iris-pgwire pre-commit hook (optional)
# Automatically cleans bytecode, formats code, and runs linting

set -e

echo "Running pre-commit validation..."

# Step 1: Clean Python bytecode artifacts
echo "  🧹 Cleaning bytecode artifacts..."
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Step 2: Get list of staged Python files
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.py$' || true)

if [ -z "$STAGED_FILES" ]; then
    echo "  ✓ No Python files to validate"
    exit 0
fi

echo "  📝 Formatting with black..."
# Format staged Python files
for file in $STAGED_FILES; do
    if [ -f "$file" ]; then
        black "$file" --quiet
        # Re-stage the formatted file
        git add "$file"
    fi
done

echo "  🔍 Linting with ruff..."
# Run ruff on staged files (non-blocking)
ruff check $STAGED_FILES --fix --quiet || true

# Re-stage fixed files
for file in $STAGED_FILES; do
    if [ -f "$file" ]; then
        git add "$file"
    fi
done

echo "  ✅ Pre-commit validation complete"
```

Make the hook executable:

```bash
chmod +x .git/hooks/pre-commit
```

### Option 2: Using pre-commit Framework

Alternatively, use the [pre-commit](https://pre-commit.com/) framework:

1. Install pre-commit:
   ```bash
   pip install pre-commit
   ```

2. Create `.pre-commit-config.yaml` in repository root:
   ```yaml
   repos:
     - repo: https://github.com/psf/black
       rev: 23.12.1
       hooks:
         - id: black
           language_version: python3.11

     - repo: https://github.com/astral-sh/ruff-pre-commit
       rev: v0.1.9
       hooks:
         - id: ruff
           args: [--fix]

     - repo: local
       hooks:
         - id: clean-bytecode
           name: Clean Python bytecode
           entry: bash -c 'find . -type f -name "*.pyc" -delete && find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true'
           language: system
           pass_filenames: false
   ```

3. Install the hooks:
   ```bash
   pre-commit install
   ```

## Usage

Once installed, the hooks run automatically before each commit:

```bash
git add src/iris_pgwire/protocol.py
git commit -m "fix: Update protocol handling"

# Output:
# Running pre-commit validation...
#   🧹 Cleaning bytecode artifacts...
#   📝 Formatting with black...
#   🔍 Linting with ruff...
#   ✅ Pre-commit validation complete
# [main abc1234] fix: Update protocol handling
```

## Skipping Hooks

To skip hooks for a specific commit (emergency fixes, etc.):

```bash
git commit --no-verify -m "Emergency fix"
```

## Disabling Hooks

To temporarily disable the hook:

```bash
# Rename the hook file
mv .git/hooks/pre-commit .git/hooks/pre-commit.disabled

# Or delete it
rm .git/hooks/pre-commit
```

## What Gets Validated

### Bytecode Cleanup
- Removes all `.pyc` files
- Removes all `__pycache__` directories
- Runs before formatting to ensure clean working directory

### Black Formatting
- Formats all staged Python files
- Uses line-length=100 (from pyproject.toml)
- Automatically re-stages formatted files
- **Blocks commit if formatting fails** (rare - usually succeeds)

### Ruff Linting
- Checks staged Python files for style issues
- Auto-fixes issues where possible (--fix flag)
- **Non-blocking** - warnings don't prevent commit
- Re-stages fixed files automatically

## Configuration

The hooks respect project configuration from `pyproject.toml`:

```toml
[tool.black]
line-length = 100
target-version = ['py311']

[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E", "W", "F", "I", "B", "C4", "UP"]
```

## Troubleshooting

### Hook Not Running

```bash
# Check hook exists and is executable
ls -la .git/hooks/pre-commit

# If missing executable bit:
chmod +x .git/hooks/pre-commit
```

### Black/Ruff Not Found

```bash
# Install validation tools
pip install black ruff

# Or use project dependencies
pip install -e .[dev]
```

### Hook Takes Too Long

```bash
# Option 1: Skip hooks for quick commits
git commit --no-verify -m "WIP: Quick checkpoint"

# Option 2: Disable hooks temporarily
mv .git/hooks/pre-commit .git/hooks/pre-commit.disabled
```

### Conflicts with Other Hooks

The manual hook can be combined with other hooks by using a hook manager or by sourcing multiple scripts:

```bash
#!/bin/bash
# .git/hooks/pre-commit

# Run iris-pgwire validation
source .git/hooks/iris-pgwire-pre-commit

# Run other project hooks
source .git/hooks/other-hooks
```

## CI/CD Integration

Note that GitHub Actions workflow (`.github/workflows/package-quality.yml`) runs the same validation checks on all commits, so the pre-commit hooks are optional but helpful for faster feedback during development.

## Best Practices

1. **Install hooks early** - Set up hooks when starting development
2. **Commit often** - Small, validated commits are better than large ones
3. **Don't skip hooks** - Use `--no-verify` only for emergencies
4. **Keep hooks fast** - The provided hooks run in <2 seconds for typical commits
5. **Update tools regularly** - `pip install --upgrade black ruff`

## Team Adoption

For teams, consider:

- **Document in README** - Link to this guide
- **Provide setup script** - Automate hook installation
- **Make it optional** - Don't force installation (respect developer preference)
- **Ensure CI enforcement** - GitHub Actions validates all PRs regardless of hooks

## Example Workflow

```bash
# 1. Make changes
vim src/iris_pgwire/protocol.py

# 2. Stage changes
git add src/iris_pgwire/protocol.py

# 3. Commit (hooks run automatically)
git commit -m "feat: Add new protocol message type"
# → Bytecode cleaned
# → Code formatted with black
# → Linting checked with ruff
# → Files re-staged if modified
# → Commit created

# 4. Push to remote
git push origin feature-branch
# → GitHub Actions validates package quality
```

## Additional Resources

- **Black Documentation**: https://black.readthedocs.io/
- **Ruff Documentation**: https://docs.astral.sh/ruff/
- **Pre-commit Framework**: https://pre-commit.com/
- **Git Hooks Guide**: https://git-scm.com/book/en/v2/Customizing-Git-Git-Hooks

## Support

For issues or questions about pre-commit hooks:

1. Check this documentation first
2. Review pyproject.toml configuration
3. Test validation tools independently: `black --check src/`, `ruff check src/`
4. File an issue on GitLab with hook output

---

**Remember**: Pre-commit hooks are a developer productivity tool, not a requirement. Use them if they help your workflow!
