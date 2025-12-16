# Data Model: Package Hygiene Validation Entities

**Feature**: 025-comprehensive-code-and
**Phase**: Phase 1 - Design
**Date**: 2025-11-15

This document defines the entities, relationships, and validation rules for package hygiene and professional standards validation.

---

## Entity: PackageMetadata

**Purpose**: Represents package metadata defined in `pyproject.toml` (PEP 621)

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Package name (e.g., "iris-pgwire") |
| `version` | str | Yes | Semantic version (e.g., "0.1.0") |
| `description` | str | Yes | One-line package description |
| `readme` | dict | Yes | README file reference (`{file: "README.md", content-type: "text/markdown"}`) |
| `license` | dict | Yes | License reference (`{file: "LICENSE"}`) |
| `authors` | list[dict] | Yes | Author information (`[{name: "...", email: "..."}]`) |
| `maintainers` | list[dict] | No | Maintainer information |
| `keywords` | list[str] | Yes | PyPI search keywords (e.g., ["iris", "postgresql", "pgvector"]) |
| `classifiers` | list[str] | Yes | PyPI classifiers (development status, license, Python version) |
| `requires-python` | str | Yes | Python version requirement (e.g., ">=3.11") |
| `dependencies` | list[str] | Yes | Runtime dependencies with version constraints |
| `optional-dependencies` | dict | No | Optional dependency groups (`test`, `dev`, `iris`) |
| `urls` | dict | Yes | Project URLs (Homepage, Documentation, Repository, Issues) |
| `scripts` | dict | No | Entry points (e.g., `iris-pgwire = "iris_pgwire.server:main"`) |

### Validation Rules

1. **PEP 621 Compliance**:
   - All required fields MUST be present
   - Field types MUST match PEP 621 specification
   - `readme.content-type` MUST be "text/markdown" or "text/x-rst"

2. **Version Format**:
   - MUST follow semantic versioning (MAJOR.MINOR.PATCH)
   - MUST match version in `src/iris_pgwire/__init__.py`
   - MUST have corresponding entry in CHANGELOG.md

3. **Classifiers**:
   - MUST include Development Status classifier
   - MUST include License classifier matching LICENSE file
   - MUST include Python version classifiers matching `requires-python`
   - ALL classifiers MUST be valid per `trove-classifiers` package

4. **Dependencies**:
   - Runtime dependencies MUST use version constraints (`>=X.Y`)
   - Test/dev dependencies SHOULD use flexible constraints
   - ALL dependencies MUST be free of critical security vulnerabilities

5. **URLs**:
   - Homepage MUST be valid and accessible
   - Documentation URL MUST return 200 OK
   - Repository URL MUST match git remote
   - Issues URL MUST be accessible

### Quality Score

**pyroma Score**: Target ≥9/10
- 1 point: Package has name ✅
- 1 point: Package has version ✅
- 1 point: Package has description ✅
- 1 point: Package has keywords ✅
- 1 point: Package has classifiers ✅
- 1 point: Package has README (long_description) ✅
- 1 point: Package has license ✅
- 1 point: Package has author/maintainer ✅
- 1 point: Package has homepage/documentation URLs ✅
- 1 point: README format specified (text/markdown) ✅

### Relationships

- **Has many** Dependencies (runtime, test, dev)
- **References** Documentation files (README.md, LICENSE, CHANGELOG.md)
- **Produces** Source distribution (sdist) validated by check-manifest
- **Published to** PyPI (when score ≥9/10)

---

## Entity: SourceCode

**Purpose**: Represents Python source modules in `src/iris_pgwire/`

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `module_path` | Path | Full path to .py file |
| `relative_path` | str | Path relative to src/ |
| `docstring` | str \| None | Module-level docstring |
| `functions` | list[Function] | Public functions (no leading underscore) |
| `classes` | list[Class] | Public classes |
| `line_count` | int | Total lines of code |
| `complexity` | int | Cyclomatic complexity (McCabe) |
| `type_annotations` | bool | Has type hints for public APIs |
| `imports` | list[str] | Imported modules |

### Validation Rules

1. **PEP 8 Compliance**:
   - Code MUST pass black formatter (`black --check`)
   - Code MUST pass ruff linter (`ruff check`)
   - Line length MUST be ≤100 characters

2. **Docstring Coverage**:
   - Public modules MUST have docstring ✅
   - Public functions MUST have docstring ✅
   - Public classes MUST have docstring ✅
   - Overall coverage target: ≥80%

