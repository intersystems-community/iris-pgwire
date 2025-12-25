"""
Contract Tests: pg_index Catalog Emulation

Tests for PostgreSQL pg_index catalog emulation.
"""

import pytest


class TestPgIndexPrimaryKey:
    """TC: Primary key index discovery."""

    def test_pg_index_from_primary_key(self):
        """
        Given: Table with primary key
        When: Create index for PK
        Then: Return pg_index entry with correct flags
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_index import PgIndexEmulator

        oid_gen = OIDGenerator()
        emulator = PgIndexEmulator(oid_gen)

        index_class, pg_index = emulator.from_primary_key(
            schema="SQLUser",
            table_name="users",
            constraint_name="pkey",
            column_positions=[1],
        )

        # Verify pg_index entry
        assert pg_index.indisprimary is True
        assert pg_index.indisunique is True
        assert pg_index.indkey == [1]

        # Verify index class entry
        assert index_class.relkind == "i"  # index
        assert "users" in index_class.relname

    def test_pg_index_composite_primary_key(self):
        """Test composite primary key index."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_index import PgIndexEmulator

        oid_gen = OIDGenerator()
        emulator = PgIndexEmulator(oid_gen)

        index_class, pg_index = emulator.from_primary_key(
            schema="SQLUser",
            table_name="order_items",
            constraint_name="pkey",
            column_positions=[1, 2],
        )

        assert pg_index.indisprimary is True
        assert pg_index.indkey == [1, 2]
        assert pg_index.indnatts == 2


class TestPgIndexOIDConsistency:
    """Test OID consistency between pg_class and pg_index."""

    def test_index_class_and_pg_index_have_same_oid(self):
        """pg_class.oid should equal pg_index.indexrelid."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_index import PgIndexEmulator

        oid_gen = OIDGenerator()
        emulator = PgIndexEmulator(oid_gen)

        index_class, pg_index = emulator.from_primary_key(
            "SQLUser", "users", "pkey", [1]
        )

        assert index_class.oid == pg_index.indexrelid

    def test_index_references_correct_table(self):
        """pg_index.indrelid should match table OID."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_index import PgIndexEmulator

        oid_gen = OIDGenerator()
        emulator = PgIndexEmulator(oid_gen)

        index_class, pg_index = emulator.from_primary_key(
            "SQLUser", "users", "pkey", [1]
        )

        expected_table_oid = oid_gen.get_table_oid("SQLUser", "users")
        assert pg_index.indrelid == expected_table_oid


class TestPgIndexDataclass:
    """Test PgIndex dataclass."""

    def test_pg_index_dataclass_creation(self):
        """Test creating PgIndex directly."""
        from iris_pgwire.catalog.pg_index import PgIndex

        pg_index = PgIndex(
            indexrelid=12345,
            indrelid=11111,
            indnatts=1,
            indnkeyatts=1,
            indisunique=True,
            indisprimary=True,
            indisexclusion=False,
            indimmediate=True,
            indisclustered=False,
            indisvalid=True,
            indcheckxmin=False,
            indisready=True,
            indislive=True,
            indisreplident=False,
            indkey=[1],
            indcollation=[0],
            indclass=[1978],
            indoption=[0],
            indexprs=None,
            indpred=None,
        )

        assert pg_index.indexrelid == 12345
        assert pg_index.indrelid == 11111
        assert pg_index.indisprimary is True


class TestPgIndexLookup:
    """Test index lookup methods."""

    def test_get_by_table_oid(self):
        """Get all indexes for a table."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_index import PgIndexEmulator

        oid_gen = OIDGenerator()
        emulator = PgIndexEmulator(oid_gen)

        # Add index for users table
        idx1_class, idx1 = emulator.from_primary_key(
            "SQLUser", "users", "pkey", [1]
        )
        emulator.add_index(idx1_class, idx1)

        # Add index for orders table
        idx2_class, idx2 = emulator.from_primary_key(
            "SQLUser", "orders", "pkey", [1]
        )
        emulator.add_index(idx2_class, idx2)

        # Get users indexes
        table_oid = oid_gen.get_table_oid("SQLUser", "users")
        indexes = emulator.get_by_table_oid(table_oid)

        assert len(indexes) == 1
        assert indexes[0].indrelid == table_oid


class TestPgIndexUniqueIndex:
    """Test unique index creation."""

    def test_unique_index(self):
        """Test creating unique (non-primary) index."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_index import PgIndexEmulator

        oid_gen = OIDGenerator()
        emulator = PgIndexEmulator(oid_gen)

        index_class, pg_index = emulator.from_unique_constraint(
            schema="SQLUser",
            table_name="users",
            constraint_name="email_unique",
            column_positions=[3],  # email column
        )

        assert pg_index.indisunique is True
        assert pg_index.indisprimary is False
        assert pg_index.indkey == [3]
