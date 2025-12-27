# Quick Start: Contributing to Documentation

**Audience**: Contributors updating IRIS PGWire documentation
**Purpose**: Quick reference for documentation standards and workflows

---

## Documentation Update Workflow

### 1. Before Making Changes

```bash
# Check current README length
wc -l README.md
# Target: <300 lines

# List existing documentation
ls -1 docs/*.md | wc -l
# Current: 51 files

# Check for broken links (requires markdown-link-check)
npx markdown-link-check README.md
```

### 2. Creating New Documentation

**File naming**: `UPPERCASE_WITH_UNDERSCORES.md` (e.g., `PG_CATALOG.md`)

**Template**:
```markdown
# Title: Brief Description

**Last Updated**: YYYY-MM-DD
**Related**: Links to related docs

---

## Overview

[1-2 sentence description]

## [Major Section]

[Content]

### [Subsection]

[Content]

## See Also

- [Related Doc 1](FILENAME.md)
- [Related Doc 2](FILENAME.md)
```

### 3. Adding Content to README

**DON'T**:
- ❌ Add detailed explanations (move to docs/)
- ❌ Add long code examples (move to docs/)
- ❌ Add comprehensive guides (move to docs/)

**DO**:
- ✅ Keep summaries brief (1-3 sentences)
- ✅ Add links to detailed docs
- ✅ Verify README stays <300 lines

### 4. Link Format

**Always use absolute GitHub URLs**:
```markdown
❌ Wrong: [PG Catalog](docs/PG_CATALOG.md)
✅ Right: [PG Catalog](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md)
```

**Why absolute URLs**: PyPI converts markdown to HTML and breaks relative links

### 5. Testing Changes

```bash
# 1. Verify README length
wc -l README.md
# Must be <300

# 2. Check for broken links
npx markdown-link-check README.md docs/*.md

# 3. Preview on GitHub
git add README.md docs/
git commit -m "docs: ..."
git push origin feature-branch
# Open PR and check GitHub rendering

# 4. Test PyPI rendering (optional)
pip install twine
python -m build
twine check dist/*
# Upload to test.pypi.org to preview
```

---

## Style Guidelines

### Markdown Conventions

**Headings**:
```markdown
# H1: Document Title (one per file)
## H2: Major Sections
### H3: Subsections
#### H4: Rarely needed
```

**Code Blocks**:
```markdown
# Always specify language for syntax highlighting
\```bash
docker-compose up -d
\```

\```python
import psycopg
\```

\```sql
SELECT * FROM table;
\```
```

**Lists**:
```markdown
# Unordered lists
- Item 1
- Item 2
  - Nested item

# Ordered lists
1. First step
2. Second step
3. Third step
```

**Tables**:
```markdown
| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Value 1  | Value 2  | Value 3  |
```

**Links**:
```markdown
# External links
[InterSystems IRIS](https://www.intersystems.com/products/intersystems-iris/)

# Internal docs (ALWAYS absolute URLs)
[PG Catalog](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md)

# Anchor links
[Authentication Section](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md#authentication)
```

### Content Guidelines

**Keep README Scannable**:
```markdown
❌ Too detailed:
PostgreSQL wire protocol implementation for InterSystems IRIS provides
comprehensive support for the entire PostgreSQL ecosystem including...
[5 more paragraphs]

✅ Scannable:
**Access IRIS through the PostgreSQL ecosystem** - Connect BI tools, Python
frameworks, and data pipelines without custom drivers.
```

**Use Bullet Points**:
```markdown
❌ Paragraph form:
The system supports psycopg3, asyncpg, SQLAlchemy with both sync and async
modes, pandas for data analysis, and Jupyter notebooks. It also works with...

✅ Bullet points:
- **Python**: psycopg3, asyncpg, SQLAlchemy, pandas, Jupyter
- **Node.js**: pg (node-postgres), Prisma, Sequelize
- **Java**: PostgreSQL JDBC, Spring Data JPA, Hibernate
```

**Link to Details**:
```markdown
❌ All details in README:
Authentication supports three methods: OAuth 2.0 with token-based auth...
[20 lines of config examples]

✅ Summary with link:
**Authentication**: OAuth 2.0, IRIS Wallet, SCRAM-SHA-256
See [DEPLOYMENT.md](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md#authentication) for configuration.
```

### Code Example Guidelines

