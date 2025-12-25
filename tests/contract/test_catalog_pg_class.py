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
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        oid_gen = OIDGenerator()
        emulator = PgClassEmulator(oid_gen)

        pg_class = emulator.from_iris_table(
            schema="SQLUser",
            table_name="users",
            table_type="BASE TABLE",
        )

        assert pg_class.relname == "users"
        assert pg_class.relkind == "r"  # ordinary table
        assert pg_class.relnamespace == 2200  # public
        assert pg_class.oid >= 16384  # user OID range

    def test_pg_class_view_type(self):
        """Test view type mapping."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        oid_gen = OIDGenerator()
        emulator = PgClassEmulator(oid_gen)

        pg_class = emulator.from_iris_table(
            schema="SQLUser",
            table_name="users_view",
            table_type="VIEW",
        )

        assert pg_class.relkind == "v"  # view

    def test_pg_class_lowercase_name(self):
        """Test that table names are lowercased."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        oid_gen = OIDGenerator()
        emulator = PgClassEmulator(oid_gen)

        pg_class = emulator.from_iris_table(
            schema="SQLUser",
            table_name="MyTable",
            table_type="BASE TABLE",
        )

        assert pg_class.relname == "mytable"


class TestPgClassOIDStability:
    """TC-2: OID consistency tests."""

    def test_pg_class_oid_stability(self):
        """
        Given: Same table metadata
        When: Create pg_class multiple times
        Then: Same OID returned each time
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        oid_gen = OIDGenerator()
        emulator = PgClassEmulator(oid_gen)

        pg_class1 = emulator.from_iris_table("SQLUser", "users", "BASE TABLE")
        pg_class2 = emulator.from_iris_table("SQLUser", "users", "BASE TABLE")

        assert pg_class1.oid == pg_class2.oid

    def test_pg_class_oid_stability_different_instances(self):
        """OID should be stable across emulator instances."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        emulator1 = PgClassEmulator(OIDGenerator())
        emulator2 = PgClassEmulator(OIDGenerator())

        pg_class1 = emulator1.from_iris_table("SQLUser", "users", "BASE TABLE")
        pg_class2 = emulator2.from_iris_table("SQLUser", "users", "BASE TABLE")

        assert pg_class1.oid == pg_class2.oid


class TestPgClassEmptySchema:
    """TC-4: Empty schema handling."""

    def test_pg_class_no_tables(self):
        """
        Given: Empty table list
        When: Get all tables
        Then: Return empty list (not error)
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        oid_gen = OIDGenerator()
        emulator = PgClassEmulator(oid_gen)

        # Don't add any tables
        rows = emulator.get_all_as_rows()

        assert isinstance(rows, list)
        assert len(rows) == 0


class TestPgClassDataclass:
    """PgClass dataclass tests."""

    def test_pg_class_dataclass_fields(self):
        """Test PgClass dataclass has all required fields."""
        from iris_pgwire.catalog.pg_class import PgClass

        pg_class = PgClass(
            oid=12345,
            relname="users",
            relnamespace=2200,
            reltype=0,
            reloftype=0,
            relowner=10,
            relam=0,
            relfilenode=12345,
            reltablespace=0,
            relpages=1,
            reltuples=0.0,
            relallvisible=0,
            reltoastrelid=0,
            relhasindex=False,
            relisshared=False,
            relpersistence="p",
            relkind="r",
            relnatts=0,
            relchecks=0,
            relhasrules=False,
            relhastriggers=False,
            relhassubclass=False,
            relrowsecurity=False,
            relforcerowsecurity=False,
            relispopulated=True,
            relreplident="d",
            relispartition=False,
            relrewrite=0,
            relfrozenxid=0,
            relminmxid=0,
            relacl=None,
            reloptions=None,
        )

        assert pg_class.oid == 12345
        assert pg_class.relname == "users"
        assert pg_class.relnamespace == 2200
        assert pg_class.relkind == "r"


class TestPgClassResultFormat:
    """Test result formatting for pg_class queries."""

    def test_pg_class_to_row(self):
        """Test converting PgClass to query result row."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        oid_gen = OIDGenerator()
        emulator = PgClassEmulator(oid_gen)

        # Add a table
        pg_class = emulator.from_iris_table("SQLUser", "users", "BASE TABLE")
        emulator.add_table(pg_class)

        rows = emulator.get_all_as_rows()

        assert len(rows) == 1
        row = rows[0]

        # Check key fields in row
        assert row[0] == pg_class.oid  # oid
        assert row[1] == "users"  # relname
        assert row[2] == 2200  # relnamespace

    def test_get_by_name(self):
        """Test lookup by name."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        oid_gen = OIDGenerator()
        emulator = PgClassEmulator(oid_gen)

        pg_class = emulator.from_iris_table("SQLUser", "users", "BASE TABLE")
        emulator.add_table(pg_class)

        found = emulator.get_by_name("users")
        assert found is not None
        assert found.relname == "users"

        not_found = emulator.get_by_name("nonexistent")
        assert not_found is None

    def test_get_by_oid(self):
        """Test lookup by OID."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        oid_gen = OIDGenerator()
        emulator = PgClassEmulator(oid_gen)

        pg_class = emulator.from_iris_table("SQLUser", "users", "BASE TABLE")
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
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        emulator = PgClassEmulator(OIDGenerator())
        pg_class = emulator.from_iris_table("SQLUser", "t", "BASE TABLE")
        assert pg_class.relkind == "r"

    def test_relkind_view(self):
        """VIEW -> 'v'"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        emulator = PgClassEmulator(OIDGenerator())
        pg_class = emulator.from_iris_table("SQLUser", "v", "VIEW")
        assert pg_class.relkind == "v"

    def test_relkind_index(self):
        """Test creating index entry."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_class import PgClassEmulator

        emulator = PgClassEmulator(OIDGenerator())
        pg_class = emulator.create_index_entry(
            schema="SQLUser",
            table_name="users",
            index_name="users_pkey",
            num_columns=1,
        )
        assert pg_class.relkind == "i"
        assert pg_class.relam == 403  # btree
