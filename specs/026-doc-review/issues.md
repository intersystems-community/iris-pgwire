# Issues Tracker: Documentation Review

**Feature**: 026-doc-review
**Created**: 2024-12-12

## Summary

This document tracks issues found during the documentation review process.

## Issue Categories

- **Broken Link**: External or internal link that doesn't resolve
- **Broken Code**: Code example that fails when executed
- **Accuracy**: Technical claim that doesn't match implementation
- **Clarity**: Content that is unclear or confusing
- **Tone**: Language that is defensive, unprofessional, or inappropriate
- **Terminology**: Inconsistent use of terms
- **Outdated**: Information that is no longer current

---

## Phase 1: Setup

- [x] T001: Docker verified running
- [x] T002: Python 3.12.9 with psycopg and sqlalchemy available
- [x] T003: Issues tracking document created

---

## Phase 2: README.md Review (T004-T012)

### T004: Value Proposition Review
*Status: Pending*

### T005: Quick Start Testing
*Status: Pending*

### T006-T008: Code Example Testing
*Status: Pending*

### T009: External Links
*Status: Pending*

### T010: Performance Claims
*Status: Pending*

### T011: Tone Review
*Status: Pending*

---

## Phase 3: KNOWN_LIMITATIONS.md & docs/ Review (T013-T029)

*Status: Pending*

---

## Phase 4: Root Directory Cleanup (T030-T038)

### T035: iris.key Review
*Decision: Pending*

### T036: iris_pgwire.json Review
*Decision: Pending*

---

## Phase 5: Terminology & Final (T039-T047)

*Status: Pending*

---

## Issues Found

| ID | Type | File | Description | Resolution | Status |
|----|------|------|-------------|------------|--------|
| I001 | Broken Link | README.md | GitHub repo link (isc-tdyar/iris-pgwire) returns 404 - repo may be private | Verify repo is public or update URL | Open |
| I002 | Broken Link | README.md | InterSystems docs link returns 404 | Update to valid docs URL | Open |
| I003 | Clarity | README.md | Value proposition excellent - no changes needed | N/A | Closed |
| I004 | Tone | README.md | Professional tone, no defensive language found | N/A | Closed |

---

## Decisions Log

| Task | Decision | Rationale |
|------|----------|-----------|
| T033 | Remove root merge.cpf | Duplicate exists in docker/, root version had password hash |
| T035 | Keep iris.key | Community edition license needed for Docker setup |
| T036 | Keep iris_pgwire.json | Server configuration file, essential for operation |
| T037 | Update docker-compose.yml | Changed merge.cpf path from ./merge.cpf to ./docker/merge.cpf |
