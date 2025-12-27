# Implementation Plan: README Documentation Reorganization

**Branch**: `032-readme-reorg` | **Date**: 2025-12-27 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/032-readme-reorg/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path
   → Spec loaded: README reorganization (675→<300 lines, pg_catalog clarity)
2. Fill Technical Context
   → Project Type: Documentation (Markdown files)
   → Structure Decision: Docs reorganization
3. Fill Constitution Check section
   → No code changes - documentation only
4. Evaluate Constitution Check
   → No violations: Documentation improvements align with Production Readiness (Section V)
5. Execute Phase 0 → research.md
   → Audit existing docs, analyze README structure, plan content distribution
6. Execute Phase 1 → contracts (N/A), data-model.md (doc structure), quickstart.md
7. Re-evaluate Constitution Check
   → No new violations
8. Plan Phase 2 → Task generation approach
9. STOP - Ready for /tasks command
```

## Summary

Reorganize IRIS PGWire README from 675 lines to under 300 lines by moving detailed content to dedicated documentation files while preserving all information. Key objectives:

1. **Reduce README length by 55%** without information loss
2. **Clarify pg_catalog support** - README currently says "not available" but it IS implemented for ORM introspection
3. **Improve discoverability** - Categorized documentation links (Getting Started, Features, Architecture, etc.)
4. **Faster time-to-first-query** - New users can start in <5 minutes

## Technical Context

**Language/Version**: Markdown (GitHub Flavored Markdown)
**Primary Dependencies**: None (static documentation)
**Storage**: Git repository (`docs/` directory, 51 existing .md files)
**Testing**: Link validation, README length verification, content coverage check
**Target Platform**: GitHub, PyPI, Docker Hub (absolute URLs for cross-platform compatibility)
**Project Type**: Documentation reorganization (single project)
**Performance Goals**: README loads instantly (<300 lines), all links resolve in <2 seconds
**Constraints**: Zero information loss, maintain all 675 lines of content (just redistributed)
**Scale/Scope**: 675 lines → <300 lines README, 51 existing docs → ~55-60 docs after reorganization

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Applicable Constitution Principles

**V. Production Readiness** ✅
- Documentation is a core production requirement
- Clear documentation improves operational understanding
- This reorganization improves documentation quality and accessibility
- **Status**: COMPLIANT - Improves production readiness

**VII. Development Environment Synchronization** ✅
- Documentation changes don't require container restarts
- Static files, no runtime synchronization concerns
- **Status**: NOT APPLICABLE

**Authorship and Attribution** ✅
- All documentation credited to Thomas Dyar
- No AI attribution in documentation
- **Status**: COMPLIANT

### Non-Applicable Principles
- **I. Protocol Fidelity**: No protocol changes
- **II. Test-First Development**: No protocol implementation
- **III. Phased Implementation**: No phased protocol work
- **IV. IRIS Integration**: No IRIS integration changes
- **VI. Vector Performance**: No vector operation changes

### Violations
None. This is a pure documentation reorganization that improves production readiness by making documentation more accessible and maintainable.

## Project Structure

### Documentation (this feature)
```
specs/032-readme-reorg/
├── plan.md              # This file (/plan command output)
├── spec.md              # Feature specification
├── research.md          # Phase 0: README audit, content categorization
├── data-model.md        # Phase 1: Documentation structure and linking strategy
├── quickstart.md        # Phase 1: Quick reference for contributors
├── checklists/
│   └── requirements.md  # Spec validation checklist
└── tasks.md             # Phase 2: (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
# Documentation structure (existing + new files)
docs/
├── GETTING_STARTED.md      # NEW: Detailed installation and first queries
├── AUTHENTICATION.md       # NEW: Comprehensive auth guide (OAuth, Wallet, SCRAM)
├── PG_CATALOG.md           # NEW: pg_catalog implementation and limitations
├── BI_TOOLS.md             # NEW: Consolidated BI tool guides
├── ORM_INTEGRATION.md      # NEW: Prisma, SQLAlchemy, etc. setup guides
├── VECTOR_OPERATIONS.md    # NEW: Vector ops, pgvector syntax, HNSW
├── ARCHITECTURE.md         # NEW: High-level architecture overview
├── DEPLOYMENT.md           # EXISTING: Production deployment guide
├── DUAL_PATH_ARCHITECTURE.md  # EXISTING: DBAPI vs Embedded execution
├── KNOWN_LIMITATIONS.md    # EXISTING: Update with pg_catalog info
├── CLIENT_RECOMMENDATIONS.md  # EXISTING: PostgreSQL client matrix
├── VECTOR_PARAMETER_BINDING.md  # EXISTING: High-dimensional vector support
├── INTEGRATEDML_SUPPORT.md  # EXISTING: IntegratedML capabilities
├── INTEGRATEDML_CONFIGURATION.md  # EXISTING: IntegratedML setup
├── INTEGRATEDML_ANALYSIS.md  # EXISTING: IntegratedML compatibility
└── [48 other existing docs remain unchanged]

