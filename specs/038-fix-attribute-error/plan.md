# Implementation Plan: Fix Connection Pool AttributeError

**Branch**: `038-fix-attribute-error` | **Date**: 2026-01-29 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/038-fix-attribute-error/spec.md`

## Summary

This feature fixes critical `AttributeError` crashes in the `IRISConnectionPool` introduced in `v1.2.31`. The fix involves adding missing attributes (`is_overflow`) and computed properties (`idle_seconds`) to the `DBAPIConnection` model, and updating the connection pool's logging logic to use safe attribute access via `getattr()`.

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: `pydantic`, `structlog`, `intersystems-irispython`  
**Storage**: InterSystems IRIS  
**Testing**: `pytest`  
**Target Platform**: InterSystems IRIS via pgwire  
**Project Type**: Python library/service extension  
**Performance Goals**: N/A (Stability fix)  
**Constraints**: Must maintain Pydantic model integrity; must not introduce new side effects in the pool logic.  
**Scale/Scope**: Targeted fix for `src/iris_pgwire/dbapi_connection_pool.py` and `src/iris_pgwire/models/dbapi_connection.py`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Library-First**: The fix is confined to the core library and its models.
- **II. CLI Interface**: N/A (Internal logic fix).
- **III. Test-First (NON-NEGOTIABLE)**: A reproduction test will be written to confirm the crash before applying the fix.
- **IV. Integration Testing**: Will verify startup stability against a real IRIS instance if possible, or via mocking the connection.
- **V. Observability**: Fixes logging statements to ensure observability remains functional without causing crashes.

## Project Structure

### Documentation (this feature)

```text
specs/038-fix-attribute-error/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (N/A)
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
src/iris_pgwire/
├── dbapi_connection_pool.py  # Fix logging and property access
└── models/
    └── dbapi_connection.py   # Add missing attributes/properties
```

**Structure Decision**: Confined to existing files in the `iris_pgwire` package.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | N/A | N/A |

