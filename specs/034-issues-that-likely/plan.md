# Implementation Plan: IRIS pgwire compatibility fixes

**Branch**: `034-issues-that-likely` | **Date**: 2026-01-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/034-issues-that-likely/spec.md`

## Summary
Address upstream IRIS pgwire compatibility gaps for comments in multi-statement DDL, prepared statement parameter translation, DEFAULT-in-VALUES handling, timestamp binding normalization, and ALTER TABLE SET DATA TYPE/DROP NOT NULL behavior with clear error signaling when IRIS cannot support the operation.

## Technical Context
**Language/Version**: Python 3.11
**Primary Dependencies**: intersystems-irispython, psycopg[binary], iris-devtester
**Storage**: InterSystems IRIS (via PostgreSQL wire protocol)
**Testing**: pytest, iris-devtester
**Target Platform**: Linux server (containerized IRIS)
**Project Type**: single (server)
**Performance Goals**: Query translation overhead < 5ms per query under normal load
**Constraints**: Must preserve PostgreSQL wire protocol compliance; no client-side SQL rewrites required
**Scale/Scope**: Supports standard PostgreSQL clients; maintain compatibility across existing pgwire test matrix

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] Protocol fidelity preserved (no non-compliant message handling)
- [x] Test-first development using real clients and iris-devtester
- [x] Phased implementation respected (changes scoped to P1/P2 translation layers)
- [x] IRIS integration rules followed (embedded Python patterns maintained)
- [x] Production readiness preserved (no regression to logging/health checks)
- [x] Vector performance requirements unaffected (no vector query changes)
- [x] Development environment sync acknowledged (container restart for validation)
- [x] Security requirements preserved (no relaxation of auth/TLS expectations)
- [x] Performance standards maintained (<5ms translation, no regression)

## Project Structure

### Documentation (this feature)
```
specs/034-issues-that-likely/
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
│   ├── protocol.py
│   ├── iris_executor.py
│   ├── sql_translator/
│   │   ├── normalizer.py
│   │   ├── date_translator.py
│   │   └── cache.py
│   └── conversions/
│       └── ddl_splitter.py

tests/
├── contract/
├── integration/
└── unit/
```

**Structure Decision**: Single project. Target SQL translation, protocol handling, and executor paths under src/iris_pgwire with tests under tests/.

## Phase 0: Outline & Research

### Research Tasks
- Confirm IRIS limitations for DEFAULT in VALUES and timestamp string formats; identify safe normalization approach.
- Confirm IRIS behavior for ALTER TABLE SET DATA TYPE/DROP NOT NULL and constraints for error handling.
- Review existing translation and splitting paths for comment handling and parameter translation ordering.

### Research Output
Create `research.md` with decisions, rationales, and alternatives for each compatibility gap.

## Phase 1: Design & Contracts

### Data Model
Create `data-model.md` describing key entities involved in translation (SQL Statement, Parameter Binding, Timestamp Value) and any validation rules for normalization.

### Contracts
No external API contracts. Define internal translation rules in `contracts/` as markdown specs for:
- SQL normalization pipeline and ordering
- DDL splitting/comment handling
- Parameter translation application across query paths
- Timestamp normalization behavior
- ALTER TABLE compatibility/error behavior

### Quickstart
Create `quickstart.md` with validation steps: run targeted tests, execute example queries for each issue category, and confirm behavior against IRIS.

### Agent Context Update
Run `.specify/scripts/bash/update-agent-context.sh opencode` after Phase 1 outputs.

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
- Use tasks template to generate tests first (iris-devtester + client queries).
- Add unit tests for SQL normalization and protocol translation.
- Implement translation fixes and update DDL/timestamp handling.
- Add integration tests for multi-statement DDL with comments and prepared statements.

**Ordering Strategy**:
- Write failing tests for each issue (P1/P2 paths, executor paths).
- Implement translation and normalization changes.
- Run protocol-level integration tests.

**Estimated Output**: 18-25 ordered tasks in tasks.md

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)
**Phase 4**: Implementation (execute tasks.md following constitutional principles)
**Phase 5**: Validation (run tests, execute quickstart.md, performance validation)

## Complexity Tracking
*Fill ONLY if Constitution Check has violations that must be justified*

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|

## Progress Tracking
*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command)
- [x] Phase 1: Design complete (/plan command)
- [x] Phase 2: Task planning complete (/plan command - describe approach only)
- [x] Phase 3: Tasks generated (/tasks command)
- [x] Phase 4: Implementation complete
- [x] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS
- [x] Post-Design Constitution Check: PASS
- [x] All NEEDS CLARIFICATION resolved
- [ ] Complexity deviations documented

---
*Based on Constitution v1.3.1 - See `/memory/constitution.md`*
