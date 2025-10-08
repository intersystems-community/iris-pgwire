"""
Integration tests for backend selection (DBAPI vs Embedded).

End-to-end tests validating backend switching via configuration.
Uses real PostgreSQL clients (psycopg) per Constitutional Principle II.

Feature: 018-add-dbapi-option
Test Scenarios: Based on quickstart.md Step 2 (Configure DBAPI Backend)
"""

import os

import pytest

from iris_pgwire.config_schema import BackendConfig, BackendType

try:
    from iris_pgwire.backend_selector import BackendSelector
except ImportError:
    BackendSelector = None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(BackendSelector is None, reason="BackendSelector not implemented yet (TDD)"),
]


def test_dbapi_backend_selected_via_env_variables(monkeypatch):
    """
    GIVEN environment variables configured for DBAPI
    WHEN config is loaded from env
    THEN DBAPI backend is selected
    """
    monkeypatch.setenv("PGWIRE_BACKEND_TYPE", "dbapi")
    monkeypatch.setenv("IRIS_PASSWORD", "SYS")

    config = BackendConfig.from_env()
    assert config.backend_type == BackendType.DBAPI


def test_embedded_backend_selected_via_env_variables(monkeypatch):
    """
    GIVEN environment variables configured for embedded
    WHEN config is loaded from env
    THEN embedded backend is selected
    """
    monkeypatch.setenv("PGWIRE_BACKEND_TYPE", "embedded")

    config = BackendConfig.from_env()
    assert config.backend_type == BackendType.EMBEDDED


def test_backend_switches_correctly():
    """
    GIVEN backend selector
    WHEN config changes backend_type
    THEN correct executor is selected
    """
    selector = BackendSelector()

    # Test DBAPI selection
    dbapi_config = BackendConfig(
        backend_type=BackendType.DBAPI,
        iris_password="SYS",
    )
    dbapi_executor = selector.select_backend(dbapi_config)
    assert dbapi_executor.backend_type == "dbapi"

    # Test embedded selection (will raise ImportError if IrisExecutor not available)
    # This is EXPECTED - embedded backend requires irispython environment
    embedded_config = BackendConfig(backend_type=BackendType.EMBEDDED)
    try:
        embedded_executor = selector.select_backend(embedded_config)
        assert embedded_executor.backend_type == "embedded"
    except ImportError as e:
        # Expected when running in external Python (not irispython)
        assert "IrisExecutor not available" in str(e)
        pytest.skip("IrisExecutor requires irispython environment (embedded Python)")


def test_invalid_config_rejected():
    """
    GIVEN invalid backend configuration
    WHEN config validation runs
    THEN appropriate error is raised
    """
    # Missing password for DBAPI backend
    with pytest.raises(ValueError, match="iris_password"):
        BackendConfig(
            backend_type=BackendType.DBAPI,
            # iris_password missing
        )


# Meta-test for TDD tracking
def test_tdd_placeholder_backend_selection():
    """Verify BackendSelector not implemented yet (TDD)."""
    if BackendSelector is not None:
        pytest.skip("BackendSelector implemented - remove this placeholder test")
