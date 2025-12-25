"""
Contract Tests: pg_attrdef Catalog Emulation

Tests for PostgreSQL pg_attrdef catalog emulation (column defaults).
"""

import pytest


class TestPgAttrdefBasic:
    """TC: Column default value discovery."""

    def test_pg_attrdef_string_default(self):
        """
        Given: Column with string default value
        When: Create attrdef entry
        Then: Return pg_attrdef with correct default expression
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attrdef import PgAttrdefEmulator

        oid_gen = OIDGenerator()
        emulator = PgAttrdefEmulator(oid_gen)

        attrdef = emulator.from_iris_default(
            schema="SQLUser",
            table_name="users",
            column_name="status",
            column_position=4,
            default_value="'active'",
        )

        assert attrdef.adnum == 4
        assert "'active'" in attrdef.adbin or "active" in attrdef.adbin

    def test_pg_attrdef_numeric_default(self):
        """Test numeric default value."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attrdef import PgAttrdefEmulator

        oid_gen = OIDGenerator()
        emulator = PgAttrdefEmulator(oid_gen)

        attrdef = emulator.from_iris_default(
            schema="SQLUser",
            table_name="products",
            column_name="quantity",
            column_position=3,
            default_value="0",
        )

        assert attrdef.adnum == 3
        assert "0" in attrdef.adbin

    def test_pg_attrdef_now_default(self):
        """Test NOW() / CURRENT_TIMESTAMP default."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attrdef import PgAttrdefEmulator

        oid_gen = OIDGenerator()
        emulator = PgAttrdefEmulator(oid_gen)

        attrdef = emulator.from_iris_default(
            schema="SQLUser",
            table_name="events",
            column_name="created_at",
            column_position=5,
            default_value="CURRENT_TIMESTAMP",
        )

        assert attrdef.adnum == 5
        # Should contain timestamp-related default
        assert any(
            x in attrdef.adbin.upper()
            for x in ["NOW", "CURRENT_TIMESTAMP", "TIMESTAMP"]
        )


class TestPgAttrdefOIDConsistency:
    """Test OID consistency for defaults."""

    def test_attrdef_references_correct_table(self):
        """pg_attrdef.adrelid should match table OID."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attrdef import PgAttrdefEmulator

        oid_gen = OIDGenerator()
        emulator = PgAttrdefEmulator(oid_gen)

        attrdef = emulator.from_iris_default(
            schema="SQLUser",
            table_name="users",
            column_name="status",
            column_position=4,
            default_value="'active'",
        )

        expected_table_oid = oid_gen.get_table_oid("SQLUser", "users")
        assert attrdef.adrelid == expected_table_oid


class TestPgAttrdefDataclass:
    """Test PgAttrdef dataclass."""

    def test_pg_attrdef_dataclass_creation(self):
        """Test creating PgAttrdef directly."""
        from iris_pgwire.catalog.pg_attrdef import PgAttrdef

        attrdef = PgAttrdef(
            oid=12345,
            adrelid=11111,
            adnum=3,
            adbin="'default_value'",
        )

        assert attrdef.oid == 12345
        assert attrdef.adrelid == 11111
        assert attrdef.adnum == 3
        assert attrdef.adbin == "'default_value'"


class TestPgAttrdefLookup:
    """Test default lookup methods."""

    def test_get_by_table_oid(self):
        """Get all defaults for a table."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attrdef import PgAttrdefEmulator

        oid_gen = OIDGenerator()
        emulator = PgAttrdefEmulator(oid_gen)

        # Add defaults for users table
        d1 = emulator.from_iris_default(
            "SQLUser", "users", "status", 4, "'active'"
        )
        d2 = emulator.from_iris_default(
            "SQLUser", "users", "created_at", 5, "CURRENT_TIMESTAMP"
        )
        emulator.add_default(d1)
        emulator.add_default(d2)

        # Add default for different table
        d3 = emulator.from_iris_default(
            "SQLUser", "products", "quantity", 3, "0"
        )
        emulator.add_default(d3)

        # Get users defaults
        table_oid = oid_gen.get_table_oid("SQLUser", "users")
        defaults = emulator.get_by_table_oid(table_oid)

        assert len(defaults) == 2

    def test_get_by_column(self):
        """Get default for specific column."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attrdef import PgAttrdefEmulator

        oid_gen = OIDGenerator()
        emulator = PgAttrdefEmulator(oid_gen)

        d1 = emulator.from_iris_default(
            "SQLUser", "users", "status", 4, "'active'"
        )
        emulator.add_default(d1)

        table_oid = oid_gen.get_table_oid("SQLUser", "users")
        attrdef = emulator.get_by_column(table_oid, 4)

        assert attrdef is not None
        assert attrdef.adnum == 4


class TestPgAttrdefSequenceDefault:
    """Test sequence/serial defaults."""

    def test_nextval_sequence_default(self):
        """Test nextval() sequence default for SERIAL columns."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attrdef import PgAttrdefEmulator

        oid_gen = OIDGenerator()
        emulator = PgAttrdefEmulator(oid_gen)

        # IRIS auto-increment is translated to nextval()
        attrdef = emulator.from_iris_default(
            schema="SQLUser",
            table_name="users",
            column_name="id",
            column_position=1,
            default_value="$IDENTITY",  # IRIS auto-increment marker
        )

        assert attrdef.adnum == 1
        # Should contain nextval for sequence
        assert "nextval" in attrdef.adbin.lower()