3. **Type Annotations**:
   - Public function signatures SHOULD have type hints
   - Return types SHOULD be specified
   - mypy validation MUST pass for public APIs

4. **Complexity**:
   - Cyclomatic complexity SHOULD be <10 per function
   - File length SHOULD be <500 lines
   - Function length SHOULD be <50 lines

5. **Security**:
   - NO hardcoded passwords or secrets
   - NO SQL injection vulnerabilities
   - NO use of `eval()` or `exec()` without sanitization
   - NO insecure cryptography (md5, sha1 for security)

### State Transitions

```
Unvalidated
    ↓
[black --check]
    ↓
Formatted
    ↓
[ruff check]
    ↓
Linted
    ↓
[mypy src/]
    ↓
Type-Checked
    ↓
[interrogate -vv]
    ↓
Documented
    ↓
[bandit -r src/]
    ↓
Secured
    ↓
Validated ✅
```

### Relationships

- **Belongs to** Package (iris-pgwire)
- **Tested by** TestSuite
- **Documented in** Documentation
- **Imports** Dependencies

---

## Entity: Dependencies

**Purpose**: Represents external packages required by iris-pgwire

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `package_name` | str | PyPI package name (e.g., "structlog") |
| `version_constraint` | str | Version specifier (e.g., ">=23.0.0") |
| `dependency_type` | enum | runtime \| test \| dev |
| `security_status` | enum | safe \| vulnerable \| unknown |
| `cve_ids` | list[str] | Known CVE identifiers |
| `license` | str | Dependency license (e.g., "MIT", "Apache-2.0") |
| `last_updated` | date | Last PyPI release date |

### Validation Rules

1. **Version Constraints**:
   - Runtime dependencies MUST specify lower bound (`>=X.Y`)
   - Version constraints SHOULD specify upper bound for breaking-prone packages
   - Constraints MUST be compatible with each other (no conflicts)

2. **Security**:
   - NO critical vulnerabilities (CVSS ≥9.0)
   - NO high vulnerabilities (CVSS ≥7.0) without documented exception
   - pip-audit MUST report zero critical/high vulnerabilities

3. **License Compatibility**:
   - ALL dependencies MUST have OSI-approved licenses
   - Licenses MUST be compatible with MIT (iris-pgwire license)
   - Copyleft licenses (GPL) SHOULD be avoided for runtime dependencies

4. **Freshness**:
   - Dependencies SHOULD be updated within last 2 years
   - Deprecated packages SHOULD be replaced

### Relationships

- **Required by** PackageMetadata
- **Validated by** pip-audit, bandit
- **Documented in** pyproject.toml [project.dependencies]

---

## Entity: TestSuite

**Purpose**: Represents automated test coverage for iris-pgwire

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `total_tests` | int | Total test count |
| `contract_tests` | int | Contract test count (tests/contract/) |
| `integration_tests` | int | Integration test count (tests/integration/) |
| `unit_tests` | int | Unit test count (tests/unit/) |
| `passing_tests` | int | Tests passing |
| `failing_tests` | int | Tests failing |
| `pass_rate` | float | Percentage passing (0-100%) |
| `coverage_percentage` | float | Code coverage (0-100%, informational) |
| `avg_execution_time` | float | Average test execution time (seconds) |
| `timeout_count` | int | Tests exceeding 30s timeout |

### Validation Rules

1. **Test Pass Rate**:
   - Target: 100% tests passing ✅
   - Acceptable: ≥95% tests passing ⚠️
   - Critical: <95% tests passing ❌

2. **Test Coverage** (informational only):
   - Coverage tracked but NO fail_under threshold
   - Coverage report generated for analysis
   - Uncovered lines identified for future work

3. **Test Categorization**:
   - Contract tests: Validate framework contracts (TDD)
   - Integration tests: E2E workflows with IRIS
   - Unit tests: Isolated component testing

4. **Performance**:
   - Individual tests MUST complete within 30s
   - Test suite SHOULD complete within 10 minutes
   - Timeout handling: Diagnostics provided for >30s tests

### Relationships

- **Tests** SourceCode modules
- **Validates** Functionality against Contracts
- **Configured in** pyproject.toml [tool.pytest.ini_options]

---

## Entity: Documentation

**Purpose**: Represents documentation files and inline documentation

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | Path | Path to documentation file |
| `file_type` | enum | markdown \| python \| other |
| `word_count` | int | Total words (for .md files) |
| `completeness_score` | int | 0-100% completeness rating |
| `last_updated` | date | Last modification date |
| `sections` | list[str] | Section headings (for .md files) |
| `code_examples` | int | Number of code examples |
| `external_links` | int | Number of external references |

