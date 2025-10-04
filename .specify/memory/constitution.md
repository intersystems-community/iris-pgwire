<!--
Sync Impact Report:
- Version change: 1.2.0 → 1.2.1
- Modified principles:
  * IV. IRIS Integration - Added terminology clarification for IRIS DBAPI vs IRIS Native
- Added sections: None
- Removed sections: None
- Templates requiring updates:
  ✅ plan-template.md - No changes needed (constitution check already present)
  ✅ spec-template.md - No changes needed (requirements validation aligned)
  ✅ tasks-template.md - No changes needed (task categories aligned)
  ✅ CLAUDE.md - Terminology corrections already completed (2025-10-03)
- Follow-up TODOs: None
- Bump Rationale: PATCH version bump - Terminology clarification to prevent
  confusion between "IRIS native" (low-level globals SDK) and external DBAPI
  driver connections. Documentation corrections completed 2025-10-03.
-->

# IRIS PostgreSQL Wire Protocol Constitution

## Core Principles

### I. Protocol Fidelity

Every implementation decision MUST prioritize PostgreSQL wire protocol compliance over convenience. The protocol specification is the ultimate authority for message formats, authentication flows, and client interaction patterns. Deviations from the standard protocol are technical debt that will cause client incompatibilities and MUST be justified with concrete evidence and migration plans.

**Rationale**: PostgreSQL clients expect exact protocol compliance. Even minor deviations break real-world applications and defeat the purpose of providing PostgreSQL compatibility.

### II. Test-First Development

All protocol features MUST be validated with end-to-end tests using real PostgreSQL clients before implementation begins. Write failing tests with psql, psycopg, and other clients, then implement to make them pass. Mock testing is forbidden for database connectivity and protocol validation - only real IRIS instances and real clients provide sufficient validation.

**Rationale**: Protocol implementation is complex and brittle. Real client testing is the only way to ensure compatibility and catch subtle implementation errors that break in production.

### III. Phased Implementation

Development MUST follow the P0-P6 phase sequence strictly: P0 (handshake), P1 (simple query), P2 (extended protocol), P3 (authentication), P4 (cancellation), P5 (types/vectors), P6 (COPY/performance). Each phase builds on previous phases and MUST be fully validated before proceeding to the next phase.

**Rationale**: Protocol implementation has complex interdependencies. Attempting to implement multiple phases simultaneously leads to debugging nightmares and incomplete functionality. Sequential validation ensures a solid foundation.

### IV. IRIS Integration

**CRITICAL REQUIREMENT**: All embedded Python deployments MUST enable the CallIn service via merge.cpf configuration:

```
[Actions]
ModifyService:Name=%Service_CallIn,Enabled=1,AutheEnabled=48
```

Without CallIn service enabled, the `iris` module will fail with IRIS_ACCESSDENIED errors when importing from irispython. This is a non-negotiable infrastructure prerequisite.

All IRIS interactions MUST use the embedded Python approach following official patterns from intersystems-community/iris-embedded-python-template:

- Server execution via `irispython` command (NOT system Python)
- Direct `import iris` with NO external authentication required
- SQL execution via `iris.sql.exec()` with iterator-based result handling
- Async threading with `asyncio.to_thread()` to prevent event loop blocking
- Namespace switching via `iris.system.Process.SetNamespace()`

The merge.cpf MUST be applied during IRIS container startup via `iris merge IRIS /path/to/merge.cpf` command. Leverage proven patterns from caretdev SQLAlchemy IRIS implementation for type mappings and INFORMATION_SCHEMA queries.

**Terminology Clarification**: "IRIS native" refers to the low-level SDK for accessing IRIS globals (multivalue B+-tree storage engine), NOT external DBAPI driver connections. When documenting limitations with external TCP connections using the IRIS DBAPI driver (e.g., vector parameter binding issues), use precise terminology: "external DBAPI connections" or "IRIS DBAPI driver limitations" rather than "native protocol" which has a different technical meaning.

