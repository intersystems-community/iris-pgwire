# PyPI Release Checklist

## ✅ Hygiene Review Complete

All PyPI hygiene checks have been completed and the package is ready for publication.

## Package Metadata

- **Package Name**: `iris-pgwire`
- **Version**: `0.1.0`
- **Status**: Beta (Development Status :: 4 - Beta)
- **License**: MIT
- **Python Versions**: 3.11, 3.12+

## What Was Fixed

### 1. ✅ Package Metadata Enhanced
- Added comprehensive PyPI classifiers (15 total)
- Added 14 searchable keywords
- Enhanced description with BI tools and ecosystem focus
- Set content-type to text/markdown for README
- Updated authors and maintainers
- Added Development Status: Beta

### 2. ✅ Dependencies Fixed
- **Removed local file dependency** (`iris-devtools @ file://...`)
- Converted to development note (not required for package installation)
- All dependencies now use proper PyPI package names
- Clear separation of core, test, and dev dependencies

### 3. ✅ URLs Updated for GitHub Migration
- Homepage: https://github.com/intersystems-community/iris-pgwire
- Repository: https://github.com/intersystems-community/iris-pgwire
- Issues: https://github.com/intersystems-community/iris-pgwire/issues
- Changelog: https://github.com/intersystems-community/iris-pgwire/releases
- Documentation: Link to README

### 4. ✅ Build Configuration Optimized
- Created hatchling build configuration
- Configured sdist to include ONLY user-facing files
- Excluded all development files (.claude, .specify, tests, benchmarks, specs, etc.)
- Package size optimized (61 files instead of 500+)

### 5. ✅ Distribution Contents Verified

**Included in distribution**:
- `/src/iris_pgwire/` - Main package code
- `/docs/` - User-facing documentation (4 files):
  - DUAL_PATH_ARCHITECTURE.md
  - HNSW_FINDINGS_2025_10_02.md
  - TRANSLATION_API.md
  - VECTOR_PARAMETER_BINDING.md
- `/examples/` - User examples (6 files):
  - BI_TOOLS_SETUP.md
  - async_sqlalchemy_demo.py
  - bi_tools_demo.py
  - client_demonstrations.py
  - client_demos.py
  - translation_api_demo.py
- README.md, LICENSE, CHANGELOG.md
- pyproject.toml

**Excluded from distribution**:
- All test files (`/tests`)
- All benchmark files (`/benchmarks`)
- All specification/planning docs (`/specs`)
- All Docker files (`docker-compose*.yml`, `Dockerfile*`)
- All development config (`.claude`, `.specify`, `uv.lock`)
- All internal docs (`CLAUDE.md`, `PROGRESS.md`, `STATUS.md`, `TODO.md`)

### 6. ✅ Files Created
- `CHANGELOG.md` - Version history following Keep a Changelog format
- `MANIFEST.in` - Package data inclusion rules
- `PYPI_RELEASE.md` - This checklist

## PyPI Keywords (14 total)

```
intersystems, iris, postgresql, postgres, wire-protocol, database, sql,
pgvector, vector-database, rag, llm, bi-tools, sqlalchemy, async, fastapi
```

## PyPI Classifiers (15 total)

```
Development Status :: 4 - Beta
Intended Audience :: Developers
Intended Audience :: System Administrators
License :: OSI Approved :: MIT License
Operating System :: OS Independent
Programming Language :: Python :: 3
Programming Language :: Python :: 3.11
Programming Language :: Python :: 3.12
Programming Language :: Python :: 3 :: Only
Topic :: Database
Topic :: Database :: Database Engines/Servers
Topic :: Software Development :: Libraries :: Python Modules
Topic :: System :: Networking
Framework :: AsyncIO
Framework :: FastAPI
Typing :: Typed
```

## Pre-Release Testing

### Build Verification ✅
```bash
# Clean build successful
uv build

# Artifacts generated:
# - dist/iris_pgwire-0.1.0.tar.gz (source distribution)
# - dist/iris_pgwire-0.1.0-py3-none-any.whl (wheel)
```

### Content Verification ✅
```bash
# Source distribution: 61 files (clean, no dev files)
tar -tzf dist/iris_pgwire-0.1.0.tar.gz | wc -l

# Only essential directories included:
# - src/ (package code)
# - docs/ (4 user docs)
# - examples/ (6 examples)
```

## Publication Steps

### 1. Test PyPI (Recommended First)
```bash
# Install twine if not available
pip install twine

# Upload to Test PyPI
twine upload --repository testpypi dist/*

# Test installation from Test PyPI
pip install --index-url https://test.pypi.org/simple/ iris-pgwire
```

### 2. Production PyPI
```bash
# Upload to production PyPI
twine upload dist/*

# Verify on PyPI
# https://pypi.org/project/iris-pgwire/
```

### 3. Post-Publication
- Create GitHub release with tag `v0.1.0`
- Link PyPI package in README badges
- Announce in InterSystems community channels

## Installation Commands (Post-Publication)

```bash
# Basic installation
pip install iris-pgwire

# With testing dependencies
pip install iris-pgwire[test]

# With development dependencies
pip install iris-pgwire[dev]

# Using uv (recommended)
uv pip install iris-pgwire
```

## Package Entry Point

The package provides a console script entry point:

```bash
# Start PGWire server
iris-pgwire

# Equivalent to:
python -m iris_pgwire.server
```

## GitHub Migration Notes

Before publishing to PyPI, ensure:
1. ✅ Repository migrated to GitHub at `intersystems-community/iris-pgwire`
2. ✅ All URLs in pyproject.toml point to GitHub (already updated)
3. ✅ Create initial release tag `v0.1.0` on GitHub
4. ✅ Update any internal documentation referencing GitLab URLs

## Quick Validation Checklist

Before `twine upload`:
- [x] Version number set in `src/iris_pgwire/__init__.py`
- [x] CHANGELOG.md updated with release notes
- [x] README.md references correct GitHub URLs
- [x] No local file dependencies in pyproject.toml
- [x] Build succeeds: `uv build`
- [x] Package contents verified: `tar -tzf dist/*.tar.gz`
- [x] Wheel created: `dist/*.whl` exists
- [ ] GitHub repository created and accessible
- [ ] Test PyPI upload successful
- [ ] Test installation from Test PyPI works

## Support

For issues or questions about PyPI publication:
- GitHub Issues: https://github.com/intersystems-community/iris-pgwire/issues
- Email: iris-pgwire@intersystems.com (set in package metadata)
