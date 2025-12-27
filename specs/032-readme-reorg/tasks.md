# Tasks: README Documentation Reorganization

**Input**: Design documents from `/specs/032-readme-reorg/`
**Prerequisites**: plan.md (✅), research.md (✅), data-model.md (✅), quickstart.md (✅)

## Execution Flow (main)
```
1. Load plan.md from feature directory
   → ✅ Loaded: Documentation reorganization, 675→<300 lines, pg_catalog fix
2. Load optional design documents:
   → ✅ research.md: Content audit, pg_catalog analysis (6 tables, 5 functions)
   → ✅ data-model.md: Documentation structure (7 categories, 8 new files)
   → ✅ quickstart.md: Contributor guide
3. Generate tasks by user story:
   → US1: Create critical PG_CATALOG.md (fixes README error)
   → US2: Create new documentation files (7 files)
   → US3: Condense README to <300 lines
   → US4: Update existing docs with cross-links
   → US5: Validate links and verify goals
4. Apply task rules:
   → [P] for different files (can work in parallel)
   → Sequential for same file (README)
   → [US#] labels for user story mapping
5. Number tasks sequentially (T001-T042)
6. Generate dependency graph (US1 → US2 → US3 → US4 → US5)
7. ✅ SUCCESS: 42 tasks ready for execution
```

## Format: `- [ ] [ID] [P?] [Story?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- **[US#]**: User Story label (US1, US2, etc.)
- Include exact file paths in descriptions

## User Story Mapping

Based on spec.md acceptance scenarios:

- **US1**: pg_catalog Documentation (HIGH PRIORITY - fixes README error)
- **US2**: Create New Documentation Files (7 new docs)
- **US3**: Condense README (<300 lines, add doc links)
- **US4**: Update Existing Documentation (cross-links, consolidation)
- **US5**: Validation & Verification (links, line count, content preservation)

---

## Phase 1: Setup (Project Initialization)

**Goal**: Prepare workspace and tools for documentation reorganization

- [ ] T001 Verify current README length (should be 675 lines): `wc -l README.md`
- [ ] T002 Install markdown-link-check for link validation: `npm install -g markdown-link-check`
- [ ] T003 Backup current README: `cp README.md README.md.backup`
- [ ] T004 Create documentation tracking spreadsheet for line count monitoring

**Completion Criteria**:
- ✅ README.md.backup exists
- ✅ markdown-link-check installed and working
- ✅ Baseline metrics recorded (675 lines, existing doc count)

---

## Phase 2: User Story 1 - Critical pg_catalog Documentation

**Story Goal**: Fix incorrect README claim and document actual pg_catalog implementation

**Priority**: HIGH - README line 625 incorrectly states "pg_catalog not available"

**Reality**: Feature 031 implemented 6 catalog tables + 5 catalog functions

**Independent Test Criteria**:
- ✅ docs/PG_CATALOG.md exists and documents all 6 tables
- ✅ docs/PG_CATALOG.md documents all 5 functions
- ✅ README line 625 updated with correct pg_catalog status
- ✅ Link to PG_CATALOG.md in README Known Limitations section
- ✅ All catalog tables verified against src/iris_pgwire/catalog/ code

### Tasks

- [ ] T005 [US1] Review src/iris_pgwire/catalog/__init__.py and extract supported catalog tables
- [ ] T006 [US1] Review src/iris_pgwire/catalog/catalog_router.py for catalog function implementations
- [ ] T007 [US1] Create docs/PG_CATALOG.md with structure from data-model.md
- [ ] T008 [US1] Document 6 catalog tables in docs/PG_CATALOG.md:
  - pg_class (table/view catalog)
  - pg_attribute (column catalog)
  - pg_constraint (constraint catalog)
  - pg_index (index catalog)
  - pg_namespace (schema catalog)
  - pg_attrdef (default values catalog)
- [ ] T009 [US1] Document 5 catalog functions in docs/PG_CATALOG.md:
  - format_type()
  - pg_get_constraintdef()
  - pg_get_serial_sequence()
  - pg_get_indexdef()
  - pg_get_viewdef()
