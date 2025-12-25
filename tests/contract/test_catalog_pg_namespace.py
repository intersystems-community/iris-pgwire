"""
Contract Tests: pg_namespace Catalog Emulation

Tests for PostgreSQL namespace/schema catalog emulation.
"""

import pytest


class TestPgNamespaceBasic:
    """Basic pg_namespace functionality tests."""

    def test_pg_namespace_returns_public_schema(self):
        """
        Given: Default pg_namespace emulator
        When: Get all namespaces
        Then: 'public' schema should be present with OID 2200
        """
        from iris_pgwire.catalog.pg_namespace import PgNamespaceEmulator

        emulator = PgNamespaceEmulator()
        namespaces = emulator.get_all()

        public_ns = [ns for ns in namespaces if ns.nspname == "public"]
        assert len(public_ns) == 1
        assert public_ns[0].oid == 2200

    def test_pg_namespace_returns_pg_catalog(self):
        """
        Given: Default pg_namespace emulator
        When: Get all namespaces
        Then: 'pg_catalog' schema should be present with OID 11
        """
        from iris_pgwire.catalog.pg_namespace import PgNamespaceEmulator

        emulator = PgNamespaceEmulator()
        namespaces = emulator.get_all()

        pg_catalog_ns = [ns for ns in namespaces if ns.nspname == "pg_catalog"]
        assert len(pg_catalog_ns) == 1
        assert pg_catalog_ns[0].oid == 11

    def test_pg_namespace_returns_information_schema(self):
        """
        Given: Default pg_namespace emulator
        When: Get all namespaces
        Then: 'information_schema' should be present with OID 11323
        """
        from iris_pgwire.catalog.pg_namespace import PgNamespaceEmulator

        emulator = PgNamespaceEmulator()
        namespaces = emulator.get_all()

        info_schema_ns = [ns for ns in namespaces if ns.nspname == "information_schema"]
        assert len(info_schema_ns) == 1
        assert info_schema_ns[0].oid == 11323


class TestPgNamespaceLookup:
    """pg_namespace lookup tests."""

    def test_get_by_name_public(self):
        """Test lookup by name for public schema."""
        from iris_pgwire.catalog.pg_namespace import PgNamespaceEmulator

        emulator = PgNamespaceEmulator()
        ns = emulator.get_by_name("public")

        assert ns is not None
        assert ns.nspname == "public"
        assert ns.oid == 2200

    def test_get_by_name_not_found(self):
        """Test lookup by name returns None for unknown schema."""
        from iris_pgwire.catalog.pg_namespace import PgNamespaceEmulator

        emulator = PgNamespaceEmulator()
        ns = emulator.get_by_name("nonexistent_schema")

        assert ns is None

    def test_get_by_oid_2200(self):
        """Test lookup by OID for public schema."""
        from iris_pgwire.catalog.pg_namespace import PgNamespaceEmulator

        emulator = PgNamespaceEmulator()
        ns = emulator.get_by_oid(2200)

        assert ns is not None
        assert ns.nspname == "public"

    def test_get_by_oid_not_found(self):
        """Test lookup by OID returns None for unknown OID."""
        from iris_pgwire.catalog.pg_namespace import PgNamespaceEmulator

        emulator = PgNamespaceEmulator()
        ns = emulator.get_by_oid(99999)

        assert ns is None


class TestPgNamespaceDataclass:
    """PgNamespace dataclass tests."""

    def test_pg_namespace_dataclass_creation(self):
        """Test PgNamespace dataclass creation."""
        from iris_pgwire.catalog.pg_namespace import PgNamespace

        ns = PgNamespace(
            oid=2200,
            nspname="public",
            nspowner=10,
            nspacl=None,
        )

        assert ns.oid == 2200
        assert ns.nspname == "public"
        assert ns.nspowner == 10
        assert ns.nspacl is None

    def test_pg_namespace_with_acl(self):
        """Test PgNamespace with ACL."""
        from iris_pgwire.catalog.pg_namespace import PgNamespace

        ns = PgNamespace(
            oid=12345,
            nspname="custom",
            nspowner=10,
            nspacl="{admin=UC/admin}",
        )

        assert ns.nspacl == "{admin=UC/admin}"


class TestPgNamespaceResultFormat:
    """Test result formatting for pg_namespace queries."""

    def test_namespace_to_row(self):
        """Test converting namespace to query result row."""
        from iris_pgwire.catalog.pg_namespace import PgNamespaceEmulator

        emulator = PgNamespaceEmulator()
        rows = emulator.get_all_as_rows()

        # Should return list of tuples
        assert isinstance(rows, list)
        assert len(rows) >= 3  # At least pg_catalog, public, information_schema

        # Each row should have (oid, nspname, nspowner, nspacl)
        for row in rows:
            assert len(row) == 4
            assert isinstance(row[0], int)  # oid
            assert isinstance(row[1], str)  # nspname
            assert isinstance(row[2], int)  # nspowner
