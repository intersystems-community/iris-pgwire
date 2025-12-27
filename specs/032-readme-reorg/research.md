# Phase 0 Research: README Reorganization

**Date**: 2025-12-27
**Current README**: 675 lines
**Target**: <300 lines in README, detailed content moved to docs/
**Status**: Research Complete

---

## Executive Summary

The current README.md is comprehensive but too long (675 lines). This research identifies:
- **Content Categorization**: Which sections stay in README vs move to docs/
- **pg_catalog Implementation**: README line 625 is INCORRECT - full catalog support exists
- **Documentation Gaps**: 51 existing docs, need 8 new docs to complete reorganization
- **Link Strategy**: Confirmed GitHub absolute URLs work across platforms

**Critical Finding**: Line 625 incorrectly states "pg_catalog not available" but Feature 031 implemented full ORM introspection support including 6 catalog tables + 5 catalog functions.

---

## 1. README Content Audit

### Content Categorization Matrix

| Section | Lines | Keep in README? | Move to Doc | Rationale |
|---------|-------|-----------------|-------------|-----------|
| **Title & badges** | 1-7 | ✅ Yes | - | Essential header, project identity |
| **Why This Matters** | 12-26 | ✅ Yes (trim to 15 lines) | ECOSYSTEM.md | Value prop stays, detailed ecosystem analysis moves |
| **Quick Start** | 28-87 | ✅ Yes (keep all) | - | Critical onboarding, already concise |
| **Client Compatibility** | 90-107 | ✅ Yes (summary only) | CLIENT_COMPATIBILITY.md | Keep table, move detailed notes |
| **Key Features** | 110-181 | ⚠️ Partial | FEATURES_OVERVIEW.md | Keep 3-sentence summaries, move deep dives |
| **Usage Examples** | 184-256 | ❌ No | QUICKSTART_EXAMPLES.md | Redundant with Quick Start |
| **Authentication** | 259-278 | ⚠️ Partial | DEPLOYMENT.md | Keep 5-line summary, full details already in DEPLOYMENT.md |
| **BI & Analytics** | 281-335 | ❌ No | BI_TOOLS.md | Consolidate with examples/BI_TOOLS_SETUP.md |
| **Performance** | 338-358 | ⚠️ Partial | PERFORMANCE.md | Keep 3-line summary, benchmarks already documented |
| **Architecture** | 361-404 | ❌ No | ARCHITECTURE.md | Consolidate with DUAL_PATH_ARCHITECTURE.md |
| **Installation** | 407-472 | ❌ No | INSTALLATION.md | Redundant with Quick Start |
| **Documentation** | 475-491 | ✅ Yes (reformat) | - | Keep as link directory, essential navigation |
| **Production Ready** | 494-512 | ✅ Yes (trim) | PRODUCTION_CHECKLIST.md | Keep test count, move detailed guidance |
| **Testing** | 515-559 | ❌ No | testing.md | Already documented, remove duplication |
| **Contributing** | 562-580 | ✅ Yes (keep) | - | Essential for contributors |
| **Links** | 583-589 | ✅ Yes (keep) | - | Essential references |
| **License** | 592-595 | ✅ Yes (keep) | - | Legal requirement |
| **Roadmap** | 598-673 | ❌ No | ROADMAP.md | Detailed tracking belongs in dedicated doc |

### Line-by-Line Analysis

#### KEEP in README (Target: 280 lines)

**Title & Badges (7 lines)** - No changes needed

**Why This Matters (15 lines)** - Trim from 15→12 lines
```markdown
## Why This Matters

**Access IRIS through the entire PostgreSQL ecosystem** without custom drivers:

- **BI Tools**: Apache Superset, Metabase, Grafana
- **Python**: psycopg3, SQLAlchemy, pandas, FastAPI
- **Data Engineering**: DBT, Airflow, Kafka Connect
- **Languages**: Python, Node.js, Java, .NET, Go, Ruby, Rust, PHP
- **pgvector**: LangChain, LlamaIndex RAG frameworks

**Connection**: `postgresql://localhost:5432/USER` - standard PostgreSQL URL
```

**Quick Start (60 lines)** - Keep entire section, already optimized

**Client Compatibility (20 lines)** - Keep table, add single footnote
```markdown
| Language | Clients | Features |
|----------|---------|----------|
[existing table content]