**Rationale**: The CallIn service is the bridge between embedded Python and IRIS internals. Without it, embedded Python cannot access IRIS functionality. The official InterSystems Community template provides battle-tested patterns that eliminate authentication complexity and ensure reliable integration. Async threading is essential for handling concurrent connections without blocking. Clear terminology prevents confusion between IRIS native globals access and DBAPI driver behavior.

### V. Production Readiness

Every feature MUST include monitoring, security hardening, and observability from day one. Production-grade logging, metrics collection, health checks, and error handling are not optional polish items - they are core requirements. SSL/TLS MUST be the default with proper certificate handling.

**Rationale**: This is infrastructure software that will handle production database traffic. Security vulnerabilities and operational blind spots are unacceptable in database proxy software.

### VI. Vector Performance Requirements

**HNSW INDEX REQUIREMENTS**: Vector similarity operations MUST use standard HNSW indexing with proper dataset scale awareness:

```sql
-- Required HNSW index syntax (Distance parameter mandatory)
CREATE INDEX idx_vector ON table_name(vector_column) AS HNSW(Distance='Cosine')
```

**Dataset Scale Thresholds** (based on empirical testing with 1024-dimensional vectors):
- **< 10,000 vectors**: HNSW index overhead exceeds benefits, optimizer may use sequential scan
- **10,000-99,999 vectors**: HNSW index used but overhead approximately equals benefits (0.98-1.02× performance)
- **≥ 100,000 vectors**: HNSW provides documented 4-10× performance improvement (validated: 5.14× at 100K scale)

**ACORN-1 DEPRECATION**: The ACORN-1 algorithm (`SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1`) is NOT RECOMMENDED for production use. Empirical testing shows consistent performance degradation (20-72% slower) at all dataset scales despite correct engagement. ACORN-1 syntax is documented for reference but MUST NOT be used in production deployments.

**Performance Validation Requirements**:
- All vector operations MUST be benchmarked against dataset scale thresholds
- Performance tests MUST include EXPLAIN query plan analysis to verify index usage
- Vector datasets below 100K scale SHOULD consider alternative optimization strategies
- Production deployments MUST target ≥100K vector scale for HNSW benefits

**Rationale**: Comprehensive investigation (1K, 10K, 100K vector scales) proved HNSW requires sufficient dataset scale to overcome index overhead. ACORN-1 consistently degrades performance despite documentation claims. These empirically-validated thresholds prevent premature optimization and ensure production deployments achieve expected 4-10× performance improvements.

## Security Requirements

All network communication MUST use TLS encryption in production environments. Authentication MUST implement SCRAM-SHA-256 with proper salt generation and verification. Input validation MUST sanitize all client inputs to prevent SQL injection and protocol attacks. Error messages MUST NOT leak sensitive information about IRIS internals or database schemas.

## Performance Standards

Query translation overhead MUST NOT exceed 5ms per query under normal load. Connection establishment MUST complete within 1 second. The server MUST support at least 1000 concurrent connections with proper connection pooling. Memory usage per connection MUST NOT exceed 10MB baseline.

Vector similarity queries at production scale (≥100K vectors) MUST achieve 4-10× performance improvement with HNSW indexing versus sequential scan baseline. Translation overhead for vector query optimization MUST remain below 5ms constitutional limit.

## Development Workflow

All code changes MUST pass through the established phase gates before integration. Constitution compliance MUST be verified during code review. Performance benchmarks MUST be run for any changes affecting the query execution path. Integration tests MUST pass against real IRIS instances before deployment.

Vector performance changes MUST include benchmark results across multiple dataset scales (minimum: 1K, 10K, 100K vectors) with EXPLAIN query plan validation to prove index engagement.

## Governance

This constitution supersedes all other development practices and coding guidelines. Amendments require documented justification with performance and compatibility impact analysis. All code reviews MUST verify compliance with these principles. Violations require explicit justification in commit messages and technical debt tracking.

Constitution violations may be permitted only when:

1. PostgreSQL protocol compliance demands the deviation
2. IRIS technical limitations make strict compliance impossible
3. Production security requirements override development convenience
4. Performance requirements documented with benchmarks justify the complexity

**Version**: 1.2.1 | **Ratified**: 2025-01-19 | **Last Amended**: 2025-10-03
