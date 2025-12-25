"""
Contract Tests: pg_get_constraintdef() Function

Validates pg_get_constraintdef(constraint_oid, pretty) behavior per
contracts/constraint_def_contract.md

Tests cover:
- PRIMARY KEY constraints (single and composite)
- FOREIGN KEY constraints (basic and with actions)
- UNIQUE constraints
- Edge cases (non-existent OID, invalid OID)

Note: These tests require a mock executor that simulates INFORMATION_SCHEMA queries.
"""

import pytest
from unittest.mock import Mock

from iris_pgwire.catalog.catalog_functions import CatalogFunctionHandler
from iris_pgwire.catalog.oid_generator import OIDGenerator


class MockExecutor:
    """Mock executor for testing constraint definition queries."""

    def __init__(self):
        self.constraints = {}
        self.columns = {}
        self.fk_references = {}

    def add_constraint(self, schema, name, ctype, table, columns):
        """Add a constraint to the mock database."""
        self.constraints[(schema, name)] = {
            "constraint_schema": schema,
            "constraint_name": name,
            "constraint_type": ctype,
            "table_name": table,
        }
        self.columns[(schema, name)] = columns

    def add_fk_reference(self, schema, name, ref_table, ref_columns, update_rule="NO ACTION", delete_rule="NO ACTION"):
        """Add FK reference information."""
        self.fk_references[(schema, name)] = {
            "ref_table": ref_table,
            "ref_columns": ref_columns,
            "update_rule": update_rule,
            "delete_rule": delete_rule,
        }

    def _execute_iris_query(self, query):
        """Mock IRIS query execution."""
        query_upper = query.upper()

        # Handle TABLE_CONSTRAINTS query
        if "TABLE_CONSTRAINTS" in query_upper:
            # Check if query selects only TABLE_NAME (for FK reference lookup)
            if "SELECT TABLE_NAME" in query_upper and "CONSTRAINT_NAME" in query_upper:
                # Return only table_name column for matching constraints
                rows = [
                    (info["table_name"],)
                    for info in self.constraints.values()
                ]
            else:
                # Return full constraint info
                rows = [
                    (info["constraint_schema"], info["constraint_name"], info["constraint_type"], info["table_name"])
                    for info in self.constraints.values()
                ]
            return {"success": True, "rows": rows}

        # Handle KEY_COLUMN_USAGE query
        if "KEY_COLUMN_USAGE" in query_upper:
            # Extract constraint name from query (simplified)
            for (schema, name), columns in self.columns.items():
                if name.upper() in query_upper:
                    rows = [(col,) for col in columns]
                    return {"success": True, "rows": rows}
            return {"success": True, "rows": []}

        # Handle REFERENTIAL_CONSTRAINTS query
        if "REFERENTIAL_CONSTRAINTS" in query_upper:
            for (schema, name), ref_info in self.fk_references.items():
                if name.upper() in query_upper:
                    rows = [(schema, f"{ref_info['ref_table']}_pkey", ref_info["update_rule"], ref_info["delete_rule"])]
                    return {"success": True, "rows": rows}
            return {"success": True, "rows": []}

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
    return handler, oid_gen, mock_executor


# ============================================================================
# Primary Key Constraints
# ============================================================================


def test_pk_single_column(catalog_handler):
    """Test PRIMARY KEY constraint with single column."""
    handler, oid_gen, executor = catalog_handler

    # Setup: users table with PK on id
    executor.add_constraint("SQLUser", "users_pkey", "PRIMARY KEY", "users", ["id"])

    # Get OID
    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "users_pkey")

    # Test
    result = handler.pg_get_constraintdef(constraint_oid)
    assert result == "PRIMARY KEY (id)"


def test_pk_multi_column(catalog_handler):
    """Test PRIMARY KEY constraint with multiple columns."""
    handler, oid_gen, executor = catalog_handler

    # Setup: composite PK
    executor.add_constraint("SQLUser", "orders_pkey", "PRIMARY KEY", "orders", ["tenant_id", "order_id"])

    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "orders_pkey")

    result = handler.pg_get_constraintdef(constraint_oid)
    assert result == "PRIMARY KEY (tenant_id, order_id)"


