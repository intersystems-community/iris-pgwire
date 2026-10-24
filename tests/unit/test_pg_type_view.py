"""pg_type is a view of rows captured from real PostgreSQL, not a handler that guesses.

Why this exists. The ADBC PostgreSQL driver cannot connect to iris-pgwire: at connect it runs

    SELECT oid, typname, typreceive, typbasetype, typrelid, typarray FROM pg_catalog.pg_type
    WHERE (typreceive != 0 OR typsend != 0) AND typtype != 'r' AND typreceive::TEXT != 'array_recv'

and fails with "Expected 5 or 6 columns from type resolver pg_type query but got 4". The old
handler matched the *shape* of a query in Python, returned a fixed 21-row table, ignored the WHERE
and put the columns it chose in its own order. The driver then decides how to decode every
result column from `typreceive`, by name, so the names must be PostgreSQL's.

The catalog already moved to views for the same reason (specs/044-catalog-as-views): a real view
hands projection, ordering and predicates back to IRIS. pg_type was one of the last holdouts.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from iris_pgwire.catalog.catalog_router import CatalogRouter
from iris_pgwire.catalog.pg_type_data import PG_TYPE_COLUMNS, PG_TYPE_ROWS
from iris_pgwire.catalog.views.definitions import (
    BOOLEAN_CATALOG_COLUMNS,
    CATALOG_COLUMN_TYPE_OIDS,
    CATALOG_VIEWS,
    PG_TYPE,
    VIEW_BACKED_TABLES,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "iris_pgwire"

# PostgreSQL 16's pg_type, in order.
POSTGRES_16_COLUMNS = (
    "oid", "typname", "typnamespace", "typowner", "typlen", "typbyval", "typtype", "typcategory",
    "typispreferred", "typisdefined", "typdelim", "typrelid", "typsubscript", "typelem", "typarray",
    "typinput", "typoutput", "typreceive", "typsend", "typmodin", "typmodout", "typanalyze",
    "typalign", "typstorage", "typnotnull", "typbasetype", "typtypmod", "typndims", "typcollation",
    "typdefaultbin", "typdefault", "typacl",
)  # fmt: skip

# The 81 receive-function names compiled into adbc-driver-postgresql 1.12.0 (read from the shared
# library). A row whose typreceive is not one of these is a type the driver cannot decode.
DRIVER_RECEIVE_NAMES = frozenset(
    """aclitem_recv anyarray_recv anycompatiblearray_recv array_recv bit_recv boolrecv box_recv
    bpcharrecv brin_bloom_summary_recv brin_minmax_multi_summary_recv bytearecv cash_recv charrecv
    cidr_recv cidrecv circle_recv cstring_recv date_recv demux_recv domain_recv enum_recv float4recv
    float8recv inet_recv int2recv int2vectorrecv int4recv int8recv interval_recv json_recv
    jsonb_recv jsonpath_recv line_recv lseg_recv macaddr8_recv macaddr_recv multirange_recv namerecv
    numeric_recv oidrecv oidvectorrecv path_recv pg_ddl_command_recv pg_dependencies_recv
    pg_lsn_recv pg_mcv_list_recv pg_ndistinct_recv pg_node_tree_recv pg_snapshot_recv point_recv
    poly_recv range_recv record_recv regclassrecv regcollationrecv regconfigrecv regdictionaryrecv
    regnamespacerecv regoperatorrecv regoperrecv regprocedurerecv regprocrecv regrolerecv
    regtyperecv textrecv tidrecv time_recv timestamp_recv timestamptz_recv timetz_recv tsqueryrecv
    tsvectorrecv txid_snapshot_recv unknownrecv uuid_recv varbit_recv varcharrecv void_recv
    xid8recv xidrecv xml_recv""".split()
)
# pgvector's own type: not the driver's to know. It treats an unknown receive function as a type it
# will not decode, which is the honest outcome for a column it cannot represent.
EXTENSION_RECEIVE_NAMES = frozenset({"vector_recv"})

# PostgreSQL's built-in base and array type OIDs (from a PostgreSQL 16.15 pg_type), plus the
# `unknown` pseudo-type. Used only to recognise a type OID in source code.
KNOWN_PG_TYPE_OIDS = frozenset(
    [16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 114, 142, 194, 600, 601, 602, 603,
     604, 628, 650, 700, 701, 705, 718, 774, 790, 829, 869, 1033, 1042, 1043, 1082, 1083, 1114,
     1184, 1186, 1266, 1560, 1562, 1700, 1790, 2202, 2203, 2204, 2205, 2206, 2950, 2970, 3220,
     3361, 3402, 3614, 3615, 3642, 3734, 3769, 3802, 4072, 4089, 4096, 4191, 4600, 4601, 5017,
     5038, 5069,
     143, 199, 210, 270, 271, 272, 273, 629, 651, 719, 775, 791, 1000, 1001, 1002, 1003, 1005,
     1006, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014, 1015, 1016, 1017, 1018, 1019, 1020,
     1021, 1022, 1027, 1028, 1034, 1040, 1041, 1115, 1182, 1183, 1185, 1187, 1231, 1263, 1270,
     1561, 1563, 2201, 2207, 2208, 2209, 2210, 2211, 2949, 2951, 3221, 3643, 3644, 3645, 3735,
     3770, 3807, 3905, 3907, 3909, 3911, 3913, 3927, 4073, 4090, 4097, 4192, 5039]
)  # fmt: skip

# The modules that put a type OID into a RowDescription.
EMITTING_MODULES = (
    "iris_executor.py", "dbapi_executor.py", "_result_processing.py", "_type_mapping.py",
    "protocol.py", "bulk_executor.py",
)  # fmt: skip

ROWS = [dict(zip(PG_TYPE_COLUMNS, row, strict=True)) for row in PG_TYPE_ROWS]
BY_OID = {r["oid"]: r for r in ROWS}
BY_NAME = {r["typname"]: r for r in ROWS}


class TestItIsAView:
    def test_it_is_registered_so_exactly_one_path_answers_it(self):
        assert PG_TYPE in CATALOG_VIEWS
        assert "pg_type" in VIEW_BACKED_TABLES

    def test_the_old_handler_no_longer_answers_for_it(self):
        router = CatalogRouter()
        result = asyncio.run(
            router.handle_catalog_query("SELECT typname FROM pg_type", session_id="t")
        )
        assert result is None, "a handler must decline a table that a view serves"

    def test_columns_are_postgresqls_in_postgresqls_order(self):
        assert PG_TYPE.columns == POSTGRES_16_COLUMNS
        assert PG_TYPE_COLUMNS == POSTGRES_16_COLUMNS

    def test_every_row_has_every_column(self):
        assert all(len(row) == len(POSTGRES_16_COLUMNS) for row in PG_TYPE_ROWS)

    def test_the_ddl_has_one_select_per_row_and_valid_literals(self):
        ddl = PG_TYPE.create_sql()
        assert ddl.startswith("CREATE VIEW pg_catalog.pg_type AS")
        assert len(re.findall(r"^SELECT ", PG_TYPE.body, re.M)) == len(PG_TYPE_ROWS)
        assert "True" not in ddl and "False" not in ddl and "None" not in ddl

    def test_oids_are_unique(self):
        assert len(BY_OID) == len(ROWS)

    def test_booleans_are_declared_so_clients_get_a_one_byte_bool(self):
        for column in ("typbyval", "typispreferred", "typisdefined", "typnotnull"):
            assert column in BOOLEAN_CATALOG_COLUMNS
            assert CATALOG_COLUMN_TYPE_OIDS[column] == 16

    def test_single_byte_columns_are_declared_char(self):
        for column in ("typtype", "typcategory", "typdelim", "typalign", "typstorage"):
            assert CATALOG_COLUMN_TYPE_OIDS[column] == 18


class TestWhatTheServerEmitsIsDescribed:
    def test_every_oid_the_server_can_emit_has_a_row(self):
        """A column typed with an OID that pg_type does not list cannot be decoded by a client
        that resolves types from the catalog, which is exactly what the ADBC driver does."""
        found: dict[int, list[str]] = {}
        for name in EMITTING_MODULES:
            for number, line in iter_type_oid_literals((SRC / name).read_text().splitlines()):
                if number in KNOWN_PG_TYPE_OIDS or number == 16388:
                    found.setdefault(number, []).append(f"{name}: {line.strip()[:70]}")
        missing = {oid: where[:2] for oid, where in found.items() if oid not in BY_OID}
        assert not missing, f"emitted but absent from pg_type: {missing}"

    def test_the_scan_actually_finds_something(self):
        # Guards the scan itself: if it matched nothing, the test above would pass vacuously.
        found = {
            n
            for name in EMITTING_MODULES
            for n, _ in iter_type_oid_literals((SRC / name).read_text().splitlines())
        }
        assert {16, 20, 23, 25, 701, 1043, 1082, 1114, 1700} <= found

    @pytest.mark.parametrize(
        "name", ["bool", "bytea", "int2", "int4", "int8", "float4", "float8", "text", "varchar",
                 "bpchar", "date", "time", "timestamp", "timestamptz", "numeric", "uuid", "json",
                 "jsonb", "bit", "varbit", "oid", "name", "char", "interval", "timetz", "vector"],
    )  # fmt: skip
    def test_the_scalar_types_clients_ask_for_are_present(self, name):
        assert name in BY_NAME


class TestTheDriverCanDecodeWhatItIsTold:
    def test_every_receive_function_is_one_the_adbc_driver_knows(self):
        unknown = {
            (r["typname"], r["typreceive"])
            for r in ROWS
            if r["typreceive"] not in DRIVER_RECEIVE_NAMES | EXTENSION_RECEIVE_NAMES
        }
        assert not unknown

    def test_no_row_lacks_a_receive_function(self):
        # IRIS compares a name column with 0 as strings, so `typreceive != 0` is true for every
        # row (measured). The predicate is only meaningful if every row really has a function.
        assert all(r["typreceive"] not in ("-", "", None) for r in ROWS)
        assert all(r["typsend"] not in ("-", "", None) for r in ROWS)

    def test_array_types_and_their_elements_point_at_each_other(self):
        for row in ROWS:
            if row["typcategory"] == "A":
                assert row["typreceive"] == "array_recv", row["typname"]
                assert row["typelem"] in BY_OID, row["typname"]
                assert BY_OID[row["typelem"]]["typarray"] == row["oid"], row["typname"]
        for row in ROWS:
            if row["typarray"]:
                array = BY_OID[row["typarray"]]
                assert array["typelem"] == row["oid"] and array["typcategory"] == "A"

    def test_the_driver_query_keeps_the_scalars_and_drops_arrays_and_ranges(self):
        """The driver's WHERE, evaluated here in Python as PostgreSQL would evaluate it."""
        kept = [
            r for r in ROWS
            if (r["typreceive"] != "-" or r["typsend"] != "-")
            and r["typtype"] != "r"
            and r["typreceive"] != "array_recv"
        ]  # fmt: skip
        names = {r["typname"] for r in kept}
        assert {"int4", "text", "bool", "timestamp", "numeric", "vector"} <= names
        assert not {n for n in names if n.startswith("_")}


