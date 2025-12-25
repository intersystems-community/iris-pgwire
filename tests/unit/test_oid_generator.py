"""
Unit Tests: OID Generator

Tests for deterministic OID generation per oid_generator_contract.md.
"""

import pytest


class TestOIDGeneratorBasic:
    """TC-1: Basic OID generation behavior."""

    def test_oid_generation_returns_int(self):
        """
        Given: Object identity (schema, type, name)
        When: Generate OID
        Then: Return valid 32-bit unsigned integer >= 16384
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()
        oid = gen.get_oid("SQLUser", "table", "users")

        assert isinstance(oid, int)
        assert 16384 <= oid <= 4294967295

    def test_oid_generation_different_types(self):
        """Test OID generation for different object types."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()

        table_oid = gen.get_oid("SQLUser", "table", "users")
        column_oid = gen.get_oid("SQLUser", "column", "users.id")
        constraint_oid = gen.get_oid("SQLUser", "constraint", "users_pkey")

        # All should be valid OIDs
        for oid in [table_oid, column_oid, constraint_oid]:
            assert isinstance(oid, int)
            assert oid >= 16384


class TestOIDDeterminism:
    """TC-2: OID determinism across instances."""

    def test_oid_determinism_same_instance(self):
        """
        Given: Same object identity
        When: Generate OID multiple times from same instance
        Then: Return same value each time
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()

        oid1 = gen.get_oid("SQLUser", "table", "users")
        oid2 = gen.get_oid("SQLUser", "table", "users")

        assert oid1 == oid2

    def test_oid_determinism_different_instances(self):
        """
        Given: Same object identity
        When: Generate OID from different generator instances
        Then: Return same value
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen1 = OIDGenerator()
        gen2 = OIDGenerator()  # Fresh instance

        oid1 = gen1.get_oid("SQLUser", "table", "users")
        oid2 = gen2.get_oid("SQLUser", "table", "users")

        assert oid1 == oid2


class TestOIDUniqueness:
    """TC-3: OID uniqueness for different objects."""

    def test_oid_uniqueness_different_tables(self):
        """
        Given: Different table names
        When: Generate OIDs
        Then: Return unique values
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()

        oids = [
            gen.get_oid("SQLUser", "table", "users"),
            gen.get_oid("SQLUser", "table", "orders"),
            gen.get_oid("SQLUser", "table", "products"),
        ]

        assert len(oids) == len(set(oids))  # All unique

    def test_oid_uniqueness_different_object_types(self):
        """
        Given: Same name but different object types
        When: Generate OIDs
        Then: Return unique values
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()

        oids = [
            gen.get_oid("SQLUser", "table", "users"),
            gen.get_oid("SQLUser", "column", "users.id"),
            gen.get_oid("SQLUser", "column", "users.name"),
            gen.get_oid("SQLUser", "constraint", "users_pkey"),
        ]

        assert len(oids) == len(set(oids))  # All unique

    def test_oid_uniqueness_large_batch(self):
        """Test uniqueness with many objects."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()

        # Generate OIDs for 100 tables
        oids = [gen.get_oid("SQLUser", "table", f"table_{i}") for i in range(100)]

        assert len(oids) == len(set(oids))  # All unique


class TestWellKnownNamespaceOIDs:
    """TC-4: Well-known namespace OIDs."""

    def test_pg_catalog_namespace_oid(self):
        """pg_catalog should return OID 11."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()
        assert gen.get_namespace_oid("pg_catalog") == 11

    def test_public_namespace_oid(self):
        """public should return OID 2200."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()
        assert gen.get_namespace_oid("public") == 2200

    def test_information_schema_namespace_oid(self):
        """information_schema should return OID 11323."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()
        assert gen.get_namespace_oid("information_schema") == 11323

    def test_custom_namespace_oid(self):
        """Custom namespaces should return generated OID >= 16384."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()
        custom_oid = gen.get_namespace_oid("my_custom_schema")

        assert custom_oid >= 16384


class TestOIDCache:
    """TC-5: Cache behavior."""

    def test_oid_cache_stores_values(self):
        """
        Given: OID generator with cache
        When: Request same OID multiple times
        Then: Return cached value
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()

        # First call generates and caches
        oid1 = gen.get_oid("SQLUser", "table", "users")

        # Verify cache contains the key
        assert len(gen._cache) > 0

        # Second call returns cached
        oid2 = gen.get_oid("SQLUser", "table", "users")

        assert oid1 == oid2


class TestCaseHandling:
    """TC-6: Case sensitivity handling."""

    def test_case_normalization(self):
        """
        Given: Object names with different cases
        When: Generate OIDs
        Then: Treat as same (normalized to lowercase)
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()

        # PostgreSQL is case-insensitive for unquoted identifiers
        oid_lower = gen.get_oid("SQLUser", "table", "users")
        oid_upper = gen.get_oid("SQLUser", "table", "USERS")
        oid_mixed = gen.get_oid("SQLUser", "table", "Users")

        # All should be same (normalized)
        assert oid_lower == oid_upper == oid_mixed


class TestColumnOIDFormat:
    """TC-7: Column OID format."""

    def test_column_oid_table_column_format(self):
        """
        Given: Column identity with table.column format
        When: Generate OID
        Then: Return unique OID for each column
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()

        oid_id = gen.get_oid("SQLUser", "column", "users.id")
        oid_name = gen.get_oid("SQLUser", "column", "users.name")
        oid_other = gen.get_oid("SQLUser", "column", "orders.id")

        # Different columns same table
        assert oid_id != oid_name

        # Same column name different table
        assert oid_id != oid_other


class TestObjectIdentity:
    """Tests for ObjectIdentity dataclass."""

    def test_object_identity_creation(self):
        """Test ObjectIdentity dataclass creation."""
        from iris_pgwire.catalog.oid_generator import ObjectIdentity

        identity = ObjectIdentity(
            namespace="SQLUser", object_type="table", object_name="users"
        )

        assert identity.namespace == "SQLUser"
        assert identity.object_type == "table"
        assert identity.object_name == "users"

    def test_object_identity_string(self):
        """Test identity_string property."""
        from iris_pgwire.catalog.oid_generator import ObjectIdentity

        identity = ObjectIdentity(
            namespace="SQLUser", object_type="table", object_name="users"
        )

        assert identity.identity_string == "SQLUser:table:users"

    def test_object_identity_with_oid_generator(self):
        """Test using ObjectIdentity with OIDGenerator."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator, ObjectIdentity

        gen = OIDGenerator()
        identity = ObjectIdentity(
            namespace="SQLUser", object_type="table", object_name="users"
        )

        oid = gen.get_oid_from_identity(identity)

        assert isinstance(oid, int)
        assert oid >= 16384


class TestTableOIDShortcut:
    """Tests for get_table_oid convenience method."""

    def test_get_table_oid(self):
        """Test get_table_oid shortcut method."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()

        table_oid = gen.get_table_oid("SQLUser", "users")
        direct_oid = gen.get_oid("SQLUser", "table", "users")

        assert table_oid == direct_oid

    def test_get_table_oid_valid_range(self):
        """Table OID should be in valid user range."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator

        gen = OIDGenerator()
        oid = gen.get_table_oid("SQLUser", "users")

        assert oid >= 16384
