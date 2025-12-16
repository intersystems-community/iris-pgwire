
# Implementation Plan: 3-Way Database Performance Benchmark

**Branch**: `015-add-3-way` | **Date**: 2025-01-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/015-add-3-way/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path
   → If not found: ERROR "No feature spec at {path}"
2. Fill Technical Context (scan for NEEDS CLARIFICATION)
   → Detect Project Type from file system structure or context (web=frontend+backend, mobile=app+api)
   → Set Structure Decision based on project type
3. Fill the Constitution Check section based on the content of the constitution document.
4. Evaluate Constitution Check section below
   → If violations exist: Document in Complexity Tracking
   → If no justification possible: ERROR "Simplify approach first"
   → Update Progress Tracking: Initial Constitution Check
5. Execute Phase 0 → research.md
   → If NEEDS CLARIFICATION remain: ERROR "Resolve unknowns"
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, agent-specific template file (e.g., `CLAUDE.md` for Claude Code, `.github/copilot-instructions.md` for GitHub Copilot, `GEMINI.md` for Gemini CLI, `QWEN.md` for Qwen Code or `AGENTS.md` for opencode).
7. Re-evaluate Constitution Check section
   → If new violations: Refactor design, return to Phase 1
   → Update Progress Tracking: Post-Design Constitution Check