# Root documentation
README.md               # MODIFIED: Reduced from 675 to <300 lines
└── [Links to all detailed docs above]

# Examples (referenced but not modified)
examples/
├── superset-iris-healthcare/
├── prisma-iris-demo/
└── [other examples]

# Benchmarks (referenced but not modified)
benchmarks/
└── README_4WAY.md      # Comprehensive performance benchmarks
```

## Phase 0: Content Audit & Research

### Research Tasks

1. **README Content Audit**
   - Analyze all 675 lines of current README
   - Categorize content by type (quick start, detailed features, architecture, etc.)
   - Identify "above the fold" content vs deep-dive content
   - Document current link structure and broken links

2. **pg_catalog Implementation Review**
   - Review `src/iris_pgwire/catalog/` module implementation
   - Document what pg_catalog tables are emulated (pg_class, pg_attribute, pg_constraint, pg_index, etc.)
   - Identify limitations and PostgreSQL incompatibilities
   - Extract accurate description from code comments and implementation

3. **Existing Documentation Analysis**
   - Inventory all 51 existing docs in `docs/` directory
   - Identify overlapping content that can be consolidated
   - Find gaps where new docs are needed (PG_CATALOG.md, BI_TOOLS.md, etc.)
   - Document cross-references and linking patterns

4. **Distribution Channel Requirements**
   - GitHub: Markdown rendering, relative links work
   - PyPI: Markdown to HTML conversion, need absolute links
   - Docker Hub: README display limitations
   - Determine absolute URL pattern for cross-platform links

### Research Output (`research.md`)

Document findings for:
- Content categorization matrix (keep in README vs move to docs)
- pg_catalog implementation details (what's supported, what's not)
- Documentation gaps requiring new files
- Link validation strategy
- Optimal README structure (target <300 lines)

## Phase 1: Documentation Structure Design

### Data Model (`data-model.md`)

Define documentation information architecture:

1. **README Structure** (target <300 lines):
   - Title and badges (10 lines)
   - Project description (15 lines)
   - Quick Start (50 lines) - Docker, PyPI, ZPM
   - Key Features (40 lines) - Brief overview with links
   - Client Compatibility (30 lines) - Condensed matrix
   - Performance Summary (20 lines) - Key metrics with benchmark link
   - Documentation Index (50 lines) - Categorized links
   - Resources and License (20 lines)
   - **Total: ~235 lines** (buffer for adjustments)

2. **Documentation Categories**:
   - **Getting Started**: Installation, first queries, quick wins
   - **Features**: pgvector, ORM support, pg_catalog, authentication
   - **Architecture**: High-level overview, dual backend, protocol flow
   - **Integration**: BI tools, ORMs, frameworks
   - **Deployment**: Production setup, security, monitoring
   - **Performance**: Benchmarks, optimization, HNSW indexes
   - **Reference**: API docs, known limitations, troubleshooting

3. **New Documentation Files**:
   - `docs/GETTING_STARTED.md`: Expanded quick start with troubleshooting
   - `docs/PG_CATALOG.md`: pg_catalog implementation, supported tables, limitations
   - `docs/BI_TOOLS.md`: Consolidate Superset, Metabase, Grafana guides
   - `docs/ORM_INTEGRATION.md`: Prisma, SQLAlchemy, Sequelize, Hibernate setup
   - `docs/VECTOR_OPERATIONS.md`: pgvector syntax, HNSW, performance tips
   - `docs/AUTHENTICATION.md`: OAuth 2.0, IRIS Wallet, SCRAM-SHA-256 detailed guides
   - `docs/ARCHITECTURE.md`: High-level system overview with diagrams

4. **Link Strategy**:
   - Use absolute GitHub URLs for cross-platform compatibility
   - Format: `https://github.com/intersystems-community/iris-pgwire/blob/main/docs/FILE.md`
   - Anchor links for subsections: `#subsection-title`
   - Validate all links before committing

### Contracts (`contracts/`)

Not applicable - this is a documentation reorganization with no API contracts.

### Quick Start (`quickstart.md`)

Create contributor guide for documentation updates:

