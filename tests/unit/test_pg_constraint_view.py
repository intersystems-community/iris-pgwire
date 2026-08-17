"""T015 / FR-016…FR-021: `pg_constraint` as a view, and what must hold of it.

The handler this replaces did not merely fail to answer — it answered *wrongly*.
Prisma's constraints query joins `pg_constraint` to `pg_class` and
`pg_namespace`; the "a mixed query stays with the handler" rule handed it to the
**pg_class** handler, which replied with pg_class's own 32 columns, including
`relfrozenxid` typed `xid`, and Prisma stopped at

    Column type 'xid' could not be deserialized from the database.

Answering a query with a different table's column set is wrong however the views
progress, so the row-shape assertions here matter as much as the content ones.

The IRIS-side behaviour is verified in
`tests/integration/test_pg_constraint_against_iris.py`; this file pins the parts
that are decided in Python.
"""

from __future__ import annotations

import pytest

from iris_pgwire.catalog.views.definitions import (
    CATALOG_COLUMN_TYPE_OIDS,
    CATALOG_VIEWS,
    PG_CONSTRAINT,
    VIEW_BACKED_TABLES,
)

# PostgreSQL 15's pg_constraint, in attnum order, measured against
# postgres:15-alpine: SELECT attname FROM pg_attribute
# WHERE attrelid = 'pg_catalog.pg_constraint'::regclass AND attnum > 0.
POSTGRES_15_COLUMNS = (
    "oid",
    "conname",
    "connamespace",
    "contype",
    "condeferrable",
    "condeferred",
    "convalidated",
    "conrelid",
    "contypid",
    "conindid",
    "conparentid",
    "confrelid",
    "confupdtype",
    "confdeltype",
    "confmatchtype",
    "conislocal",
    "coninhcount",
    "connoinherit",
    "conkey",
    "confkey",
    "conpfeqop",
    "conppeqop",
    "conffeqop",
    "confdelsetcols",
    "conexclop",
    "conbin",
)


class TestTheColumnListMatchesPostgreSQL:
    """FR-004: against a named authority, not from memory (CHK007)."""

    def test_every_column_in_postgresql_order(self):
        assert PG_CONSTRAINT.columns == POSTGRES_15_COLUMNS

    def test_the_body_projects_exactly_those_columns(self):
        """A count mismatch here means positional access returns the wrong column."""
        aliased = PG_CONSTRAINT.body.upper().count(" AS ")
        # Every projected column is aliased; subquery internals add none, since
        # they alias only at the outer level.
        assert aliased >= len(POSTGRES_15_COLUMNS)

    def test_the_columns_prismas_query_selects_are_present(self):
        for column in ("conname", "contype", "condeferrable", "condeferred", "conrelid", "oid"):
            assert column in PG_CONSTRAINT.columns


class TestRoutingIsExclusive:
    """FR-011: exactly one path answers a catalog table."""

    def test_the_view_is_registered(self):
        assert PG_CONSTRAINT in CATALOG_VIEWS

    def test_the_router_declines_it(self):
        assert "pg_constraint" in VIEW_BACKED_TABLES

    def test_the_handler_declines_prismas_constraints_query(self):
        """The pg_class handler answering a constraints query is the live defect.

        Prisma's query names all three of pg_constraint, pg_class and
        pg_namespace. Before pg_constraint became a view, the "a mixed query
        stays with the handler" rule sent it to the pg_class handler, which
        replied with pg_class's 32 columns.
        """
        import asyncio

        from iris_pgwire.catalog.catalog_router import CatalogRouter

        router = CatalogRouter()
        # Verbatim, including the pg_get_constraintdef call: a `pg_*` *function*
        # name used to count as a targeted catalog table, so the set was never a
        # subset of the view-backed tables and the decline never fired. Dropping
        # the call from this query is exactly what made an earlier version of
        # this test pass while `prisma db pull` still failed.
        sql = (
            "SELECT constr.conname, constr.contype, "
            "pg_get_constraintdef(constr.oid) AS constraint_definition "
            "FROM pg_constraint constr "
            "JOIN pg_class AS tableinfo ON tableinfo.oid = constr.conrelid "
            "JOIN pg_namespace AS schemainfo ON schemainfo.oid = tableinfo.relnamespace "
            "WHERE schemainfo.nspname = ANY ( ? ) AND contype NOT IN ('p', 'u', 'f')"
        )
        result = asyncio.run(router.handle_catalog_query(sql, session_id="test"))
        assert result is None, (
            "a query naming pg_constraint must reach the view; the handler answers it "
            f"with pg_class's columns, including relfrozenxid typed xid. Got: {result}"
        )


