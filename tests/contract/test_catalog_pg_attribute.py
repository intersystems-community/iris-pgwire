"""
Contract Tests: pg_attribute Catalog Emulation

Tests for PostgreSQL pg_attribute catalog emulation per pg_attribute_contract.md.
"""

import pytest


class TestPgAttributeColumnEnumeration:
    """TC-1: Basic column enumeration."""

    def test_pg_attribute_from_iris_column(self):
        """
        Given: IRIS column metadata
        When: Convert to pg_attribute row
        Then: Return PgAttribute with correct fields
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        oid_gen = OIDGenerator()
        emulator = PgAttributeEmulator(oid_gen)

        attr = emulator.from_iris_column(
            schema="SQLUser",
            table_name="users",
            column_name="id",
            data_type="INTEGER",
            ordinal_position=1,
            is_nullable="NO",
            column_default=None,
        )

        assert attr.attname == "id"
        assert attr.attnum == 1
        assert attr.atttypid == 23  # int4
        assert attr.attnotnull is True
        assert attr.atthasdef is False

    def test_pg_attribute_multiple_columns(self):
        """Test creating attributes for multiple columns."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        oid_gen = OIDGenerator()
        emulator = PgAttributeEmulator(oid_gen)

        columns = [
            ("id", "INTEGER", 1, "NO", None),
            ("name", "VARCHAR(100)", 2, "YES", None),
            ("email", "VARCHAR(255)", 3, "NO", None),
        ]

        for col_name, data_type, pos, nullable, default in columns:
            attr = emulator.from_iris_column(
                "SQLUser", "users", col_name, data_type, pos, nullable, default
            )
            emulator.add_attribute(attr)

        rows = emulator.get_all_as_rows()
        assert len(rows) == 3


class TestPgAttributeNotNull:
    """TC-2: NOT NULL detection."""

    def test_attnotnull_true_for_not_null_column(self):
        """IS_NULLABLE='NO' -> attnotnull=True"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "INTEGER", 1, "NO", None
        )

        assert attr.attnotnull is True

    def test_attnotnull_false_for_nullable_column(self):
        """IS_NULLABLE='YES' -> attnotnull=False"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "INTEGER", 1, "YES", None
        )

        assert attr.attnotnull is False


class TestPgAttributeTypeModifier:
    """TC-3: Type modifier (atttypmod) for VARCHAR."""

    def test_varchar_typmod(self):
        """VARCHAR(255) -> atttypmod = 259 (255 + 4)"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "VARCHAR(255)", 1, "YES", None
        )

        assert attr.atttypmod == 259  # 255 + 4

    def test_varchar_100_typmod(self):
        """VARCHAR(100) -> atttypmod = 104"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "VARCHAR(100)", 1, "YES", None
        )

        assert attr.atttypmod == 104  # 100 + 4

    def test_char_typmod(self):
        """CHAR(10) -> atttypmod = 14"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "CHAR(10)", 1, "YES", None
        )

        assert attr.atttypmod == 14  # 10 + 4

    def test_integer_no_typmod(self):
        """INTEGER -> atttypmod = -1"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "INTEGER", 1, "YES", None
        )

        assert attr.atttypmod == -1


class TestPgAttributeTypeMapping:
    """Test IRIS to PostgreSQL type OID mapping."""

    def test_type_mapping_integer(self):
        """INTEGER -> int4 (OID 23)"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "INTEGER", 1, "YES", None
        )
        assert attr.atttypid == 23

    def test_type_mapping_bigint(self):
        """BIGINT -> int8 (OID 20)"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "BIGINT", 1, "YES", None
        )
        assert attr.atttypid == 20

    def test_type_mapping_varchar(self):
        """VARCHAR -> varchar (OID 1043)"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "VARCHAR(255)", 1, "YES", None
        )
        assert attr.atttypid == 1043

    def test_type_mapping_timestamp(self):
        """TIMESTAMP -> timestamp (OID 1114)"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "TIMESTAMP", 1, "YES", None
        )
        assert attr.atttypid == 1114

    def test_type_mapping_decimal(self):
        """DECIMAL -> numeric (OID 1700)"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "DECIMAL(10,2)", 1, "YES", None
        )
        assert attr.atttypid == 1700

    def test_type_mapping_bit(self):
        """BIT -> bool (OID 16)"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "BIT", 1, "YES", None
        )
        assert attr.atttypid == 16

    def test_type_mapping_text(self):
        """TEXT/LONGVARCHAR -> text (OID 25)"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "LONGVARCHAR", 1, "YES", None
        )
        assert attr.atttypid == 25


class TestPgAttributeDefault:
    """Test column default value handling."""

    def test_atthasdef_with_default(self):
        """Column with default -> atthasdef=True"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "INTEGER", 1, "YES", "0"
        )

        assert attr.atthasdef is True

    def test_atthasdef_without_default(self):
        """Column without default -> atthasdef=False"""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        emulator = PgAttributeEmulator(OIDGenerator())
        attr = emulator.from_iris_column(
            "SQLUser", "t", "c", "INTEGER", 1, "YES", None
        )

        assert attr.atthasdef is False


class TestPgAttributeLookup:
    """Test attribute lookup methods."""

    def test_get_by_table_oid(self):
        """Get all attributes for a table."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator

        oid_gen = OIDGenerator()
        emulator = PgAttributeEmulator(oid_gen)

        # Add attributes for users table
        for col_name, pos in [("id", 1), ("name", 2)]:
            attr = emulator.from_iris_column(
                "SQLUser", "users", col_name, "INTEGER", pos, "YES", None
            )
            emulator.add_attribute(attr)

        # Add attribute for different table
        attr = emulator.from_iris_column(
            "SQLUser", "orders", "id", "INTEGER", 1, "NO", None
        )
        emulator.add_attribute(attr)

        # Get users table OID
        table_oid = oid_gen.get_table_oid("SQLUser", "users")
        attrs = emulator.get_by_table_oid(table_oid)

        assert len(attrs) == 2
        assert all(a.attrelid == table_oid for a in attrs)


class TestPgAttributeDataclass:
    """Test PgAttribute dataclass."""

    def test_pg_attribute_dataclass_creation(self):
        """Test creating PgAttribute directly."""
        from iris_pgwire.catalog.pg_attribute import PgAttribute

        attr = PgAttribute(
            attrelid=12345,
            attname="id",
            atttypid=23,
            attstattarget=-1,
            attlen=4,
            attnum=1,
            attndims=0,
            attcacheoff=-1,
            atttypmod=-1,
            attbyval=True,
            attstorage="p",
            attalign="i",
            attnotnull=True,
            atthasdef=False,
            atthasmissing=False,
            attidentity="",
            attgenerated="",
            attisdropped=False,
            attislocal=True,
            attinhcount=0,
            attcollation=0,
            attacl=None,
            attoptions=None,
            attfdwoptions=None,
            attmissingval=None,
        )

        assert attr.attrelid == 12345
        assert attr.attname == "id"
        assert attr.attnum == 1
