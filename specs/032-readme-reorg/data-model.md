# Phase 1: Documentation Structure Design

**Date**: 2025-12-27
**Based on**: research.md Phase 0 findings

---

## Documentation Information Architecture

This document defines the structure, organization, and relationships of all documentation in the IRIS PGWire project.

## 1. README Structure (Target: 278 lines)

### Section Breakdown

| Section | Lines | Content |
|---------|-------|---------|
| Title & Badges | 7 | Project name, license, version badges |
| Project Description | 12 | What IRIS PGWire does, why it matters |
| Quick Start | 60 | Docker, PyPI, ZPM installation + first query |
| Client Compatibility | 20 | Language matrix with features |
| Key Features | 40 | Brief feature summaries with doc links |
| Documentation Index | 50 | Categorized links to all docs |
| Production Status | 15 | Test count, pg_catalog correction |
| Contributing | 20 | How to contribute |
| Links & License | 15 | External resources, license |
| **Total** | **239** | *39 lines under target* |

### Content Principles

**Keep in README:**
- ✅ Essential onboarding (Quick Start)
- ✅ Value proposition (Why This Matters)
- ✅ Navigation (Documentation Index)
- ✅ Project status (test coverage, production readiness)
- ✅ Legal (license, attribution)

**Move to Dedicated Docs:**
- ❌ Detailed explanations (architecture, implementation)
- ❌ Comprehensive guides (authentication, BI tools, ORMs)
- ❌ Examples beyond Quick Start (usage patterns, tutorials)
- ❌ Deep technical content (performance analysis, troubleshooting)
- ❌ Long-term planning (roadmap, known limitations)

## 2. Documentation Categories

### Category: Getting Started

**Purpose**: Help users go from zero to first query in <5 minutes

**Files**:
- `docs/INSTALLATION.md` - Comprehensive installation guide (Docker, PyPI, ZPM, from source)
- `docs/QUICKSTART_EXAMPLES.md` - Working examples (psql, Python, Node.js, Java)
- `docs/FIRST_QUERIES.md` - Common query patterns, troubleshooting

**Content from README**: Lines 407-472 (Installation section), 184-256 (Usage Examples)

### Category: Core Features

**Purpose**: Explain what IRIS PGWire can do

**Files**:
- `docs/PG_CATALOG.md` - **NEW** - pg_catalog implementation (6 tables, 5 functions)
- `docs/FEATURES_OVERVIEW.md` - **NEW** - Comprehensive feature guide
- `docs/VECTOR_PARAMETER_BINDING.md` - EXISTING - Vector operations deep dive
- `docs/SQLALCHEMY_ASYNC_SUPPORT.md` - EXISTING - Async Python patterns
- `docs/CLIENT_RECOMMENDATIONS.md` - EXISTING - Client compatibility matrix

**Content from README**: Lines 110-181 (Key Features), 90-107 (Client Compatibility details)

**CRITICAL: pg_catalog Documentation**
- **Problem**: README line 625 incorrectly states "pg_catalog not available"
- **Reality**: Feature 031 implemented full ORM introspection support:
  - 6 catalog tables: pg_class, pg_attribute, pg_constraint, pg_index, pg_namespace, pg_attrdef
  - 5 catalog functions: format_type(), pg_get_constraintdef(), pg_get_serial_sequence(), pg_get_indexdef(), pg_get_viewdef()
- **Solution**: Create `docs/PG_CATALOG.md` with accurate implementation details
- **README Fix**: Change line 625 to "Partial pg_catalog support - see [PG_CATALOG.md](docs/PG_CATALOG.md)"

### Category: Architecture & Design

**Purpose**: Explain how IRIS PGWire works internally

**Files**:
- `docs/ARCHITECTURE.md` - **NEW** - High-level system overview
- `docs/DUAL_PATH_ARCHITECTURE.md` - EXISTING - DBAPI vs Embedded execution
- `docs/PROTOCOL_COMPLETENESS_AUDIT.md` - EXISTING - Protocol implementation status
- `docs/IRIS_INTEGRATION_LAYER.md` - EXISTING - IRIS connection patterns

**Content from README**: Lines 361-404 (Architecture section)

### Category: Integration Guides

**Purpose**: Help users integrate with specific tools/frameworks

**Files**:
- `docs/BI_TOOLS.md` - **NEW** - Consolidate Superset, Metabase, Grafana
- `docs/ORM_INTEGRATION.md` - EXISTING (examples/) - Prisma, SQLAlchemy, Sequelize
- `examples/BI_TOOLS_SETUP.md` - EXISTING - Working BI examples
- `examples/superset-iris-healthcare/` - EXISTING - Healthcare demo

**Content from README**: Lines 281-335 (BI & Analytics section)

**Consolidation**: Merge README BI section + examples/BI_TOOLS_SETUP.md → docs/BI_TOOLS.md

### Category: Deployment & Operations

**Purpose**: Production deployment, security, monitoring

