"""
Contract Tests: Catalog Router

Tests for routing pg_catalog queries to appropriate emulators.
"""

import pytest


class TestCatalogRouterDetection:
    """Test pg_catalog query detection."""

    def test_can_handle_pg_class_query(self):
        """Router should detect pg_catalog.pg_class queries."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        query = "SELECT * FROM pg_catalog.pg_class WHERE relname = 'users'"
        assert router.can_handle(query) is True

    def test_can_handle_pg_attribute_query(self):
        """Router should detect pg_attribute queries."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        query = "SELECT attname FROM pg_attribute WHERE attrelid = 12345"
        assert router.can_handle(query) is True

    def test_cannot_handle_regular_query(self):
        """Router should not handle regular SQL queries."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        query = "SELECT * FROM users WHERE id = 1"
        assert router.can_handle(query) is False

    def test_can_handle_information_schema_query(self):
        """Router should detect information_schema queries."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        # Prisma often queries information_schema first
        query = "SELECT * FROM information_schema.tables"
        assert router.can_handle(query) is True


class TestCatalogRouterParsing:
    """Test query parsing for catalog table extraction."""

    def test_extract_catalog_table_from_pg_class(self):
        """Extract pg_class from query."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        query = "SELECT * FROM pg_catalog.pg_class"
        tables = router.extract_catalog_tables(query)

        assert "pg_class" in tables

    def test_extract_multiple_catalog_tables(self):
        """Extract multiple catalog tables from JOIN query."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        query = """
        SELECT c.relname, a.attname
        FROM pg_class c
        JOIN pg_attribute a ON a.attrelid = c.oid
        """
        tables = router.extract_catalog_tables(query)

        assert "pg_class" in tables
        assert "pg_attribute" in tables


class TestCatalogRouterJoinQueries:
    """Test JOIN query handling across catalog tables."""

    def test_join_pg_class_pg_attribute(self):
        """Handle pg_class JOIN pg_attribute queries."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        # Typical Prisma introspection query
        query = """
        SELECT c.relname, a.attname, a.atttypid
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid
        WHERE n.nspname = 'public'
        AND c.relkind = 'r'
        AND a.attnum > 0
        """

        assert router.can_handle(query) is True
        tables = router.extract_catalog_tables(query)

        assert "pg_class" in tables
        assert "pg_namespace" in tables
        assert "pg_attribute" in tables


class TestCatalogRouterArrayParams:
    """Test array parameter handling."""

    def test_detect_any_array_param(self):
        """Detect ANY($1) array parameter pattern."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        # Prisma uses this pattern for IN clauses
        query = "SELECT * FROM pg_class WHERE oid = ANY($1)"

        assert router.has_array_param(query) is True

    def test_translate_any_to_in(self):
        """Translate ANY($1) to IN clause."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        query = "SELECT * FROM pg_class WHERE oid = ANY($1)"
        values = [16384, 16385, 16386]

        translated = router.translate_array_param(query, values)

        assert "IN" in translated
        assert "ANY" not in translated


class TestCatalogRouterRegclass:
    """Test ::regclass cast handling."""

    def test_detect_regclass_cast(self):
        """Detect ::regclass cast in query."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        query = "SELECT * FROM pg_attribute WHERE attrelid = 'users'::regclass"

        assert router.has_regclass_cast(query) is True

    def test_resolve_regclass_literal(self):
        """Resolve 'tablename'::regclass to OID."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        oid_gen = OIDGenerator()
        router = CatalogRouter(oid_generator=oid_gen)

        # Register a table first
        table_oid = oid_gen.get_table_oid("SQLUser", "users")

        # Resolve the regclass
        resolved_oid = router.resolve_regclass("users", schema="SQLUser")

        assert resolved_oid == table_oid


class TestCatalogRouterCaseInsensitivity:
    """Test case-insensitive query handling."""

    def test_pg_catalog_case_variations(self):
        """Handle various case combinations."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()

        queries = [
            "SELECT * FROM PG_CATALOG.PG_CLASS",
            "SELECT * FROM Pg_Catalog.Pg_Class",
            "SELECT * FROM pg_catalog.PG_CLASS",
        ]

        for query in queries:
            assert router.can_handle(query) is True, f"Failed for: {query}"
