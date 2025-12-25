"""
Contract Tests: pg_constraint Catalog Emulation

Tests for PostgreSQL pg_constraint catalog emulation per pg_constraint_contract.md.
"""

import pytest


class TestPgConstraintPrimaryKey:
    """TC-1: Primary key discovery."""

    def test_pg_constraint_primary_key(self):
        """
        Given: Table with primary key on 'id'
        When: Create constraint
        Then: Return PK constraint with correct type
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator

        oid_gen = OIDGenerator()
        emulator = PgConstraintEmulator(oid_gen)

        constraint = emulator.from_iris_constraint(
            schema="SQLUser",
            table_name="users",
            constraint_name="users_pkey",
            constraint_type="PRIMARY KEY",
            column_positions=[1],
        )

        assert constraint.contype == "p"  # primary key
        assert constraint.conkey == [1]
        assert constraint.confrelid == 0  # No referenced table
        assert constraint.confkey == []

    def test_pg_constraint_composite_primary_key(self):
        """Test composite primary key."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator

        oid_gen = OIDGenerator()
        emulator = PgConstraintEmulator(oid_gen)

        constraint = emulator.from_iris_constraint(
            schema="SQLUser",
            table_name="order_items",
            constraint_name="order_items_pkey",
            constraint_type="PRIMARY KEY",
            column_positions=[1, 2],  # composite key
        )

        assert constraint.contype == "p"
        assert constraint.conkey == [1, 2]


class TestPgConstraintForeignKey:
    """TC-2: Foreign key discovery."""

    def test_pg_constraint_foreign_key(self):
        """
        Given: Table with FK referencing another table
        When: Create FK constraint
        Then: Return FK with correct referenced table and columns
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator

        oid_gen = OIDGenerator()
        emulator = PgConstraintEmulator(oid_gen)

        constraint = emulator.from_iris_constraint(
            schema="SQLUser",
            table_name="orders",
            constraint_name="orders_user_fk",
            constraint_type="FOREIGN KEY",
            column_positions=[2],  # user_id is 2nd column
            ref_table_name="users",
            ref_column_positions=[1],  # id is 1st column
        )

        assert constraint.contype == "f"  # foreign key
        assert constraint.conkey == [2]
        assert constraint.confkey == [1]
        assert constraint.confrelid != 0  # Should have referenced table OID

    def test_pg_constraint_fk_references_correct_table(self):
        """FK confrelid should point to referenced table OID."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator

        oid_gen = OIDGenerator()
        emulator = PgConstraintEmulator(oid_gen)

        # Create FK
        constraint = emulator.from_iris_constraint(
            schema="SQLUser",
            table_name="orders",
            constraint_name="orders_user_fk",
            constraint_type="FOREIGN KEY",
            column_positions=[2],
            ref_table_name="users",
            ref_column_positions=[1],
        )

        # Verify confrelid matches users table OID
        expected_ref_oid = oid_gen.get_table_oid("SQLUser", "users")
        assert constraint.confrelid == expected_ref_oid


class TestPgConstraintUnique:
    """TC-3: Unique constraint."""

    def test_pg_constraint_unique(self):
        """
        Given: Table with UNIQUE constraint
        When: Create constraint
        Then: Return UNIQUE constraint
        """
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator

        oid_gen = OIDGenerator()
        emulator = PgConstraintEmulator(oid_gen)

        constraint = emulator.from_iris_constraint(
            schema="SQLUser",
            table_name="users",
            constraint_name="users_email_unique",
            constraint_type="UNIQUE",
            column_positions=[3],  # email column
        )

        assert constraint.contype == "u"  # unique
        assert constraint.conkey == [3]


class TestPgConstraintCompositeKey:
    """TC-4: Composite key handling."""

    def test_pg_constraint_composite_unique(self):
        """Test composite unique constraint."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator

        oid_gen = OIDGenerator()
        emulator = PgConstraintEmulator(oid_gen)

        constraint = emulator.from_iris_constraint(
            schema="SQLUser",
            table_name="subscriptions",
            constraint_name="subscriptions_user_product_unique",
            constraint_type="UNIQUE",
            column_positions=[1, 2],  # (user_id, product_id)
        )

        assert constraint.contype == "u"
        assert constraint.conkey == [1, 2]


class TestPgConstraintOIDStability:
    """Test OID stability for constraints."""

    def test_constraint_oid_stability(self):
        """Same constraint should have same OID."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator

        emulator1 = PgConstraintEmulator(OIDGenerator())
        emulator2 = PgConstraintEmulator(OIDGenerator())

        c1 = emulator1.from_iris_constraint(
            "SQLUser", "users", "users_pkey", "PRIMARY KEY", [1]
        )
        c2 = emulator2.from_iris_constraint(
            "SQLUser", "users", "users_pkey", "PRIMARY KEY", [1]
        )

        assert c1.oid == c2.oid


class TestPgConstraintDataclass:
    """Test PgConstraint dataclass."""

    def test_pg_constraint_dataclass_creation(self):
        """Test creating PgConstraint directly."""
        from iris_pgwire.catalog.pg_constraint import PgConstraint

        constraint = PgConstraint(
            oid=12345,
            conname="users_pkey",
            connamespace=2200,
            contype="p",
            condeferrable=False,
            condeferred=False,
            convalidated=True,
            conrelid=11111,
            contypid=0,
            conindid=0,
            conparentid=0,
            confrelid=0,
            confupdtype=" ",
            confdeltype=" ",
            confmatchtype=" ",
            conislocal=True,
            coninhcount=0,
            connoinherit=True,
            conkey=[1],
            confkey=[],
            conpfeqop=[],
            conppeqop=[],
            conffeqop=[],
            conexclop=[],
            conbin=None,
        )

        assert constraint.oid == 12345
        assert constraint.conname == "users_pkey"
        assert constraint.contype == "p"


class TestPgConstraintLookup:
    """Test constraint lookup methods."""

    def test_get_by_table_oid(self):
        """Get all constraints for a table."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator

        oid_gen = OIDGenerator()
        emulator = PgConstraintEmulator(oid_gen)

        # Add constraints for users table
        pk = emulator.from_iris_constraint(
            "SQLUser", "users", "users_pkey", "PRIMARY KEY", [1]
        )
        unique = emulator.from_iris_constraint(
            "SQLUser", "users", "users_email_unique", "UNIQUE", [3]
        )
        emulator.add_constraint(pk)
        emulator.add_constraint(unique)

        # Add constraint for different table
        other = emulator.from_iris_constraint(
            "SQLUser", "orders", "orders_pkey", "PRIMARY KEY", [1]
        )
        emulator.add_constraint(other)

        # Get users constraints
        table_oid = oid_gen.get_table_oid("SQLUser", "users")
        constraints = emulator.get_by_table_oid(table_oid)

        assert len(constraints) == 2

    def test_get_by_referenced_table(self):
        """Get FK constraints referencing a table."""
        from iris_pgwire.catalog.oid_generator import OIDGenerator
        from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator

        oid_gen = OIDGenerator()
        emulator = PgConstraintEmulator(oid_gen)

        # Add FK constraint
        fk = emulator.from_iris_constraint(
            "SQLUser",
            "orders",
            "orders_user_fk",
            "FOREIGN KEY",
            [2],
            ref_table_name="users",
            ref_column_positions=[1],
        )
        emulator.add_constraint(fk)

        # Get constraints referencing users
        users_oid = oid_gen.get_table_oid("SQLUser", "users")
        constraints = emulator.get_by_referenced_table(users_oid)

        assert len(constraints) == 1
        assert constraints[0].contype == "f"
