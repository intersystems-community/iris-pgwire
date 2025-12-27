# Documentation Reorganization Tracking

**Feature**: 032-readme-reorg
**Started**: 2025-12-27
**Goal**: Reduce README from 675 lines to <300 lines (target: 278 lines)

---

## Baseline Metrics (T001)

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| README.md lines | 675 | <300 (278) | 🔴 Needs Work |
| Reduction needed | - | 397 lines (59%) | - |
| Documentation files | 51 | ~55-60 | 📊 Baseline |
| Broken links | TBD | 0 | ⏳ Pending |

---

## Line Count Progress

| Phase | Task Range | README Lines | Change | Notes |
|-------|-----------|--------------|--------|-------|
| **Baseline** | - | 675 | - | Original (backed up to README.md.backup) |
| **Phase 1: Setup** | T001-T004 | 675 | 0 | ✅ Setup complete, no content changes |
| **Phase 2: US1** | T005-T014 | 675 | 0 | ✅ pg_catalog doc created, README line 625 fixed |
| **Phase 3: US2** | T015-T025 | TBD | TBD | Create 7 new docs |
| **Phase 4: US3** | T026-T043 | TBD | TBD | **Major condensing phase** |
| **Phase 5: US4** | T044-T047 | TBD | TBD | Cross-link updates |
| **Phase 6: US5** | T048-T064 | TBD | TBD | Final validation |

---

## New Documentation Files Created

| File | Status | Lines | Content Source | User Story |
|------|--------|-------|----------------|-----------|
| docs/PG_CATALOG.md | ✅ Complete | 378 | src/iris_pgwire/catalog/ analysis | US1 |
| docs/FEATURES_OVERVIEW.md | ⏳ Pending | - | README lines 110-181 | US2 |
| docs/ARCHITECTURE.md | ⏳ Pending | - | README lines 361-404 + existing doc | US2 |
| docs/BI_TOOLS.md | ⏳ Pending | - | README lines 281-335 + examples | US2 |
| docs/PERFORMANCE.md | ⏳ Pending | - | README lines 338-358 | US2 |
| docs/INSTALLATION.md | ⏳ Pending | - | README lines 407-472 | US2 |
| docs/QUICKSTART_EXAMPLES.md | ⏳ Pending | - | README lines 184-256 | US2 |
| docs/ROADMAP.md | ⏳ Pending | - | README lines 598-673 | US2 |

---

## Content Preservation Tracking

| Content Category | Original Lines | Target Location | Status |
|------------------|----------------|-----------------|--------|
| Quick Start (Docker/PyPI/ZPM) | 28-87 (60) | README (keep) | ✅ Preserved |
| Key Features Details | 110-181 (72) | docs/FEATURES_OVERVIEW.md | ⏳ Pending |
| Usage Examples | 184-256 (73) | docs/QUICKSTART_EXAMPLES.md | ⏳ Pending |
| Authentication | 259-278 (20) | Link to DEPLOYMENT.md | ⏳ Pending |
| BI & Analytics | 281-335 (55) | docs/BI_TOOLS.md | ⏳ Pending |
| Performance | 338-358 (21) | docs/PERFORMANCE.md | ⏳ Pending |
| Architecture | 361-404 (44) | docs/ARCHITECTURE.md | ⏳ Pending |
| Installation | 407-472 (66) | Condensed in Quick Start | ⏳ Pending |
| Testing | 515-559 (45) | Link to testing.md | ⏳ Pending |
| Roadmap | 598-673 (76) | docs/ROADMAP.md | ⏳ Pending |
| **Total to Move** | **447 lines** | Various docs | **Zero loss goal** |

---

## Critical Issues Tracking

| Issue | Line(s) | Status | Resolution | Task |
|-------|---------|--------|------------|------|
| Incorrect pg_catalog claim | 625 | ✅ Fixed | Updated to "Partial pg_catalog support" + link to PG_CATALOG.md | T012 |
| README too long | All | 🔴 Open | Move 447 lines to dedicated docs | T026-T043 |

---

## Link Validation

| File | Total Links | Broken | Status | Last Check |
|------|-------------|--------|--------|------------|
| README.md | TBD | TBD | ⏳ Pending | - |
| docs/*.md (all) | TBD | TBD | ⏳ Pending | - |

---

## Phase Completion

- [x] **Phase 1: Setup** (T001-T004) - Baseline established, tracking ready
- [x] **Phase 2: US1 - pg_catalog** (T005-T014) - ✅ PG_CATALOG.md created, README fixed
- [ ] **Phase 3: US2 - New Docs** (T015-T025) - 7 parallel file creation
- [ ] **Phase 4: US3 - Condense README** (T026-T043) - Major reduction phase
- [ ] **Phase 5: US4 - Update Existing** (T044-T047) - Cross-references
- [ ] **Phase 6: US5 - Validation** (T048-T064) - Final verification

---

## Success Criteria Checklist

- [ ] README length <300 lines (current: 675)
- [ ] Zero information loss (all 675 lines preserved somewhere)
- [ ] Time-to-first-query <5 minutes for new users
- [ ] All links validate (100% success rate)
- [ ] pg_catalog accurately documented
- [ ] All topics within 2 clicks from README

---

**Update Instructions**: After each phase, update this file with:
1. Current README line count
2. Files created/modified
3. Link validation results
4. Any issues discovered