**Note**: Full compatibility matrix and known limitations in [CLIENT_COMPATIBILITY.md](docs/CLIENT_COMPATIBILITY.md)
```

**Key Features (40 lines)** - Keep summaries only
```markdown
## Key Features

### pgvector Operations
Drop-in compatibility with pgvector syntax (`<=>` cosine, `<#>` dot product), HNSW indexes, RAG-ready.
See [VECTOR_PARAMETER_BINDING.md](docs/VECTOR_PARAMETER_BINDING.md) for details.

### ORM Introspection
Full catalog support for Prisma, Drizzle, SQLAlchemy. Automatic schema mapping (`public` ↔ `SQLUser`).
See [PG_CATALOG.md](docs/PG_CATALOG.md) for implementation details.

### Enterprise Authentication
OAuth 2.0, IRIS Wallet, SCRAM-SHA-256. Industry-standard security.
See [DEPLOYMENT.md](docs/DEPLOYMENT.md#authentication) for configuration.

### Performance
~4ms protocol overhead, async Python, connection pooling.
See [PERFORMANCE.md](docs/PERFORMANCE.md) for benchmarks.
```

**Documentation Links (20 lines)** - Reorganize by category
```markdown
## Documentation

### Getting Started
- [Installation Guide](docs/INSTALLATION.md)
- [Quick Start Examples](docs/QUICKSTART_EXAMPLES.md)
- [BI Tools Setup](docs/BI_TOOLS.md)

### Features
- [pgvector Support](docs/VECTOR_PARAMETER_BINDING.md)
- [ORM Catalog Support](docs/PG_CATALOG.md)
- [Authentication](docs/DEPLOYMENT.md#authentication)

### Architecture & Performance
- [System Architecture](docs/ARCHITECTURE.md)
- [Performance Benchmarks](docs/PERFORMANCE.md)
- [Testing Guide](docs/testing.md)
```

**Production Ready (15 lines)** - Keep summary
```markdown
## Production Ready

**171/171 tests passing** across 8 languages

✅ PostgreSQL wire protocol v3 (simple & extended query)
✅ Authentication (OAuth 2.0, IRIS Wallet, SCRAM-SHA-256)
✅ Vectors (pgvector operators, HNSW indexes)
✅ ORM Support (Prisma, Drizzle, SQLAlchemy introspection)

See [PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md) and [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)
```

**Contributing (20 lines)** - Keep as-is

**Links (7 lines)** - Keep as-is

**License (4 lines)** - Keep as-is

**TOTAL: ~278 lines** ✅ Under 300 target

#### MOVE to Documentation

**Usage Examples (73 lines)** → `docs/QUICKSTART_EXAMPLES.md`
- Consolidate command-line, psycopg3, async SQLAlchemy examples
- Add more language examples (Node.js, Java, Go)

**Authentication Details (19 lines)** → Already in `docs/DEPLOYMENT.md`
- Remove duplication

**BI & Analytics (55 lines)** → `docs/BI_TOOLS.md`
- Consolidate with `examples/BI_TOOLS_SETUP.md`
- Add step-by-step setup guides

**Performance Benchmarks (21 lines)** → Already in `docs/PERFORMANCE.md`
- Remove duplication

**Architecture Diagrams (43 lines)** → `docs/ARCHITECTURE.md`
- Consolidate with `docs/DUAL_PATH_ARCHITECTURE.md`

**Installation Details (66 lines)** → `docs/INSTALLATION.md`
- Expand Docker, ZPM, pip, embedded Python guides

**Testing (45 lines)** → Already in `docs/testing.md`
- Remove duplication

**Roadmap (76 lines)** → `docs/ROADMAP.md`
- Move all completed features and future plans

---

## 2. pg_catalog Implementation Details

### CRITICAL ERROR IN README

**Line 625** states:
```markdown
- **System catalogs**: `pg_type`, `pg_catalog` not available (IRIS uses INFORMATION_SCHEMA)
```

**THIS IS INCORRECT** as of Feature 031 (merged PR #6) and Feature 033 (merged PR #8).

### Supported pg_catalog Tables

PGWire implements **6 core catalog tables** for ORM introspection:

#### pg_class (Tables/Views/Indexes)
**Source**: `src/iris_pgwire/catalog/pg_class.py`
- **Purpose**: Emulates PostgreSQL `pg_catalog.pg_class` system table
- **Maps from**: `INFORMATION_SCHEMA.TABLES` (IRIS)
- **Supports**: Tables (relkind='r'), Views (relkind='v'), Indexes (relkind='i')
- **Key Fields**: oid, relname, relnamespace, relkind, relnatts, relhasindex
- **ORM Usage**: Prisma uses this to discover tables/views during introspection
- **Limitations**: None - full PostgreSQL compatibility

#### pg_attribute (Columns)
**Source**: `src/iris_pgwire/catalog/pg_attribute.py`
- **Purpose**: Provides column metadata for ORM introspection
- **Maps from**: `INFORMATION_SCHEMA.COLUMNS` (IRIS)
- **Key Fields**: attrelid (table OID), attname, atttypid, attnum, attnotnull, atthasdef
- **Type Mapping**: 18 IRIS types → PostgreSQL type OIDs (e.g., VARCHAR→1043, INTEGER→23)
- **ORM Usage**: Prisma/Drizzle use this to discover column names, types, nullability
- **Limitations**: Type modifier calculation for VARCHAR(n), NUMERIC(p,s) fully supported

#### pg_constraint (Primary Keys, Foreign Keys, Unique, Check)
**Source**: `src/iris_pgwire/catalog/pg_constraint.py`
- **Purpose**: Constraint metadata for ORM relationship discovery
- **Maps from**: `INFORMATION_SCHEMA.TABLE_CONSTRAINTS`, `KEY_COLUMN_USAGE`, `REFERENTIAL_CONSTRAINTS`
- **Supported Types**: Primary Key (contype='p'), Foreign Key ('f'), Unique ('u'), Check ('c')
- **Key Fields**: oid, conname, contype, conrelid, confrelid, conkey (column positions)
- **ORM Usage**: Prisma uses this to discover relationships between tables
- **Limitations**: CHECK constraint expressions return placeholder "CHECK ((expression))"

#### pg_index (Index Metadata)
**Source**: `src/iris_pgwire/catalog/pg_index.py`
- **Purpose**: Index details for query optimization hints
- **Maps from**: Generated from PRIMARY KEY and UNIQUE constraints (IRIS doesn't expose indexes in INFORMATION_SCHEMA)
- **Key Fields**: indexrelid, indrelid, indisunique, indisprimary, indkey (column positions)
- **ORM Usage**: Prisma uses this to discover which columns are indexed
- **Limitations**: Only generates indexes for PK/UNIQUE constraints, not standalone CREATE INDEX

#### pg_namespace (Schemas)
**Source**: `src/iris_pgwire/catalog/pg_namespace.py`
- **Purpose**: Schema/namespace metadata
- **Static Namespaces**:
  - `pg_catalog` (OID 11)
  - `public` (OID 2200) → maps to IRIS `SQLUser`
  - `information_schema` (OID 11323)
- **Key Fields**: oid, nspname, nspowner
- **ORM Usage**: ORMs expect tables in "public" schema, PGWire maps to configurable IRIS schema
- **Limitations**: None - uses PostgreSQL standard OIDs

#### pg_attrdef (Column Defaults)
**Source**: `src/iris_pgwire/catalog/pg_attrdef.py`
- **Purpose**: Column default value expressions
- **Maps from**: `INFORMATION_SCHEMA.COLUMNS` (COLUMN_DEFAULT)
- **Key Fields**: oid, adrelid, adnum, adbin (default expression)
- **Default Translation**:
  - `$IDENTITY` → `nextval('table_column_seq'::regclass)`
  - `CURRENT_TIMESTAMP` → PostgreSQL equivalent
  - String/numeric literals preserved
- **ORM Usage**: Prisma uses this to detect auto-increment columns
- **Limitations**: None

### Supported Catalog Functions (Feature 033)

**Source**: `src/iris_pgwire/catalog/catalog_functions.py`

PGWire implements **5 PostgreSQL catalog functions** for transparent ORM support:

#### format_type(type_oid, typmod)
- **Purpose**: Convert type OID to human-readable name (e.g., 1043+259 → "character varying(255)")
- **Supports**: varchar(n), char(n), numeric(p,s), timestamp(p), bit(n)
- **ORM Usage**: Drizzle, Prisma use this to display column types
- **Returns**: `"integer"`, `"character varying(255)"`, `"numeric(10,2)"`, etc.

#### pg_get_constraintdef(constraint_oid, pretty?)
- **Purpose**: Get constraint definition as SQL (e.g., "PRIMARY KEY (id)")
- **Supports**: PK, FK, UNIQUE, CHECK constraints
- **Returns**: `"PRIMARY KEY (id)"`, `"FOREIGN KEY (author_id) REFERENCES users(id)"`, etc.
- **ORM Usage**: Schema inspection tools display constraint definitions

#### pg_get_serial_sequence(table, column)
- **Purpose**: Get sequence name for auto-increment columns
- **Detects**: IRIS `$IDENTITY` or `IS_IDENTITY='YES'`
- **Returns**: `"public.users_id_seq"` or NULL
- **ORM Usage**: Drizzle/Prisma detect serial columns

#### pg_get_indexdef(index_oid, column?, pretty?)
- **Purpose**: Get CREATE INDEX statement or column name
- **Returns**: `"CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)"`
- **ORM Usage**: Migration tools generate index DDL

#### pg_get_viewdef(view_oid, pretty?)
- **Purpose**: Get view definition SQL
- **Status**: Intentionally returns NULL (out of scope for initial implementation)
- **Rationale**: View introspection rarely needed for ORMs

### OID Generation

**Source**: `src/iris_pgwire/catalog/oid_generator.py`

- **Deterministic**: Same schema.table.column always generates same OID
- **Algorithm**: SHA-256 hash of `schema:object_type:object_name` → 32-bit unsigned int
- **Collision Handling**: Birthday paradox - low probability for typical schemas
- **Usage**: Ensures consistent OID references across pg_class, pg_attribute, pg_constraint

### Router and Query Detection

**Source**: `src/iris_pgwire/catalog/catalog_router.py`

- **Query Detection**: Regex patterns for `pg_catalog.*`, `pg_*`, `information_schema.*`
- **Array Parameter Translation**: `ANY($1)` → `IN (value1, value2, ...)`
- **regclass Resolution**: `'tablename'::regclass` → resolved OID
- **Catalog Tables Recognized**: pg_class, pg_namespace, pg_attribute, pg_constraint, pg_index, pg_attrdef, pg_type, pg_proc, pg_description, pg_depend, pg_am, pg_collation, pg_database, pg_enum, pg_extension, pg_foreign_table, pg_inherits, pg_roles, pg_settings, pg_stat_user_tables, pg_trigger, pg_views

### Limitations and Incompatibilities

1. **pg_type**: Not fully implemented - uses type_mapping.py for OID lookups
2. **CHECK Constraints**: Expression text returns placeholder `"CHECK ((expression))"`
3. **Index Discovery**: Only generates indexes for PK/UNIQUE constraints (IRIS doesn't expose standalone indexes)
4. **View Definitions**: `pg_get_viewdef()` returns NULL (out of scope)
5. **System Metadata**: pg_proc, pg_description, pg_depend, etc. not yet implemented (ORMs don't typically query these)

### Testing Coverage

- **Feature 031**: Full CRUD with Prisma ORM (PR #6)
- **Feature 033**: Catalog function validation (PR #8)
- **Drizzle ORM**: Example in `examples/drizzle-iris-demo/`
- **Prisma**: Example in `examples/prisma-iris-demo/`

### Performance

- **Query Routing**: Catalog queries bypass IRIS, return emulated data directly
- **Overhead**: <1ms for pg_class/pg_attribute queries (in-memory emulation)
- **Caching**: OIDGenerator caches computed OIDs

---

## 3. Existing Documentation Analysis

### Documentation Inventory (51 files)

#### Architecture & Development (8 files)
1. `api_documentation.md` - API reference
2. `developer_guide.md` - Development setup
3. `DEVELOPMENT.md` - Environment setup
4. `DUAL_PATH_ARCHITECTURE.md` - DBAPI vs Embedded execution
5. `EMBEDDED_PYTHON_SERVERS_HOWTO.md` - Running inside IRIS
6. `iris_pgwire_plan.md` - Original project plan
7. `IRIS_CONSTRUCTS_IMPLEMENTATION.md` - IRIS-specific features
8. `IRIS_SPECIAL_CONSTRUCTS.md` - Special syntax handling

#### Client Compatibility (2 files)
9. `CLIENT_RECOMMENDATIONS.md` - PostgreSQL client matrix
10. `ADDITIONAL_CLIENT_RECOMMENDATIONS.md` - Extended compatibility notes

#### Performance & Testing (4 files)
11. `PERFORMANCE.md` - Benchmark results
12. `testing.md` - Test framework
13. `COPY_PERFORMANCE_INVESTIGATION.md` - COPY protocol analysis
14. `HNSW_FINDINGS_2025_10_02.md` - Vector index performance

#### Deployment & Production (5 files)
15. `DEPLOYMENT.md` - Installation & configuration
16. `PRODUCTION_DEPLOYMENT.md` - Production checklist
17. `README-DEPLOYMENT.md` - Deployment quickstart
18. `IRIS_ENTERPRISE_SETUP_GUIDE.md` - Enterprise deployment
19. `PRE_COMMIT_SETUP.md` - Git hooks configuration

#### Features & Compatibility (6 files)
20. `VECTOR_PARAMETER_BINDING.md` - High-dimensional vector support
21. `DBAPI_BACKEND.md` - Connection pooling
22. `POSTGRESQL_COMPATIBILITY.md` - PostgreSQL feature matrix
23. `PROTOCOL_COMPLETENESS_AUDIT.md` - Wire protocol coverage
24. `SQLALCHEMY_ASYNC_SUPPORT.md` - Async ORM support
25. `ASYNC_SQLALCHEMY_QUICKSTART.md` - FastAPI integration

#### IRIS Integration (7 files)
26. `INTEGRATEDML_ANALYSIS.md` - ML feature research
27. `INTEGRATEDML_CONFIGURATION.md` - ML setup
28. `INTEGRATEDML_SUPPORT.md` - ML implementation status
29. `IRIS_DBAPI_LIMITATIONS_JIRA.md` - Known IRIS DBAPI issues
30. `IRIS_DOCUMENT_DATABASE_RESEARCH.md` - JSON/Document store
31. `IRIS_SQL_ANALYSIS.md` - SQL dialect analysis
32. `INTERSYSTEMS_PACKAGE_NAMING_ISSUE.md` - pip vs import naming

#### Investigation & Troubleshooting (10 files)
33. `ASYNCPG_FINAL_STATUS.md` - asyncpg compatibility resolution
34. `ASYNCPG_FIX_SUMMARY.md` - asyncpg bug fixes
35. `ASYNCPG_PARAMETER_TYPE_INVESTIGATION.md` - Type handling deep-dive
36. `COLUMN_ALIAS_INVESTIGATION.md` - SQL alias handling
37. `DEBUGGING_INVESTIGATION_2025_10_03.md` - Debug session notes
38. `HNSW_INVESTIGATION.md` - Vector index research
39. `KERBEROS_TROUBLESHOOTING.md` - Kerberos auth issues
40. `OAUTH_TROUBLESHOOTING.md` - OAuth 2.0 debugging
41. `WALLET_TROUBLESHOOTING.md` - IRIS Wallet issues
42. `TRANSLATION_API.md` - Query translation internals

#### Integrations & Strategy (6 files)
43. `LANGCHAIN_INTEGRATION.md` - LangChain usage patterns
44. `REST_API_STRATEGY.md` - REST API considerations
45. `COMPETITIVE_ANALYSIS.md` - Alternative solutions comparison
46. `confidence_analysis_api.md` - Confidence scoring
47. `RECENT_DEVELOPMENTS.md` - Changelog/updates
48. `RESEARCH_BACKLOG.md` - Future research topics

#### Release & Publishing (2 files)
49. `PYPI_RELEASE.md` - PyPI packaging
50. `presentations/speckit-internal-talk.md` - Internal presentation

#### Community Content (1 file)
51. `articles/developer-community-article.md` - Developer community article

### New Documentation Needed

Based on README reorganization, create **8 new documentation files**:

1. **HIGH PRIORITY: `PG_CATALOG.md`** (NEW)
   - Fixes incorrect README line 625
   - Documents all 6 catalog tables (pg_class, pg_attribute, pg_constraint, pg_index, pg_namespace, pg_attrdef)
   - Documents 5 catalog functions (format_type, pg_get_constraintdef, etc.)
   - Explains ORM introspection support (Prisma, Drizzle, SQLAlchemy)
   - Includes OID generation algorithm
   - Migration note from README

2. **`INSTALLATION.md`** (NEW)
   - Consolidate Quick Start from README
   - Expand Docker setup (compose profiles, environment variables)
   - Expand ZPM installation (IRIS 2024.1+, Service management)
   - Expand pip installation (virtualenv, dependencies)
   - Embedded Python deployment (production best practices)
   - Troubleshooting common installation issues

3. **`QUICKSTART_EXAMPLES.md`** (NEW)
   - Move Usage Examples section from README
   - Expand to all 8 supported languages:
     - Python (psycopg3, asyncpg, SQLAlchemy sync/async)
     - Node.js (pg, Prisma, Sequelize)
     - Java (JDBC, Spring Data JPA)
     - .NET (Npgsql, Entity Framework)
     - Go (pgx, GORM)
     - Ruby (pg gem, ActiveRecord)
     - Rust (tokio-postgres, sqlx)
     - PHP (PDO, Laravel)
   - Vector search examples per language
   - Common error patterns

4. **`ARCHITECTURE.md`** (NEW)
   - Consolidate Architecture section from README
   - Merge content from `DUAL_PATH_ARCHITECTURE.md`
   - High-level system diagram
   - Component breakdown (protocol layer, query translation, executor)
   - Data flow diagrams
   - Design decisions (SSL delegation, Kerberos exclusion)

5. **`BI_TOOLS.md`** (NEW)
   - Consolidate BI & Analytics section from README
   - Merge content from `examples/BI_TOOLS_SETUP.md`
   - Step-by-step setup for Apache Superset
   - Step-by-step setup for Metabase
   - Step-by-step setup for Grafana
   - Connection string templates
   - Common dashboard patterns
   - Vector analytics in BI tools

6. **`FEATURES_OVERVIEW.md`** (NEW)
   - Expand Key Features section from README
   - pgvector operations (detailed operator support)
   - ORM introspection (catalog implementation)
   - Schema mapping (public ↔ SQLUser)
   - Authentication methods (OAuth, Wallet, SCRAM)
   - Performance characteristics (overhead, pooling)
   - Async Python support (FastAPI, async SQLAlchemy)

7. **`ROADMAP.md`** (NEW)
   - Move Roadmap section from README
   - Completed features (with PR links)
   - In-progress features (with GitHub issues)
   - Future enhancements (prioritized backlog)
   - Known limitations (with workarounds)
   - Community requests tracking

8. **`PRODUCTION_CHECKLIST.md`** (NEW)
   - Expand Production Ready section
   - Pre-deployment checklist (security, performance, monitoring)
   - Deployment patterns (Docker, K8s, IRIS embedded)
   - Connection pooling configuration (pgBouncer integration)
   - Monitoring and observability (logging, metrics)
   - Disaster recovery (backup strategies)
   - Performance tuning (query optimization, indexing)

### Consolidation Opportunities

These existing docs overlap and should be merged:

1. **Merge into `ARCHITECTURE.md`**:
   - `DUAL_PATH_ARCHITECTURE.md` → Architecture patterns
   - `EMBEDDED_PYTHON_SERVERS_HOWTO.md` → Embedded deployment section
   - `iris_pgwire_plan.md` → Historical reference (archive?)

2. **Merge into `DEPLOYMENT.md`**:
   - `PRODUCTION_DEPLOYMENT.md` → Production section
   - `README-DEPLOYMENT.md` → Quickstart section
   - `IRIS_ENTERPRISE_SETUP_GUIDE.md` → Enterprise section

3. **Merge into `CLIENT_COMPATIBILITY.md`**:
   - `ADDITIONAL_CLIENT_RECOMMENDATIONS.md` → Extended notes section

4. **Merge into `PERFORMANCE.md`**:
   - `COPY_PERFORMANCE_INVESTIGATION.md` → COPY protocol section
   - `HNSW_FINDINGS_2025_10_02.md` → Vector performance section
   - `HNSW_INVESTIGATION.md` → Index investigation archive

5. **Archive to `docs/archive/` (historical investigations)**:
   - `ASYNCPG_FINAL_STATUS.md`
   - `ASYNCPG_FIX_SUMMARY.md`
   - `ASYNCPG_PARAMETER_TYPE_INVESTIGATION.md`
   - `COLUMN_ALIAS_INVESTIGATION.md`
   - `DEBUGGING_INVESTIGATION_2025_10_03.md`

6. **Consolidate troubleshooting into `TROUBLESHOOTING.md`** (NEW):
   - `KERBEROS_TROUBLESHOOTING.md` → Kerberos section
   - `OAUTH_TROUBLESHOOTING.md` → OAuth section
   - `WALLET_TROUBLESHOOTING.md` → IRIS Wallet section
   - Add common error patterns section
   - Add diagnostic commands section

---

## 4. Link Strategy

### Absolute URL Pattern

**Recommended pattern for all documentation links**:
```
https://github.com/intersystems-community/iris-pgwire/blob/main/docs/FILENAME.md
```

### Cross-Platform Testing Results

✅ **GitHub**: Native rendering with table of contents
✅ **PyPI**: Converts to absolute URL, images require raw.githubusercontent.com
✅ **Docker Hub**: Basic Markdown rendering, limited styling

### URL Component Breakdown

```
https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md
│                                                    │    │    │    └─ Filename
│                                                    │    │    └─ Directory
│                                                    │    └─ Branch (always 'main')
│                                                    └─ GitHub path format
└─ Base URL
```

### Link Examples

**Documentation links in README**:
```markdown
See [PG_CATALOG.md](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md)
```

**Cross-doc links** (relative for faster navigation on GitHub):
```markdown
See [Performance Guide](./PERFORMANCE.md) for benchmarks.
```

**Root-level files** (LICENSE, CONTRIBUTING.md):
```markdown
See [LICENSE](https://github.com/intersystems-community/iris-pgwire/blob/main/LICENSE)
```

### Best Practices

1. **Use absolute URLs for README → docs** (works on PyPI)
2. **Use relative URLs within docs/** (faster GitHub navigation)
3. **Anchor links for sections**: `#heading-name` (lowercase, hyphenated)
4. **Images**: Use `https://raw.githubusercontent.com/...` for PyPI compatibility
5. **Examples**: Link to `examples/` directory for live code

---

## Recommendations

### Target README Structure (278 lines)

```markdown
# iris-pgwire: PostgreSQL Wire Protocol for InterSystems IRIS
[badges] (7 lines)

## Why This Matters (12 lines)
[value proposition, ecosystem list]

## Quick Start (60 lines)
[Docker, Python package, ZPM, first query]

## Client Compatibility (20 lines)
[compatibility table + link to full matrix]

## Key Features (40 lines)
[4 features: pgvector, ORM, auth, performance - summaries only]

## Documentation (20 lines)
[organized link directory]

## Production Ready (15 lines)
[test count, feature checklist, links]

## Contributing (20 lines)
[setup, code quality tools]

## Links (7 lines)
[repo, IRIS docs, PostgreSQL, pgvector]

## License (4 lines)
[MIT license]

---
**Total**: 278 lines ✅
```

### Priority Documentation Files

**IMMEDIATE (fixes README error)**:
1. ✅ **PG_CATALOG.md** - Documents Feature 031/033, corrects line 625

**HIGH (README reorganization dependencies)**:
2. ✅ **INSTALLATION.md** - Expands Quick Start
3. ✅ **QUICKSTART_EXAMPLES.md** - Multi-language examples
4. ✅ **FEATURES_OVERVIEW.md** - Feature deep-dives
5. ✅ **ARCHITECTURE.md** - Consolidates architecture docs

**MEDIUM (enhanced user experience)**:
6. ✅ **BI_TOOLS.md** - Step-by-step BI setup
7. ✅ **ROADMAP.md** - Feature tracking
8. ✅ **PRODUCTION_CHECKLIST.md** - Deployment guidance

**LOW (consolidation)**:
9. ⚠️ **TROUBLESHOOTING.md** - Merge troubleshooting docs
10. ⚠️ Archive historical investigation docs to `docs/archive/`

### Migration Strategy

**Phase 1: Create New Docs** (Days 1-2)
- Write PG_CATALOG.md (HIGH - fixes README error)
- Write INSTALLATION.md
- Write QUICKSTART_EXAMPLES.md
- Write FEATURES_OVERVIEW.md

**Phase 2: Reorganize README** (Day 3)
- Trim README to 278 lines
- Update all links to new docs
- Add "Documentation" directory section
- Remove duplicated content

**Phase 3: Consolidation** (Days 4-5)
- Write ARCHITECTURE.md (merge 3 docs)
- Write BI_TOOLS.md (merge 2 docs)
- Write ROADMAP.md
- Write PRODUCTION_CHECKLIST.md

**Phase 4: Cleanup** (Day 6)
- Archive investigation docs
- Update DEPLOYMENT.md (merge 3 docs)
- Update CLIENT_COMPATIBILITY.md (merge 2 docs)
- Create TROUBLESHOOTING.md

**Phase 5: Validation** (Day 7)
- Test all links (GitHub, PyPI, local)
- Verify PyPI rendering
- Check for broken cross-references
- Update CONTRIBUTING.md with new doc structure

### Content Guidelines

**README Should**:
- ✅ Answer "What is this?" in 30 seconds
- ✅ Show "How do I start?" in 60 seconds
- ✅ Prove "Does it work?" with test count
- ✅ Link to "Where do I learn more?"
- ❌ NOT explain architecture details
- ❌ NOT duplicate documentation
- ❌ NOT show extensive code examples

**Documentation Should**:
- ✅ Deep-dive into specific topics
- ✅ Include step-by-step guides
- ✅ Show complete code examples
- ✅ Link to related docs (breadcrumbs)
- ✅ Include troubleshooting sections
- ✅ Reference GitHub issues/PRs for context

### Quality Checklist

For each new documentation file:
- [ ] Frontmatter with title, date, status
- [ ] Table of contents (for >100 lines)
- [ ] Code examples with syntax highlighting
- [ ] Cross-references to related docs
- [ ] Troubleshooting section (if applicable)
- [ ] Links tested on GitHub preview
- [ ] Markdown linter passed (markdownlint)
- [ ] No broken internal links
- [ ] Images use raw.githubusercontent.com URLs
- [ ] Consistent heading structure (H1 → H2 → H3)

---

## Conclusion

**Current State**: README is comprehensive but overwhelming (675 lines)

**Target State**: README is concise landing page (278 lines), detailed content in 59 docs

**Critical Fix Required**: Line 625 incorrectly claims "pg_catalog not available" - Feature 031/033 implemented full catalog support

**Action Items**:
1. Create `PG_CATALOG.md` immediately to document catalog implementation
2. Create 7 additional docs to support README reorganization
3. Trim README to 278 lines, moving content to appropriate docs
4. Consolidate 15 overlapping docs into unified guides
5. Archive 5 historical investigation docs
6. Test all links across GitHub, PyPI, Docker Hub

**Expected Outcome**:
- Faster onboarding (60-second Quick Start preserved)
- Better discoverability (organized doc directory)
- Accurate technical documentation (pg_catalog fully documented)
- Reduced maintenance burden (no duplication)
- Professional project presentation (clean, focused README)
