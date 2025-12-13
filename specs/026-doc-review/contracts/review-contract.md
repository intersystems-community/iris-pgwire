# Documentation Review Contract

**Feature**: 026-doc-review
**Date**: 2024-12-12

## Purpose

This contract defines the acceptance criteria and validation methods for the documentation review process.

## Contract: README.md Review

### Input
- File: `/README.md`
- Current size: ~16KB, 526 lines

### Acceptance Criteria

| ID | Criterion | Validation Method |
|----|-----------|-------------------|
| R-001 | Value proposition clear in first 30 seconds | Human review: can reader explain purpose? |
| R-002 | Quick Start works in 60 seconds | Timed execution of Docker commands |
| R-003 | All code examples execute | Manual smoke test each example |
| R-004 | All external links valid | HTTP HEAD request to each URL |
| R-005 | Performance claims verifiable | Cross-reference with benchmarks/ |
| R-006 | Tone is professional | Human review against tone checklist |

### Output
- List of issues found (if any)
- Corrected README.md (if changes needed)

---

## Contract: KNOWN_LIMITATIONS.md Review

### Input
- File: `/KNOWN_LIMITATIONS.md`
- Current size: ~14KB

### Acceptance Criteria

| ID | Criterion | Validation Method |
|----|-----------|-------------------|
| K-001 | Industry comparison accurate | Verify against cited sources |
| K-002 | Limitations match implementation | Cross-reference with source code |
| K-003 | Context provided for decisions | Human review: are rationales clear? |
| K-004 | No defensive language | Human review against tone checklist |
| K-005 | References are current | Check dates, versions, links |

### Output
- List of issues found (if any)
- Corrected KNOWN_LIMITATIONS.md (if changes needed)

---

## Contract: docs/ Directory Review

### Input
- Directory: `/docs/`
- File count: 50 files
- File types: .md, .yaml

### Acceptance Criteria

| ID | Criterion | Validation Method |
|----|-----------|-------------------|
| D-001 | Each file categorized | Review and tag as user-facing or internal |
| D-002 | User-facing docs accurate | Manual review per file |
| D-003 | Internal docs archived | Move to docs/archive/ or remove |
| D-004 | Terminology consistent | Grep for variant terms |
| D-005 | No broken internal links | Check all `](` references |
| D-006 | Code examples work | Smoke test where applicable |

### Output
- Categorized file list
- Archive of internal documents
- List of issues per file
- Corrected files (if changes needed)

---

## Contract: Root Directory Cleanup

### Input
- Directory: `/` (repo root)
- Current non-essential files: 6

### Acceptance Criteria

| ID | Criterion | Validation Method |
|----|-----------|-------------------|
| ROOT-001 | Only essential files in root | ls comparison against allowed list |
| ROOT-002 | Relocated files work | Verify no broken references |
| ROOT-003 | Git history preserved | Use git mv for relocations |

### Essential Files Allowed in Root
```
README.md
LICENSE
CHANGELOG.md
KNOWN_LIMITATIONS.md
pyproject.toml
pytest.ini
MANIFEST.in
Dockerfile
Dockerfile.test
docker-compose.yml
docker-compose.prod.yml
.gitignore
.bandit
.bumpversion.cfg
uv.lock
```

### Files to Relocate
```
interrogate_badge.svg → .github/badges/
test_performance_simple.py → tests/performance/
merge.cpf → docker/
start-production.sh → scripts/
```

### Files to Review
```
iris.key - Verify if needed publicly
iris_pgwire.json - IPM manifest, keep if needed
```

### Output
- Cleaned root directory
- Updated references (if any broken by moves)

---

## Contract: Terminology Consistency

### Input
- All markdown files in repo

### Acceptance Criteria

| ID | Criterion | Validation Method |
|----|-----------|-------------------|
| T-001 | "IRIS PGWire" used consistently | Grep for variants |
| T-002 | "PostgreSQL" not "Postgres" | Grep for variants |
| T-003 | "SCRAM-SHA-256" formatted correctly | Grep for variants |
| T-004 | "OAuth 2.0" includes version | Grep for variants |

### Output
- List of terminology violations
- Corrected files

---

## Validation Commands

```bash
# Link validation (basic)
grep -roh 'https://[^)]*' docs/ README.md KNOWN_LIMITATIONS.md | sort -u

# Terminology check: IRIS PGWire variants
grep -ri "pgwire\|pg-wire\|pg wire" --include="*.md" .

# Terminology check: PostgreSQL variants
grep -ri "postgres[^ql]" --include="*.md" .

# Find internal doc references
grep -roh '\[.*\](.*\.md)' docs/ README.md | grep -v 'http'

# List root directory files
ls -la | grep -v "^d" | awk '{print $NF}'
```