class TestValuesAreThoseOfRealPostgres:
    """Spot checks against PostgreSQL 16.15, so a hand edit of the captured data is caught."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("int4", {"oid": 23, "typlen": 4, "typbyval": True, "typcategory": "N", "typarray": 1007,
                          "typreceive": "int4recv", "typsend": "int4send", "typalign": "i"}),
            ("int8", {"oid": 20, "typlen": 8, "typbyval": True, "typarray": 1016, "typreceive": "int8recv"}),
            ("text", {"oid": 25, "typlen": -1, "typbyval": False, "typcategory": "S", "typarray": 1009,
                          "typreceive": "textrecv", "typstorage": "x", "typcollation": 100}),
            ("bool", {"oid": 16, "typlen": 1, "typcategory": "B", "typispreferred": True,
                          "typreceive": "boolrecv"}),
            ("timestamp", {"oid": 1114, "typcategory": "D", "typarray": 1115,
                               "typreceive": "timestamp_recv"}),
            ("numeric", {"oid": 1700, "typcategory": "N", "typreceive": "numeric_recv"}),
            ("uuid", {"oid": 2950, "typlen": 16, "typbyval": False, "typreceive": "uuid_recv"}),
            ("bytea", {"oid": 17, "typreceive": "bytearecv"}),
            ("_int4", {"oid": 1007, "typcategory": "A", "typelem": 23, "typreceive": "array_recv"}),
            ("vector", {"oid": 16388, "typarray": 16389, "typreceive": "vector_recv", "typcategory": "U"}),
        ],
    )  # fmt: skip
    def test_row(self, name, expected):
        row = BY_NAME[name]
        for column, value in expected.items():
            assert row[column] == value, f"{name}.{column}"

    def test_the_catalog_namespace_is_pg_catalog_for_builtins(self):
        assert BY_NAME["int4"]["typnamespace"] == 11
        assert BY_NAME["vector"]["typnamespace"] == 2200


def iter_type_oid_literals(lines):
    """Yield (number, line) for integer literals on lines that talk about a type OID."""
    for line in lines:
        if not re.search(r"oid|OID|# [A-Z]{3,}|type", line):
            continue
        for match in re.finditer(r"(?<![\w.\"'])(\d{2,5})(?![\w.\"'])", line):
            yield int(match.group(1)), line


class TestBareNamesReachTheView:
    """`SELECT ... FROM pg_type` (no schema) is how most clients write it. The old handler
    matched the bare name; a view lives in the pg_catalog schema, so the name has to be qualified
    on its way in. Found against a real IRIS: the schema-qualified form the ADBC driver uses worked
    and the bare form was "Table 'SQLUSER.PG_TYPE' not found"."""

    def test_a_bare_pg_type_is_qualified(self):
        from iris_pgwire.schema_mapper import translate_input_schema

        # Qualified the way every other view is: pg_catalog."PG_CLASS", pg_catalog."PG_TYPE", ...
        assert 'pg_catalog."PG_TYPE"' in translate_input_schema(
            "SELECT typname FROM pg_type WHERE typname = 'int4'"
        )

    def test_a_qualified_pg_type_is_left_alone(self):
        from iris_pgwire.schema_mapper import translate_input_schema

        sql = "SELECT typname FROM pg_catalog.pg_type"
        assert translate_input_schema(sql).lower().count("pg_catalog") == 1

    def test_the_schema_mappers_list_agrees_with_the_view_definitions(self):
        """schema_mapper keeps its own copy (importing the definitions would be circular), and a
        comment there says a test keeps the two in agreement. Until now each view carried its own
        "the mapper knows it too" assertion, so a view added without one was silently unreachable
        by its bare name. This is the single comparison that was promised."""
        from iris_pgwire.schema_mapper import VIEW_BACKED_TABLES as MAPPER_TABLES

        assert MAPPER_TABLES == VIEW_BACKED_TABLES, (
            f"only in the mapper: {sorted(MAPPER_TABLES - VIEW_BACKED_TABLES)}; "
            f"only in the definitions: {sorted(VIEW_BACKED_TABLES - MAPPER_TABLES)}"
        )
