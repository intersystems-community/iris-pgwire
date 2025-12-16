# Implementation Plan: Package Hygiene and Professional Standards Review

**Branch**: `025-comprehensive-code-and` | **Date**: 2025-11-15 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/025-comprehensive-code-and/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path → ✅ COMPLETE
2. Fill Technical Context (scan for NEEDS CLARIFICATION) → ✅ COMPLETE
3. Fill the Constitution Check section → ✅ COMPLETE
4. Evaluate Constitution Check section → ✅ COMPLETE
5. Execute Phase 0 → research.md → IN PROGRESS
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, CLAUDE.md
7. Re-evaluate Constitution Check
8. Plan Phase 2 → Describe task generation approach (DO NOT create tasks.md)
9. STOP - Ready for /tasks command
```

**IMPORTANT**: The /plan command STOPS at step 9. Phases 2-4 are executed by other commands:
- Phase 2: /tasks command creates tasks.md
- Phase 3-4: Implementation execution (manual or via tools)

## Summary

This feature implements a comprehensive package hygiene and professional standards review for the iris-pgwire Python package to ensure it meets industry best practices for PyPI distribution. The primary requirement is to audit and validate package quality against professional standards across seven categories: metadata configuration, documentation, code quality, testing, security, repository hygiene, and accessibility/distribution.

**Technical Approach** (from research):
- **Audit Framework**: Use industry-standard tools (pyroma, check-manifest, black, ruff, mypy, bandit)
- **Validation Scope**: 31 functional requirements across 7 categories
- **Constitutional Compliance**: Maintain Production Readiness principle (security, monitoring, observability)
- **Quality Metrics**: Measurable success criteria from automated tooling
- **No Breaking Changes**: Package hygiene improvements must maintain backward compatibility

## Technical Context

**Language/Version**: Python 3.11+ (as specified in pyproject.toml:52)
**Primary Dependencies**:
- intersystems-irispython>=5.1.2 (IRIS integration)
- psycopg2-binary>=2.9.10 (PostgreSQL driver - legacy)
- psycopg[binary]>=3.1.0 (PostgreSQL driver - recommended)
- structlog>=23.0.0, cryptography>=41.0.0 (core functionality)
- python-gssapi>=1.8.0 (authentication)

**Storage**: Package metadata in pyproject.toml, source in src/iris_pgwire/, tests in tests/
**Testing**: pytest with contract/integration/unit categories, 30s timeout, coverage tracking
**Target Platform**: OS Independent (classifiers), Python 3.11+ required
**Project Type**: single - Python package with src/ layout

**Performance Goals**:
- Package quality score: Target 10/10 on pyroma checker
- Linter pass rate: 100% (black, ruff)
- Type checking: mypy compliance for public APIs
- Security: Zero critical vulnerabilities from bandit scan
- Documentation completeness: All public APIs documented

**Constraints**:
- Backward compatibility: MUST NOT break existing installations or usage patterns
- Constitutional compliance: MUST maintain Production Readiness standards
- Test coverage: Informational only (no fail_under threshold per pyproject.toml:260)
- Deployment: MUST remain installable via pip, uv, poetry

**Scale/Scope**:
- Source files: ~50 modules in src/iris_pgwire/
- Test files: ~100 test modules across contract/integration/unit categories
- Documentation: ~20 markdown files (README, CLAUDE, specs/)
- Dependencies: 17 runtime, 11 test, 3 dev optional dependencies

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Principle I: Protocol Fidelity
- ✅ **NO VIOLATION**: Package hygiene does NOT modify PostgreSQL wire protocol implementation
- This feature only audits/validates package quality, no protocol changes

### Principle II: Test-First Development
- ✅ **NO VIOLATION**: Testing requirements already comprehensive (102 tests documented)
- Validation will ADD quality checks (pyroma, check-manifest), not remove tests
- Framework already uses iris-devtester for isolated test environments (constitutional requirement)

### Principle III: Phased Implementation
- ✅ **NO VIOLATION**: Package hygiene is independent of P0-P6 protocol phases
- This is maintenance/quality work, not protocol implementation

### Principle IV: IRIS Integration
- ✅ **NO VIOLATION**: No changes to embedded Python execution patterns
- Audit validates existing integration patterns, does NOT modify them

### Principle V: Production Readiness
- ✅ **ALIGNMENT**: This feature DIRECTLY implements Production Readiness principle
- Monitoring: Validates observability patterns (structlog usage)
- Security: Validates dependency security (bandit scan, vulnerability checks)
- Observability: Validates documentation and error handling

### Principle VI: Vector Performance Requirements
- ✅ **NO VIOLATION**: No changes to vector operations or HNSW indexing
- Package hygiene does NOT affect vector performance

### Principle VII: Development Environment Synchronization
- ✅ **ALIGNMENT**: Documentation updates will REINFORCE proper development practices
- Will validate .gitignore coverage of Python bytecode (.pyc, __pycache__)
- Will document proper container restart procedures for code changes

**GATE STATUS**: ✅ **PASS** - No constitutional violations, aligns with Production Readiness principle

## Project Structure

### Documentation (this feature)
```
specs/025-comprehensive-code-and/
├── plan.md              # This file (/plan command output)
├── research.md          # Phase 0 output (/plan command) - IN PROGRESS
├── data-model.md        # Phase 1 output (/plan command)
├── quickstart.md        # Phase 1 output (/plan command)
├── contracts/           # Phase 1 output (/plan command)
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
# Single project structure (iris-pgwire package)
src/iris_pgwire/              # Main source code
├── __init__.py               # Package version (0.1.0)
├── server.py                 # PGWire server entry point
├── protocol.py               # PostgreSQL wire protocol
├── vector_optimizer.py       # pgvector → IRIS translation
├── iris_executor.py          # IRIS SQL execution
├── dbapi_executor.py         # DBAPI backend execution
├── sql_translator/           # SQL translation subsystem
│   ├── translator.py
│   ├── transaction_translator.py
│   └── copy_parser.py
└── auth/                     # Authentication bridge (Feature 024)
    ├── oauth_bridge.py
    ├── gssapi_auth.py
    └── wallet_credentials.py

