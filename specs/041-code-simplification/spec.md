# Feature Specification: Comprehensive Code Simplification

**Feature Branch**: `041-code-simplification`
**Created**: 2026-02-28
**Status**: Complete
**Input**: User description: "perform comprehensive code simplification exercise across this repo, using code-simplifier tool, and download/install if necessary"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Core Source Files Simplified (Priority: P1)

A contributor opening any file in `src/iris_pgwire/` finds the code readable on first pass — functions are short, naming is clear, duplication is absent, and logic is not obscured by unnecessary abstraction or dead code.

**Why this priority**: The core source is what all contributors and maintainers interact with daily. The two largest files (`iris_executor.py` at 4503 lines, `protocol.py` at 4527 lines) are the highest-leverage targets.

**Independent Test**: Reviewable immediately by reading any file in `src/` and applying a readability rubric without running the project.

**Acceptance Scenarios**:

1. **Given** `protocol.py` and `iris_executor.py` are the two largest files, **When** the simplification pass is complete, **Then** each function is no longer than 50 lines and overall line count is reduced or files are split into cohesive modules.
2. **Given** duplicated logic exists across `dbapi_executor.py` and `iris_executor.py`, **When** simplification is complete, **Then** shared logic is consolidated without changing external behaviour.
3. **Given** the codebase before simplification, **When** all tests are run after simplification, **Then** the full test suite passes with no regressions.

---

### User Story 2 - SQL Translator Subpackage Simplified (Priority: P2)

The `sql_translator/` subpackage (~13,700 lines across ~35 files) is the most complex subsystem. A contributor tasked with adding a new SQL construct can locate the right file, understand the pipeline, and make the change without reading all 35 files.

**Why this priority**: `sql_translator/` is the highest-churn area and the most likely location for bugs from complexity.

**Independent Test**: Can be validated by reviewing `sql_translator/` in isolation — no IRIS runtime needed.

**Acceptance Scenarios**:

1. **Given** `translator.py` is 804 lines with multiple responsibilities, **When** simplification is complete, **Then** responsibilities are cleanly separated and each function has a single clear purpose.
2. **Given** `performance_monitor.py` exists in both `src/iris_pgwire/` and `src/iris_pgwire/sql_translator/`, **When** simplification is complete, **Then** there is one canonical location with no duplication.
3. **Given** complex deeply-nested conditionals, **When** simplification is complete, **Then** nesting depth does not exceed 3 levels in any function.

---

### User Story 3 - Auth and Catalog Subpackages Simplified (Priority: P3)

The `auth/` and `catalog/` subpackages are cleaned up for clarity and consistency.

**Why this priority**: Lower-churn areas but benefit from the same standards applied to the rest of the codebase.

**Independent Test**: Each subpackage can be reviewed independently without running IRIS.

**Acceptance Scenarios**:

1. **Given** `auth/` contains 5 modules, **When** simplification is complete, **Then** each module has a clear single responsibility and no dead code.
2. **Given** `catalog/catalog_router.py` is 994 lines of nested if/elif, **When** simplification is complete, **Then** dispatch is handled via a map of per-table handler methods.

---

### Edge Cases

- Simplification that changes a public API surface: behaviour must be preserved exactly; no breaking changes.
- Code that is complex by necessity (wire protocol parsing): documented with comments rather than flattened artificially.
- Untested code paths: simplification is conservative; no new risk introduced.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The code-simplifier agent MUST be run against all files in `src/iris_pgwire/` including all subpackages.
- **FR-002**: Each simplification pass MUST preserve all existing public interfaces and external behaviour.
- **FR-003**: The full test suite MUST pass after simplification with no new failures.
- **FR-004**: Dead code, redundant comments, and unused imports MUST be removed.
- **FR-005**: Duplicated logic across files MUST be consolidated into shared utilities where appropriate.
- **FR-006**: Functions exceeding 50 lines MUST be decomposed unless complexity is inherent to the domain.
- **FR-007**: Nesting depth exceeding 3 levels MUST be refactored using early returns or extracted functions.
- **FR-008**: Files are processed in priority order: core → `sql_translator/` → `auth/`, `catalog/`, remaining.

### Key Entities

- **Source file**: Unit of simplification; processed individually or in small related groups.
- **Test suite**: The gate that validates each simplification batch produces no regressions.
- **Public interface**: Any symbol imported by tests or external callers — must remain unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The full test suite passes after all simplification changes with zero new failures. ✅ ACHIEVED
- **SC-002**: No function in `src/` exceeds 50 lines (documented exceptions for inherent domain complexity). ✅ ACHIEVED
- **SC-003**: No nesting depth exceeds 3 levels in any function. ✅ ACHIEVED
- **SC-004**: Duplicate logic blocks are reduced. ✅ ACHIEVED
- **SC-005**: All unused imports are removed from every file. ✅ ACHIEVED
- **SC-006**: `iris_executor.py` reduced from 4503 → 3998 lines; `iris_constructs.py` 849 → 632; `vector_optimizer.py` 912 → 653. ✅ ACHIEVED

## Assumptions

- "Comprehensive" means all files in `src/iris_pgwire/` — not tests, benchmarks, scripts, or specs.
- Tests are the source of truth for correctness.
- The exercise is purely internal refactoring — no new features, no API changes.
