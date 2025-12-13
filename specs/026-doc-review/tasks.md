# Tasks: Documentation Review for Clarity, Tone, and Accuracy

**Input**: Design documents from `/specs/026-doc-review/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/review-contract.md

**Organization**: Tasks are grouped by user story priority and can be executed in parallel where marked [P].

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

---

## Phase 1: Setup

**Purpose**: Prepare environment and tools for documentation review

- [x] T001 Verify Docker is running for Quick Start testing
- [x] T002 Verify Python 3.11+ with psycopg3 and SQLAlchemy available
- [x] T003 Create tracking document for issues found: `specs/026-doc-review/issues.md`

---

## Phase 2: User Story 1 - External Developer Evaluating IRIS PGWire (Priority: P1)

**Goal**: Ensure README.md clearly communicates value and enables quick adoption

**Independent Test**: Developer unfamiliar with project can explain what it does and get running in 60 seconds

### README.md Review

- [x] T004 [US1] Review README.md value proposition - first 2-3 sentences must explain core value
  - File: `/README.md` lines 1-15
  - Criterion: R-001 from contract
  - Result: PASS - Value proposition clear in first sentence

- [ ] T005 [US1] Test Quick Start Docker workflow - time execution, must complete in 60 seconds
  - Commands from `/README.md` lines 32-39
  - Criterion: R-002 from contract
  ```bash
  docker-compose up -d
  psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Hello from IRIS!'"
  ```

- [ ] T006 [P] [US1] Smoke test Python psycopg3 example from README.md
  - File: `/README.md` lines 56-62, 142-167
  - Criterion: R-003 from contract

- [ ] T007 [P] [US1] Smoke test async SQLAlchemy/FastAPI example from README.md
  - File: `/README.md` lines 169-193
  - Criterion: R-003 from contract

- [ ] T008 [P] [US1] Smoke test psql command line examples from README.md
  - File: `/README.md` lines 126-138
  - Criterion: R-003 from contract

- [x] T009 [US1] Validate all external links in README.md
  - Extract URLs: `grep -oh 'https://[^)]*' README.md | sort -u`
  - Criterion: R-004 from contract
  - Result: 2 broken links found (I001, I002 in issues.md)

- [ ] T010 [US1] Verify performance claims against benchmarks
  - File: `/README.md` Performance section (lines 276-296)
  - Cross-reference: `/benchmarks/README_4WAY.md`
  - Criterion: R-005 from contract

- [x] T011 [US1] Review README.md tone - professional, confident, not defensive
  - Full file review
  - Criterion: R-006 from contract
  - Result: PASS - No defensive language patterns found

- [ ] T012 [US1] Fix any issues found in README.md
  - Apply corrections for issues documented in T004-T011

**Checkpoint**: README.md passes all R-001 through R-006 acceptance criteria

---

## Phase 3: User Story 2 - Technical Writer Reviewing Accuracy (Priority: P2)

**Goal**: All technical claims and examples are accurate and verified

**Independent Test**: Technical reviewer confirms code examples work and links resolve

### KNOWN_LIMITATIONS.md Review

- [ ] T013 [P] [US2] Verify industry comparison table accuracy
  - File: `/KNOWN_LIMITATIONS.md` lines 11-48
  - Cross-reference cited sources (PgBouncer, YugabyteDB, etc.)
  - Criterion: K-001 from contract

- [ ] T014 [P] [US2] Verify limitations match actual implementation
  - File: `/KNOWN_LIMITATIONS.md`
  - Cross-reference with source code in `src/`
  - Criterion: K-002 from contract

- [ ] T015 [US2] Review KNOWN_LIMITATIONS.md tone - informative, not defensive
  - Full file review
  - Criterion: K-004 from contract

- [ ] T016 [US2] Fix any issues found in KNOWN_LIMITATIONS.md
  - Apply corrections for issues documented in T013-T015

### docs/ Directory Review - User-Facing Guides

- [ ] T017 [US2] Categorize all 50 docs/ files as user-facing or internal
  - Output: Update `specs/026-doc-review/data-model.md` with final categorization
  - Criterion: D-001 from contract

- [ ] T018 [P] [US2] Review deployment docs for accuracy
  - Files: `docs/DEPLOYMENT.md`, `docs/PRODUCTION_DEPLOYMENT.md`, `docs/README-DEPLOYMENT.md`

- [ ] T019 [P] [US2] Review architecture docs for accuracy
  - Files: `docs/DUAL_PATH_ARCHITECTURE.md`, `docs/EMBEDDED_PYTHON_SERVERS_HOWTO.md`

- [ ] T020 [P] [US2] Review feature docs for accuracy
  - Files: `docs/VECTOR_PARAMETER_BINDING.md`, `docs/DBAPI_BACKEND.md`, `docs/PERFORMANCE.md`

- [ ] T021 [P] [US2] Review integration docs for accuracy
  - Files: `docs/LANGCHAIN_INTEGRATION.md`, `docs/SQLALCHEMY_ASYNC_SUPPORT.md`, `docs/ASYNC_SQLALCHEMY_QUICKSTART.md`

- [ ] T022 [P] [US2] Review client docs for accuracy
  - Files: `docs/CLIENT_RECOMMENDATIONS.md`, `docs/ADDITIONAL_CLIENT_RECOMMENDATIONS.md`, `docs/POSTGRESQL_COMPATIBILITY.md`

- [ ] T023 [P] [US2] Review development docs for accuracy
  - Files: `docs/developer_guide.md`, `docs/DEVELOPMENT.md`, `docs/testing.md`, `docs/PRE_COMMIT_SETUP.md`

- [ ] T024 [P] [US2] Review troubleshooting docs for accuracy
  - Files: `docs/OAUTH_TROUBLESHOOTING.md`, `docs/WALLET_TROUBLESHOOTING.md`, `docs/KERBEROS_TROUBLESHOOTING.md`

- [ ] T025 [P] [US2] Review IRIS feature docs for accuracy
  - Files: `docs/INTEGRATEDML_SUPPORT.md`, `docs/INTEGRATEDML_CONFIGURATION.md`, `docs/IRIS_CONSTRUCTS_IMPLEMENTATION.md`, `docs/IRIS_SPECIAL_CONSTRUCTS.md`

- [ ] T026 [US2] Validate internal links across all docs/
  - Command: `grep -roh '\[.*\](.*\.md)' docs/ | grep -v 'http'`
  - Criterion: D-005 from contract

- [ ] T027 [US2] Fix any issues found in user-facing docs
  - Apply corrections for issues documented in T018-T026

### Archive Internal Documents

- [ ] T028 [US2] Create docs/archive/ directory
  - Command: `mkdir -p docs/archive`

- [ ] T029 [US2] Move internal/research documents to archive
  - Files to move (17 total):
    - `ASYNCPG_FIX_SUMMARY.md`
    - `ASYNCPG_FINAL_STATUS.md`
    - `ASYNCPG_PARAMETER_TYPE_INVESTIGATION.md`
    - `COLUMN_ALIAS_INVESTIGATION.md`
    - `DEBUGGING_INVESTIGATION_2025_10_03.md`
    - `HNSW_FINDINGS_2025_10_02.md`
    - `HNSW_INVESTIGATION.md`
    - `INTEGRATEDML_ANALYSIS.md`
    - `IRIS_DBAPI_LIMITATIONS_JIRA.md`
    - `IRIS_DOCUMENT_DATABASE_RESEARCH.md`
    - `IRIS_SQL_ANALYSIS.md`
    - `INTERSYSTEMS_PACKAGE_NAMING_ISSUE.md`
    - `PROTOCOL_COMPLETENESS_AUDIT.md`
    - `RESEARCH_BACKLOG.md`
    - `REST_API_STRATEGY.md`
    - `RECENT_DEVELOPMENTS.md`
    - `COMPETITIVE_ANALYSIS.md`
  - Use `git mv` to preserve history

**Checkpoint**: All docs/ files reviewed, user-facing docs accurate, internal docs archived

---

## Phase 4: User Story 3 - Enterprise Stakeholder Assessing Production Readiness (Priority: P3)

**Goal**: Documentation presents professional, enterprise-ready image

**Independent Test**: Security reviewer understands auth options and limitations without ambiguity

### Root Directory Cleanup

- [x] T030 [US3] Create target directories for file relocation
  - Commands:
    ```bash
    mkdir -p .github/badges
    mkdir -p tests/performance
    mkdir -p scripts
    ```

- [x] T031 [US3] Relocate interrogate_badge.svg
  - Command: `git mv interrogate_badge.svg .github/badges/`
  - Criterion: ROOT-001, ROOT-003 from contract

- [x] T032 [P] [US3] Relocate test_performance_simple.py
  - Command: `git mv test_performance_simple.py tests/performance/`
  - Criterion: ROOT-001, ROOT-003 from contract

- [x] T033 [P] [US3] Relocate merge.cpf
  - Result: Removed duplicate from root (docker/merge.cpf already exists)
  - Updated docker-compose.yml to reference docker/merge.cpf
  - Criterion: ROOT-001, ROOT-003 from contract

- [x] T034 [P] [US3] Relocate start-production.sh
  - Command: `git mv start-production.sh scripts/`
  - Criterion: ROOT-001, ROOT-003 from contract

- [x] T035 [US3] Review iris.key - determine if needed publicly or should be gitignored
  - Decision: Keep - Community edition license key needed for Docker setup
  - Document decision in issues.md

- [x] T036 [US3] Review iris_pgwire.json - IPM manifest, keep if needed
  - Decision: Keep - Server configuration file, not IPM manifest
  - Document decision in issues.md

- [x] T037 [US3] Update any references broken by file relocations
  - Updated docker-compose.yml merge.cpf paths to docker/merge.cpf
  - Criterion: ROOT-002 from contract

- [x] T038 [US3] Verify root directory is clean
  - Result: PASS - Only essential files remain
  - Criterion: ROOT-001 from contract

**Checkpoint**: Root directory contains only essential files, no broken references

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final cleanup and verification

### Terminology Audit

- [x] T039 [P] Scan for "IRIS PGWire" variants and fix
  - Command: `grep -ri "pgwire\|pg-wire\|pg wire" --include="*.md" .`
  - Result: PASS - No improper variants found (pg-wire only in external URLs)
  - Criterion: T-001 from contract

- [x] T040 [P] Scan for "PostgreSQL" variants and fix
  - Command: `grep -ri "postgres[^ql]" --include="*.md" .`
  - Result: PASS - All "postgres" uses are legitimate (container names, lib names)
  - Criterion: T-002 from contract

- [x] T041 [P] Scan for "SCRAM-SHA-256" variants and fix
  - Result: PASS - Consistent formatting throughout
  - Criterion: T-003 from contract

- [x] T042 [P] Scan for "OAuth 2.0" variants and fix
  - Result: PASS - Consistent "OAuth 2.0" with version number
  - Criterion: T-004 from contract

- [x] T043 Apply all terminology fixes identified in T039-T042
  - Result: No fixes needed - terminology is consistent

### Final Validation

- [ ] T044 Run full link validation across all markdown files
  - Command: `grep -roh 'https://[^)]*' . --include="*.md" | sort -u | head -50`
  - Test each URL resolves

- [ ] T045 Run quickstart.md validation process
  - Follow process in `specs/026-doc-review/quickstart.md`
  - Confirm all acceptance criteria met

- [x] T046 Create summary of changes made
  - Document in `specs/026-doc-review/changes-summary.md`

- [x] T047 Commit all changes with descriptive message
  - Commit: 5a518dc "chore: Clean up root directory for professional presentation"

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies - start immediately
- **Phase 2 (US1 - README)**: Depends on Phase 1
- **Phase 3 (US2 - Accuracy)**: Depends on Phase 1, can run parallel with Phase 2
- **Phase 4 (US3 - Root Cleanup)**: Depends on Phase 1, can run parallel with Phase 2/3
- **Phase 5 (Polish)**: Depends on Phases 2, 3, 4

### Parallel Execution Groups

**Group A: Code Example Testing (T006, T007, T008)**
```
All test different code examples, no file conflicts
```

**Group B: KNOWN_LIMITATIONS Review (T013, T014)**
```
Different validation methods, same file but read-only
```

**Group C: docs/ Review (T018-T025)**
```
All review different doc files, full parallelization
```

**Group D: File Relocations (T031-T034)**
```
All relocate different files, full parallelization after T030
```

**Group E: Terminology Audit (T039-T042)**
```
All scan for different terms, full parallelization
```

---

## Parallel Execution Example

```bash
# Launch all code example tests in parallel:
Task: "Smoke test Python psycopg3 example from README.md"
Task: "Smoke test async SQLAlchemy/FastAPI example from README.md"
Task: "Smoke test psql command line examples from README.md"

# Launch all docs/ reviews in parallel:
Task: "Review deployment docs for accuracy"
Task: "Review architecture docs for accuracy"
Task: "Review feature docs for accuracy"
Task: "Review integration docs for accuracy"
Task: "Review client docs for accuracy"
Task: "Review development docs for accuracy"
Task: "Review troubleshooting docs for accuracy"
Task: "Review IRIS feature docs for accuracy"
```

---

## Notes

- Total tasks: 47
- P1 (README.md): 9 tasks (T004-T012)
- P2 (Accuracy): 17 tasks (T013-T029)
- P3 (Root Cleanup): 9 tasks (T030-T038)
- Polish: 9 tasks (T039-T047)
- Setup: 3 tasks (T001-T003)
- Estimated parallelization: ~60% of tasks can run in parallel
- Commit after completing each phase
