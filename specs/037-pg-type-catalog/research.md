# Research: pg_type Catalog Emulation

## Decision: Static Emulation vs Dynamic Discovery

### Decision
Use a **static list of 21 standard PostgreSQL data types** for the initial implementation.

### Rationale
- **Compatibility**: Standard clients (Drizzle, Prisma, asyncpg) primarily care about the OIDs of standard types to map them to language-level types.
- **Performance**: Static emulation avoids expensive metadata queries to IRIS for every connection/introspection.
- **Reliability**: Deterministic OIDs (standard PG OIDs) prevent confusion in clients that have hardcoded expectations.
- **MVP Focus**: Resolves the immediate "table not found" error without introducing complexity of full type system mapping.

### Alternatives Considered
- **Dynamic Discovery from INFORMATION_SCHEMA.DATATYPES**: Rejected for MVP due to OID generation complexity and lack of direct 1:1 mapping for many IRIS types to PG standard OIDs.
- **On-the-fly OID hashing**: Rejected because standard types (like `int4`) MUST have their standard OIDs (23) for many clients to function correctly.

## Research Findings: Drizzle/Prisma Introspection

- Drizzle Kit executes `SELECT ... FROM pg_catalog.pg_type` early in its introspection phase.
- It specifically looks for standard OIDs to identify boolean, integer, and string columns.
- Failure to find `pg_type` results in a fatal migration error.

## Best Practices: Catalog Emulation in Adapters

- **Deterministic OIDs**: Standard types MUST use standard PostgreSQL OIDs.
- **Empty Extension Catalog**: Intercepting `pg_extension` and returning empty prevents clients from trying to use PG-specific extensions that don't exist in IRIS.
- **Case Sensitivity**: Query interception must be case-insensitive (handle `pg_type`, `PG_TYPE`, `pg_catalog.pg_type`).
