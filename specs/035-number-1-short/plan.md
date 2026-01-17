# Implementation Plan: PostgreSQL DDL Compatibility (ENUM, RLS, Boolean Defaults)

**Branch**: `035-number-1-short` | **Date**: 2026-01-17 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/035-number-1-short/spec.md`

## Summary
Extend iris-pgwire SQL translation layer to handle three categories of PostgreSQL DDL statements that currently fail on IRIS: (1) ENUM type definitions and column usages, (2) Row Level Security statements, and (3) boolean default literals. The approach is to skip unsupported statements with no-op success responses, translate enum type references to VARCHAR(64), and normalize boolean defaults from `true`/`false` to `1`/`0`.

## Technical Context
**Language/Version**: Python 3.11  
**Primary Dependencies**: intersystems-irispython, psycopg[binary], iris-devtester  
**Storage**: InterSystems IRIS (via PostgreSQL wire protocol)  
**Testing**: pytest, iris-devtester  
**Target Platform**: Linux server (containerized IRIS)  
**Project Type**: single  
**Performance Goals**: Translation overhead < 5ms per statement  
**Constraints**: Must preserve PostgreSQL wire protocol compliance; no client-side SQL rewrites required  
**Scale/Scope**: 64 failing statements across 35 migration files; 171 existing client compatibility tests must pass

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] Protocol fidelity preserved (no non-compliant message handling)
- [x] Test-first development using real clients and iris-devtester
- [x] Phased implementation respected (changes scoped to SQL translation layers)
- [x] IRIS integration rules followed (embedded Python patterns maintained)
- [x] Production readiness preserved (no regression to logging/health checks)
- [x] Vector performance requirements unaffected (no vector query changes)
- [x] Development environment sync acknowledged (container restart for validation)
- [x] Security requirements preserved (no relaxation of auth/TLS expectations)
- [x] Performance standards maintained (<5ms translation overhead)

## Project Structure

### Documentation (this feature)
```
specs/035-number-1-short/
├── plan.md              # This file (/plan command output)
├── research.md          # Phase 0 output (/plan command)
├── data-model.md        # Phase 1 output (/plan command)
├── quickstart.md        # Phase 1 output (/plan command)
├── contracts/           # Phase 1 output (/plan command)
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
src/
├── iris_pgwire/
│   ├── sql_translator/
│   │   ├── normalizer.py           # Main translation orchestrator
│   │   ├── boolean_translator.py   # NEW: Boolean literal translation
│   │   └── statement_filter.py     # NEW: Skip unsupported statements
│   └── conversions/
│       ├── ddl_splitter.py         # Existing DDL handling
│       └── enum_translator.py      # NEW: Enum type handling

tests/
├── contract/
│   ├── test_enum_translation.py    # NEW: Enum contract tests
│   ├── test_rls_handling.py        # NEW: RLS contract tests
│   └── test_boolean_defaults.py    # NEW: Boolean contract tests
├── integration/
│   ├── test_enum_e2e.py            # NEW: Enum E2E tests
│   ├── test_rls_e2e.py             # NEW: RLS E2E tests
│   └── test_boolean_e2e.py         # NEW: Boolean E2E tests
└── unit/
```

**Structure Decision**: Single project. Target SQL translation layers under src/iris_pgwire with tests under tests/.

## Phase 0: Outline & Research

### Research Tasks
1. Confirm IRIS limitations for enum types and best practices for VARCHAR substitution
2. Review existing DDL handling patterns in ddl_splitter.py and normalizer.py
3. Research boolean literal detection approaches that avoid false positives in strings/comments
4. Document session-scoped enum type registry approach

### Research Output
Create `research.md` with decisions, rationales, and alternatives for each translation category.

## Phase 1: Design & Contracts

### Data Model
Create `data-model.md` describing:
- Enum Type Registry: session-scoped tracking of registered enum type names
- Statement Classification: how statements are identified for skip/translate/pass-through
- Translation Pipeline: order of operations in normalizer

### Contracts
Define internal translation rules in `contracts/` as markdown specs for:
- `enum-handling.md`: CREATE TYPE skip, column type translation, cast handling
- `rls-handling.md`: RLS statement identification and skip behavior
- `boolean-translation.md`: DEFAULT true/false translation with context safety

### Quickstart
Create `quickstart.md` with validation steps:
1. Run targeted tests for each translation category
2. Execute example migration statements through pgwire
3. Confirm behavior against IRIS

### Agent Context Update
Run `.specify/scripts/bash/update-agent-context.sh opencode` after Phase 1 outputs.

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
- Use tasks template to generate tests first (iris-devtester + client queries)
- Create contract tests for each translation rule
- Create E2E tests using actual Drizzle migration patterns
- Implementation tasks to make tests pass
- Integration task to remove duplicate handling from sim_sql_patch.py

**Ordering Strategy**:
- TDD order: Tests before implementation
- Dependency order: Statement filter before enum/RLS handlers before boolean translator
- Mark [P] for parallel execution (independent test files)

**Estimated Output**: 20-25 numbered, ordered tasks in tasks.md

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)  
**Phase 4**: Implementation (execute tasks.md following constitutional principles)  
**Phase 5**: Validation (run tests, execute quickstart.md, performance validation)

## Complexity Tracking
*No constitution violations requiring justification*

## Progress Tracking
*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command)
- [x] Phase 1: Design complete (/plan command)
- [x] Phase 2: Task planning complete (/plan command - describe approach only)
- [x] Phase 3: Tasks generated (/tasks command) - 46 tasks in tasks.md
- [x] Phase 4: Implementation complete - 87 tests passing (60 contract + 27 E2E)
- [x] Phase 5: Validation passed - Performance 0.12ms avg (SLA <5ms)

**Gate Status**:
- [x] Initial Constitution Check: PASS
- [x] Post-Design Constitution Check: PASS
- [x] All NEEDS CLARIFICATION resolved
- [x] Complexity deviations documented

---
*Based on Constitution v1.3.1 - See `.specify/memory/constitution.md`*