# ============================================================================
# Unique Constraints
# ============================================================================


def test_unique_single_column(catalog_handler):
    """Test UNIQUE constraint with single column."""
    handler, oid_gen, executor = catalog_handler

    executor.add_constraint("SQLUser", "users_email_key", "UNIQUE", "users", ["email"])

    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "users_email_key")

    result = handler.pg_get_constraintdef(constraint_oid)
    assert result == "UNIQUE (email)"


def test_unique_multi_column(catalog_handler):
    """Test UNIQUE constraint with multiple columns."""
    handler, oid_gen, executor = catalog_handler

    executor.add_constraint("SQLUser", "users_tenant_email_key", "UNIQUE", "users", ["tenant_id", "email"])

    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "users_tenant_email_key")

    result = handler.pg_get_constraintdef(constraint_oid)
    assert result == "UNIQUE (tenant_id, email)"


# ============================================================================
# Foreign Key Constraints
# ============================================================================


def test_fk_basic(catalog_handler):
    """Test basic FOREIGN KEY constraint."""
    handler, oid_gen, executor = catalog_handler

    # Setup: posts.author_id references users.id
    executor.add_constraint("SQLUser", "users_pkey", "PRIMARY KEY", "users", ["id"])  # Referenced PK
    executor.add_constraint("SQLUser", "posts_author_id_fkey", "FOREIGN KEY", "posts", ["author_id"])
    executor.add_fk_reference("SQLUser", "posts_author_id_fkey", "users", ["id"], "NO ACTION", "NO ACTION")

    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "posts_author_id_fkey")

    result = handler.pg_get_constraintdef(constraint_oid)
    assert result == "FOREIGN KEY (author_id) REFERENCES users(id)"


def test_fk_multi_column(catalog_handler):
    """Test multi-column FOREIGN KEY constraint."""
    handler, oid_gen, executor = catalog_handler

    # Setup: orders(tenant_id, user_id) references accounts(tenant_id, user_id)
    executor.add_constraint("SQLUser", "accounts_pkey", "PRIMARY KEY", "accounts", ["tenant_id", "user_id"])  # Referenced PK
    executor.add_constraint("SQLUser", "orders_tenant_user_fkey", "FOREIGN KEY", "orders", ["tenant_id", "user_id"])
    executor.add_fk_reference("SQLUser", "orders_tenant_user_fkey", "accounts", ["tenant_id", "user_id"])

    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "orders_tenant_user_fkey")

    result = handler.pg_get_constraintdef(constraint_oid)
    assert result == "FOREIGN KEY (tenant_id, user_id) REFERENCES accounts(tenant_id, user_id)"


def test_fk_with_cascade(catalog_handler):
    """Test FOREIGN KEY with ON DELETE CASCADE."""
    handler, oid_gen, executor = catalog_handler

    executor.add_constraint("SQLUser", "users_pkey", "PRIMARY KEY", "users", ["id"])  # Referenced PK
    executor.add_constraint("SQLUser", "posts_author_id_fkey", "FOREIGN KEY", "posts", ["author_id"])
    executor.add_fk_reference("SQLUser", "posts_author_id_fkey", "users", ["id"], "NO ACTION", "CASCADE")

    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "posts_author_id_fkey")

    result = handler.pg_get_constraintdef(constraint_oid)
    assert "ON DELETE CASCADE" in result
    assert result.startswith("FOREIGN KEY (author_id) REFERENCES users(id)")


def test_fk_with_update_and_delete(catalog_handler):
    """Test FOREIGN KEY with both ON UPDATE and ON DELETE actions."""
    handler, oid_gen, executor = catalog_handler

    executor.add_constraint("SQLUser", "users_pkey", "PRIMARY KEY", "users", ["id"])  # Referenced PK
    executor.add_constraint("SQLUser", "posts_author_id_fkey", "FOREIGN KEY", "posts", ["author_id"])
    executor.add_fk_reference("SQLUser", "posts_author_id_fkey", "users", ["id"], "CASCADE", "SET NULL")

    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "posts_author_id_fkey")

    result = handler.pg_get_constraintdef(constraint_oid)
    assert "ON UPDATE CASCADE" in result
    assert "ON DELETE SET NULL" in result
    # Update should come before Delete
    assert result.index("UPDATE") < result.index("DELETE")


