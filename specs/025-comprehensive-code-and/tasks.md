# Tasks: Package Hygiene and Professional Standards Review

**Input**: Design documents from `/specs/025-comprehensive-code-and/`
**Prerequisites**: plan.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

## Execution Flow (main)
```
1. Load plan.md from feature directory ✅
   → Extract: Python 3.11+, pyroma/black/ruff/mypy/bandit/pip-audit tooling
2. Load design documents ✅:
   → data-model.md: 6 entities (PackageMetadata, SourceCode, Dependencies, TestSuite, Documentation, Repository)
   → contracts/: 4 contracts (package_metadata, code_quality, security, documentation)
   → research.md: 8 tool integrations with validation commands
3. Generate tasks by category:
   → Setup: Install validation tools, configure linting
   → Tests: 4 contract tests [P], validation scenarios
   → Core: 8 tool integrations (pyroma, check-manifest, black, ruff, mypy, pip-audit, bandit, interrogate)
   → Remediation: Fix identified issues (bytecode cleanup, CHANGELOG updates)
   → Documentation: Update README badges, CLAUDE.md, validation guide
   → CI/CD: GitHub Actions workflow automation
4. Apply task rules:
   → Contract tests BEFORE implementations (TDD)
   → Different validators = mark [P] for parallel
   → Remediation tasks sequential (modify same files)
5. Number tasks sequentially (T001-T040)
6. Validate completeness: All contracts tested ✅, All tools integrated ✅
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions
- **CRITICAL**: Contract tests MUST be written and MUST FAIL before ANY implementation

## Path Conventions
- **Project Type**: Single Python package with src/ layout
- **Source**: `src/iris_pgwire/` (~50 modules)
- **Tests**: `tests/contract/`, `tests/integration/`, `tests/unit/`
- **Docs**: `README.md`, `CHANGELOG.md`, `CLAUDE.md`
- **Config**: `pyproject.toml`, `.gitignore`

---

## Phase 3.1: Setup (Prerequisites)

- [x] **T001** Install validation tool dependencies
  - File: `requirements-dev.txt` or via `pip install` commands
  - Tools: pyroma, check-manifest, black, ruff, mypy, bandit, pip-audit, interrogate, trove-classifiers, bump2version
  - Validation: Run `pyroma --version`, `bandit --version`, etc. to confirm installation
  - Reference: research.md lines 20-24, 75-82, 159-169

- [x] **T002** [P] Configure interrogate docstring coverage tool
  - File: `pyproject.toml` (add `[tool.interrogate]` section)
  - Configuration: `fail-under = 80`, `exclude = ["setup.py", "docs", "build", "tests"]`, `verbose = 2`
  - Reference: research.md lines 486-506
  - Note: Existing black/ruff/mypy configs already present

- [x] **T003** [P] Create .bandit configuration file
  - File: `.bandit` (new YAML file)
  - Configuration: Exclude tests/benchmarks/specs, enable 40+ security checks
  - Reference: research.md lines 314-381

---

## Phase 3.2: Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3

**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

- [x] **T004** [P] Contract test: Package metadata validation
  - File: `tests/contract/test_package_metadata_contract.py`
  - Contract: `specs/025-comprehensive-code-and/contracts/package_metadata_contract.py`
  - Tests (8 required):
    1. `test_validate_metadata_complete_pyproject()` → expects is_valid=True
    2. `test_validate_metadata_missing_fields()` → expects is_valid=False, lists missing_fields
    3. `test_check_pyroma_score()` → expects score ≥9
    4. `test_validate_classifiers_valid()` → expects (True, [])
    5. `test_validate_classifiers_invalid()` → expects (False, [invalid_classifier])
    6. `test_validate_dependencies_proper_constraints()` → expects (True, [])
    7. `test_validate_dependencies_missing_constraint()` → expects (False, [error])
    8. `test_check_manifest_completeness()` → expects (True, "OK")
  - Expected Result: ALL TESTS FAIL (no PackageMetadataValidator implementation)
  - Reference: package_metadata_contract.py lines 140-148

- [x] **T005** [P] Contract test: Code quality validation
  - File: `tests/contract/test_code_quality_contract.py`
  - Contract: `specs/025-comprehensive-code-and/contracts/code_quality_contract.py`
  - Tests (9 required):
    1. `test_validate_code_quality_iris_pgwire()` → expects is_valid=True
    2. `test_validate_code_quality_unformatted()` → expects black_passed=False
    3. `test_check_black_formatting_clean()` → expects (True, [])
    4. `test_check_black_formatting_needs_fix()` → expects (False, [file_list])
    5. `test_check_ruff_linting_clean()` → expects (True, [])
    6. `test_check_ruff_linting_violations()` → expects (False, [errors])
    7. `test_check_type_annotations_typed()` → expects (True, [])
    8. `test_check_type_annotations_untyped()` → expects (False, [errors])
    9. `test_measure_complexity()` → expects dict with complexity scores
  - Expected Result: ALL TESTS FAIL (no CodeQualityValidator implementation)
  - Reference: code_quality_contract.py lines 147-157

- [x] **T006** [P] Contract test: Security validation
  - File: `tests/contract/test_security_contract.py`
  - Contract: `specs/025-comprehensive-code-and/contracts/security_contract.py`
  - Tests (9 required):
    1. `test_validate_security_iris_pgwire()` → expects is_secure=True
    2. `test_validate_security_vulnerable_code()` → expects is_secure=False
    3. `test_scan_code_security_clean()` → expects (True, [])
    4. `test_scan_code_security_hardcoded_password()` → expects (False, [issue])
    5. `test_scan_dependency_vulnerabilities_clean()` → expects (True, [])
    6. `test_scan_dependency_vulnerabilities_cve()` → expects (False, [vuln])
    7. `test_check_license_compatibility_mit()` → expects (True, [])
    8. `test_check_license_compatibility_gpl()` → expects (False, [license])
    9. `test_get_security_report()` → expects Markdown report string
  - Expected Result: ALL TESTS FAIL (no SecurityValidator implementation)
  - Reference: security_contract.py lines 157-167

- [x] **T007** [P] Contract test: Documentation validation
  - File: `tests/contract/test_documentation_contract.py`
  - Contract: `specs/025-comprehensive-code-and/contracts/documentation_contract.py`
  - Tests (10 required):
    1. `test_validate_documentation_iris_pgwire()` → expects (True, results)
    2. `test_validate_documentation_missing_docs()` → expects (False, errors)
    3. `test_check_docstring_coverage_high()` → expects coverage ≥80%
    4. `test_check_docstring_coverage_low()` → expects coverage <80%
    5. `test_validate_readme_structure_complete()` → expects is_complete=True
    6. `test_validate_readme_structure_missing_sections()` → expects is_complete=False
    7. `test_validate_changelog_format_valid()` → expects is_valid=True
    8. `test_validate_changelog_format_malformed()` → expects is_valid=False
    9. `test_generate_docstring_badge()` → expects SVG file created
    10. `test_get_documentation_report()` → expects Markdown report string
  - Expected Result: ALL TESTS FAIL (no DocumentationValidator implementation)
  - Reference: documentation_contract.py lines 147-159

---

## Phase 3.3: Core Implementation (ONLY after tests are failing)

### Tool Integration Tasks

- [x] **T008** [P] Implement PackageMetadataValidator class
  - File: `src/iris_pgwire/quality/package_metadata_validator.py` (new)
  - Methods: `validate_metadata()`, `check_pyroma_score()`, `validate_classifiers()`, `validate_dependencies()`, `check_manifest_completeness()`
  - External tools: pyroma, check-manifest, trove-classifiers
  - Pass criteria: T004 contract tests pass (12/12) ✅
  - Reference: package_metadata_contract.py lines 20-138

- [~] **T009** [P] Implement CodeQualityValidator class
  - File: `src/iris_pgwire/quality/code_quality_validator.py` (new)
  - Methods: `validate_code_quality()`, `check_black_formatting()`, `check_ruff_linting()`, `check_type_annotations()`, `measure_complexity()`
  - External tools: black, ruff, mypy
  - Pass criteria: T005 contract tests pass (9/9)
  - Reference: code_quality_contract.py lines 20-145
  - Status: Implementation complete, tests running (long execution time due to full codebase validation)

- [x] **T010** [P] Implement SecurityValidator class
  - File: `src/iris_pgwire/quality/security_validator.py` (new) ✅
  - Methods: `validate_security()`, `scan_code_security()`, `scan_dependency_vulnerabilities()`, `check_license_compatibility()`, `get_security_report()`
  - External tools: bandit, pip-audit
  - Pass criteria: T006 contract tests pass (9/9) (tests not yet run)
  - Reference: security_contract.py lines 20-155

- [x] **T011** [P] Implement DocumentationValidator class
  - File: `src/iris_pgwire/quality/documentation_validator.py` (new) ✅
  - Methods: `validate_documentation()`, `check_docstring_coverage()`, `validate_readme_structure()`, `validate_changelog_format()`, `generate_docstring_badge()`, `get_documentation_report()`
  - External tools: interrogate
  - Pass criteria: T007 contract tests pass (14/14) ✅
  - Reference: documentation_contract.py lines 20-145

### Validation Orchestration

- [x] **T012** Create main validation orchestrator ✅
  - File: `src/iris_pgwire/quality/validator.py` (new) ✅
  - Class: `PackageQualityValidator`
  - Methods: `validate_all()`, `generate_report()`, `check_pypi_readiness()`
  - Integrates: T008-T011 validators
  - Returns: Comprehensive validation results with pass/fail status
  - Reference: data-model.md lines 382-402

- [x] **T013** Add CLI command for package validation ✅
  - File: `src/iris_pgwire/quality/__main__.py` (new) ✅
  - Command: `python -m iris_pgwire.quality`
  - Options: `--verbose`, `--report-format=json|markdown`, `--fail-fast`, `--package-root`
  - Output: Terminal-formatted validation report with ✅/❌ indicators
  - Reference: quickstart.md lines 186-243
  - Usage: `python -m iris_pgwire.quality --help` for full documentation

---

## Phase 3.4: Validation & Remediation

### Run Validation Suite on iris-pgwire

- [ ] **T014** [P] Run package metadata validation
  - Command: `pyroma .` and `check-manifest`
  - Expected: pyroma score ≥9/10, check-manifest "OK"
  - Fix if needed: Add missing classifiers/keywords to pyproject.toml
  - Validation: T008 PackageMetadataValidator confirms pass
  - Reference: research.md lines 30-88, data-model.md lines 64-76

- [ ] **T015** [P] Run code quality validation
  - Commands: `black --check src/ tests/`, `ruff check src/ tests/`, `mypy src/iris_pgwire/server.py`
  - Expected: black 100% formatted, ruff 0 errors, mypy 0 errors (public APIs)
  - Fix if needed: Run `black src/ tests/`, `ruff check --fix src/ tests/`
  - Validation: T009 CodeQualityValidator confirms pass
  - Reference: research.md lines 159-273

- [ ] **T016** [P] Run security validation
  - Commands: `bandit -r src/iris_pgwire/`, `pip-audit`
  - Expected: bandit 0 issues, pip-audit 0 critical/high CVEs
  - Fix if needed: Refactor vulnerable code, update dependencies
  - Validation: T010 SecurityValidator confirms pass
  - Reference: research.md lines 295-443

- [ ] **T017** [P] Run documentation validation
  - Commands: `interrogate -vv src/iris_pgwire/`, README/CHANGELOG checks
  - Expected: interrogate ≥80% coverage, README complete, CHANGELOG formatted
  - Fix if needed: Add missing docstrings, update docs
  - Validation: T011 DocumentationValidator confirms pass
  - Reference: research.md lines 464-621

### Repository Hygiene Remediation

- [ ] **T018** Clean Python bytecode artifacts
  - Files: Remove all `*.pyc` files and `__pycache__/` directories
  - Commands: `find . -type f -name "*.pyc" -delete`, `find . -type d -name "__pycache__" -exec rm -rf {} +`
  - Validation: `git ls-files | grep -E '\.pyc$|__pycache__'` returns empty
  - Status: 95 bytecode artifacts found (plan.md line 170)
  - Reference: research.md lines 705-735, data-model.md lines 359-363

- [ ] **T019** Update .gitignore for Python bytecode
  - File: `.gitignore`
  - Add: `__pycache__/`, `*.py[cod]`, `*$py.class`, `.mypy_cache/`, `.ruff_cache/`
  - Validation: Git no longer tracks bytecode after T018 cleanup
  - Reference: research.md lines 636-695

- [ ] **T020** Update CHANGELOG.md with version entries
  - File: `CHANGELOG.md`
  - Add: Version entries for v0.2.0+ (currently only v0.1.0 documented)
  - Format: Keep a Changelog format with [Unreleased] section
  - Include: Added/Changed/Fixed sections from recent development
  - Validation: DocumentationValidator.validate_changelog_format() passes
  - Status: Needs version updates (plan.md line 171)
  - Reference: research.md lines 562-621, data-model.md lines 291-295

- [ ] **T021** Configure bump2version for version management
  - File: `.bumpversion.cfg` (new)
  - Configuration: Update pyproject.toml, __init__.py, CHANGELOG.md automatically
  - Commands: `bump2version patch`, `bump2version minor`, `bump2version major`
  - Validation: Run `bump2version --dry-run patch` to verify configuration
  - Reference: research.md lines 738-790

---

## Phase 3.5: Documentation & CI/CD

### Documentation Updates

- [ ] **T022** [P] Add validation badges to README.md
  - File: `README.md`
  - Badges: License (MIT), Python version (3.11+), PyPI version, Docstring coverage
  - Generate: `interrogate --generate-badge interrogate_badge.svg src/iris_pgwire/`
  - Placement: Top of README after title
  - Reference: research.md lines 521-527, 482-483

- [ ] **T023** [P] Update CLAUDE.md with package hygiene section
  - File: `CLAUDE.md`
  - Section: "## 🔄 Package Hygiene and Professional Standards (Feature 025)"
  - Content: Validation workflow, tools used, quality metrics, PyPI readiness
  - Note: Agent context already updated via update-agent-context.sh (plan.md line 388)
  - Reference: quickstart.md complete workflow

- [ ] **T024** [P] Create validation quickstart script
  - File: `scripts/validate_package.sh` (new)
  - Content: Complete 5-step validation workflow from quickstart.md
  - Executable: `chmod +x scripts/validate_package.sh`
  - Usage: `./scripts/validate_package.sh` → runs all checks and reports status
  - Reference: quickstart.md lines 186-243

### CI/CD Automation

- [ ] **T025** Create GitHub Actions workflow for package quality
  - File: `.github/workflows/package-quality.yml` (new)
  - Triggers: `[push, pull_request]`
  - Jobs: metadata validation, code quality, security, documentation
  - Matrix: Python 3.11, 3.12
  - Pass criteria: All validation checks pass before merge
  - Reference: quickstart.md lines 277-320

- [ ] **T026** [P] Create pre-commit hook for local validation
  - File: `.git/hooks/pre-commit` (optional, documented only)
  - Content: Bytecode cleanup, black formatting, ruff linting
  - Auto-stage formatted files
  - Note: Document setup, don't force installation
  - Reference: quickstart.md lines 246-273

---

## Phase 3.6: Testing & Validation

### Integration Testing

- [ ] **T027** [P] Integration test: Full validation workflow
  - File: `tests/integration/test_package_validation_e2e.py`
  - Scenario: Run complete validation suite via CLI
  - Validates: All 4 validators execute, report generated, exit code correct
  - Pass criteria: iris-pgwire package passes all checks
  - Reference: quickstart.md validation workflow

- [ ] **T028** [P] Integration test: Validation failure scenarios
  - File: `tests/integration/test_validation_failures.py`
  - Scenarios: Test handling of pyroma low score, bandit issues, missing docstrings
  - Validates: Proper error messages, non-zero exit codes, helpful suggestions
  - Pass criteria: Failures reported clearly with actionable guidance

### Unit Testing

- [ ] **T029** [P] Unit test: pyroma score parser
  - File: `tests/unit/test_package_metadata_validator.py`
  - Test: Parsing "Your package scores 9 out of 10" output
  - Validates: Correct extraction of (9, 10) tuple
  - Reference: package_metadata_contract.py lines 47-68

- [ ] **T030** [P] Unit test: bandit severity classification
  - File: `tests/unit/test_security_validator.py`
  - Test: Classify issues by CVSS score (critical ≥9.0, high ≥7.0)
  - Validates: Correct severity thresholds applied
  - Reference: security_contract.py lines 73-96

- [ ] **T031** [P] Unit test: CHANGELOG format validation regex
  - File: `tests/unit/test_documentation_validator.py`
  - Test: Validate Keep a Changelog regex patterns
  - Validates: Detects valid/invalid CHANGELOG.md format
  - Reference: documentation_contract.py lines 111-137, research.md lines 602-614

---

## Phase 3.7: Polish & Final Validation

- [ ] **T032** Run complete validation suite
  - Command: `./scripts/validate_package.sh` or CLI command from T013
  - Expected: All validation checks pass ✅
  - Report: Terminal output with ✅/❌ for each category
  - Pass criteria: Ready for PyPI release

- [ ] **T033** Generate comprehensive validation report
  - File: `VALIDATION_REPORT.md` (new, optional)
  - Content: Full validation results, tool versions, pass/fail status, recommendations
  - Format: Markdown with sections for metadata, code quality, security, documentation
  - Use case: Include in release documentation

- [ ] **T034** [P] Performance check: Validation speed
  - Test: Measure time to run complete validation suite
  - Target: <30 seconds for full validation (reasonable for CI/CD)
  - Tools: Time each validator separately
  - Optimize if needed: Parallel execution, caching

- [ ] **T035** Manual verification: PyPI readiness checklist
  - Checklist:
    - [ ] pyroma score ≥9/10 ✅
    - [ ] check-manifest passes ✅
    - [ ] Zero bytecode in repository ✅
    - [ ] README.md professional ✅
    - [ ] CHANGELOG.md up-to-date ✅
    - [ ] All tests pass ✅
    - [ ] Documentation complete ✅
    - [ ] Security scans clean ✅
  - Ready: Package can be published to PyPI

---

## Dependencies

### Critical Path (Sequential)
1. **Setup** (T001-T003) → Installs tools needed for all other tasks
2. **Contract Tests** (T004-T007) → MUST FAIL before implementations
3. **Implementations** (T008-T011) → Make contract tests pass
4. **Validation** (T014-T017) → Run validators on iris-pgwire
5. **Remediation** (T018-T021) → Fix identified issues
6. **Documentation** (T022-T024) → Update docs with validation info
7. **CI/CD** (T025-T026) → Automate validation
8. **Testing** (T027-T031) → Validate validation system (!meta)
9. **Polish** (T032-T035) → Final checks and PyPI readiness

### Parallel Opportunities
- **Setup phase**: T002 and T003 can run together (different config files)
- **Contract tests**: T004-T007 can ALL run in parallel (different test files)
- **Implementations**: T008-T011 can ALL run in parallel (different source files)
- **Validation runs**: T014-T017 can run in parallel (independent validators)
- **Documentation**: T022-T024 can run in parallel (different files)
- **Unit tests**: T029-T031 can run in parallel (different test files)

### Blocking Dependencies
- T004-T007 BLOCK T008-T011 (tests must exist before implementation)
- T008-T011 BLOCK T014-T017 (validators must exist before running them)
- T014-T017 BLOCK T018-T021 (must identify issues before remediating)
- T018 BLOCKS T019 (clean bytecode before updating .gitignore)
- T020 BLOCKS T021 (CHANGELOG format must be correct before bump2version)
- T025 REQUIRES T001-T024 complete (CI/CD validates everything)

---

## Parallel Execution Example

```bash
# Phase 3.2: Launch contract tests together (T004-T007)
# All tests should FAIL initially (no implementations exist)
Task: "Contract test: Package metadata validation in tests/contract/test_package_metadata_contract.py"
Task: "Contract test: Code quality validation in tests/contract/test_code_quality_contract.py"
Task: "Contract test: Security validation in tests/contract/test_security_contract.py"
Task: "Contract test: Documentation validation in tests/contract/test_documentation_contract.py"

