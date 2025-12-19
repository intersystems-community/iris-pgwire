# Feature Specification: Repository Documentation Archive

**Feature Branch**: `029-archive-non-essential`
**Created**: 2025-12-19
**Status**: Draft
**Input**: User description: "Archive non-essential docs to clean up root and docs directory for clean, professional repo"

---

## Summary

Clean up the IRIS PGWire repository to present a professional, focused appearance for Open Exchange publication and public visibility. Move internal investigation reports, troubleshooting guides, and historical analysis documents to an archive location while keeping essential documentation in the main docs directory.

---

## User Scenarios & Testing

### Primary User Story

As a developer discovering IRIS PGWire on Open Exchange or GitHub, I want to see a clean, organized repository with essential documentation prominently displayed so I can quickly understand the project's purpose, installation, and usage without being overwhelmed by internal development artifacts.

### Acceptance Scenarios

1. **Given** a new visitor to the repository, **When** they browse the root directory, **Then** they see only essential files (README, LICENSE, CHANGELOG, config files) without clutter from development artifacts.

2. **Given** a developer looking for documentation, **When** they open the docs/ directory, **Then** they find organized, essential documentation (deployment guides, API reference, architecture) without investigation reports or troubleshooting logs.

3. **Given** an existing contributor needing historical context, **When** they need investigation reports or troubleshooting guides, **Then** they can still access these documents in a clearly labeled archive location.

4. **Given** a CI/CD pipeline or documentation generator, **When** processing the repository, **Then** only public-facing documentation is included in generated outputs.

### Edge Cases

- What happens when a document is referenced from README but moved to archive? Links must be updated or documents kept in main location.
- How does the archive handle documents that are both historical AND still useful? Classification criteria must be clear.

---

## Requirements

### Functional Requirements

- **FR-001**: Repository MUST organize documentation into two tiers: essential (public-facing) and archive (internal/historical)

- **FR-002**: Essential documentation MUST include:
  - Installation and deployment guides
  - API documentation
  - Architecture overview
  - Client compatibility matrix
  - Quick start guides

- **FR-003**: Archive documentation MUST include:
  - Investigation reports (e.g., HNSW_INVESTIGATION, ASYNCPG_PARAMETER_TYPE_INVESTIGATION)
  - Troubleshooting guides for specific issues (e.g., KERBEROS_TROUBLESHOOTING, OAUTH_TROUBLESHOOTING)
  - Historical analysis documents (e.g., COLUMN_ALIAS_INVESTIGATION, DEBUGGING_INVESTIGATION)
  - Dated findings (e.g., HNSW_FINDINGS_2025_10_02)
  - Internal planning documents (e.g., iris_pgwire_plan.md)
  - Research backlogs and competitive analysis

- **FR-004**: Root directory MUST be cleaned of development artifacts:
  - Test failure logs (test_failures.jsonl) MUST be gitignored
  - Any temporary or generated files MUST be excluded

- **FR-005**: All links in README and essential docs MUST remain valid after reorganization (either by keeping referenced docs in place or updating links)

- **FR-006**: Archive location MUST be clearly labeled and documented so contributors can find historical context when needed

- **FR-007**: The reorganization MUST NOT break any CI/CD workflows or automated documentation generation

### Key Entities

- **Essential Documentation**: User-facing guides that help with installation, usage, and integration
- **Archive Documentation**: Internal reports, investigations, and historical context useful for contributors
- **Root Directory Artifacts**: Build outputs, test logs, and generated files that should be gitignored

---

## Success Criteria

- Root directory contains only essential files visible to visitors (README, LICENSE, CHANGELOG, configuration files, source directories)
- docs/ directory reduced from 52 files to fewer than 20 essential documents
- All README links verified working after reorganization
- Repository presents clean, professional appearance suitable for Open Exchange listing
- Historical documentation remains accessible for contributors who need it
- No broken references in documentation after archival

---

## Assumptions

1. **Archive location**: Documents will be moved to `docs/archive/` subdirectory (keeps them in repo but clearly separated)
2. **Gitignore updates**: Development artifacts like `test_failures.jsonl` will be added to .gitignore rather than deleted
3. **Link handling**: External absolute links in README are already correct; internal relative links may need updates
4. **CI preservation**: No changes to `.github/workflows/` or build configuration needed
5. **Classification criteria**: Documents with dates or "INVESTIGATION" in the name are archive candidates; documents referenced from README are essential

---

## Dependencies

- Feature 028 (readme-performance) should be merged first to ensure README links are baseline
- No external system dependencies
- No infrastructure changes required

---

## Out of Scope

- Rewriting or improving document content (only moving/organizing)
- Changing documentation format (markdown remains markdown)
- Creating new documentation
- Modifying source code or tests
- Changes to specs/ directory (that's part of speckit workflow)

---
