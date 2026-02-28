# Implementation Plan: Comprehensive Code Simplification

**Branch**: `041-code-simplification` | **Date**: 2026-02-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/041-code-simplification/spec.md`

## Summary

Comprehensive readability and maintainability refactoring of the entire `src/iris_pgwire/` codebase (~110 Python files, ~32,000 lines). No new features, no API changes — purely internal restructuring to reduce function length, nesting depth, dead code, and duplication. **Implementation is complete as of commit `41801be`.**

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: intersystems-irispython, psycopg[binary], iris-devtester, structlog, pydantic
**Storage**: N/A (refactoring only)
**Testing**: pytest (unit, contract, protocol suites)
**Target Platform**: Linux server (InterSystems IRIS embedded Python + external)
**Project Type**: Single project
**Performance Goals**: No regression in test suite; no behavioural changes
**Constraints**: All public interfaces preserved exactly; zero new test failures
**Scale/Scope**: ~110 source files, ~32,000 lines across 6 subpackages

## Constitution Check

*Constitution file is unpopulated (template placeholders only) — no gates to enforce.*

No violations detected. Proceeding.

## Project Structure

### Documentation (this feature)

```text
specs/041-code-simplification/
├── plan.md              ← this file
├── spec.md              ← feature specification
├── research.md          ← Phase 0 output (see below)
└── data-model.md        ← N/A (no new data entities)
```

### Source Code

```text
src/iris_pgwire/
├── protocol.py              4527 → 4469 lines
├── iris_executor.py         4503 → 3998 lines  (-11%)
├── dbapi_executor.py        1411 → 1291 lines  (-9%)
├── iris_constructs.py        849 →  632 lines  (-26%)
├── vector_optimizer.py       912 →  653 lines  (-28%)
├── auth/                    5 modules simplified
├── catalog/                 catalog_router: if/elif → dispatch map
├── conversions/             ddl_splitter decomposed
├── models/                  backend_config from_env() extracted
├── sql_translator/          all 35 files simplified
└── [remaining top-level]    bulk_executor, constitutional, copy_handler,
                             csv_processor, dbapi_connection_pool, integratedml,
                             iris_user_management, server, vector_metrics
```

## Phase 0: Research

*No external unknowns. All decisions based on existing codebase analysis.*

See [research.md](research.md) for full findings.

## Phase 1: Design & Implementation

### Simplification Approach

**Dispatch table pattern** (used in `catalog_router.py`, `constitutional.py`, `integratedml.py`):
Replace long if/elif chains with `{key: handler}` dicts.

**Helper extraction pattern** (used everywhere):
Functions >50 lines decomposed into named helpers with single responsibilities.

**Early return pattern** (used everywhere):
Deep nesting flattened by returning/raising early on guard conditions.

**Dead code removal** (used everywhere):
Unreachable code after `return` statements, unused imports, no-op methods.

### Bugs Fixed During Verification

1. `confidence_analyzer.py`: `return []` before helper calls (dead code after return introduced by simplification agent) — fixed inline.
2. `ddl_splitter.py`: `_should_toggle_quote()` missing parameter in new signature — fixed inline.

### Test Results

- **595+ unit/contract/protocol tests passing**
- **Zero new regressions**
- Pre-existing failures (timing benchmark, timestamp normalization, black/ruff formatting in migrations/) confirmed unchanged on `main`

## Complexity Tracking

No constitution violations.
