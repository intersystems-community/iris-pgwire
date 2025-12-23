# Tasks: README Performance Benchmarks Section

**Input**: Design documents from `/specs/028-readme-performance/`
**Prerequisites**: plan.md (complete), spec.md (complete), research.md (complete)

## Execution Flow (main)
```
1. Load plan.md from feature directory → ✅ COMPLETE
   → Tech stack: Markdown (documentation only)
   → Libraries: None
   → Structure: Single file update (README.md)
2. Load optional design documents:
   → research.md: Benchmark data analysis with exact numbers
3. Generate tasks by category:
   → Setup: N/A (documentation feature)
   → Core: Add performance section to README.md
   → Validation: Manual review of rendered output
4. Apply task rules:
   → Single file modification = sequential
   → No TDD required (documentation feature)
5. Number tasks sequentially (T001, T002, T003)
6. Generate dependency graph
7. Validate task completeness
8. Return: SUCCESS (tasks ready for execution)
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

---

## Phase 1: Implementation

### User Story: Performance Visibility
**As a** developer evaluating IRIS PGWire,
**I want to** see clear performance comparisons,
**So that** I can make informed deployment decisions.

- [x] T001 [US1] Add Performance Benchmarks section to README.md after Architecture section

**Task T001 Details**:
- Location: Insert after "## Architecture" section, before "## Supported Clients" section
- Content from research.md:
  - Performance comparison table (4 connection paths × 2 query types)
  - Test conditions (50 iterations, 128 dimensions, 2025-10-05)
  - Key takeaways highlighting IRIS DBAPI Direct as fastest
  - Link to benchmarks/README_4WAY.md for full methodology

**Benchmark Data** (from `benchmarks/results/benchmark_4way_results.json`):
```
| Connection Path       | Simple SELECT | Vector Similarity | Best For                    |
|-----------------------|---------------|-------------------|-----------------------------|
| IRIS DBAPI Direct     | 0.21ms        | 2.35ms            | Maximum performance         |
| PGWire + DBAPI        | 3.82ms        | 6.76ms            | PostgreSQL compatibility    |
| PGWire + Embedded     | 4.75ms        | N/A               | Single-container deployment |
| PostgreSQL (baseline) | 0.32ms        | 0.59ms            | Reference comparison        |
```

---

## Phase 2: Validation

- [x] T002 [US1] Verify README.md renders correctly on GitHub

**Task T002 Details**:
- Preview README.md in GitHub or markdown viewer
- Verify table formatting is correct
- Verify numbers match benchmark_4way_results.json
- Verify link to benchmarks/README_4WAY.md works

- [x] T003 [US1] Commit changes with descriptive message

**Task T003 Details**:
- Stage: `git add README.md`
- Commit message: "docs: Add performance benchmarks section to README"
- Push to branch: `git push`

---

## Dependencies
```
T001 → T002 → T003
```
- T001 must complete before T002 (validation requires content)
- T002 must pass before T003 (don't commit broken formatting)

## Parallel Opportunities
None - this is a sequential 3-task workflow for a single file update.

## Validation Checklist

- [x] All functional requirements (FR-001 through FR-008) addressed in T001
- [x] Each task specifies exact file path (README.md)
- [x] Tasks are in dependency order
- [x] No tests required (documentation-only feature per Constitution Check)

## Notes
- Simple documentation update - total estimated time: 15-30 minutes
- Benchmark data already validated in research.md
- No code changes, no container restarts needed

---

## Summary
- **Total Tasks**: 3
- **Parallel Tasks**: 0 (sequential workflow)
- **Files Modified**: 1 (README.md)
- **Estimated Effort**: Minimal (documentation only)