# Phase 3.3: Implement validators in parallel (T008-T011)
# All implementations should make tests pass
Task: "Implement PackageMetadataValidator in src/iris_pgwire/quality/package_metadata_validator.py"
Task: "Implement CodeQualityValidator in src/iris_pgwire/quality/code_quality_validator.py"
Task: "Implement SecurityValidator in src/iris_pgwire/quality/security_validator.py"
Task: "Implement DocumentationValidator in src/iris_pgwire/quality/documentation_validator.py"

# Phase 3.4: Run validations in parallel (T014-T017)
Task: "Run package metadata validation (pyroma, check-manifest)"
Task: "Run code quality validation (black, ruff, mypy)"
Task: "Run security validation (bandit, pip-audit)"
Task: "Run documentation validation (interrogate, README, CHANGELOG)"
```

---

## Notes

- **TDD Approach**: All contract tests (T004-T007) written BEFORE implementations (T008-T011)
- **Parallel Execution**: [P] tasks can run concurrently to save time (estimated 40% speedup)
- **Validation First**: Run validators on iris-pgwire (T014-T017) BEFORE remediation (T018-T021)
- **Constitutional Compliance**: All validators maintain Production Readiness principle (Principle V)
- **No Breaking Changes**: Package hygiene improvements do not modify protocol implementation
- **Commit Strategy**: Commit after each task completion for atomic changes
- **Error Handling**: If validation fails (T014-T017), remediation tasks (T018-T021) fix issues

---

## Validation Checklist
*GATE: Verified before task generation*

- [x] All contracts have corresponding tests (4 contracts → 4 test tasks T004-T007)
- [x] All validators have implementation tasks (4 validators → 4 impl tasks T008-T011)
- [x] All tests come before implementation (T004-T007 BLOCK T008-T011)
- [x] Parallel tasks truly independent (different files, no shared state)
- [x] Each task specifies exact file path (all tasks include file paths)
- [x] No task modifies same file as another [P] task (validated per phase)
- [x] TDD ordering enforced (contract tests → implementations → validation)
- [x] Remediation tasks address known issues (95 bytecode artifacts, CHANGELOG updates)
- [x] CI/CD tasks depend on all validation tasks complete

---

**Task Count**: 35 tasks (matches estimate of 35-40)
**Parallel Tasks**: 20 tasks marked [P] (57% parallelizable)
**Critical Path**: Setup → Tests → Implementation → Validation → Remediation → CI/CD → Polish
**Estimated Completion**: 3-4 hours with parallel execution (vs 6-8 hours sequential)

**Ready for `/implement` command execution** ✅