8. Plan Phase 2 → Describe task generation approach (DO NOT create tasks.md)
9. STOP - Ready for /tasks command
```

**IMPORTANT**: The /plan command STOPS at step 7. Phases 2-4 are executed by other commands:
- Phase 2: /tasks command creates tasks.md
- Phase 3-4: Implementation execution (manual or via tools)

## Summary
Create a comprehensive performance benchmark comparing three database access methods: IRIS with PostgreSQL wire protocol (PGWire), native PostgreSQL with psycopg3 driver, and IRIS with direct database API (DBAPI). The benchmark will test query types including simple SELECT, vector similarity operations, and complex joins using production-scale datasets (100K-1M rows) with 1024-dimensional vectors. Results will be presented in both JSON and console table formats showing raw performance metrics (QPS, P50/P95/P99 latencies) without statistical interpretation.

## Technical Context
**Language/Version**: Python 3.11+ (matching existing iris-pgwire project)
**Primary Dependencies**: psycopg3 (PostgreSQL driver), iris module (IRIS embedded Python), asyncio, pytest
**Storage**: IRIS database (existing container), PostgreSQL database (to be provisioned)
**Testing**: pytest for benchmark validation, real database connections (no mocks per constitution)
**Target Platform**: Docker containers (Linux), local development environment
**Project Type**: Single project (benchmark utility within iris-pgwire repository)
**Performance Goals**: Measure and compare QPS (queries per second) and latency percentiles (P50/P95/P99) across three database access methods
**Constraints**: Must use identical test data and query patterns per FR-008; abort on connection failure per FR-006; handle 1024-dimensional vectors per FR-003
**Scale/Scope**: Production-scale datasets (100K-1M rows), configurable vector dimensions (1024 default), multiple query types (simple, vector similarity, complex joins)

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Principle II: Test-First Development ✅ COMPLIANT
- Benchmark will validate against real IRIS and PostgreSQL instances
- No mock testing for database connections (constitutional requirement)
- End-to-end validation with actual query execution

### Principle IV: IRIS Integration ✅ COMPLIANT
- Uses existing IRIS embedded Python setup with CallIn service enabled
- Follows `iris.sql.exec()` patterns from existing codebase
- DBAPI testing validates external driver behavior separately

### Principle V: Production Readiness ✅ COMPLIANT
- Benchmark includes error handling (FR-006: abort on failure)
- Structured output formats (JSON + console table) for observability
- Performance metrics align with constitutional standards

### Principle VI: Vector Performance Requirements ✅ COMPLIANT
- Tests with production-scale datasets (100K-1M rows per clarification)
- Uses 1024-dimensional vectors (constitutional compliance with HNSW requirements)
- Measures performance metrics required by constitution (P50/P95/P99 latencies)
- Validates against constitutional 5ms translation overhead limit

### Performance Standards ✅ COMPLIANT
- Benchmark measures query translation overhead (constitutional <5ms requirement)
- Tests at production scale (≥100K vectors for HNSW validation)
- Includes latency percentile measurements per constitutional standards

**GATE STATUS**: ✅ PASS - No constitutional violations detected

## Project Structure

### Documentation (this feature)
```
specs/[###-feature]/
├── plan.md              # This file (/plan command output)
├── research.md          # Phase 0 output (/plan command)
├── data-model.md        # Phase 1 output (/plan command)
├── quickstart.md        # Phase 1 output (/plan command)
├── contracts/           # Phase 1 output (/plan command)
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
benchmarks/                    # New directory for benchmark utilities
├── 3way_comparison.py         # Main benchmark script
├── config.py                  # Configuration management
├── results/                   # Benchmark results output
│   ├── json/
│   └── tables/
└── test_data/                 # Shared test data generators
    ├── vector_generator.py
    └── query_templates.py

tests/
├── performance/               # New directory for benchmark tests
│   ├── test_3way_benchmark.py
│   └── test_data_generation.py
├── integration/               # Existing directory
└── unit/                      # Existing directory
```

**Structure Decision**: Single project structure. The benchmark is a utility within the existing iris-pgwire repository. New `benchmarks/` directory at repository root contains the 3-way comparison implementation. Test data generators are shared across all three database methods to ensure FR-008 compliance (identical test data). Results are stored separately by format (JSON, console tables) per FR-010.

## Phase 0: Outline & Research
1. **Extract unknowns from Technical Context** above:
   - For each NEEDS CLARIFICATION → research task
   - For each dependency → best practices task
   - For each integration → patterns task

2. **Generate and dispatch research agents**:
   ```
   For each unknown in Technical Context:
     Task: "Research {unknown} for {feature context}"
   For each technology choice:
     Task: "Find best practices for {tech} in {domain}"
   ```

3. **Consolidate findings** in `research.md` using format:
   - Decision: [what was chosen]
   - Rationale: [why chosen]
   - Alternatives considered: [what else evaluated]

**Output**: research.md with all NEEDS CLARIFICATION resolved

## Phase 1: Design & Contracts
*Prerequisites: research.md complete*

1. **Extract entities from feature spec** → `data-model.md`:
   - Entity name, fields, relationships
   - Validation rules from requirements
   - State transitions if applicable

2. **Generate API contracts** from functional requirements:
   - For each user action → endpoint
   - Use standard REST/GraphQL patterns
   - Output OpenAPI/GraphQL schema to `/contracts/`

3. **Generate contract tests** from contracts:
   - One test file per endpoint
   - Assert request/response schemas
   - Tests must fail (no implementation yet)

4. **Extract test scenarios** from user stories:
   - Each story → integration test scenario
   - Quickstart test = story validation steps

5. **Update agent file incrementally** (O(1) operation):
   - Run `.specify/scripts/bash/update-agent-context.sh claude`
     **IMPORTANT**: Execute it exactly as specified above. Do not add or remove any arguments.
   - If exists: Add only NEW tech from current plan
   - Preserve manual additions between markers
   - Update recent changes (keep last 3)
   - Keep under 150 lines for token efficiency
   - Output to repository root

**Output**: data-model.md, /contracts/*, failing tests, quickstart.md, agent-specific file

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
1. **Infrastructure Setup** (1-3):
   - Set up PostgreSQL with pgvector container
   - Create benchmark directory structure
   - Install Python dependencies

2. **Contract Tests** (4-6):
   - Test BenchmarkConfiguration validation
   - Test PerformanceResult validation
   - Test BenchmarkReport JSON/table export

3. **Data Layer** (7-10):
   - Implement vector data generator (FR-008: identical across methods)
   - Implement query template definitions (FR-002: three categories)
   - Create test data setup for all three databases
   - Implement connection validation (FR-006)

4. **Benchmark Core** (11-15):
   - Implement BenchmarkRunner initialization
   - Implement warmup query execution (FR-009)
   - Implement timing measurement with perf_counter
   - Implement percentile calculations (FR-004: P50/P95/P99)
   - Implement QPS calculation

5. **Database Methods** (16-18) [P]:
   - Implement IRIS + PGWire query execution [P]
   - Implement PostgreSQL + psycopg3 query execution [P]
   - Implement IRIS + DBAPI query execution [P]

6. **Output Formatting** (19-20):
   - Implement JSON export (FR-010)
   - Implement console table export (FR-010)

7. **Integration Tests** (21-24):
   - Test end-to-end benchmark with all three methods
   - Test abort-on-failure behavior (FR-006)
   - Test identical data validation (FR-008)
   - Test performance metrics accuracy

8. **Quickstart Validation** (25):
   - Execute quickstart.md scenarios to validate implementation

**Ordering Strategy**:
- Infrastructure first (setup environment)
- TDD order: Contract tests → implementation → integration tests
- Parallel execution for database method implementations (independent)
- Quickstart validation last (validates entire system)

**Estimated Output**: 25 numbered, ordered tasks in tasks.md

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)  
**Phase 4**: Implementation (execute tasks.md following constitutional principles)  
**Phase 5**: Validation (run tests, execute quickstart.md, performance validation)

## Complexity Tracking
*Fill ONLY if Constitution Check has violations that must be justified*

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |


## Progress Tracking
*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command)
- [x] Phase 1: Design complete (/plan command)
- [x] Phase 2: Task planning complete (/plan command - describe approach only)
- [x] Phase 3: Tasks generated (/tasks command) - 28 tasks created
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS
- [x] Post-Design Constitution Check: PASS
- [x] All NEEDS CLARIFICATION resolved
- [x] Complexity deviations documented (none - no violations)

**Artifacts Generated**:
- [x] research.md - All technical decisions documented
- [x] data-model.md - Five core entities defined with validation rules
- [x] contracts/benchmark_api.py - Complete API contract with dataclasses
- [x] quickstart.md - Step-by-step validation scenarios
- [x] CLAUDE.md - Updated with benchmark context
- [x] tasks.md - 28 detailed tasks with dependencies and parallel execution guidance

**Ready for**: /analyze command (quality check) or implementation execution

---
*Based on Constitution v2.1.1 - See `/memory/constitution.md`*