tests/                        # Test suite
├── contract/                 # Contract tests (framework validation)
│   ├── test_*_contract.py    # ~30 contract test modules
│   └── __init__.py
├── integration/              # Integration tests (E2E workflows)
│   ├── test_*_integration.py # ~25 integration test modules
│   └── conftest.py
└── unit/                     # Unit tests (isolated)
    └── test_*.py             # ~15 unit test modules

docs/                         # Documentation
├── README.md                 # Main project documentation
├── CLAUDE.md                 # Development guidelines
├── CHANGELOG.md              # Version history
├── KNOWN_LIMITATIONS.md      # Limitations catalog
└── *.md                      # Technical guides (~15 files)

# Root configuration files
pyproject.toml                # Package metadata (PEP 621 compliant)
LICENSE                       # MIT license
.gitignore                    # Git exclusions
docker-compose.yml            # Docker deployment
uv.lock                       # Dependency lock file (uv)
```

**Structure Decision**: Single project with src/ layout following PEP 420/517/518 standards. Package uses hatchling build backend, pytest for testing, and follows modern Python packaging best practices. Docker deployment supported via docker-compose.yml with dual backend execution paths (DBAPI external, embedded Python).

**Key Observations**:
- ✅ Clean src/ layout separation
- ✅ Modern pyproject.toml configuration (PEP 621)
- ✅ Comprehensive test categorization (contract/integration/unit)
- ✅ Well-documented codebase (~20 markdown files)
- ⚠️ 95 Python bytecode artifacts present (__pycache__, *.pyc)
- ⚠️ No explicit CHANGELOG version updates (only v0.1.0 documented)

## Phase 0: Outline & Research

**Goal**: Research Python packaging best practices and define measurable quality criteria for all 31 functional requirements.

1. **Extract unknowns from Technical Context** above:
   - RESOLVED: Python version requirement (3.11+ from pyproject.toml)
   - RESOLVED: Testing framework (pytest with 30s timeout, contract/integration/unit)
   - RESOLVED: Current package structure (src/ layout, hatchling backend)
   - **NEEDS RESEARCH**: Industry-standard quality metrics (pyroma scoring, check-manifest validation)
   - **NEEDS RESEARCH**: Security vulnerability scanning tools (bandit, safety, pip-audit)
   - **NEEDS RESEARCH**: Documentation completeness validation (docstring coverage tools)
   - **NEEDS RESEARCH**: Best practices for .gitignore Python projects
   - **NEEDS RESEARCH**: PyPI classifiers completeness validation

2. **Generate and dispatch research agents**:
   ```
   Research Task 1: Python Packaging Best Practices (PEP 517/518/621)
     - pyroma package quality scoring methodology
     - check-manifest source distribution validation
     - PyPI classifiers completeness checklist

   Research Task 2: Code Quality Standards
     - black formatter configuration best practices
     - ruff linter rule selection for production packages
     - mypy type checking requirements for public APIs

   Research Task 3: Security and Dependency Management
     - bandit security scanner configuration
     - pip-audit/safety vulnerability scanning
     - Dependency version pinning strategies (requirements vs constraints)

   Research Task 4: Documentation Standards
     - Docstring coverage measurement tools (interrogate, pydocstyle)
     - README.md completeness checklist (shields.io badges, quickstart)
     - CHANGELOG.md format validation (Keep a Changelog)

   Research Task 5: Repository Hygiene
     - .gitignore templates for Python projects (GitHub official)
     - Bytecode cleanup automation (.pyc, __pycache__)
     - Semantic versioning validation tools (bump2version, python-semantic-release)
   ```

3. **Consolidate findings** in `research.md` using format:
   - **Decision**: Tool/approach selected for each requirement
   - **Rationale**: Why this tool/approach is industry standard
   - **Alternatives considered**: Other options evaluated
   - **Validation command**: Exact command to run for verification

**Output**: research.md with measurable quality criteria for all 31 functional requirements

## Phase 1: Design & Contracts

*Prerequisites: research.md complete*

**Goal**: Design validation contracts, document package metadata model, and create quickstart validation workflow.

1. **Extract entities from feature spec** → `data-model.md`:
   - **Entity: PackageMetadata**
     - Fields: name, version, description, authors, license, keywords, classifiers
     - Validation rules: PEP 621 compliance, required fields complete
     - Relationships: Has dependencies (runtime, test, dev optional)

   - **Entity: SourceCode**
     - Fields: module_path, docstring, type_hints, complexity
     - Validation rules: PEP 8 compliance, docstring coverage ≥80%, cyclomatic complexity <10
     - State transitions: Unvalidated → Linted → Type-Checked → Validated

   - **Entity: Dependencies**
     - Fields: package_name, version_constraint, security_status
     - Validation rules: No critical vulnerabilities, version constraints specified
     - Relationships: Belongs to PackageMetadata (runtime/test/dev)

   - **Entity: TestSuite**
     - Fields: test_count, pass_rate, coverage_percentage
     - Validation rules: All tests pass, coverage informational only
     - Relationships: Tests SourceCode modules

   - **Entity: Documentation**
     - Fields: file_path, completeness_score, last_updated
     - Validation rules: All public APIs documented, CHANGELOG current
     - State transitions: Draft → Reviewed → Published

2. **Generate API contracts** from functional requirements:
   - **FR-001: Package Metadata Contract** (`contracts/package_metadata_contract.py`)
     - Validates pyproject.toml completeness (name, version, description, authors, license)
     - Asserts all required PEP 621 fields present

   - **FR-011: Code Quality Contract** (`contracts/code_quality_contract.py`)
     - Validates PEP 8 compliance via black --check
     - Validates linting via ruff check
     - Asserts zero linter errors/warnings

   - **FR-020: Security Contract** (`contracts/security_contract.py`)
     - Validates dependency security via pip-audit or bandit
     - Asserts zero critical vulnerabilities

   - **FR-006: Documentation Contract** (`contracts/documentation_contract.py`)
     - Validates README.md structure (installation, usage, examples)
     - Validates CHANGELOG.md format (Keep a Changelog)
     - Asserts docstring coverage ≥80%

3. **Generate contract tests** from contracts:
   - Contract tests MUST fail initially (no validation tooling configured)
   - Tests assert expected outputs from quality tools (pyroma, check-manifest)
   - Tests validate error handling when quality standards not met

4. **Extract test scenarios** from user stories:
   - **Scenario 1 (FR-001)**: Package maintainer validates metadata completeness
     - Test: Run pyroma checker, assert score ≥9/10

   - **Scenario 2 (FR-011)**: Contributor validates code quality before PR
     - Test: Run black --check, ruff check, mypy; assert zero errors

   - **Scenario 3 (FR-020)**: Security audit validates dependency safety
     - Test: Run pip-audit, assert zero critical vulnerabilities

   - **Scenario 4 (FR-006)**: New user discovers package via PyPI
     - Test: Validate README.md completeness, CHANGELOG.md format

5. **Update agent file incrementally** (O(1) operation):
   - Run `.specify/scripts/bash/update-agent-context.sh claude`
   - **IMPORTANT**: Execute exactly as specified above (no additional arguments)
   - Add NEW technologies from current plan:
     - pyroma (package quality scoring)
     - check-manifest (source distribution validation)
     - pip-audit (dependency vulnerability scanning)
     - interrogate (docstring coverage measurement)
   - Update recent changes (keep last 3):
     - Feature 024: Authentication bridge (OAuth, Wallet, Kerberos)
     - Feature 023: P6 COPY protocol implementation
     - Feature 025: Package hygiene and professional standards (current)
   - Keep under 150 lines for token efficiency

**Output**: data-model.md, /contracts/*, failing tests, quickstart.md, CLAUDE.md (updated)

## Phase 2: Task Planning Approach

*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
- Load `.specify/templates/tasks-template.md` as base
- Generate tasks from Phase 1 design docs (contracts, data model, quickstart)
- One contract test task per contract (4 contracts → 4 test tasks marked [P])
- One implementation task per quality tool integration (pyroma, black, ruff, mypy, pip-audit, check-manifest)
- One validation task per functional requirement category (7 categories → 7 validation tasks)

**Ordering Strategy**:
- **TDD order**: Contract tests BEFORE tool integration (tests must fail first)
- **Dependency order**:
  1. Metadata validation (pyroma, check-manifest) - no dependencies
  2. Code quality (black, ruff, mypy) - requires source code access
  3. Security (pip-audit, bandit) - requires dependency manifest
  4. Documentation (interrogate, README validation) - requires complete package
- **Parallel execution**: Mark [P] for independent validation tasks (contract tests, tool integrations)

**Estimated Output**: 35-40 numbered, ordered tasks in tasks.md breakdown:
- 4 contract test tasks [P] (metadata, code quality, security, documentation)
- 8 tool integration tasks (pyroma, check-manifest, black, ruff, mypy, pip-audit, bandit, interrogate)
- 7 validation tasks (one per FR category)
- 5-8 remediation tasks (fix identified issues from validation)
- 3-5 documentation tasks (update README, CLAUDE.md, CHANGELOG)
- 2-3 CI/CD tasks (GitHub Actions workflow for automated validation)

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Phase 3+: Future Implementation

*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)
**Phase 4**: Implementation (execute tasks.md following constitutional principles)
**Phase 5**: Validation (run quality tools, verify all checks pass, validate PyPI readiness)

## Complexity Tracking

*Fill ONLY if Constitution Check has violations that must be justified*

**No Violations Found** - This feature aligns with constitutional principles and does not introduce new complexity. Package hygiene improvements maintain Production Readiness standards without modifying protocol implementation.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| N/A       | N/A        | N/A                                  |

## Progress Tracking

*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command) - COMPLETE ✅
- [x] Phase 1: Design complete (/plan command) - COMPLETE ✅
- [x] Phase 2: Task planning approach documented (/plan command) - COMPLETE ✅
- [x] Phase 3: Tasks generated (/tasks command) - COMPLETE ✅ (35 tasks)
- [ ] Phase 4: Implementation execution (/implement command) - READY TO EXECUTE
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS (no violations, aligns with Production Readiness)
- [x] Post-Design Constitution Check: PASS (contracts created, no new violations)
- [x] All NEEDS CLARIFICATION resolved (proceeded with industry standards)
- [x] Complexity deviations documented (N/A - no violations)

**Research Progress** (Phase 0):
- [x] Research Task 1: Python Packaging Best Practices (pyroma, check-manifest)
- [x] Research Task 2: Code Quality Standards (black, ruff, mypy)
- [x] Research Task 3: Security and Dependency Management (bandit, pip-audit)
- [x] Research Task 4: Documentation Standards (interrogate, Keep a Changelog)
- [x] Research Task 5: Repository Hygiene (.gitignore, bytecode cleanup, bump2version)

**Design Artifacts Created** (Phase 1):
- [x] data-model.md: 6 entities with validation rules (PackageMetadata, SourceCode, Dependencies, TestSuite, Documentation, Repository)
- [x] quickstart.md: 5-step validation workflow with bash script
- [x] contracts/package_metadata_contract.py: FR-001 validation interface
- [x] contracts/code_quality_contract.py: FR-011 validation interface
- [x] contracts/security_contract.py: FR-020 validation interface
- [x] contracts/documentation_contract.py: FR-006 validation interface
- [x] CLAUDE.md: Updated agent context via update-agent-context.sh

---

*Based on Constitution v2.1.1 - See `/memory/constitution.md`*
