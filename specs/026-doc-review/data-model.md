# Data Model: Documentation Review

**Feature**: 026-doc-review
**Date**: 2024-12-12

## Overview

This feature does not involve traditional data modeling (no database entities). Instead, this document defines the structure of documentation artifacts being reviewed and the review tracking schema.

## Documentation Artifact Types

### 1. Primary Documents

| Document | Location | Purpose | Review Priority |
|----------|----------|---------|-----------------|
| README.md | `/README.md` | Entry point, adoption driver | P1 - Critical |
| KNOWN_LIMITATIONS.md | `/KNOWN_LIMITATIONS.md` | Enterprise trust | P1 - Critical |

### 2. User-Facing Guides (docs/)

| Category | Files | Review Priority |
|----------|-------|-----------------|
| Deployment | DEPLOYMENT.md, PRODUCTION_DEPLOYMENT.md, README-DEPLOYMENT.md | P1 |
| Architecture | DUAL_PATH_ARCHITECTURE.md, EMBEDDED_PYTHON_SERVERS_HOWTO.md | P1 |
| Features | VECTOR_PARAMETER_BINDING.md, DBAPI_BACKEND.md | P1 |
| Integrations | LANGCHAIN_INTEGRATION.md, SQLALCHEMY_ASYNC_SUPPORT.md, ASYNC_SQLALCHEMY_QUICKSTART.md | P2 |
| Client Support | CLIENT_RECOMMENDATIONS.md, ADDITIONAL_CLIENT_RECOMMENDATIONS.md, POSTGRESQL_COMPATIBILITY.md | P2 |
| Development | developer_guide.md, DEVELOPMENT.md, PRE_COMMIT_SETUP.md, testing.md | P2 |
| Troubleshooting | OAUTH_TROUBLESHOOTING.md, WALLET_TROUBLESHOOTING.md, KERBEROS_TROUBLESHOOTING.md | P2 |
| IRIS Features | INTEGRATEDML_SUPPORT.md, INTEGRATEDML_CONFIGURATION.md, IRIS_CONSTRUCTS_IMPLEMENTATION.md, IRIS_SPECIAL_CONSTRUCTS.md | P3 |
| Performance | PERFORMANCE.md, COPY_PERFORMANCE_INVESTIGATION.md | P2 |

### 3. Internal/Research Documents (docs/)

These documents appear to be internal research/investigation notes rather than user documentation. Consider archiving or removing from public repo:

| File | Assessment |
|------|------------|
| ASYNCPG_FIX_SUMMARY.md | Internal - fix summary |
| ASYNCPG_FINAL_STATUS.md | Internal - status report |
| ASYNCPG_PARAMETER_TYPE_INVESTIGATION.md | Internal - investigation |
| COLUMN_ALIAS_INVESTIGATION.md | Internal - investigation |
| DEBUGGING_INVESTIGATION_2025_10_03.md | Internal - dated investigation |
| HNSW_FINDINGS_2025_10_02.md | Internal - dated findings |
| HNSW_INVESTIGATION.md | Internal - investigation |
| INTEGRATEDML_ANALYSIS.md | Internal - analysis |
| IRIS_DBAPI_LIMITATIONS_JIRA.md | Internal - JIRA reference |
| IRIS_DOCUMENT_DATABASE_RESEARCH.md | Internal - research |
| IRIS_SQL_ANALYSIS.md | Internal - analysis |
| INTERSYSTEMS_PACKAGE_NAMING_ISSUE.md | Internal - issue tracking |
| PROTOCOL_COMPLETENESS_AUDIT.md | Internal - audit |
| RESEARCH_BACKLOG.md | Internal - backlog |
| REST_API_STRATEGY.md | Internal - strategy |
| RECENT_DEVELOPMENTS.md | Internal - status |
| COMPETITIVE_ANALYSIS.md | Internal - competitive intel |

### 4. API Documentation (docs/)

| File | Purpose |
|------|---------|
| api_documentation.md | API reference |
| confidence_analysis_api.md | Confidence API |
| openapi_spec.yaml | OpenAPI specification |
| TRANSLATION_API.md | SQL translation API |

## Review Tracking Schema

### Document Review Record

```
DocumentReview:
  - file_path: string (relative to repo root)
  - review_status: enum [pending, in_progress, completed, archived]
  - issues_found: list of Issue
  - last_reviewed: datetime
  - reviewer_notes: string

Issue:
  - type: enum [broken_link, broken_code, accuracy, clarity, tone, terminology, outdated]
  - severity: enum [critical, major, minor]
  - location: string (line number or section)
  - description: string
  - resolution: string (nullable)
  - resolved: boolean
```

### Root Directory Audit Record

```
RootFileAudit:
  - file_name: string
  - disposition: enum [keep, relocate, remove, review]
  - target_location: string (nullable, for relocate)
  - rationale: string
```

## Terminology Glossary

To ensure consistency, these terms should be used uniformly:

| Canonical Term | Avoid | Notes |
|----------------|-------|-------|
| IRIS PGWire | PGWire, pgwire, Pgwire | Full product name |
| PostgreSQL | Postgres, postgres, PG | Except in code/config |
| wire protocol | Wire Protocol, wire-protocol | Lowercase |
| SCRAM-SHA-256 | SCRAM, scram-sha-256 | All caps with hyphen |
| OAuth 2.0 | OAuth, oauth, OAuth2 | Include version |
| IRIS Wallet | wallet, Wallet | Capitalize both |
| pgvector | PGVector, pgVector | All lowercase |
| HNSW | hnsw | All caps (algorithm name) |

## File Relocation Plan

### Root Directory Changes

| File | Action | Target | Rationale |
|------|--------|--------|-----------|
| interrogate_badge.svg | Move | `.github/badges/` | Badge belongs with CI artifacts |
| test_performance_simple.py | Move | `tests/performance/` | Test file belongs in tests |
| iris.key | Review | Keep or `.gitignore` | May be sensitive |
| iris_pgwire.json | Keep | Root | IPM manifest, common location |
| merge.cpf | Move | `docker/` | IRIS config for Docker |
| start-production.sh | Move | `scripts/` | Shell scripts directory |

### docs/ Directory Changes

| Action | Files | Target |
|--------|-------|--------|
| Archive | 17 internal/research docs | `docs/archive/` or remove |
| Keep | 33 user-facing docs | `docs/` (review for accuracy) |