1. **Documentation Update Workflow**
   - How to add new documentation files
   - Link validation process
   - README length verification (`wc -l README.md`)
   - Cross-platform testing (GitHub, PyPI preview)

2. **Style Guidelines**
   - GitHub Flavored Markdown conventions
   - Code block language tags (bash, python, sql, etc.)
   - Heading hierarchy (H1 for title, H2 for major sections, H3 for subsections)
   - Link text best practices (descriptive, not "click here")

3. **Content Guidelines**
   - Keep README scannable (bullet points, short paragraphs)
   - Move detailed explanations to dedicated docs
   - Use tables for comparison/compatibility matrices
   - Include working code examples (verified to run)

## Phase 2: Task Generation Strategy

The `/tasks` command will generate tasks organized by documentation file:

### Task Categories

1. **README Condensing Tasks** (10-15 tasks)
   - Remove detailed content from each major section
   - Add links to new/existing detailed docs
   - Verify length reduction milestones (500→400→<300 lines)

2. **New Documentation Tasks** (7 tasks)
   - Create `docs/PG_CATALOG.md` from catalog module analysis
   - Create `docs/GETTING_STARTED.md` from README quick start expansion
   - Create `docs/BI_TOOLS.md` consolidating existing BI guides
   - Create `docs/ORM_INTEGRATION.md` for Prisma/SQLAlchemy patterns
   - Create `docs/VECTOR_OPERATIONS.md` from README vector section
   - Create `docs/AUTHENTICATION.md` from DEPLOYMENT.md auth section
   - Create `docs/ARCHITECTURE.md` high-level overview

3. **Documentation Update Tasks** (3-5 tasks)
   - Update `docs/KNOWN_LIMITATIONS.md` with accurate pg_catalog info
   - Update `docs/CLIENT_RECOMMENDATIONS.md` links from README
   - Update `docs/DEPLOYMENT.md` to link to new AUTHENTICATION.md

4. **Link Validation Tasks** (2 tasks)
   - Validate all absolute GitHub URLs
   - Test links across GitHub, PyPI, Docker Hub

5. **Verification Tasks** (2 tasks)
   - Verify README <300 lines
   - Verify all 675 lines of content preserved (no information loss)

### Task Dependencies

```
research.md (Phase 0)
  ↓
data-model.md (Phase 1) - Documentation structure
  ↓
┌─────────────────────────────────────────┐
│ Create new docs (parallel)              │
│ - PG_CATALOG.md                         │
│ - GETTING_STARTED.md                    │
│ - BI_TOOLS.md                           │
│ - ORM_INTEGRATION.md                    │
│ - VECTOR_OPERATIONS.md                  │
│ - AUTHENTICATION.md                     │
│ - ARCHITECTURE.md                       │
└─────────────────────────────────────────┘
  ↓
Condense README with links to new docs
  ↓
Update existing docs with new links
  ↓
Link validation
  ↓
Final verification (<300 lines, content preserved)
```

## Complexity Tracking

### Scope Creep Risks
- **Adding new content** instead of just reorganizing → Mitigation: Strict "no new content" rule
- **Over-architecting** documentation structure → Mitigation: Keep simple categorization
- **Link maintenance burden** → Mitigation: Use absolute URLs, automated link checking

### Quality Gates
1. ✅ README reduced to <300 lines
2. ✅ Zero information loss (all 675 lines preserved in docs)
3. ✅ All links validated (100% success rate)
4. ✅ pg_catalog accurately described
5. ✅ Time-to-first-query <5 minutes for new users

### Technical Debt
None - this is pure documentation improvement with no code changes.

## Progress Tracking

- [x] Phase 0: Research completed (research.md)
- [x] Phase 1: Data model and contracts defined (data-model.md, quickstart.md)
- [x] Phase 1: Agent context updated (N/A - documentation only)
- [x] Phase 1: Constitution re-check passed (no code changes)
- [ ] Phase 2: Tasks ready for generation (/tasks command)

## Notes

- **pg_catalog Implementation**: Current README line 625 says "pg_catalog not available" but `src/iris_pgwire/catalog/` provides ORM introspection for Prisma, SQLAlchemy, etc. Need to correct this and add detailed docs.
- **Absolute URLs**: PyPI converts markdown to HTML and breaks relative links - must use absolute GitHub URLs
- **No Code Changes**: This feature is documentation-only, no container restarts or testing required
- **Constitution Compliance**: Aligns with Production Readiness principle (Section V) - improves operational documentation

---

**Ready for Phase 0 Research**: All prerequisites met, no technical clarifications needed.
