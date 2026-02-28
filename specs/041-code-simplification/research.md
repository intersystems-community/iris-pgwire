# Research: Comprehensive Code Simplification

**Feature**: 041-code-simplification
**Date**: 2026-02-28

## No External Unknowns

This feature is a pure internal refactoring. No external APIs, new dependencies, or architectural decisions were required. All decisions were driven by direct codebase analysis.

## Key Findings

### Decision: code-simplifier agent model
- **Decision**: Use `@fixer` and `@code-simplifier` agents (file-by-file, not bulk)
- **Rationale**: Bulk requests (entire subpackages at once) caused agents to refuse due to scope. File-by-file or small-group tasks succeeded reliably.
- **Alternatives considered**: Single large task — failed with "scope too large" refusal.

### Decision: Dispatch table vs if/elif
- **Decision**: Replace long if/elif chains with `{key: callable}` dispatch dicts
- **Rationale**: Reduces cognitive load, eliminates nesting, makes adding new cases trivial
- **Applied in**: `catalog_router.py`, `constitutional.py`, `integratedml.py`

### Decision: Helper extraction over inline simplification
- **Decision**: Extract multi-responsibility functions into focused helpers rather than compressing logic
- **Rationale**: Clarity over brevity; each helper has a single named purpose
- **Applied in**: All files with functions >50 lines

### Decision: Do not consolidate the two performance_monitor.py files
- **Decision**: Keep `src/iris_pgwire/performance_monitor.py` and `src/iris_pgwire/sql_translator/performance_monitor.py` as separate files
- **Rationale**: They serve different domains (generic vs SQL translation specific) with different interfaces; consolidating would create coupling
- **Alternatives considered**: Merge into one — rejected due to differing concerns

### Decision: quality/ subpackage left as-is
- **Decision**: `src/iris_pgwire/quality/` was not simplified
- **Rationale**: These files inspect code structure; modifying them risks subtle correctness issues. Conservative approach taken.

## Patterns Established

1. **No function >50 lines** — except inherent domain complexity (wire protocol byte parsing, SQL parsing)
2. **No nesting >3 levels** — early returns and extracted guards
3. **Dispatch tables** for multi-branch dispatch
4. **Shared helper extraction** for repeated patterns (e.g., `_execute_iris_operation` in `iris_user_management.py`)
