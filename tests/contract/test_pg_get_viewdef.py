"""
Contract Tests: pg_get_viewdef() Function

Validates pg_get_viewdef(view_oid, pretty) behavior per
contracts/catalog_functions_api.md

Per plan.md, pg_get_viewdef intentionally returns NULL (out of scope).
This is acceptable as ORMs don't require view definitions for introspection.

Tests validate that the function exists and returns None consistently.
"""

import pytest

from iris_pgwire.catalog.catalog_functions import CatalogFunctionHandler
from iris_pgwire.catalog.oid_generator import OIDGenerator


@pytest.fixture
def catalog_handler():
    """Create CatalogFunctionHandler for testing."""
    oid_gen = OIDGenerator()
    # pg_get_viewdef doesn't need executor (always returns None)
    return CatalogFunctionHandler(oid_gen, executor=None)


# ============================================================================
# Intentional NULL Behavior
# ============================================================================


def test_pg_get_viewdef_returns_none(catalog_handler):
    """Test pg_get_viewdef returns None (intentional per plan.md)."""
    result = catalog_handler.pg_get_viewdef(12345, False)
    assert result is None


def test_pg_get_viewdef_with_pretty_returns_none(catalog_handler):
    """Test pg_get_viewdef with pretty=True returns None."""
    result = catalog_handler.pg_get_viewdef(12345, True)
    assert result is None


def test_pg_get_viewdef_valid_oid_returns_none(catalog_handler):
    """Test pg_get_viewdef with valid-looking OID returns None."""
    # Even with a plausible OID, should return None
    result = catalog_handler.pg_get_viewdef(100000, False)
    assert result is None


def test_pg_get_viewdef_invalid_oid_returns_none(catalog_handler):
    """Test pg_get_viewdef with invalid OID returns None."""
    result = catalog_handler.pg_get_viewdef(0, False)
    assert result is None


def test_pg_get_viewdef_negative_oid_returns_none(catalog_handler):
    """Test pg_get_viewdef with negative OID returns None."""
    result = catalog_handler.pg_get_viewdef(-1, False)
    assert result is None


# ============================================================================
# Handler Integration
# ============================================================================


def test_pg_get_viewdef_via_handler(catalog_handler):
    """Test pg_get_viewdef through handler interface."""
    result = catalog_handler.handle("pg_get_viewdef", ("12345",))
    assert result.function_name == "pg_get_viewdef"
    assert result.result is None
    assert result.error is None


def test_pg_get_viewdef_with_pretty_via_handler(catalog_handler):
    """Test pg_get_viewdef with pretty parameter through handler."""
    result = catalog_handler.handle("pg_get_viewdef", ("12345", "true"))
    assert result.function_name == "pg_get_viewdef"
    assert result.result is None
    assert result.error is None


def test_pg_get_viewdef_with_pretty_false_via_handler(catalog_handler):
    """Test pg_get_viewdef with pretty=false through handler."""
    result = catalog_handler.handle("pg_get_viewdef", ("12345", "false"))
    assert result.function_name == "pg_get_viewdef"
    assert result.result is None
    assert result.error is None


# ============================================================================
# Contract Validation
# ============================================================================


def test_pg_get_viewdef_contract_compliance(catalog_handler):
    """
    Validate that pg_get_viewdef behavior complies with contract.

    Contract states:
    - Initial implementation returns NULL for all views
    - This is intentionally out of scope per plan.md
    - ORMs don't require view definitions for basic introspection
    """
    # Test multiple scenarios - all should return None
    assert catalog_handler.pg_get_viewdef(1, False) is None
    assert catalog_handler.pg_get_viewdef(999999, False) is None
    assert catalog_handler.pg_get_viewdef(12345, True) is None
    assert catalog_handler.pg_get_viewdef(12345, False) is None
