"""
Integration Tests: Catalog Router Integration

Tests for catalog router integration with iris_executor.
"""

import pytest


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
