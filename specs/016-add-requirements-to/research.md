# Phase 0: Research Findings

**Feature**: Benchmark Debug Capabilities and Vector Optimizer Fix
**Date**: 2025-10-03

## Summary

No new research required - all technical context already known from existing codebase and diagnostic findings.

## Known Context

### 1. Vector Optimizer Bug (Root Cause Identified)

**Decision**: Fix bracket-stripping regex in `src/iris_pgwire/vector_optimizer.py`

**Rationale**:
- Diagnostic script (`diagnose_hanging_queries.py`) confirmed vector_cosine queries timeout
- PGWire logs show: `VECTOR_COSINE(embedding, TO_VECTOR('0.1,0.1,...', FLOAT))` (missing brackets)
- IRIS requires: `VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.1,...]', FLOAT))` (with brackets)
- SQLCODE -400 error: "Error compiling cached query class %sqlcq.USER.cls7"

**Alternatives Considered**:
- Rewrite optimizer from scratch → Rejected (high risk, existing code mostly works)
- Add workaround in IRIS executor → Rejected (doesn't fix root cause)

### 2. Benchmark Infrastructure

**Decision**: Enhance existing 3-way comparison framework (`benchmarks/3way_comparison.py`)

**Rationale**:
- Infrastructure already established with Docker Compose orchestration
- PostgreSQL (port 5433), IRIS via PGWire (port 5434), IRIS via DBAPI (port 1974) already configured
- Test data generation working (`benchmarks/test_data/vector_generator.py`)
- Only debug logging and error handling need enhancement

**Alternatives Considered**:
- Create new benchmark suite → Rejected (duplicate effort, testing complexity)
- Use third-party benchmarking tool → Rejected (doesn't integrate with IRIS)

### 3. Debug Logging Strategy

**Decision**: Structured logging with query traces and optimization metrics

**Rationale**:
- Constitutional requirement: <5ms translation overhead measurement
- Need visibility into optimizer transformations for future debugging
- Timeout protection essential to prevent indefinite hangs on compiler errors
- Dry-run mode allows query validation without IRIS execution

**Alternatives Considered**:
- Verbose logging to stdout → Rejected (unstructured, hard to parse)
- External tracing tools → Rejected (adds deployment complexity)

### 4. Testing Approach

**Decision**: Contract tests for optimizer syntax, integration tests for E2E validation

**Rationale**:
- TDD principle: Tests must fail before implementation
- Contract tests validate bracket preservation in isolation
- Integration tests confirm full pipeline (optimizer → PGWire → IRIS)
- Existing pytest infrastructure supports both test types

**Alternatives Considered**:
- Unit tests only → Rejected (doesn't catch integration issues)
- E2E tests only → Rejected (slow feedback, hard to isolate bugs)

## Dependencies

**Existing**:
- `src/iris_pgwire/vector_optimizer.py` - Requires regex fix
- `benchmarks/` - Infrastructure for 3-way comparison
- `diagnose_hanging_queries.py` - Diagnostic script for timeout testing
- Docker Compose setup - postgres-benchmark, iris-benchmark, pgwire-benchmark containers

**New** (to be created in Phase 1):
- Contract tests: `tests/contract/test_vector_optimizer_syntax.py`
- Integration tests: `tests/integration/test_benchmark_debug.py`
- Data model: `specs/016-add-requirements-to/data-model.md`
- Quickstart: `specs/016-add-requirements-to/quickstart.md`

## Risk Assessment

**Low Risk**:
- Regex fix in vector_optimizer.py (targeted change, well-tested)
- Debug logging additions (non-breaking, opt-in)
- Contract tests (independent of implementation)

**Medium Risk**:
- SQL validation layer (must not block valid queries)
- Timeout protection (ensure proper cleanup on timeout)

**Mitigation**:
- Start with contract tests (TDD)
- Incremental testing: simple queries → vector queries → joins
- Dry-run mode for validation without IRIS execution

## Open Questions

None - all requirements clarified in spec.md.

---
*No NEEDS CLARIFICATION detected - all technical context known from existing codebase.*