class TestAFunctionNameIsNotATable:
    """`pg_*` followed by `(` is a call, and the distinction decided the defect."""

    def test_a_catalog_function_call_is_not_counted_as_a_table(self):
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        tables = CatalogRouter().extract_catalog_tables(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c"
        )
        assert tables == {"pg_constraint"}

    def test_obj_description_style_calls_too(self):
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        tables = CatalogRouter().extract_catalog_tables(
            "SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d"
        )
        assert "pg_get_expr" not in tables

    def test_a_table_name_is_still_found(self):
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        tables = CatalogRouter().extract_catalog_tables("SELECT * FROM pg_class")
        assert "pg_class" in tables


class TestConstraintTypeCodes:
    """FR-016: PostgreSQL's own codes, or a client cannot classify a constraint."""

    @pytest.mark.parametrize(
        ("iris_type", "expected_code"),
        [
            ("PRIMARY KEY", "p"),
            ("FOREIGN KEY", "f"),
            ("UNIQUE", "u"),
            ("CHECK", "c"),
        ],
    )
    def test_each_kind_maps_to_its_code(self, iris_type, expected_code):
        # Case matters: the IRIS constraint type is upper case and the
        # PostgreSQL code is lower case, in the same expression.
        assert f"WHEN '{iris_type}' THEN '{expected_code}'" in PG_CONSTRAINT.body


class TestReferentialActions:
    """FR-019: an ORM reads these to generate onDelete behaviour."""

    @pytest.mark.parametrize(
        ("rule", "code"),
        [("CASCADE", "c"), ("SET NULL", "n"), ("SET DEFAULT", "d"), ("RESTRICT", "r")],
    )
    def test_each_rule_maps_to_its_code(self, rule, code):
        assert f"WHEN '{rule}' THEN '{code}'" in PG_CONSTRAINT.body

    def test_no_action_is_the_default(self):
        assert "ELSE 'a'" in PG_CONSTRAINT.body


class TestColumnPositionsAreTableRelative:
    """FR-018 — the subtle one, and easy to get wrong.

    `KEY_COLUMN_USAGE.ORDINAL_POSITION` is the position of the column *within the
    constraint*: for a single-column foreign key it is always 1, whatever the
    column's place in the table. `conkey` must carry the table-relative position,
    the same number `pg_attribute.attnum` reports, so the position has to come
    from `INFORMATION_SCHEMA.COLUMNS`.
    """

    def test_conkey_reads_positions_from_columns_not_from_key_column_usage(self):
        body = PG_CONSTRAINT.body.upper()
        assert "INFORMATION_SCHEMA.COLUMNS" in body, (
            "conkey built from KEY_COLUMN_USAGE.ORDINAL_POSITION alone reports 1 for "
            "every single-column constraint"
        )

    def test_the_arrays_are_in_postgresql_text_format(self):
        assert "'{' ||" in PG_CONSTRAINT.body
        assert "|| '}'" in PG_CONSTRAINT.body

    def test_positions_are_aggregated_with_list(self):
        """IRIS has no LIST_AGG; LIST() joins with commas, which is the format."""
        assert "LIST(" in PG_CONSTRAINT.body.upper()


class TestDeclaredTypes:
    """Column types a value cannot convey have to be declared (T011g/T011h)."""

    def test_the_boolean_columns_are_declared_bool(self):
        for column in ("condeferrable", "condeferred", "convalidated", "conislocal"):
            assert CATALOG_COLUMN_TYPE_OIDS.get(column) == 16, column

    def test_conkey_is_int2_not_text(self):
        """int2[] is 1005; text[] is 1009. A typed client rejects the wrong one."""
        assert CATALOG_COLUMN_TYPE_OIDS["conkey"] == 1005
        assert CATALOG_COLUMN_TYPE_OIDS["confkey"] == 1005

    def test_contype_is_char(self):
        assert CATALOG_COLUMN_TYPE_OIDS["contype"] == 18


class TestTheConstraintDefFunction:
    """FR-020: unknown function means the query fails at prepare time."""

    def test_it_is_registered_for_installation(self):
        from iris_pgwire.catalog.functions import CATALOG_FUNCTIONS

        names = {function.qualified_name.lower() for function in CATALOG_FUNCTIONS}
        assert "pgwire.pg_get_constraintdef" in names

    def test_the_translator_maps_the_unqualified_call(self):
        from iris_pgwire.sql_translator.pg_functions import PG_FUNCTION_MAP

        assert PG_FUNCTION_MAP["pg_get_constraintdef"] == "PGWire.PG_GET_CONSTRAINTDEF"

    def test_it_returns_definitions_for_each_supported_kind(self):
        from iris_pgwire.catalog.functions import PG_GET_CONSTRAINTDEF

        body = PG_GET_CONSTRAINTDEF.body.upper()
        for fragment in ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "REFERENCES"):
            assert fragment in body
