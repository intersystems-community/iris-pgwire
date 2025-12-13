# Research: IRIS SQL Constructs Translation

**Date**: 2025-01-19 | **Feature**: 004-iris-sql-constructs

## SQL Parsing Library Selection

**Decision**: sqlparse with custom IRIS extensions
**Rationale**:
- Lightweight and fast Python SQL parser
- Extensible for custom SQL dialects
- Better performance than ANTLR for simple translations
- Proven in production SQL tools
- Handles SQL tokenization and basic parsing well

**Alternatives considered**:
- ANTLR4 with custom grammar: Too complex for simple translations
- Hand-written parser: Too much maintenance overhead
- lark-parser: Good but less SQL-specific features

## IRIS SQL Construct Mapping Strategy

**Decision**: Registry-based mapping with pattern matching
**Rationale**:
- Modular design allows adding new construct mappings
- Pattern matching enables complex syntax transformations
- Registry approach supports runtime extension
- Easier testing of individual mappings

**Alternatives considered**:
- Hardcoded translation rules: Not extensible
- AST transformation: Too complex for syntax-level changes
- Template-based replacement: Insufficient for complex logic

## Caching Strategy for Translated Queries

**Decision**: LRU cache with TTL and query signature hashing
**Rationale**:
- LRU eviction prevents memory bloat
- TTL handles schema changes and invalidation
- Query signature hashing handles parameterized queries
- In-memory cache avoids I/O overhead

**Alternatives considered**:
- No caching: Performance impact too high
- Redis cache: Adds external dependency
- File-based cache: I/O overhead defeats purpose

## IRIS-PostgreSQL Type Mapping

**Decision**: Leverage caretdev SQLAlchemy patterns with extensions
**Rationale**:
- Proven mappings in production use
- Handles IRIS-specific types like VECTOR, %List
- Established OID assignments for PostgreSQL compatibility
- Battle-tested type conversion logic

**Alternatives considered**:
- Custom type mapping: Reinventing tested solutions
- Simple string replacement: Insufficient for complex types
- Binary protocol mapping: Not needed for wire protocol

## Error Handling for Unsupported Constructs

**Decision**: Hybrid strategy with construct criticality classification
**Rationale**:
- Critical constructs (SELECT, JOIN) get best-effort translation
- Administrative constructs (VACUUM) fail with clear errors
- Edge constructs logged for analysis and future support
- Matches patterns from successful PostgreSQL-compatible databases

**Alternatives considered**:
- Fail-fast on all unsupported: Too restrictive
- Best-effort on all: Could produce incorrect results
- Silent pass-through: Breaks PostgreSQL client expectations

## Performance Monitoring and Debug Tracing

**Decision**: Structured logging with configurable verbosity levels
**Rationale**:
- Production: ERROR/WARN only for minimal overhead
- Debug: Full trace with before/after SQL and timing
- Structured format enables log aggregation and analysis
- Configurable levels balance observability vs performance

**Alternatives considered**:
- Always-on verbose logging: Performance impact
- No debug capability: Poor troubleshooting
- Separate debug mode: Complicates deployment

## SQL Hint Pass-through Implementation

**Decision**: Preserve IRIS hints in translation, strip PostgreSQL-incompatible syntax
**Rationale**:
- IRIS optimizer benefits from native hints
- PostgreSQL clients expect valid syntax
- Hybrid approach maximizes optimization while maintaining compatibility
- Allows gradual hint translation as needed

**Alternatives considered**:
- Strip all hints: Loses IRIS optimization
- Translate all hints: Complex mapping with limited benefit
- Pass all hints unchanged: Breaks PostgreSQL parsing

## Integration with IRIS Embedded Python

**Decision**: AsyncIO with ThreadPoolExecutor for IRIS calls
**Rationale**:
- Prevents blocking the event loop during SQL execution
- Maintains compatibility with existing IRIS connection patterns
- Scales to concurrent connections
- Follows proven async/await patterns

**Alternatives considered**:
- Synchronous IRIS calls: Blocks event loop
- Multiple processes: Complex state sharing
- Native async IRIS library: Not available

## Testing Strategy for Translation Validation

**Decision**: Multi-layer testing with real clients and IRIS instances
**Rationale**:
- E2E tests with psql/psycopg prove client compatibility
- Real IRIS integration tests verify semantic correctness
- Unit tests enable rapid development cycles
- Contract tests document expected behavior

**Alternatives considered**:
- Mock-based testing: Insufficient for database protocols
- Manual testing only: Not scalable or reliable
- Unit tests only: Misses integration issues

---

**Research Complete**: All technical decisions documented with rationale