<!--
Sync Impact Report:
- Version change: 1.2.3 → 1.2.4
- Modified principles:
  * VI. Vector Performance Requirements - Corrected L2 distance handling strategy
- Changed sections: "IRIS Vector Function Limitations" - Changed from "must map L2 to cosine" to "must REJECT L2 with NOT IMPLEMENTED error"
- Removed sections: None
- Templates requiring updates:
  ✅ plan-template.md - No changes needed (constitution check already present)
  ✅ spec-template.md - No changes needed (requirements validation aligned)
  ✅ tasks-template.md - No changes needed (task categories aligned)
  ✅ CLAUDE.md - Vector limitations documented in existing vector sections
- Follow-up TODOs: Update vector optimizer to default to DOUBLE instead of FLOAT; implement L2 rejection in vector_optimizer.py
- Bump Rationale: PATCH version bump - Corrected L2 distance handling strategy based on
  user feedback. Previous version incorrectly stated server should map <-> to <=>, but
  correct behavior is to REJECT L2 queries with NOT IMPLEMENTED error. Tests should use
  cosine (<=>) or dot product (<#>) exclusively. Server now raises NotImplementedError
  when <-> operator detected. Documentation corrected 2025-10-05.
-->

# IRIS PostgreSQL Wire Protocol Constitution

## Core Principles

### I. Protocol Fidelity

Every implementation decision MUST prioritize PostgreSQL wire protocol compliance over convenience. The protocol specification is the ultimate authority for message formats, authentication flows, and client interaction patterns. Deviations from the standard protocol are technical debt that will cause client incompatibilities and MUST be justified with concrete evidence and migration plans.

**Rationale**: PostgreSQL clients expect exact protocol compliance. Even minor deviations break real-world applications and defeat the purpose of providing PostgreSQL compatibility.

### II. Test-First Development

All protocol features MUST be validated with end-to-end tests using real PostgreSQL clients before implementation begins. Write failing tests with psql, psycopg, and other clients, then implement to make them pass. Mock testing is forbidden for database connectivity and protocol validation - only real IRIS instances and real clients provide sufficient validation.

**MANDATORY: Isolated Test Infrastructure**

All E2E and integration tests MUST use `iris-devtester` (https://github.com/caretdev/iris-devtester) for isolated, reproducible test environments:

- **Zero Configuration**: IRISContainer.community() provides isolated IRIS instances per test
- **Automatic Cleanup**: Containers and state managed automatically via testcontainers
- **DAT Fixture Loading**: 10-100× faster than INSERT statements for test data
- **No State Pollution**: Each test suite gets fresh IRIS instance
- **Password Management**: Automatic handling of IRIS password policies
- **DBAPI Performance**: 3× faster than JDBC connections

**Pattern**:
```python
from iris_devtester import IRISContainer

def test_copy_protocol_with_isolated_iris():
    with IRISContainer.community() as iris:
        conn = iris.get_connection()
        # Run tests against clean IRIS instance
        # Automatic cleanup on exit
```

**Rationale**: Testing against "whatever IRIS container is running" leads to state pollution, foreign key conflicts, and unreproducible failures. iris-devtester provides medical-grade reliability (94%+ test coverage) with zero manual setup. Protocol implementation is complex and brittle. Real client testing with isolated instances is the only way to ensure compatibility and catch subtle implementation errors that break in production.

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

**CRITICAL: Python Package Naming (Non-Standard)**

The `intersystems-irispython` package violates standard Python naming conventions and requires special attention:

```python
# PyPI Package (pip install)
pip install intersystems-irispython>=5.1.2

# Module imports (COMPLETELY DIFFERENT from package name!)
import iris                # ✅ CORRECT - Main embedded Python module
import iris.dbapi         # ✅ CORRECT - External DBAPI driver
import irisnative         # ✅ CORRECT - Low-level globals SDK

# WRONG imports that WILL FAIL:
import intersystems_irispython        # ❌ Module doesn't exist!
import intersystems_iris              # ❌ Old package name
import intersystems_irispython.dbapi  # ❌ No such module path
```

**Why This Matters**:
- Package name: `intersystems-irispython` (pip/PyPI)
- Module names: `iris` and `irisnative` (completely different!)
- Violates PEP 8 convention: package name should approximate module name
- Caused by legacy design: InterSystems wanted short import name (`iris`) but descriptive package name

**Deployment Pattern Differences**:
1. **Embedded Python** (runs inside IRIS process via `irispython` command):
   - Import: `import iris`
   - NO connection required - direct access to IRIS internals
   - Use for: PGWire server execution, internal IRIS operations

2. **External DBAPI** (runs in external Python process, connects via TCP):
   - Import: `import iris.dbapi as dbapi`
   - Connection required: `dbapi.connect(hostname, port, namespace, username, password)`
   - Use for: Tests, external applications, connection pooling

Both patterns use the SAME PyPI package (`intersystems-irispython`) but serve different architectural purposes. Always use the correct import path for your deployment pattern.

**Rationale**: The CallIn service is the bridge between embedded Python and IRIS internals. Without it, embedded Python cannot access IRIS functionality. The official InterSystems Community template provides battle-tested patterns that eliminate authentication complexity and ensure reliable integration. Async threading is essential for handling concurrent connections without blocking. Clear terminology prevents confusion between IRIS native globals access and DBAPI driver behavior. The non-standard package naming is a known InterSystems design decision that requires explicit documentation to prevent import errors.

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

**IRIS Vector Function Limitations**:

IRIS supports ONLY two vector similarity functions:
- `VECTOR_COSINE(vec1, vec2)` - Cosine similarity
- `VECTOR_DOT_PRODUCT(vec1, vec2)` - Dot product

**CRITICAL**: IRIS does NOT support L2 distance (`VECTOR_L2` does not exist). This creates incompatibility with pgvector's default `<->` operator which represents L2/Euclidean distance. The server MUST REJECT any queries using the `<->` operator with a NOT IMPLEMENTED error.

**pgvector Operator Mapping**:
```sql
-- pgvector operators and IRIS equivalents:
<=>  →  VECTOR_COSINE()      ✅ Supported (cosine distance)
<#>  →  VECTOR_DOT_PRODUCT()  ✅ Supported (negative inner product)
<->  →  VECTOR_L2()           ❌ NOT SUPPORTED - server must REJECT with error
```

**Vector Datatype Matching Requirement**:

Vector operations FAIL with "Cannot perform vector operation on vectors of different datatypes" if the table schema datatype (FLOAT/DOUBLE/DECIMAL) does not match the `TO_VECTOR()` call datatype:

```sql
-- Table created with DOUBLE:
CREATE TABLE vectors (id INT, embedding VECTOR(DOUBLE, 128))

-- Query MUST use matching DOUBLE type:
SELECT * FROM vectors
ORDER BY VECTOR_COSINE(embedding, TO_VECTOR('[...]', DOUBLE))  -- ✅ Works

-- Query with FLOAT type FAILS:
SELECT * FROM vectors
ORDER BY VECTOR_COSINE(embedding, TO_VECTOR('[...]', FLOAT))   -- ❌ Datatype error
```

**Additional pgvector Incompatibilities**:

Beyond L2 distance and datatype matching, IRIS vector search has additional limitations compared to pgvector:

1. **No L1 (Manhattan) distance** - pgvector supports L1 via custom operators, IRIS does not
2. **No Hamming distance** - Binary vector comparison not supported
3. **No half-precision vectors** - pgvector supports `halfvec`, IRIS requires FLOAT/DOUBLE/DECIMAL
4. **No sparse vectors** - pgvector's `sparsevec` type not supported
5. **Limited index types** - Only HNSW available (no IVFFlat equivalent)
6. **No vector aggregation functions** - pgvector has `avg(vector)`, IRIS does not
7. **Parameter binding restrictions** - Vectors in ORDER BY must be literals (server rewrites automatically)

All vector query rewriting MUST:
1. REJECT queries using `<->` operator (L2 distance) with NOT IMPLEMENTED error
2. REJECT unsupported pgvector features (L1, Hamming, halfvec, sparsevec, etc.) with clear error messages
3. Support `<=>` (cosine) and `<#>` (dot product) operators only
4. Preserve or detect the vector column's datatype (FLOAT/DOUBLE/DECIMAL)
5. Use matching datatype in all `TO_VECTOR()` calls
6. Transform parameter-bound vectors to literals for ORDER BY clauses (automatic via optimizer)

**Performance Validation Requirements**:
- All vector operations MUST be benchmarked against dataset scale thresholds
- Performance tests MUST include EXPLAIN query plan analysis to verify index usage
- Vector datasets below 100K scale SHOULD consider alternative optimization strategies
- Production deployments MUST target ≥100K vector scale for HNSW benefits

**Rationale**: Comprehensive investigation (1K, 10K, 100K vector scales) proved HNSW requires sufficient dataset scale to overcome index overhead. ACORN-1 consistently degrades performance despite documentation claims. These empirically-validated thresholds prevent premature optimization and ensure production deployments achieve expected 4-10× performance improvements. The absence of L2 distance support in IRIS is a fundamental limitation that breaks pgvector's default `<->` operator - the server must explicitly reject these queries rather than attempting automatic mapping to alternative distance functions. Datatype mismatches cause runtime failures that are difficult to debug without understanding IRIS's strict type checking for vector operations.

### VII. Development Environment Synchronization

**CRITICAL REQUIREMENT**: Docker containers running the PGWire server DO NOT automatically reload Python code changes. Every code modification MUST be followed by an explicit container restart to ensure the updated code is active:

```bash
# MANDATORY workflow after ANY code change:
docker restart iris-pgwire-db
sleep 3  # Wait for server to initialize
# THEN verify fix with test query
```

**Stale Code Detection Patterns**:

When encountering errors that were previously fixed, immediately suspect stale code and check:
1. **Container uptime**: `docker ps` shows "Up X minutes/hours" - if uptime > time since code change, code is stale
2. **Error patterns**: Seeing errors that match pre-fix behavior (e.g., "Field 'LastName' not found" when normalization should uppercase it)
3. **Double normalization**: SQL showing `TO_DATE(TO_DATE(...))` or `UPPERCASE(UPPERCASE(...))` patterns
4. **Missing functionality**: Features that should work based on code but don't execute

**iris-devtester Integration** (Constitutional Test Requirement):

MUST implement automated stale code detection via iris-devtester:
```python
# Required test in iris-devtester suite:
def test_code_synchronization():
    """Verify Docker container is running current code version"""
    # 1. Inject CODE_VERSION constant into server code
    # 2. Query via PGWire: SELECT current_setting('pgwire.code_version')
    # 3. Compare against expected CODE_VERSION from Git commit
    # 4. FAIL if mismatch detected with clear instructions to restart
```

**Development Workflow Requirements**:
1. **BEFORE each test run**: Verify `docker ps` uptime vs last code change timestamp
2. **AFTER code changes**: ALWAYS restart container - NEVER assume hot reload works
3. **WHEN debugging**: First action is to restart container to eliminate stale code as root cause
4. **IN CI/CD**: Build fresh containers for each test run (never reuse existing containers)

**Known Trigger Scenarios** (empirically validated during Feature 021 development):
- Editing Python files in `src/iris_pgwire/` while container is running
- Server crashes and auto-restarts (Docker restart policy loads original image code, not workspace edits)
- Long-running development sessions spanning multiple code iterations

**Rationale**: The iris-pgwire server runs embedded Python code loaded at container startup. Python modules are cached in memory and not reloaded unless explicitly triggered. Docker's restart policy can auto-restart crashed containers, but they load the IMAGE's code (from last `docker build`), NOT the workspace's edited files mounted via volumes. This caused three separate debugging incidents during Feature 021 where fixes appeared to fail because the container was running pre-fix code. Automated version checking prevents wasted debugging time and ensures test failures reflect actual code bugs, not deployment synchronization issues.

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

**Version**: 1.3.0 | **Ratified**: 2025-01-19 | **Last Amended**: 2025-11-08