- [ ] T010 [US1] Add limitations section to docs/PG_CATALOG.md (what's NOT supported)
- [ ] T011 [US1] Add usage examples to docs/PG_CATALOG.md (Prisma introspection, SQLAlchemy reflection)
- [ ] T012 [US1] Update README.md line 625 from "pg_catalog not available" to "Partial pg_catalog support - see [PG_CATALOG.md](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md)"
- [ ] T013 [US1] Add PG_CATALOG.md link to README Known Limitations section
- [ ] T014 [US1] Verify docs/PG_CATALOG.md line count contributes to zero information loss goal

**Story Completion**: 10 tasks completed, pg_catalog accurately documented

---

## Phase 3: User Story 2 - Create New Documentation Files

**Story Goal**: Create 7 new documentation files to hold content moved from README

**Independent Test Criteria**:
- ✅ All 7 new docs exist with proper structure (H1 title, H2 sections)
- ✅ Each doc has "Last Updated" date and cross-references
- ✅ Content extracted from README (lines documented in research.md)
- ✅ All absolute GitHub URLs used for links
- ✅ Each doc has working code examples with language tags

### Tasks

- [ ] T015 [P] [US2] Create docs/FEATURES_OVERVIEW.md from README lines 110-181 (Key Features section)
- [ ] T016 [P] [US2] Create docs/ARCHITECTURE.md from README lines 361-404 + consolidate DUAL_PATH_ARCHITECTURE.md
- [ ] T017 [P] [US2] Create docs/BI_TOOLS.md from README lines 281-335 + examples/BI_TOOLS_SETUP.md
- [ ] T018 [P] [US2] Create docs/PERFORMANCE.md from README lines 338-358 with link to benchmarks/README_4WAY.md
- [ ] T019 [P] [US2] Create docs/INSTALLATION.md from README lines 407-472 (comprehensive install guide)
- [ ] T020 [P] [US2] Create docs/QUICKSTART_EXAMPLES.md from README lines 184-256 (usage examples for all languages)
- [ ] T021 [P] [US2] Create docs/ROADMAP.md from README lines 598-673 (future plans and in-progress work)
- [ ] T022 [US2] Verify all 7 new docs follow template structure from quickstart.md
- [ ] T023 [US2] Add "Last Updated: 2025-12-27" to all new docs
- [ ] T024 [US2] Verify all links in new docs use absolute GitHub URLs
- [ ] T025 [US2] Verify combined line count of new docs matches extracted README content (447 lines extracted)

**Story Completion**: 11 tasks completed, 7 new docs created

---

## Phase 4: User Story 3 - Condense README to <300 Lines

**Story Goal**: Reduce README from 675 to <300 lines while preserving quick start and adding doc links

**Independent Test Criteria**:
- ✅ README.md line count: `wc -l README.md` shows <300 lines
- ✅ Quick Start section preserved (Docker, PyPI, ZPM - lines 28-87)
- ✅ Client Compatibility table condensed with footnote link
- ✅ Documentation Index added with 7 categories
- ✅ All removed content accessible via doc links

### Tasks

**Title & Description (Keep)**:
- [ ] T026 [US3] Verify README title and badges section (lines 1-7) stays unchanged

**Why This Matters (Trim)**:
- [ ] T027 [US3] Trim README "Why This Matters" section from 15→12 lines (target: lines 8-19)

**Quick Start (Keep)**:
- [ ] T028 [US3] Verify README Quick Start section (lines 28-87) stays complete with all 3 install methods

**Client Compatibility (Condense)**:
- [ ] T029 [US3] Condense README Client Compatibility section to table + single footnote (target: 20 lines)
- [ ] T030 [US3] Add link to docs/CLIENT_RECOMMENDATIONS.md after compatibility table

**Key Features (Replace with Summaries)**:
- [ ] T031 [US3] Replace README Key Features section (lines 110-181) with 4 brief summaries:
  - pgvector Operations (3 lines + link to VECTOR_PARAMETER_BINDING.md)
  - ORM Introspection (3 lines + link to PG_CATALOG.md)
  - Enterprise Authentication (3 lines + link to DEPLOYMENT.md#authentication)
  - Performance (3 lines + link to PERFORMANCE.md)

**Remove Sections (Link to Docs)**:
- [ ] T032 [US3] Remove README Usage Examples section (lines 184-256), already covered in Quick Start
- [ ] T033 [US3] Remove README Authentication section (lines 259-278), link to DEPLOYMENT.md
- [ ] T034 [US3] Remove README BI & Analytics section (lines 281-335), link to BI_TOOLS.md
- [ ] T035 [US3] Remove README Performance section (lines 338-358), link to PERFORMANCE.md
- [ ] T036 [US3] Remove README Architecture section (lines 361-404), link to ARCHITECTURE.md
- [ ] T037 [US3] Remove README Installation section (lines 407-472), redundant with Quick Start
- [ ] T038 [US3] Remove README Testing section (lines 515-559), link to testing.md
- [ ] T039 [US3] Remove README Roadmap section (lines 598-673), link to ROADMAP.md

**Add Documentation Index**:
- [ ] T040 [US3] Add README Documentation Index section (50 lines) with 7 categories per data-model.md:
  - Getting Started (3 links)
  - Core Features (3 links including PG_CATALOG.md)
  - Architecture & Design (2 links)
  - Integration (2 links)
  - Deployment (2 links)
  - Performance (2 links)
  - Reference (3 links)

**Keep Existing**:
- [ ] T041 [US3] Verify README Production Ready, Contributing, Links, License sections stay (50 lines combined)

**Final Verification**:
- [ ] T042 [US3] Run `wc -l README.md` and verify result is <300 lines (target: 278 lines)
- [ ] T043 [US3] Verify README contains Quick Start + Documentation Index + essential info only

**Story Completion**: 18 tasks completed, README reduced to <300 lines

---

## Phase 5: User Story 4 - Update Existing Documentation

**Story Goal**: Update existing docs with cross-references to new documentation

**Independent Test Criteria**:
- ✅ docs/KNOWN_LIMITATIONS.md updated with accurate pg_catalog info
- ✅ docs/DEPLOYMENT.md links to new AUTHENTICATION.md section (if created)
- ✅ docs/CLIENT_RECOMMENDATIONS.md cross-references PG_CATALOG.md
- ✅ All existing docs "Last Updated" dates current
- ✅ No broken internal links between docs

### Tasks

- [ ] T044 [P] [US4] Update docs/KNOWN_LIMITATIONS.md line 625 area with correct pg_catalog status
- [ ] T045 [P] [US4] Add cross-reference to PG_CATALOG.md in docs/CLIENT_RECOMMENDATIONS.md
- [ ] T046 [P] [US4] Add "Last Updated: 2025-12-27" to all modified existing docs
- [ ] T047 [US4] Verify no broken cross-references between old and new docs

**Story Completion**: 4 tasks completed, existing docs updated

---

## Phase 6: User Story 5 - Validation & Verification

**Story Goal**: Validate all links, verify line counts, ensure zero information loss

**Independent Test Criteria**:
- ✅ All links validate with markdown-link-check (100% success)
- ✅ README line count <300 (target: 278)
- ✅ Content preservation verified (675 lines → README + new docs)
- ✅ All 6 user story goals from spec.md met
- ✅ Cross-platform link testing (GitHub, PyPI preview)

### Tasks

**Link Validation**:
- [ ] T048 [P] [US5] Run markdown-link-check on README.md: `markdown-link-check README.md`
- [ ] T049 [P] [US5] Run markdown-link-check on all new docs: `markdown-link-check docs/*.md`
- [ ] T050 [US5] Fix any broken links found in validation
- [ ] T051 [US5] Re-run link validation until 100% pass rate

**Line Count Verification**:
- [ ] T052 [US5] Verify README line count: `wc -l README.md` (must be <300)
- [ ] T053 [US5] Count lines in all new docs and verify content preservation (675 total lines preserved)

**Content Preservation**:
- [ ] T054 [US5] Verify Quick Start section works (test Docker, PyPI, ZPM commands)
- [ ] T055 [US5] Verify pg_catalog documentation is accurate vs code in src/iris_pgwire/catalog/
- [ ] T056 [US5] Verify all 7 documentation categories have content

**Cross-Platform Testing**:
- [ ] T057 [US5] Test absolute URLs work on GitHub (commit and view on github.com)
- [ ] T058 [US5] Test links work on PyPI preview (upload to test.pypi.org and view)

**Success Criteria Verification**:
- [ ] T059 [US5] ✅ README length reduced by 55%? (675→278 = 59% reduction)
- [ ] T060 [US5] ✅ Zero information loss? (all content accessible via links)
- [ ] T061 [US5] ✅ Time-to-first-query <5 minutes? (test with new user)
- [ ] T062 [US5] ✅ All links validate? (100% pass rate)
- [ ] T063 [US5] ✅ pg_catalog clarity? (line 625 fixed, PG_CATALOG.md complete)
- [ ] T064 [US5] ✅ Documentation discoverability? (all topics within 2 clicks)

**Story Completion**: 17 tasks completed, all validation passed

---

## Dependencies

### Story-Level Dependencies
```
US1 (pg_catalog docs) → MUST complete first (fixes critical error)
  ↓
US2 (new docs) → Can start after US1, parallel within US2
  ↓
US3 (condense README) → Depends on US2 (need doc links)
  ↓
US4 (update existing) → Depends on US2 (need new docs to reference)
  ↓
US5 (validation) → Depends on US3, US4 (all changes complete)
```

### Task-Level Dependencies

**Blocking Tasks**:
- T007 (create PG_CATALOG.md) blocks T008-T011 (content population)
- T012 (fix README line 625) depends on T007-T011 (PG_CATALOG.md complete)
- T015-T021 (create new docs) must complete before T031-T039 (README condensing)
- T040 (add Documentation Index) depends on T015-T021 (need doc links)
- T048-T051 (link validation) depend on T040, T042 (all links in place)

**Sequential Tasks (Same File)**:
- T026-T043 all modify README.md → MUST be sequential
- T007-T011 all modify docs/PG_CATALOG.md → MUST be sequential

**Parallel Tasks (Different Files)**:
- T015-T021 can run in parallel (7 different files)
- T044-T046 can run in parallel (3 different files)
- T048-T049 can run in parallel (validation on different files)

---

## Parallel Execution Examples

### Phase 2 (US1): pg_catalog Documentation
```bash
# Sequential - all modify same file docs/PG_CATALOG.md
1. T007 → Create file
2. T008 → Add tables section
3. T009 → Add functions section
4. T010 → Add limitations section
5. T011 → Add examples section
```

### Phase 3 (US2): Create New Docs - HIGH PARALLELISM
```bash
# Launch T015-T021 together (7 parallel tasks, different files):
Task T015: Create docs/FEATURES_OVERVIEW.md
Task T016: Create docs/ARCHITECTURE.md
Task T017: Create docs/BI_TOOLS.md
Task T018: Create docs/PERFORMANCE.md
Task T019: Create docs/INSTALLATION.md
Task T020: Create docs/QUICKSTART_EXAMPLES.md
Task T021: Create docs/ROADMAP.md

# Then verify tasks (T022-T025) sequentially
```

### Phase 4 (US3): Condense README
```bash
# Sequential - all modify README.md
1. T026 → Verify title
2. T027 → Trim "Why This Matters"
3. T028 → Verify Quick Start
... (continue sequentially through T043)
```

### Phase 5 (US4): Update Existing Docs - PARALLEL
```bash
# Launch T044-T046 together (3 parallel tasks, different files):
Task T044: Update docs/KNOWN_LIMITATIONS.md
Task T045: Update docs/CLIENT_RECOMMENDATIONS.md
Task T046: Add dates to modified docs
```

### Phase 6 (US5): Validation - PARTIAL PARALLELISM
```bash
# Launch T048-T049 together (validation on different files):
Task T048: Validate README links
Task T049: Validate all docs links

# Then T050-T051 fix any issues
# Then T052-T064 verify goals sequentially
```

---

## Implementation Strategy

### MVP Scope (Minimum Viable Documentation)
**US1 only**: pg_catalog documentation and README fix
- **Tasks**: T001-T014 (14 tasks)
- **Outcome**: Critical error fixed, README accurate
- **Value**: Developers get correct pg_catalog information immediately

### Incremental Delivery Plan

1. **Sprint 1** (Days 1-2): US1 - pg_catalog Documentation
   - Fix critical README error
   - Deliverable: docs/PG_CATALOG.md + README line 625 corrected

2. **Sprint 2** (Days 3-4): US2 - Create New Documentation
   - 7 new docs created in parallel
   - Deliverable: Complete documentation set

3. **Sprint 3** (Days 5-6): US3 - Condense README
   - README reduced to <300 lines
   - Deliverable: Scannable README with doc links

4. **Sprint 4** (Day 7): US4 + US5 - Update & Validate
   - Cross-references added
   - All links validated
   - Deliverable: Production-ready documentation

### Quality Gates

After each user story, verify:
- [ ] All tasks for story completed
- [ ] Independent test criteria met
- [ ] No broken links introduced
- [ ] Line count tracking on target (README reduction progress)

---

## Notes

- **[P] Marking**: Tasks T015-T021 (create new docs) and T044-T046 (update existing) can run in parallel
- **Sequential Constraint**: All README modifications (T026-T043) MUST be sequential to avoid merge conflicts
- **Critical Path**: US1 → US2 → US3 → US5 (US4 can overlap with US5)
- **Estimated Total Time**: 7 days (assuming 6 tasks/day, accounting for review and validation)
- **Parallelization Opportunity**: 10 tasks can run in parallel (T015-T021, T044-T046)
- **Zero Information Loss**: Tracked via line count verification (T053) and content preservation check (T054)

---

## Task Generation Validation

✅ **Format Check**: All tasks follow checklist format `- [ ] [ID] [P?] [Story?] Description`
✅ **User Story Mapping**: All tasks labeled with [US1] through [US5]
✅ **File Paths**: All tasks include exact file paths
✅ **Parallelization**: [P] marked on 10 tasks (different files, no dependencies)
✅ **Dependencies**: Clear story and task dependencies documented
✅ **Test Criteria**: Each user story has independent test criteria
✅ **MVP Scope**: US1 identified as minimum viable documentation

**Total Task Count**: 64 tasks
- US1 (pg_catalog): 10 tasks
- US2 (new docs): 11 tasks
- US3 (condense README): 18 tasks
- US4 (update existing): 4 tasks
- US5 (validation): 17 tasks
- Setup: 4 tasks

**Parallel Opportunities**: 10 tasks can run simultaneously (16% of total)