### Validation Rules

1. **README.md Requirements**:
   - MUST have title and description ✅
   - MUST have installation instructions ✅
   - MUST have usage examples ✅
   - MUST have documentation links ✅
   - MUST have license section ✅
   - SHOULD have badges (license, Python version, test status)

2. **CHANGELOG.md Requirements**:
   - MUST follow Keep a Changelog format ✅
   - MUST have [Unreleased] section ✅
   - MUST have version sections with dates ✅
   - MUST document Added/Changed/Fixed/Security/Removed

3. **Inline Documentation**:
   - Public modules MUST have docstrings ✅
   - Public functions MUST have docstrings ✅
   - Public classes MUST have docstrings ✅
   - Overall docstring coverage target: ≥80%

4. **Technical Guides**:
   - Complex features SHOULD have dedicated guides (docs/*.md)
   - Troubleshooting guides SHOULD exist (KNOWN_LIMITATIONS.md) ✅
   - Architecture documentation SHOULD exist (CLAUDE.md) ✅

### State Transitions

```
Draft
    ↓
[Content added]
    ↓
Complete
    ↓
[Technical review]
    ↓
Reviewed
    ↓
[User feedback]
    ↓
Published ✅
```

### Relationships

- **Describes** SourceCode, PackageMetadata
- **Referenced by** README.md (internal links)
- **Validated by** interrogate (docstring coverage)

---

## Entity: Repository

**Purpose**: Represents git repository hygiene and file organization

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `total_files` | int | Total tracked files |
| `ignored_files` | int | Files in .gitignore |
| `bytecode_artifacts` | int | *.pyc and __pycache__ directories |
| `uncommitted_changes` | int | Modified files not staged |
| `branch_name` | str | Current git branch |
| `remote_url` | str | Git remote URL |
| `last_commit_date` | date | Most recent commit timestamp |

### Validation Rules

1. **.gitignore Coverage**:
   - MUST exclude Python bytecode (*.pyc, __pycache__) ✅
   - MUST exclude virtual environments (.venv/, venv/) ✅
   - MUST exclude build artifacts (dist/, build/, *.egg-info/) ✅
   - MUST exclude IDE files (.vscode/, .idea/) ✅
   - MUST exclude test artifacts (.pytest_cache/, .coverage) ✅

2. **Bytecode Cleanup**:
   - Zero *.pyc files in repository ✅
   - Zero __pycache__ directories in repository ✅
   - git ls-files MUST NOT show *.pyc

3. **Version Consistency**:
   - pyproject.toml version MUST match src/iris_pgwire/__init__.py
   - CHANGELOG.md MUST have entry for current version
   - Git tags SHOULD match released versions

4. **Source Distribution**:
   - check-manifest MUST pass ("OK" output) ✅
   - sdist MUST include README.md, LICENSE, CHANGELOG.md ✅
   - sdist MUST NOT include tests/, specs/, benchmarks/ ✅

### Relationships

- **Contains** SourceCode, Documentation, Tests
- **Configured by** .gitignore, pyproject.toml
- **Validated by** check-manifest, git commands

---

## Validation Workflow

```
PackageMetadata
    ↓
[pyroma checker]
    ↓
Score ≥9/10?
    ↓
SourceCode → [black] → [ruff] → [mypy] → [bandit] → Validated ✅
    ↓
Documentation → [interrogate] → Coverage ≥80%? → Validated ✅
    ↓
Dependencies → [pip-audit] → Zero critical CVEs? → Validated ✅
    ↓
Repository → [check-manifest] → "OK"? → Validated ✅
    ↓
TestSuite → [pytest] → Pass rate ≥95%? → Validated ✅
    ↓
ALL Validated → Package Ready for PyPI ✅
```

---

## Summary: Validation Checkpoints

| Entity | Tool | Pass Criteria |
|--------|------|---------------|
| PackageMetadata | pyroma | Score ≥9/10 |
| SourceCode | black, ruff, mypy | Zero errors |
| Dependencies | pip-audit, bandit | Zero critical CVEs |
| TestSuite | pytest | Pass rate ≥95% |
| Documentation | interrogate | Coverage ≥80% |
| Repository | check-manifest, git | "OK" + zero *.pyc |

**All checkpoints MUST pass before PyPI release.**