**Files**:
- `docs/DEPLOYMENT.md` - EXISTING - Production setup, authentication
- `docs/PRODUCTION_CHECKLIST.md` - **NEW** - Pre-launch checklist
- `docs/WALLET_TROUBLESHOOTING.md` - EXISTING - IRIS Wallet debugging
- `docs/OAUTH_TROUBLESHOOTING.md` - EXISTING - OAuth configuration
- `docs/KERBEROS_TROUBLESHOOTING.md` - EXISTING - Kerberos (experimental)

**Content from README**: Lines 259-278 (Authentication), 494-512 (Production Ready details)

### Category: Performance & Optimization

**Purpose**: Benchmarks, tuning, troubleshooting performance

**Files**:
- `docs/PERFORMANCE.md` - **NEW** - Consolidated performance guide
- `benchmarks/README_4WAY.md` - EXISTING - Comprehensive benchmarks
- `docs/HNSW_FINDINGS_2025_10_02.md` - EXISTING - Vector index analysis
- `docs/ASYNCPG_PARAMETER_TYPE_INVESTIGATION.md` - EXISTING - Parameter binding

**Content from README**: Lines 338-358 (Performance section)

### Category: Reference & Troubleshooting

**Purpose**: API reference, known issues, workarounds

**Files**:
- `docs/KNOWN_LIMITATIONS.md` - EXISTING - Update with pg_catalog info
- `docs/testing.md` - EXISTING - Test framework guide
- `docs/developer_guide.md` - EXISTING - Contributor setup
- `docs/ROADMAP.md` - **NEW** - Future plans, in-progress work

**Content from README**: Lines 598-673 (Roadmap section), 515-559 (Testing section)

## 3. New Documentation Files Required

### HIGH PRIORITY

**1. `docs/PG_CATALOG.md` - pg_catalog Implementation**
- **Purpose**: Fix incorrect README claim, document catalog support
- **Content**:
  - Overview: ORM introspection for Prisma, Drizzle, SQLAlchemy
  - Supported tables (6): pg_class, pg_attribute, pg_constraint, pg_index, pg_namespace, pg_attrdef
  - Supported functions (5): format_type(), pg_get_constraintdef(), etc.
  - Limitations: What's NOT supported (e.g., pg_type partial support)
  - Usage examples: Prisma introspection, SQLAlchemy reflection
- **Source**: `src/iris_pgwire/catalog/` module analysis from research.md

**2. `docs/FEATURES_OVERVIEW.md` - Comprehensive Features**
- **Purpose**: Deep dive into all IRIS PGWire capabilities
- **Content from README**: Lines 110-181 (expanded with examples)
- **Structure**:
  - pgvector Operations (syntax, operators, HNSW)
  - ORM Introspection (catalog support, schema mapping)
  - Authentication (OAuth, Wallet, SCRAM-SHA-256)
  - Performance (overhead, connection pooling, async)
  - Protocol Compliance (extended query, COPY, transactions)

### MEDIUM PRIORITY

**3. `docs/ARCHITECTURE.md` - System Overview**
- **Purpose**: High-level architecture for developers
- **Content from README**: Lines 361-404 (Architecture section)
- **Content from existing**: Consolidate DUAL_PATH_ARCHITECTURE.md
- **Structure**:
  - System diagram (clients → PGWire → IRIS)
  - Protocol layer (message handling, encoding)
  - Query translation (SQL rewriting, pgvector → IRIS)
  - Backend execution (DBAPI vs Embedded)
  - Link to detailed architecture docs

**4. `docs/BI_TOOLS.md` - BI Integration**
- **Purpose**: Consolidate BI tool setup guides
- **Content from README**: Lines 281-335 (BI & Analytics)
- **Content from examples**: examples/BI_TOOLS_SETUP.md
- **Structure**:
  - Zero-config connection (Superset, Metabase, Grafana)
  - Healthcare demo walkthrough (superset-iris-healthcare)
  - Vector analytics in BI tools (semantic search)
  - Troubleshooting (connection issues, query performance)

**5. `docs/PERFORMANCE.md` - Performance Guide**
- **Purpose**: Consolidated performance documentation
- **Content from README**: Lines 338-358 (Performance section)
- **Content from benchmarks**: Link to README_4WAY.md
- **Structure**:
  - Protocol overhead (4ms baseline)
  - Vector performance (HNSW indexes)
  - Connection pooling (50+20 async)
  - Benchmarking methodology
  - Optimization tips

### LOW PRIORITY

**6. `docs/INSTALLATION.md` - Detailed Installation**
- **Purpose**: Comprehensive install guide beyond Quick Start
- **Content from README**: Lines 407-472
- **Additional**: From-source builds, custom configurations

**7. `docs/QUICKSTART_EXAMPLES.md` - Usage Examples**
- **Purpose**: Working examples for all supported languages
- **Content from README**: Lines 184-256
- **Additional**: More languages (Java, .NET, Go, Ruby, Rust, PHP)

