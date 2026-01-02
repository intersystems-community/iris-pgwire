# Research: IRIS DevTester Agentic Skills Integration

## Status
- **Date**: 2025-01-02
- **Feature**: `033-devtester-skills`
- **Resolution**: All clarifications resolved.

## Clarifications & Findings

### 1. iris-devtester Integration Patterns

**Question**: How are the new slash commands (/container, /connection, /fixture, /troubleshooting) intended to be used in a pytest environment?

**Findings**:
- **Container Management**: Use `iris_devtester.IRISContainer` as a pytest fixture. It handles the `/container` skill's logic (starting, healthy check, cleanup).
- **Auto-Remediation**: The `get_connection()` function in `iris_devtester.connections` implements the `/connection` skill logic. It automatically detects and fixes "Password change required" and enables "CallIn" service.
- **Fixtures**: `iris_devtester.fixtures.creator.FixtureCreator` and `FixtureValidator` implement the `/fixture` skill logic for loading/exporting `.DAT` files.
- **Troubleshooting**: Integration into `pytest_runtest_makereport` allows capturing IRIS state on failure, effectively automating the `/troubleshooting` skill.

**Decision**: Update `tests/conftest.py` and `src/iris_pgwire/tests/conftest.py` to use these high-level APIs instead of manual Docker/subprocess calls.

### 2. Dependency Management

**Question**: What version of `iris-devtester` is required?

**Findings**:
- The "agentic skills" are part of the latest version of `iris-devtester` (currently being developed/updated in a sibling repo).
- Local development requires `pip install -e ../iris-devtester`.
- CI/CD should point to the latest commit/tag.

**Decision**: Update `pyproject.toml` or `requirements.txt` to ensure the correct version is referenced. For now, rely on local dev installation.

### 3. New Features to Test

**Question**: Which "new-ish" features should be the focus of the new tests?

**Findings**:
- **pg_catalog**: Tables like `pg_type`, `pg_class` for ORM compatibility.
- **ORM Introspection**: Prisma/SQLAlchemy reflection.
- **Vector Operations**: HNSW indexing and similarity operators (`<=>`, `<#>`).

**Decision**: Implement 3 new test files in `tests/integration/` using `iris-devtester` fixtures to validate these features.

## Alternatives Considered

### Manual Docker Compose vs. iris-devtester
- **Manual**: Harder to maintain, requires external setup, no auto-remediation.
- **iris-devtester**: Native IRIS knowledge, automated cleanup, integrated troubleshooting.
- **Choice**: `iris-devtester` for its "agentic" capabilities and reliability.

### Shared vs. Isolated Containers
- **Shared**: Faster, but potential state leakage.
- **Isolated**: Guaranteed clean state, but slower.
- **Decision**: Default to session-scoped shared container for speed, but use function-scoped isolated containers for specific "clean state" tests (e.g., COPY protocol or DDL tests).

## Known Issues in iris-devtester (Bug Report Summary)

During integration, several issues were identified in `iris-devtester` that require upstream fixes:

1. **Password Reset Reliability**:
   - `reset_password_if_needed` defaults to `_SYSTEM` and doesn't accept a `username` parameter, causing failures when connecting as `SuperUser`.
   - IRIS 2024.1+ sometimes requires `##class(Security.Users).Modify` for reliable flag clearing in Docker environments.
2. **Readiness Race Condition**:
   - `IRISReadyWaitStrategy` only checks port 1972. IRIS often accepts connections before the security database is fully initialized, leading to transient auth failures.
3. **Fixture Loading Issues**:
   - `DATFixtureLoader.load_fixture` skips loading if the namespace already exists (e.g., `USER`), preventing data refresh.
   - Database directory creation and permission fixing (`chown`) has issues in certain Docker configurations.
4. **API Inconsistencies**:
   - Constructor and method signatures for `FixtureCreator` and `FixtureValidator` vary between documentation and implementation.

**Mitigation in iris-pgwire**:
- Tests use `iris_container.get_connection()` which proactively resets passwords.
- `iris_fixture` helper in `conftest.py` has been updated to match the actual `iris-devtester` implementation.
- Some fixture tests are skipped until upstream fixes are available.
- `specs/033-devtester-skills/spec.md`
- `tests/test_iris_devtester_connection.py`
- `tests/e2e_isolated/test_copy_protocol_isolated.py`
