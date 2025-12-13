# IRIS PGWire Constitution

## Core Principles

### I. Authorship
All work is authored and owned by Thomas Dyar (thomas.dyar@intersystems.com).
Never attribute work to AI assistants (Claude Code, etc.) in commits, documentation, or code comments.

### II. Test-First
- TDD mandatory for new features
- Integration tests required for protocol changes
- All 171 tests must pass before merge

### III. PostgreSQL Compatibility
- Wire protocol v3 compliance
- Standard psycopg3/asyncpg clients must work unchanged
- pgvector syntax auto-translated to IRIS functions

### IV. Documentation Accuracy
- Code examples must be tested and working
- Performance claims must be backed by benchmarks
- No defensive language - present capabilities confidently

### V. Professional Presentation
- Root directory kept minimal and clean
- Internal/research docs archived, not in main docs/
- Consistent terminology throughout

## Technology Stack

- **Runtime**: Python 3.11+, IRIS embedded Python (irispython)
- **Protocol**: PostgreSQL wire protocol v3
- **Authentication**: OAuth 2.0, SCRAM-SHA-256, IRIS Wallet
- **Deployment**: Docker, embedded in IRIS process

## Governance

Constitution supersedes all other practices.
Amendments require documentation and explicit approval.

**Version**: 1.0.0 | **Ratified**: 2024-12-12 | **Owner**: Thomas Dyar