def test_fk_no_action_omitted(catalog_handler):
    """Test that NO ACTION clauses are omitted from output."""
    handler, oid_gen, executor = catalog_handler

    executor.add_constraint("SQLUser", "users_pkey", "PRIMARY KEY", "users", ["id"])  # Referenced PK
    executor.add_constraint("SQLUser", "posts_author_id_fkey", "FOREIGN KEY", "posts", ["author_id"])
    executor.add_fk_reference("SQLUser", "posts_author_id_fkey", "users", ["id"], "NO ACTION", "NO ACTION")

    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "posts_author_id_fkey")

    result = handler.pg_get_constraintdef(constraint_oid)
    # Should not contain ON UPDATE or ON DELETE
    assert "ON UPDATE" not in result
    assert "ON DELETE" not in result
    assert result == "FOREIGN KEY (author_id) REFERENCES users(id)"


# ============================================================================
# Edge Cases
# ============================================================================


def test_nonexistent_constraint(catalog_handler):
    """Test non-existent constraint OID returns None."""
    handler, oid_gen, executor = catalog_handler

    result = handler.pg_get_constraintdef(99999999)
    assert result is None


def test_invalid_oid_zero(catalog_handler):
    """Test invalid OID (zero) returns None."""
    handler, oid_gen, executor = catalog_handler

    result = handler.pg_get_constraintdef(0)
    assert result is None


def test_invalid_oid_negative(catalog_handler):
    """Test invalid OID (negative) returns None."""
    handler, oid_gen, executor = catalog_handler

    result = handler.pg_get_constraintdef(-1)
    assert result is None


# ============================================================================
# Handler Integration
# ============================================================================


def test_pg_get_constraintdef_via_handler(catalog_handler):
    """Test pg_get_constraintdef through handler interface."""
    handler, oid_gen, executor = catalog_handler

    executor.add_constraint("SQLUser", "users_pkey", "PRIMARY KEY", "users", ["id"])
    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "users_pkey")

    result = handler.handle("pg_get_constraintdef", (str(constraint_oid),))
    assert result.function_name == "pg_get_constraintdef"
    assert result.result == "PRIMARY KEY (id)"
    assert result.error is None


def test_pg_get_constraintdef_with_pretty_false(catalog_handler):
    """Test pg_get_constraintdef with pretty=false."""
    handler, oid_gen, executor = catalog_handler

    executor.add_constraint("SQLUser", "users_pkey", "PRIMARY KEY", "users", ["id"])
    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "users_pkey")

    result = handler.handle("pg_get_constraintdef", (str(constraint_oid), "false"))
    assert result.result == "PRIMARY KEY (id)"


def test_pg_get_constraintdef_with_pretty_true(catalog_handler):
    """Test pg_get_constraintdef with pretty=true (currently ignored)."""
    handler, oid_gen, executor = catalog_handler

    executor.add_constraint("SQLUser", "users_pkey", "PRIMARY KEY", "users", ["id"])
    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "users_pkey")

    # Pretty formatting is not yet implemented, so result should be same
    result = handler.handle("pg_get_constraintdef", (str(constraint_oid), "true"))
    assert result.result == "PRIMARY KEY (id)"


# ============================================================================
# Check Constraints (placeholder)
# ============================================================================


def test_check_constraint_placeholder(catalog_handler):
    """Test CHECK constraint returns placeholder format."""
    handler, oid_gen, executor = catalog_handler

    executor.add_constraint("SQLUser", "age_check", "CHECK", "users", [])

    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "age_check")

    result = handler.pg_get_constraintdef(constraint_oid)
    # Check constraints return placeholder per implementation
    assert result == "CHECK ((expression))"
