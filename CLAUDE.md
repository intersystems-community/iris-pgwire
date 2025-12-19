# Claude Code Instructions

## Authorship and Attribution

**CRITICAL**: NEVER attribute work to Claude Code, AI assistants, or any automated tools.

- All commits, PRs, documentation → credit Thomas Dyar as sole author
- NO "Generated with Claude Code" footers
- NO "Co-Authored-By: Claude" in commits
- NO mentions of AI assistance in any public-facing content

**Owner**: Thomas Dyar <thomas.dyar@intersystems.com>

## Project Constitution

See `.specify/memory/constitution.md` for full project principles including:
- Protocol Fidelity (PostgreSQL wire protocol compliance)
- Test-First Development (real clients, isolated test infrastructure)
- IRIS Integration patterns (embedded Python, CallIn service)
- Vector Performance Requirements (HNSW indexing, L2 rejection)
- Development Environment Synchronization (container restart requirements)

## Key Technical Constraints

1. **Vector Operations**: IRIS only supports cosine (`<=>`) and dot product (`<#>`). L2 distance (`<->`) must be REJECTED with NOT IMPLEMENTED error.

2. **Package Naming**: `pip install intersystems-irispython` but `import iris` (NOT `import intersystems_irispython`)

3. **Container Restarts**: Docker containers do NOT hot-reload Python changes. ALWAYS restart after code changes.

4. **Performance**: Query translation overhead must NOT exceed 5ms per query.