**8. `docs/ROADMAP.md` - Future Plans**
- **Purpose**: Roadmap, known limitations, in-progress work
- **Content from README**: Lines 598-673
- **Additional**: GitHub issues, feature requests

## 4. Link Strategy

### Absolute URL Pattern

**Format**: `https://github.com/intersystems-community/iris-pgwire/blob/main/docs/FILENAME.md`

**Why Absolute URLs**:
- ✅ GitHub: Works natively
- ✅ PyPI: Markdown → HTML conversion, relative links break
- ✅ Docker Hub: Limited markdown support, absolute URLs safer
- ✅ External sites: Links work from anywhere

### Anchor Links

**Format**: `#section-title` (lowercase, hyphens for spaces)

**Example**:
```markdown
See [Authentication](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md#authentication) for details.
```

### Link Validation

**Tools**:
- `markdown-link-check` (npm package)
- Manual testing on GitHub, PyPI preview

**Process**:
1. Write documentation with absolute links
2. Run `markdown-link-check README.md docs/*.md`
3. Fix broken links
4. Test on GitHub (commit), PyPI (preview on test.pypi.org)
5. Repeat for any failures

## 5. Documentation Index (README Section)

### Structure for README

```markdown
## 📚 Documentation

### Getting Started
- [Installation Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/INSTALLATION.md) - Comprehensive setup
- [Quick Start Examples](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/QUICKSTART_EXAMPLES.md) - Working code samples
- [First Queries](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/FIRST_QUERIES.md) - Common patterns

### Core Features
- [pg_catalog Support](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md) - ORM introspection details
- [Features Overview](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/FEATURES_OVERVIEW.md) - All capabilities
- [Vector Operations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md) - pgvector deep dive

### Architecture & Design
- [System Architecture](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ARCHITECTURE.md) - How it works
- [Dual Backend](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DUAL_PATH_ARCHITECTURE.md) - DBAPI vs Embedded

### Integration
- [BI Tools](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/BI_TOOLS.md) - Superset, Metabase, Grafana
- [ORM Integration](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ORM_INTEGRATION.md) - Prisma, SQLAlchemy

### Deployment
- [Production Deployment](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md) - Security, monitoring
- [Production Checklist](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PRODUCTION_CHECKLIST.md) - Pre-launch

### Performance
- [Performance Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PERFORMANCE.md) - Optimization tips
- [Benchmarks](https://github.com/intersystems-community/iris-pgwire/blob/main/benchmarks/README_4WAY.md) - Detailed results

### Reference
- [Known Limitations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/KNOWN_LIMITATIONS.md) - Workarounds
- [Testing Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/testing.md) - Test framework
- [Roadmap](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ROADMAP.md) - Future plans
```

## 6. Migration Strategy

### Phase 1: Create New Documentation Files (Days 1-3)
1. PG_CATALOG.md (HIGH PRIORITY)
2. FEATURES_OVERVIEW.md
3. ARCHITECTURE.md
4. BI_TOOLS.md
5. PERFORMANCE.md
6. INSTALLATION.md
7. QUICKSTART_EXAMPLES.md
8. ROADMAP.md

### Phase 2: Update Existing Documentation (Day 4)
1. KNOWN_LIMITATIONS.md - Add pg_catalog info
2. DEPLOYMENT.md - Link to new FEATURES_OVERVIEW.md
3. CLIENT_RECOMMENDATIONS.md - Cross-reference PG_CATALOG.md

### Phase 3: Condense README (Days 5-6)
1. Replace detailed sections with summaries + links
2. Verify line count <300
3. Add comprehensive Documentation Index

### Phase 4: Link Validation & Testing (Day 7)
1. Run markdown-link-check on all files
2. Test on GitHub (merge PR)
3. Test on PyPI (publish new version)
4. Verify all links work cross-platform

## 7. Quality Checklist

### Per Documentation File
- [ ] Accurate content (no hallucinations, verified against code)
- [ ] Clear structure (H1 title, H2 major sections, H3 subsections)
- [ ] Working examples (code blocks tested, language tags added)
- [ ] Cross-references (links to related docs)
- [ ] Absolute GitHub URLs (PyPI compatibility)

### README Specific
- [ ] Line count <300 (target: 278)
- [ ] All Quick Start steps work (Docker, PyPI, ZPM)
- [ ] pg_catalog claim corrected (line 625 fix)
- [ ] Documentation Index complete (all categories)
- [ ] No information loss (all 675 lines preserved in docs)

### pg_catalog Documentation
- [ ] All 6 tables documented (pg_class, pg_attribute, etc.)
- [ ] All 5 functions documented (format_type, etc.)
- [ ] Limitations clear (what's NOT supported)
- [ ] Usage examples (Prisma, SQLAlchemy introspection)
- [ ] Corrects README error (line 625)

---

**Status**: Phase 1 Design Complete
**Next**: Phase 2 Task Generation (/tasks command)
