"""
Contract Tests: pg_class Catalog Emulation

Tests for PostgreSQL pg_class catalog emulation per pg_class_contract.md.
"""

import pytest


class TestPgClassTableEnumeration:
    """TC-1: Basic table enumeration."""

    def test_pg_class_from_iris_table(self):
        """
        Given: IRIS table metadata
        When: Convert to pg_class row
        Then: Return PgClass with correct fields
        """
        from iris_pgwire.schema_mapper import IRIS_SCHEMA
        from iris_pgwire.schema_mapper import IRIS_SCHEMA
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        oid_gen = OIDGenerator()
        emulator = PgClassEmulator(oid_gen)

        pg_class = emulator.from_iris_table("users", "BASE TABLE", IRIS_SCHEMA)
        emulator.add_table(pg_class)

        found = emulator.get_by_name("users")
        assert found is not None
        assert found.relname == "users"

        not_found = emulator.get_by_name("nonexistent")
        assert not_found is None

    def test_get_by_oid(self):
        """Test lookup by OID."""
        from iris_pgwire.schema_mapper import IRIS_SCHEMA
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        oid_gen = OIDGenerator()
        emulator = PgClassEmulator(oid_gen)

        pg_class = emulator.from_iris_table("users", "BASE TABLE", IRIS_SCHEMA)
        emulator.add_table(pg_class)

        found = emulator.get_by_oid(pg_class.oid)
        assert found is not None
        assert found.relname == "users"

        not_found = emulator.get_by_oid(99999)
        assert not_found is None


class TestPgClassRelkindMapping:
    """Test relkind mapping for different object types."""

    def test_relkind_base_table(self):
        """BASE TABLE -> 'r'"""
        from iris_pgwire.schema_mapper import IRIS_SCHEMA
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        emulator = PgClassEmulator(OIDGenerator())
        pg_class = emulator.from_iris_table("t", "BASE TABLE", IRIS_SCHEMA)
        assert pg_class.relkind == "r"

    def test_relkind_view(self):
        """VIEW -> 'v'"""
        from iris_pgwire.schema_mapper import IRIS_SCHEMA
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        emulator = PgClassEmulator(OIDGenerator())
        pg_class = emulator.from_iris_table("v", "VIEW", IRIS_SCHEMA)
        assert pg_class.relkind == "v"

    def test_relkind_index(self):
        """Test creating index entry."""
        from iris_pgwire.schema_mapper import IRIS_SCHEMA
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        emulator = PgClassEmulator(OIDGenerator())
        pg_class = emulator.create_index_entry(
            table_name="users",
            index_name="users_pkey",
            num_columns=1,
            schema=IRIS_SCHEMA,
        )
        assert pg_class.relkind == "i"
        assert pg_class.relam == 403  # btree
