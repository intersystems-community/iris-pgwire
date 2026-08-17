"""T015b: `pg_attribute`, `pg_attrdef`, and pg_class's `reltype`.

Prisma's columns query is one of the two statements the empty fallback was
swallowing. Three things had to change before any of it could work, and they were
found by measurement in this order:

1. `reltype > 0` — Prisma filters its pg_class subquery on it, and our view
   hardcoded `0 AS reltype`. **0 of 9 rows survived**, so the columns query
   returned nothing however correct everything else was. Nothing downstream is
   observable until this is fixed, which is why it comes first.
2. `pg_attribute`, joined on `att.attname = info.column_name` and
   `oid.oid = att.attrelid`.
3. `pg_attrdef`, left-joined for column defaults via `pg_get_expr(adbin, adrelid)`.

`atttypmod` is not a free choice: `format_type` decodes it, and PostgreSQL's
encoding was measured against postgres:15-alpine rather than recalled —
`varchar(100)` is `104` (length + 4) and `numeric(10,2)` is `655366`
(precision × 65536 + scale + 4). A wrong value makes a client report the wrong
column width, silently.
"""

from __future__ import annotations

import pytest

from iris_pgwire.catalog.views.definitions import (
    CATALOG_VIEWS,
    PG_ATTRDEF,
    PG_ATTRIBUTE,
    PG_CLASS,
    VIEW_BACKED_TABLES,
)

# Measured against postgres:15-alpine.
PG15_ATTRIBUTE_COLUMNS = (
    "attrelid",
    "attname",
    "atttypid",
    "attstattarget",
    "attlen",
    "attnum",
    "attndims",
    "attcacheoff",
    "atttypmod",
    "attbyval",
    "attalign",
    "attstorage",
    "attcompression",
    "attnotnull",
    "atthasdef",
    "atthasmissing",
    "attidentity",
    "attgenerated",
    "attisdropped",
    "attislocal",
    "attinhcount",
    "attcollation",
    "attacl",
    "attoptions",
    "attfdwoptions",
    "attmissingval",
)

PG15_ATTRDEF_COLUMNS = ("oid", "adrelid", "adnum", "adbin")


class TestReltypeIsNoLongerZero:
    """The measurement that reordered this task."""

    def test_pg_class_gives_reltype_a_real_oid(self):
        assert "0 AS reltype" not in PG_CLASS.body, (
            "Prisma filters its pg_class subquery on reltype > 0; a hardcoded 0 excluded "
            "every row, so the columns query returned nothing whatever else was fixed"
        )
        assert "reltype" in PG_CLASS.body

    def test_the_row_type_oid_is_distinct_from_the_tables_own(self):
        """PostgreSQL's reltype is the row type's OID, a different object."""
        assert "rowtype" in PG_CLASS.body, (
            "deriving reltype from the same identity string as oid would make the two equal, "
            "which they are not in PostgreSQL"
        )


class TestColumnLists:
    def test_pg_attribute_matches_postgresql(self):
        assert PG_ATTRIBUTE.columns == PG15_ATTRIBUTE_COLUMNS

    def test_pg_attrdef_matches_postgresql(self):
        assert PG_ATTRDEF.columns == PG15_ATTRDEF_COLUMNS

    def test_both_are_registered_and_declined_by_the_router(self):
        for view in (PG_ATTRIBUTE, PG_ATTRDEF):
            assert view in CATALOG_VIEWS
            assert view.name in VIEW_BACKED_TABLES

    def test_the_schema_mapper_knows_them(self):
        from iris_pgwire.schema_mapper import VIEW_BACKED_TABLES as MAPPER_TABLES

        assert "pg_attribute" in MAPPER_TABLES
        assert "pg_attrdef" in MAPPER_TABLES

    def test_the_handlers_no_longer_claim_them(self):
        """Exactly one path per table (FR-011)."""
        from iris_pgwire.catalog.catalog_router import CatalogRouter

        handled = set(CatalogRouter()._catalog_handler_map)
        assert "pg_attribute" not in handled
        assert "pg_attrdef" not in handled


class TestTypeModifierEncoding:
    """format_type decodes atttypmod; the encoding is PostgreSQL's, not ours."""

    def test_varchar_length_is_offset_by_four(self):
        assert "+ 4" in PG_ATTRIBUTE.body, "varchar(100) is atttypmod 104, measured"

    def test_numeric_packs_precision_and_scale(self):
        assert "65536" in PG_ATTRIBUTE.body, (
            "numeric(10,2) is 655366 = precision * 65536 + scale + 4, measured"
        )

    def test_types_without_a_modifier_report_minus_one(self):
        assert "-1" in PG_ATTRIBUTE.body


