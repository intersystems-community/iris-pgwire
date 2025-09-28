<!--
Sync Impact Report:
- Version change: NEW → 1.0.0
- Added principles: Protocol Fidelity, Test-First Development, Phased Implementation, IRIS Integration, Production Readiness
- Templates requiring updates:
  ✅ plan-template.md - Constitution Check references updated
  ✅ spec-template.md - Requirement validation aligned
  ✅ tasks-template.md - Task categorization aligned
  ✅ agent-file-template.md - No changes needed
- Follow-up TODOs: None
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

All IRIS interactions MUST use the embedded Python approach with proper async threading to avoid blocking the event loop. IRIS SQL execution, authentication, and metadata queries MUST be executed in ThreadPoolExecutor contexts. Leverage proven patterns from caretdev SQLAlchemy IRIS implementation for type mappings and INFORMATION_SCHEMA queries.

**Rationale**: IRIS embedded Python provides the most reliable integration path. Async threading is essential for handling concurrent connections without blocking. The caretdev patterns are battle-tested in production.

### V. Production Readiness

Every feature MUST include monitoring, security hardening, and observability from day one. Production-grade logging, metrics collection, health checks, and error handling are not optional polish items - they are core requirements. SSL/TLS MUST be the default with proper certificate handling.

**Rationale**: This is infrastructure software that will handle production database traffic. Security vulnerabilities and operational blind spots are unacceptable in database proxy software.

## Security Requirements

All network communication MUST use TLS encryption in production environments. Authentication MUST implement SCRAM-SHA-256 with proper salt generation and verification. Input validation MUST sanitize all client inputs to prevent SQL injection and protocol attacks. Error messages MUST NOT leak sensitive information about IRIS internals or database schemas.

## Performance Standards

Query translation overhead MUST NOT exceed 5ms per query under normal load. Connection establishment MUST complete within 1 second. The server MUST support at least 1000 concurrent connections with proper connection pooling. Memory usage per connection MUST NOT exceed 10MB baseline.

## Development Workflow

All code changes MUST pass through the established phase gates before integration. Constitution compliance MUST be verified during code review. Performance benchmarks MUST be run for any changes affecting the query execution path. Integration tests MUST pass against real IRIS instances before deployment.

## Governance

This constitution supersedes all other development practices and coding guidelines. Amendments require documented justification with performance and compatibility impact analysis. All code reviews MUST verify compliance with these principles. Violations require explicit justification in commit messages and technical debt tracking.

Constitution violations may be permitted only when:

1. PostgreSQL protocol compliance demands the deviation
2. IRIS technical limitations make strict compliance impossible
3. Production security requirements override development convenience
4. Performance requirements documented with benchmarks justify the complexity

**Version**: 1.0.0 | **Ratified**: 2025-01-19 | **Last Amended**: 2025-01-19
