# Implementation Plan: Implement pg_type Catalog Emulation

**Branch**: `037-pg-type-catalog` | **Date**: 2026-01-29 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/037-pg-type-catalog/spec.md`

## Summary

This feature implements standard PostgreSQL `pg_catalog.pg_type` emulation to support Drizzle ORM migrations and other client introspection tools. The implementation will provide a static list of 21 standard PostgreSQL data types with hardcoded OIDs, ensuring compatibility regardless of whether IRIS is accessed via embedded or external mode. The system will also intercept `pg_catalog.pg_extension` queries to return empty results, avoiding "table not found" errors during client initialization.

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: `intersystems-irispython`, `psycopg[binary]`, `pydantic`, `structlog`  
**Storage**: InterSystems IRIS  
**Testing**: `pytest` (unit and integration)  
**Target Platform**: Docker-based IRIS deployments  
**Project Type**: Server/Library Extension  
**Performance Goals**: <5ms overhead for catalog query interception  
**Constraints**: Must not interfere with normal SQL execution; must respect `strict_single_connection` mode.  
**Scale/Scope**: Fixed emulation of standard system catalogs.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Library-First**: Implementation will reside in `src/iris_pgwire/catalog/` as a modular component.
- **II. CLI Interface**: Exposed via the existing pgwire server.
- **III. Test-First (NON-NEGOTIABLE)**: Integration tests will be written before final implementation.
- **IV. Integration Testing**: Verified against real IRIS and `psycopg` clients.
- **V. Observability**: Detailed logging of catalog query interceptions.

## Project Structure

### Documentation (this feature)

```text
specs/037-pg-type-catalog/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
src/iris_pgwire/
├── catalog/
│   ├── __init__.py      # Lazy loading and OID generator
│   ├── catalog_router.py # Consolidated query interception logic
│   ├── pg_type.py       # Data type catalog emulation
│   └── oid_generator.py # Deterministic OID management
├── iris_executor.py     # Call to catalog router
└── dbapi_executor.py    # Call to catalog router

tests/
├── integration/
│   └── test_catalog_emulation.py # New integration tests
└── unit/
    └── test_pg_type_emulation.py # New unit tests
```

**Structure Decision**: Enhancing existing `src/iris_pgwire/catalog/` package and integrating with both `IRISExecutor` and `DBAPIExecutor` via the `CatalogRouter`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | N/A | N/A |

