# Implementation Plan: Drizzle ORM Support

**Branch**: `032-drizzle-orm-support` | **Date**: 2025-12-25 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/032-drizzle-orm-support/spec.md`

## Summary

Validate and ensure Drizzle ORM compatibility with IRIS PGWire by leveraging existing catalog emulation (Feature 031) and RETURNING clause support. This is primarily a **verification feature** - confirming that existing implementations work with Drizzle ORM, documenting any gaps, and creating a demo project for validation.

## Technical Context
**Language/Version**: Python 3.11 (server), TypeScript (client/Drizzle)
**Primary Dependencies**: drizzle-orm, drizzle-kit, postgres.js (Drizzle driver)
**Storage**: IRIS via PGWire protocol (PostgreSQL wire protocol emulation)
**Testing**: pytest (server), Node.js test scripts (client)
**Target Platform**: IRIS PGWire server (Docker container), Node.js client
**Project Type**: single (existing IRIS PGWire server)
**Performance Goals**: Query performance comparable to direct IRIS SQL access (<5ms translation overhead)
**Constraints**: Must maintain compatibility with existing Prisma support (Feature 031)
**Scale/Scope**: Verification of existing capabilities, minimal new implementation expected

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Protocol Fidelity
- [x] **PASS**: No protocol changes required - leveraging existing PostgreSQL wire protocol implementation

### II. Test-First Development
- [x] **PASS**: Will create Drizzle demo project with test scenarios before documenting gaps

### III. Phased Implementation
- [x] **PASS**: Feature 031 completed all prerequisite phases (P0-P5 catalog support)

### IV. IRIS Integration
- [x] **PASS**: Using existing embedded Python patterns via irispython

### V. Production Readiness
- [x] **PASS**: Existing monitoring/logging infrastructure applies

### VI. Vector Performance Requirements
- [x] **PASS**: Not applicable - Drizzle ORM verification does not involve vector operations

### VII. Development Environment Synchronization
- [x] **PASS**: Will restart containers before testing to ensure current code

## Project Structure

### Documentation (this feature)
```
specs/032-drizzle-orm-support/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── drizzle-crud-contract.md
└── tasks.md             # Phase 2 output (/tasks command)
```

### Source Code (repository root)
```
src/iris_pgwire/
├── catalog/             # Existing catalog emulation (from Feature 031)
│   ├── pg_class.py
│   ├── pg_attribute.py
│   ├── pg_constraint.py
│   └── ...
├── iris_executor.py     # RETURNING clause emulation (from Feature 031)
└── protocol.py          # PostgreSQL wire protocol

examples/
├── prisma-iris-demo/    # Existing Prisma demo (Feature 031)
└── drizzle-iris-demo/   # New Drizzle demo (this feature)
    ├── package.json
    ├── drizzle.config.ts
    ├── src/
    │   └── schema.ts    # Generated or manual schema
    └── test-crud.ts     # CRUD verification tests

tests/
├── integration/
│   └── test_drizzle_compatibility.py  # New verification tests
└── contract/
    └── (existing catalog tests apply)
```

**Structure Decision**: Single project structure. Adding `examples/drizzle-iris-demo/` for Drizzle verification alongside existing Prisma demo. Minimal server-side changes expected.

## Phase 0: Outline & Research

### Research Tasks
1. **Drizzle introspection queries**: Determine exact catalog queries drizzle-kit sends
2. **Drizzle vs Prisma differences**: Identify any catalog requirements unique to Drizzle
3. **Drizzle driver selection**: Choose between postgres.js and node-postgres for IRIS compatibility
4. **Transaction patterns**: Verify Drizzle transaction semantics match IRIS capabilities

### Research Agents
- Task: "Research drizzle-kit introspect catalog queries for PostgreSQL"
- Task: "Compare Drizzle ORM and Prisma ORM PostgreSQL requirements"
- Task: "Find best practices for Drizzle with custom PostgreSQL-compatible databases"

**Output**: research.md with all findings consolidated

## Phase 1: Design & Contracts

### Entities (from spec)
- **DrizzleTable**: TypeScript table definition (`pgTable()`)
- **DrizzleColumn**: Column with type and constraints
- **DrizzleRelation**: Foreign key relationship
- **DrizzleIndex**: Index definition

### Contracts
1. **drizzle-crud-contract.md**: Expected behavior for INSERT/SELECT/UPDATE/DELETE with .returning()
2. **drizzle-introspect-contract.md**: Expected catalog query responses for drizzle-kit

### Quickstart Verification
1. Connect Drizzle to IRIS PGWire
2. Run `drizzle-kit introspect`
3. Execute CRUD operations with `.returning()`
4. Verify transaction support

**Output**: data-model.md, contracts/, quickstart.md

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
- Create Drizzle demo project structure
- Generate verification test scripts
- Document any gaps found during testing
- Add integration tests for Drizzle-specific patterns

**Ordering Strategy**:
1. Setup: Create demo project with dependencies
2. Verification: Run drizzle-kit introspect
3. Testing: Execute CRUD operations
4. Documentation: Update README with Drizzle instructions

**Estimated Output**: 10-15 tasks (mostly verification, minimal implementation)

## Complexity Tracking
*No constitution violations - this is a verification feature building on existing work*

| Aspect | Status | Notes |
|--------|--------|-------|
| New code required | Minimal | Mostly verification and documentation |
| Dependencies on Feature 031 | All met | Catalog and RETURNING support complete |
| Risk of breaking changes | Low | Read-only verification approach |

## Progress Tracking

**Phase Status**:
- [x] Phase 0: Research complete (research.md generated)
- [x] Phase 1: Design complete (data-model.md, contracts/, quickstart.md)
- [x] Phase 2: Task planning complete (approach documented)
- [x] Phase 3: Tasks generated (52 tasks in tasks.md)
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS
- [x] Post-Design Constitution Check: PASS (no new violations)
- [x] All NEEDS CLARIFICATION resolved
- [x] Complexity deviations documented (none required)

---
*Based on Constitution v1.3.1 - See `.specify/memory/constitution.md`*
