"""
Integration Tests: Catalog Functions Integration

Tests for catalog functions integration with iris_executor and ORMs.
Validates end-to-end catalog function behavior.
"""

import pytest


class TestCatalogFunctionsIntegration:
    """Test catalog functions integration with real executor."""

    @pytest.fixture
    def mock_executor(self):
        """Create mock executor for testing."""
        from unittest.mock import Mock

        executor = Mock()

        # Mock INFORMATION_SCHEMA queries
        def execute_query(query):
            query_upper = query.upper()

            # Mock for constraint queries
            if "TABLE_CONSTRAINTS" in query_upper:
                return {
                    "success": True,
                    "rows": [
                        ("SQLUser", "users_pkey", "PRIMARY KEY", "users"),
                        ("SQLUser", "posts_author_fkey", "FOREIGN KEY", "posts"),
                    ]
                }

            # Mock for column queries (for constraints)
            if "KEY_COLUMN_USAGE" in query_upper:
                # Check for constraint name in WHERE clause
                if "'USERS_PKEY'" in query_upper or "'users_pkey'" in query_upper:
                    return {"success": True, "rows": [("id",)]}
                if "'POSTS_AUTHOR_FKEY'" in query_upper or "'posts_author_fkey'" in query_upper:
                    return {"success": True, "rows": [("author_id",)]}
                # Return all columns if no specific constraint filter
                return {"success": True, "rows": [("id",), ("author_id",)]}

            # Mock for FK reference queries
            if "REFERENTIAL_CONSTRAINTS" in query_upper:
                return {
                    "success": True,
                    "rows": [("SQLUser", "users_pkey", "NO ACTION", "CASCADE")]
                }

            # Mock for IDENTITY column queries
            if "IS_IDENTITY" in query_upper:
                return {"success": True, "rows": [(None, "YES")]}

            return {"success": True, "rows": []}

        executor._execute_iris_query = execute_query
        return executor

    @pytest.fixture
    def catalog_handler(self, mock_executor):
        """Create catalog function handler."""
        from iris_pgwire.catalog.catalog_functions import CatalogFunctionHandler
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        oid_gen = OIDGenerator()
        return CatalogFunctionHandler(oid_gen, mock_executor)

    def test_format_type_integration(self, catalog_handler):
        """Test format_type through handler interface."""
        # Test basic type
        result = catalog_handler.handle("format_type", ("23", "-1"))
        assert result.error is None
        assert result.result == "integer"

        # Test parameterized type
        result = catalog_handler.handle("format_type", ("1043", "259"))
        assert result.error is None
        assert result.result == "character varying(255)"

    def test_pg_get_constraintdef_integration(self, catalog_handler):
        """Test pg_get_constraintdef with mock INFORMATION_SCHEMA."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        oid_gen = OIDGenerator()
        constraint_oid = oid_gen.get_constraint_oid("SQLUser", "users_pkey")

        result = catalog_handler.pg_get_constraintdef(constraint_oid)
        assert result == "PRIMARY KEY (id)"

    def test_pg_get_serial_sequence_integration(self, catalog_handler):
        """Test pg_get_serial_sequence with mock INFORMATION_SCHEMA."""
        result = catalog_handler.pg_get_serial_sequence("users", "id")
        assert result == "public.users_id_seq"

    def test_catalog_function_error_handling(self, catalog_handler):
        """Test catalog function error handling."""
        # Test with invalid OID
        result = catalog_handler.handle("format_type", ("99999", "-1"))
        assert result.error is None
        assert result.result is None

        # Test with invalid function name
        result = catalog_handler.handle("nonexistent_function", ("arg1",))
        assert result.error is not None


class TestCatalogRouterIntegration:
    """Test catalog router integration."""

    def test_catalog_router_can_be_imported(self):
        """CatalogRouter can be imported and instantiated."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()
        assert router is not None

    def test_catalog_emulators_can_be_imported(self):
        """All catalog emulators can be imported."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attrdef import PgAttrdefEmulator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator
        from iris_pgwire.catalog.pg_class import PgClassEmulator
        from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator
        from iris_pgwire.catalog.pg_index import PgIndexEmulator
        from iris_pgwire.catalog.pg_namespace import PgNamespaceEmulator

        oid_gen = OIDGenerator()

        # All emulators should instantiate without error
        assert PgNamespaceEmulator() is not None
        assert PgClassEmulator(oid_gen) is not None
        assert PgAttributeEmulator(oid_gen) is not None
        assert PgConstraintEmulator(oid_gen) is not None
        assert PgIndexEmulator(oid_gen) is not None
        assert PgAttrdefEmulator(oid_gen) is not None

    def test_catalog_router_detects_prisma_introspection_query(self):
        """CatalogRouter correctly identifies Prisma introspection queries."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        # Sample Prisma introspection query
        prisma_query = """
        SELECT
            c.relname AS table_name,
            n.nspname AS schema_name,
            c.oid AS table_oid
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
        AND c.relkind IN ('r', 'v')
        ORDER BY c.relname
        """

        assert router.can_handle(prisma_query) is True

        tables = router.extract_catalog_tables(prisma_query)
        assert "pg_class" in tables
        assert "pg_namespace" in tables

    def test_catalog_module_public_api(self):
        """Catalog module exposes expected public API."""
        # This tests the __init__.py lazy imports work correctly
        from iris_pgwire.catalog import (
            CatalogRouter,
            OIDGenerator,
            PgAttrdefEmulator,
            PgAttributeEmulator,
            PgClassEmulator,
            PgConstraintEmulator,
            PgIndexEmulator,
            PgNamespaceEmulator,
        )

        # All should be accessible from the module
        assert CatalogRouter is not None
        assert OIDGenerator is not None
        assert PgNamespaceEmulator is not None
        assert PgClassEmulator is not None
        assert PgAttributeEmulator is not None
        assert PgConstraintEmulator is not None
        assert PgIndexEmulator is not None
        assert PgAttrdefEmulator is not None