class TestTypeOidMapping:
    @pytest.mark.parametrize(
        ("iris_type", "oid"),
        [
            ("integer", 23),
            ("varchar", 1043),
            ("timestamp", 1114),
            ("numeric", 1700),
            ("bigint", 20),
            ("date", 1082),
        ],
    )
    def test_each_iris_type_maps_to_its_postgresql_oid(self, iris_type, oid):
        """The four in use here are integer, varchar, timestamp and numeric."""
        body = PG_ATTRIBUTE.body.upper()
        assert f"'{iris_type.upper()}' THEN {oid}" in body


class TestNullabilityAndDefaults:
    def test_attnotnull_is_derived_from_is_nullable(self):
        assert "IS_NULLABLE" in PG_ATTRIBUTE.body.upper()

    def test_atthasdef_is_derived_from_column_default(self):
        assert "COLUMN_DEFAULT" in PG_ATTRIBUTE.body.upper()

    def test_pg_attrdef_only_reports_columns_that_have_a_default(self):
        assert "COLUMN_DEFAULT IS NOT NULL" in PG_ATTRDEF.body.upper()

    def test_adbin_carries_the_default_text(self):
        """pg_get_expr(adbin, adrelid) has to be able to return something real.

        PostgreSQL stores a parse tree here and renders it with pg_get_expr. We
        have the expression text and no parse tree, so adbin carries the text and
        pg_get_expr returns it — an honest rendering of what IRIS knows.
        """
        assert "COLUMN_DEFAULT AS adbin" in PG_ATTRDEF.body


class TestNamesAreLowercased:
    """A client compares attname to a lowercase literal, and joins it to the
    column name reported by the columns view — so both must fold the same way."""

    def test_attname_is_lowercased(self):
        assert "LOWER(c.COLUMN_NAME) AS attname" in PG_ATTRIBUTE.body


class TestScopedToTheUserSchema:
    def test_only_the_mapped_schema_is_reported(self):
        from iris_pgwire.schema_mapper import IRIS_SCHEMA

        for view in (PG_ATTRIBUTE, PG_ATTRDEF):
            assert IRIS_SCHEMA.upper() in view.body.upper(), view.name


class TestTheColumnQueryFunctions:
    """T015b: format_type, pg_get_expr and col_description.

    `format_type` renders the string an ORM writes into a generated schema, so
    every case in the function body was measured against postgres:15-alpine and
    then verified against the installed function — 14/14 byte-identical,
    including the cases that are easy to get wrong: no parentheses when there is
    no modifier (`character varying`, `numeric`), and `???` for an unknown OID.
    """

    def test_all_three_are_registered_for_installation(self):
        from iris_pgwire.catalog.functions import CATALOG_FUNCTIONS

        names = {function.name for function in CATALOG_FUNCTIONS}
        assert {"FORMAT_TYPE", "PG_GET_EXPR", "COL_DESCRIPTION"} <= names

    def test_the_translator_maps_the_unqualified_calls(self):
        from iris_pgwire.sql_translator.pg_functions import PG_FUNCTION_MAP

        assert PG_FUNCTION_MAP["format_type"] == "PGWire.FORMAT_TYPE"
        assert PG_FUNCTION_MAP["pg_get_expr"] == "PGWire.PG_GET_EXPR"
        assert PG_FUNCTION_MAP["col_description"] == "PGWire.COL_DESCRIPTION"

    @pytest.mark.parametrize(
        "rendering",
        [
            "integer",
            "bigint",
            "boolean",
            "character varying",
            "numeric",
            "double precision",
            "timestamp without time zone",
            "time without time zone",
        ],
    )
    def test_format_type_carries_postgresqls_own_spelling(self, rendering):
        """`double precision`, not `float8`; the ORM writes this string out."""
        from iris_pgwire.catalog.functions import FORMAT_TYPE

        assert f'"{rendering}"' in FORMAT_TYPE.body

    def test_the_modifier_offset_is_removed_when_rendering(self):
        from iris_pgwire.catalog.functions import FORMAT_TYPE

        assert "(mod - 4)" in FORMAT_TYPE.body, (
            "varchar(100) arrives as atttypmod 104; rendering 104 would be wrong"
        )

    def test_an_unknown_oid_renders_as_postgresql_does(self):
        from iris_pgwire.catalog.functions import FORMAT_TYPE

        assert '"???"' in FORMAT_TYPE.body, "measured: format_type(99999, -1) is '???'"

    def test_col_description_returns_null_rather_than_inventing_text(self):
        from iris_pgwire.catalog.functions import COL_DESCRIPTION

        assert 'quit ""' in COL_DESCRIPTION.body
