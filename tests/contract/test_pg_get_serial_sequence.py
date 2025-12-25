"""
Contract Tests: pg_get_serial_sequence() Function

Validates pg_get_serial_sequence(table, column) behavior per
contracts/catalog_functions_api.md

Tests cover:
- Auto-increment/IDENTITY column detection
- Non-serial column handling
- Schema-qualified table names
- Edge cases
"""

import pytest
from unittest.mock import Mock

from iris_pgwire.catalog.catalog_functions import CatalogFunctionHandler
from iris_pgwire.catalog.oid_generator import OIDGenerator


class MockExecutor:
    """Mock executor for testing serial sequence queries."""

    def __init__(self):
        self.columns = {}  # (schema, table, column) -> (default, is_identity)

    def add_column(self, schema, table, column, default=None, is_identity="NO"):
        """Add column to mock database."""
        self.columns[(schema, table, column)] = (default, is_identity)

    def _execute_iris_query(self, query):
        """Mock IRIS query execution."""
        query_upper = query.upper()

        # Extract table and column from query by checking WHERE clause
        for (schema, table, column), (default, is_identity) in self.columns.items():
            # Check for exact matches in WHERE clause (avoid substring collisions like ID in IS_IDENTITY)
            table_match = f"TABLE_NAME = '{table.upper()}'" in query_upper or f"TABLE_NAME = '{table}'" in query_upper
            col_match = f"COLUMN_NAME = '{column.upper()}'" in query_upper or f"COLUMN_NAME = '{column}'" in query_upper
            if table_match and col_match:
                return {"success": True, "rows": [(default, is_identity)]}

        return {"success": True, "rows": []}


@pytest.fixture
def mock_executor():
    """Create mock executor."""
    return MockExecutor()


@pytest.fixture
def catalog_handler(mock_executor):
    """Create CatalogFunctionHandler with mock executor."""
    oid_gen = OIDGenerator()
    handler = CatalogFunctionHandler(oid_gen, mock_executor)
    return handler, mock_executor


# ============================================================================
# IDENTITY Columns
# ============================================================================


def test_serial_identity_column(catalog_handler):
    """Test serial sequence detection for IDENTITY column."""
    handler, executor = catalog_handler

    # Setup: users.id is IDENTITY
    executor.add_column("SQLUser", "users", "id", default=None, is_identity="YES")

    result = handler.pg_get_serial_sequence("users", "id")
    assert result == "public.users_id_seq"


def test_serial_identity_qualified_table(catalog_handler):
    """Test serial sequence with schema-qualified table name."""
    handler, executor = catalog_handler

    executor.add_column("SQLUser", "posts", "id", default=None, is_identity="YES")

    result = handler.pg_get_serial_sequence("public.posts", "id")
    assert result == "public.posts_id_seq"


# ============================================================================
# Non-Serial Columns
# ============================================================================


def test_non_serial_column(catalog_handler):
    """Test non-serial column returns None."""
    handler, executor = catalog_handler

    # Setup: users.name is not serial
    executor.add_column("SQLUser", "users", "name", default=None, is_identity="NO")

    result = handler.pg_get_serial_sequence("users", "name")
    assert result is None


def test_nonexistent_table(catalog_handler):
    """Test non-existent table returns None."""
    handler, executor = catalog_handler

    result = handler.pg_get_serial_sequence("nonexistent", "id")
    assert result is None


def test_nonexistent_column(catalog_handler):
    """Test non-existent column returns None."""
    handler, executor = catalog_handler

    executor.add_column("SQLUser", "users", "id", default=None, is_identity="YES")

    result = handler.pg_get_serial_sequence("users", "nonexistent")
    assert result is None


# ============================================================================
# Handler Integration
# ============================================================================


def test_pg_get_serial_sequence_via_handler(catalog_handler):
    """Test pg_get_serial_sequence through handler interface."""
    handler, executor = catalog_handler

    executor.add_column("SQLUser", "users", "id", default=None, is_identity="YES")

    result = handler.handle("pg_get_serial_sequence", ("users", "id"))
    assert result.function_name == "pg_get_serial_sequence"
    assert result.result == "public.users_id_seq"
    assert result.error is None


def test_pg_get_serial_sequence_via_handler_no_serial(catalog_handler):
    """Test pg_get_serial_sequence for non-serial column through handler."""
    handler, executor = catalog_handler

    executor.add_column("SQLUser", "users", "name", default=None, is_identity="NO")

    result = handler.handle("pg_get_serial_sequence", ("users", "name"))
    assert result.function_name == "pg_get_serial_sequence"
    assert result.result is None
    assert result.error is None


# ============================================================================
# Sequence Name Format
# ============================================================================


def test_sequence_name_format_simple(catalog_handler):
    """Test sequence name follows PostgreSQL convention."""
    handler, executor = catalog_handler

    executor.add_column("SQLUser", "customers", "customer_id", default=None, is_identity="YES")

    result = handler.pg_get_serial_sequence("customers", "customer_id")
    # PostgreSQL convention: table_column_seq
    assert result == "public.customers_customer_id_seq"


def test_sequence_name_with_schema_prefix(catalog_handler):
    """Test sequence name includes public schema prefix."""
    handler, executor = catalog_handler

    executor.add_column("SQLUser", "orders", "id", default=None, is_identity="YES")

    result = handler.pg_get_serial_sequence("orders", "id")
    # Must start with public. prefix
    assert result.startswith("public.")
    # Must end with _seq suffix
    assert result.endswith("_seq")
