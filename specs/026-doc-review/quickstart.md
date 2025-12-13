# Quickstart: Documentation Review Process

**Feature**: 026-doc-review
**Date**: 2024-12-12

## Overview

This guide outlines the process for reviewing IRIS PGWire documentation for clarity, tone, and accuracy.

## Prerequisites

- Docker installed (for testing Quick Start examples)
- Python 3.11+ with psycopg3, SQLAlchemy
- Access to repository at `/Users/tdyar/ws/iris-pgwire-gh`
- Internet connection (for link validation)

## Review Process

### Phase 1: README.md Review

1. **First Impression Test**
   - Read first 3 sentences
   - Can you explain what IRIS PGWire does?
   - Is the value proposition clear?

2. **Quick Start Validation**
   ```bash
   cd /Users/tdyar/ws/iris-pgwire-gh
   docker-compose up -d
   # Time this - should complete in ~60 seconds
   psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Hello from IRIS!'"
   ```

3. **Code Example Testing**
   - Copy each Python example
   - Run in isolated environment
   - Document any failures

4. **Link Validation**
   - Check all external links (GitHub, docs.intersystems.com, etc.)
   - Verify internal doc references exist

### Phase 2: KNOWN_LIMITATIONS.md Review

1. **Accuracy Check**
   - Verify industry comparison table against cited sources
   - Confirm limitations match actual implementation
   - Check dates/versions are current

2. **Tone Assessment**
   - Informative, not defensive
   - Context provided for decisions
   - Professional language

### Phase 3: docs/ Directory Review

For each file:

1. **Categorize**
   - User-facing guide → Review
   - Internal/research → Consider archiving

2. **Review Checklist**
   - [ ] Title/purpose clear
   - [ ] Code examples work (if any)
   - [ ] Links valid
   - [ ] Terminology consistent
   - [ ] No outdated information
   - [ ] Professional tone

### Phase 4: Root Directory Cleanup

1. **Audit Files**
   ```bash
   ls -la /Users/tdyar/ws/iris-pgwire-gh/ | grep -v "^d"
   ```

2. **Execute Relocations**
   - Move badge to `.github/badges/`
   - Move test file to `tests/performance/`
   - Move shell script to `scripts/`
   - Move IRIS config to `docker/`

3. **Verify Essential Files Remain**
   - README.md, LICENSE, CHANGELOG.md
   - pyproject.toml, pytest.ini, MANIFEST.in
   - Dockerfile*, docker-compose*.yml
   - .gitignore, uv.lock

## Review Checklists

### Clarity Checklist
- [ ] Purpose stated in first paragraph
- [ ] Technical terms defined or linked
- [ ] Steps are numbered and sequential
- [ ] Examples provided for complex concepts

### Tone Checklist
- [ ] Professional language
- [ ] No defensive phrasing ("but we...", "however...")
- [ ] Confident without being arrogant
- [ ] Appropriate for enterprise audience

### Accuracy Checklist
- [ ] Code examples execute successfully
- [ ] Performance claims match benchmarks
- [ ] Links resolve correctly
- [ ] Version numbers current
- [ ] Feature descriptions match implementation

## Issue Tracking Template

```markdown
## Issue: [Brief Description]

**File**: [path/to/file.md]
**Line(s)**: [line numbers]
**Type**: [broken_link | broken_code | accuracy | clarity | tone | terminology | outdated]
**Severity**: [critical | major | minor]

### Description
[What is wrong]

### Expected
[What should be there]

### Resolution
[How to fix it]
```

## Completion Criteria

- [ ] All README.md code examples tested
- [ ] All external links validated
- [ ] All performance claims verified
- [ ] Quick Start works in stated timeframe
- [ ] Root directory contains only essential files
- [ ] docs/ internal files archived or removed
- [ ] Terminology consistent across all documents
- [ ] No defensive language in public docs
