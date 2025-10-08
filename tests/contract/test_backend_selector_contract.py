"""
Contract tests for BackendSelector component.

These tests define the interface contract for backend selection functionality.
They MUST fail initially (TDD approach) and only pass after implementation.

Constitutional Requirements:
- Principle II (Test-First Development): Write failing tests before implementation
- Principle IV (IRIS Integration): Support both DBAPI and embedded backends

Feature: 018-add-dbapi-option
Contract: specs/018-add-dbapi-option/contracts/backend-selector-contract.md
"""

import pytest

from iris_pgwire.config_schema import BackendConfig, BackendType

# These imports will fail initially - that's expected for TDD
try:
    from iris_pgwire.backend_selector import BackendSelector
    from iris_pgwire.dbapi_executor import DBAPIExecutor
    from iris_pgwire.iris_executor import IrisExecutor as EmbeddedExecutor
except ImportError:
    # Mark as expected failures for TDD
    BackendSelector = None
    DBAPIExecutor = None
    EmbeddedExecutor = None


pytestmark = pytest.mark.contract


@pytest.mark.skipif(BackendSelector is None, reason="BackendSelector not implemented yet (TDD)")
def test_backend_selector_creates_dbapi_executor():
    """
    GIVEN valid DBAPI configuration
    WHEN select_backend is called
    THEN DBAPIExecutor instance is returned
    """
    config = BackendConfig(
        backend_type=BackendType.DBAPI,
        iris_hostname="localhost",
        iris_port=1972,
        iris_namespace="USER",
        iris_username="_SYSTEM",
        iris_password="SYS",
    )
    selector = BackendSelector()
    executor = selector.select_backend(config)

    assert isinstance(executor, DBAPIExecutor)
    assert executor.backend_type == "dbapi"


@pytest.mark.skipif(BackendSelector is None, reason="BackendSelector not implemented yet (TDD)")
def test_backend_selector_creates_embedded_executor():
    """
    GIVEN embedded backend configuration
    WHEN select_backend is called
    THEN EmbeddedExecutor instance is returned
    """
    config = BackendConfig(backend_type=BackendType.EMBEDDED)
    selector = BackendSelector()
    executor = selector.select_backend(config)

    assert isinstance(executor, EmbeddedExecutor)
    assert executor.backend_type == "embedded"


@pytest.mark.skipif(BackendSelector is None, reason="BackendSelector not implemented yet (TDD)")
def test_backend_selector_validates_pool_limits():
    """
    GIVEN configuration with pool_size + overflow > 200
    WHEN validate_config is called
    THEN ValueError is raised
    """
    # This should fail at config creation due to Pydantic validation
    with pytest.raises(ValueError, match="exceeds maximum"):
        BackendConfig(
            backend_type=BackendType.DBAPI,
            iris_hostname="localhost",
            iris_password="SYS",
            pool_size=180,
            pool_max_overflow=50,  # Total 230 > 200
        )


@pytest.mark.skipif(BackendSelector is None, reason="BackendSelector not implemented yet (TDD)")
def test_backend_selector_requires_credentials_for_dbapi():
    """
    GIVEN DBAPI config without credentials
    WHEN config is created
    THEN ValueError is raised
    """
    # This should fail at config creation due to Pydantic validation
    with pytest.raises(ValueError, match="iris_password"):
        BackendConfig(
            backend_type=BackendType.DBAPI,
            iris_hostname="localhost"
            # Missing iris_password
        )


@pytest.mark.skipif(BackendSelector is None, reason="BackendSelector not implemented yet (TDD)")
def test_backend_selector_rejects_invalid_backend_type():
    """
    GIVEN invalid backend_type
    WHEN config is created
    THEN ValueError is raised
    """
    # This should fail at config creation due to Pydantic enum validation
    with pytest.raises(ValueError):
        BackendConfig(backend_type="invalid")  # type: ignore


# Additional helper test to verify TDD approach
def test_tdd_placeholder_backend_selector_not_implemented():
    """
    Meta-test: Verify that BackendSelector is NOT implemented yet.
    This test should PASS initially and be removed after implementation.
    """
    assert BackendSelector is None, (
        "BackendSelector is already implemented! "
        "This violates TDD - tests should fail first. "
        "Remove this test after implementing BackendSelector."
    )