**Working Examples Only**:
```markdown
# All code examples MUST be tested and work

❌ Untested example:
\```python
import some_module
result = some_module.do_thing()  # Might not work
\```

✅ Verified example:
\```python
import psycopg

# Tested: 2025-12-27 on Python 3.11 + iris-pgwire 1.0.1
with psycopg.connect('host=localhost port=5432 dbname=USER') as conn:
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM YourTable')
    print(f'Rows: {cur.fetchone()[0]}')
\```
```

**Include Context**:
```markdown
# BAD: No context
\```sql
SELECT * FROM pg_class;
\```

# GOOD: Explain what it does
\```sql
-- Query pg_catalog to list all tables visible to Prisma/SQLAlchemy
SELECT relname FROM pg_class WHERE relkind = 'r';
\```
```

---

## Common Tasks

### Add New Documentation File

```bash
# 1. Create file in docs/
touch docs/NEW_FEATURE.md

# 2. Write content following template (see above)

# 3. Add link to README Documentation Index
# Edit README.md, add to appropriate category:
### Core Features
- [New Feature](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/NEW_FEATURE.md) - Brief description

# 4. Test and commit
wc -l README.md  # Verify <300
git add README.md docs/NEW_FEATURE.md
git commit -m "docs: Add NEW_FEATURE documentation"
```

### Update Existing Documentation

```bash
# 1. Edit file
vim docs/EXISTING.md

# 2. Update "Last Updated" date in file
**Last Updated**: 2025-12-27

# 3. If substantial changes, add note to README
# (No need to add link if already in Documentation Index)

# 4. Commit
git add docs/EXISTING.md
git commit -m "docs: Update EXISTING with new information"
```

### Fix Broken Links

```bash
# 1. Find broken links
npx markdown-link-check README.md docs/*.md

# 2. Fix each broken link (usually URL typos)
# Change relative to absolute:
# [Doc](docs/FILE.md) → [Doc](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/FILE.md)

# 3. Re-test
npx markdown-link-check README.md docs/*.md

# 4. Commit
git add README.md docs/
git commit -m "docs: Fix broken links"
```

### Condense README Section

```bash
# 1. Identify verbose section in README
# Example: "Architecture" section is 50 lines

# 2. Create detailed doc
touch docs/ARCHITECTURE.md
# Move detailed content from README to docs/ARCHITECTURE.md

# 3. Replace README section with summary + link
# Before (50 lines):
## Architecture
[detailed explanation]

# After (5 lines):
## Architecture
High-level overview with protocol layer, query translation, and backend execution.
See [ARCHITECTURE.md](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ARCHITECTURE.md) for details.

# 4. Verify line count reduction
wc -l README.md

# 5. Commit
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: Move architecture details to dedicated doc"
```

---

## Critical Documentation Files

### HIGH PRIORITY: PG_CATALOG.md

**Why Critical**: README line 625 incorrectly states "pg_catalog not available"

**Required Content**:
1. Overview: ORM introspection for Prisma, Drizzle, SQLAlchemy
2. Supported tables (6): pg_class, pg_attribute, pg_constraint, pg_index, pg_namespace, pg_attrdef
3. Supported functions (5): format_type(), pg_get_constraintdef(), pg_get_serial_sequence(), pg_get_indexdef(), pg_get_viewdef()
4. Limitations: What's NOT supported
5. Usage examples: Prisma introspection, SQLAlchemy reflection

**Source**: Analyze `src/iris_pgwire/catalog/` module

**README Fix**: Change line 625 to:
```markdown
- **System catalogs**: Partial pg_catalog support for ORM introspection - see [PG_CATALOG.md](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md)
```

---

## Quality Checklist

Before submitting documentation changes:

### README Specific
- [ ] Line count <300 (target: 278)
- [ ] All links are absolute GitHub URLs
- [ ] Quick Start section works (Docker, PyPI, ZPM)
- [ ] Documentation Index updated (if new file)
- [ ] No broken links (run markdown-link-check)

### New Documentation File
- [ ] Follows template structure (H1 title, H2 sections, H3 subsections)
- [ ] Code examples tested and working
- [ ] Language tags on code blocks (```bash, ```python, ```sql)
- [ ] Cross-references to related docs
- [ ] Added to README Documentation Index

### Content Quality
- [ ] Accurate (verified against code, no hallucinations)
- [ ] Clear (technical but accessible)
- [ ] Concise (no redundant explanations)
- [ ] Actionable (working examples, clear steps)

---

**Questions?** Check:
- [data-model.md](./data-model.md) - Documentation structure
- [research.md](./research.md) - Content categorization decisions
- [plan.md](./plan.md) - Overall reorganization strategy
