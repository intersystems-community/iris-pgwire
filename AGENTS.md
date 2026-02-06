# iris-pgwire-gh Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-01-17

## Active Technologies
- Python 3.11 + python>=3.11, psycopg[binary], iris-devtester, intersystems-irispython (026-address-gaps-in)
- PostgreSQL (via InterSystems IRIS) (026-address-gaps-in)
- Python 3.11 + intersystems-irispython, psycopg[binary], iris-devtester (034-issues-that-likely)
- InterSystems IRIS (via PostgreSQL wire protocol) (034-issues-that-likely)
- Python 3.11 + intersystems-irispython, psycopg[binary], iris-devtester (035-number-1-short)
- Python 3.11 + psycopg[binary], intersystems-irispython, iris-devtester (036-address-all-6)
- InterSystems IRIS (via pgwire) (036-address-all-6)
- Python 3.11 + psycopg[binary], intersystems-irispython, iris-devtester (036-address-all-6)
- Python 3.11+ + `intersystems-irispython`, `psycopg[binary]`, `pydantic`, `structlog` (037-pg-type-catalog)
- Python 3.11+ + `pydantic`, `structlog`, `intersystems-irispython` (038-fix-attribute-error)

- Python 3.11+ + `iris-devtester`, `intersystems-irispython`, `psycopg[binary]` (033-devtester-skills)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11+: Follow standard conventions

## Recent Changes
- 038-fix-attribute-error: Added Python 3.11+ + `pydantic`, `structlog`, `intersystems-irispython`
- 037-pg-type-catalog: Added Python 3.11+ + `intersystems-irispython`, `psycopg[binary]`, `pydantic`, `structlog`
- 036-address-all-6: Added Python 3.11 + psycopg[binary], intersystems-irispython, iris-devtester


<!-- MANUAL ADDITIONS START -->

## IRIS Technical Reference (Critical for DBAPI & Embedded)

### 1. DBAPI Connection Pattern (intersystems-irispython)
Always use this robust import pattern to obtain the DBAPI module. This handles different package versions and environment quirks.
```python
try:
    import iris.dbapi as iris_dbapi # Modern/Standard
except ImportError:
    try:
        import intersystems_iris.dbapi._DBAPI as iris_dbapi # Deep Fallback
    except ImportError:
        # Last resort: check if iris module itself has connect (older versions)
        import iris as iris_dbapi
```

### 2. Embedded SQL Execution (iris.sql.exec)
When running code inside IRIS (Embedded Python), parameters **MUST** be passed using the splat operator `*params` to be treated as positional arguments.
```python
# CORRECT
iris.sql.exec(sql, *params)

# INCORRECT (passes list as a single argument)
iris.sql.exec(sql, params) 
```

### 3. Case Sensitivity & Identifiers
- **Schema Name**: Always use `SQLUser` (exact casing). IRIS package/schema names are case-sensitive.
- **Quoted Identifiers**: Identifiers in double quotes (e.g., `"workflow"`) are case-sensitive in IRIS.
- **Unquoted Identifiers**: Automatically mapped to UPPERCASE by IRIS.
- **Normalization**: To ensure consistency, the normalizer should preserve the casing of quoted identifiers and map unquoted ones to uppercase, but it **MUST NOT** change the case of the `SQLUser` schema prefix.

<!-- MANUAL ADDITIONS END -->
---

## COMPOUND KNOWLEDGE BASE & DEVELOPMENT ENVIRONMENT

**Last Updated**: $(date +%Y-%m-%d)

> Central registry of development knowledge, tools, capabilities, and automation


### 📚 Knowledge Base

**Location**: `~/.config/opencode/compound-knowledge/`


**Structure**:
- `global/` - Project-agnostic knowledge (frameworks, tools, patterns)
- `projects/[name]/` - Project-specific knowledge (domain, architecture)

**Stats**: 7 solutions (7 global, 0 project)

**Quick Search**:
```bash
# Search everything
grep -ri "keywords" ~/.config/opencode/compound-knowledge/

# Global only
grep -ri "keywords" ~/.config/opencode/compound-knowledge/global/

# This project
grep -ri "keywords" ~/.config/opencode/compound-knowledge/projects/$(basename $(pwd))/
```

**Time Savings**: First solve: 30min → Next solve: 3min (90% faster)


### 🔌 MCP Servers

- `atlassian` - local
- `gemini-impl` - local
- `hallucination-detector` - local
- `jama` - local
- `perplexity` - local
- `playwright` - local
- `qwen-impl` - local
- `support-tools` - local

### 🤖 Automation & Hooks

**Orchestrator Behavior** (configured via `~/.config/opencode/oh-my-opencode-slim.json`):
- **Before tasks**: Search compound KB for similar solutions
- **After completion**: Remind to document solution

**Periodic Maintenance** (recommended):
```bash
# Weekly: Regenerate KB index
~/.config/opencode/compound-knowledge/generate-index.sh

# Monthly: Review and consolidate similar solutions
# Quarterly: Extract patterns from repeated solutions
```

**Auto-Documentation Triggers**:
- Tests pass after fixing failure → Document solution
- Error resolved → Document fix
- Performance improved → Document optimization
- Integration working → Document configuration


### 🛠️ Tools & Utilities

**Compound Engineering**:
- `~/.config/opencode/compound-knowledge/new-solution.sh` - Create solution doc
- `~/.config/opencode/compound-knowledge/generate-index.sh` - Regenerate index
- `~/.config/opencode/compound-knowledge/sync-to-agents.sh` - Update AGENTS.md files

**OpenCode Agents** (oh-my-opencode-slim):
- `orchestrator` - Master coordinator (with compound engineering)
- `explorer` - Codebase reconnaissance
- `oracle` - Strategic advisor
- `librarian` - External knowledge (websearch, context7, grep_app MCPs)
- `designer` - UI/UX implementation
- `fixer` - Fast implementation
- `code-simplifier` - Post-work code refinement


### 🎯 Skills

**speckit** (feature specification):
- `speckit.plan` - Implementation planning
- `speckit.specify` - Feature specification
- `speckit.tasks` - Task generation
- `speckit.implement` - Implementation guidance


### 📋 Quick Reference

**Full Index**: `~/.config/opencode/compound-knowledge/INDEX.md`

**Documentation Templates**:
```markdown
---
title: "Problem description"
category: [build-errors|test-failures|runtime-errors|performance-issues|
          database-issues|security-issues|ui-bugs|integration-issues|logic-errors]
date: YYYY-MM-DD
severity: high|medium|low
tags: [tag1, tag2]
time_to_solve: XXmin
---

## Problem Symptom
[What was observed]

## Solution
[How you fixed it]

## Prevention
[How to avoid future]
```

**Decision Tree** (Global vs Project-Specific):
- Framework/tool issue → `global/`
- General pattern → `global/`
- Project domain logic → `projects/[name]/`
- Project architecture → `projects/[name]/`
- When in doubt → `global/`

---

