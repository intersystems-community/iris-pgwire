"""
Unit tests for iris_pgwire.catalog.pg_type

Targets uncovered branches to push coverage from 79% → ≥85%.
No live IRIS connection required.
"""

import pytest

from iris_pgwire.catalog.oid_generator import OIDGenerator
from iris_pgwire.catalog.pg_type import PgType, PgTypeEmulator


@pytest.fixture
def oid_gen():
    return OIDGenerator()


@pytest.fixture
def emulator(oid_gen):
    return PgTypeEmulator(oid_gen)


# ---------------------------------------------------------------------------
# PgType dataclass
# ---------------------------------------------------------------------------


class TestPgTypeDataclass:
    def test_fields_accessible(self):
        t = PgType(
            oid=23,
            typname="int4",
            typnamespace=11,
            typowner=10,
            typlen=4,
            typbyval=True,
            typtype="b",
            typcategory="N",
            typispreferred=False,
            typisdefined=True,
            typdelim=",",
            typrelid=0,
            typelem=0,
            typarray=0,
            typinput="int4in",
            typoutput="int4out",
            typnotnull=False,
        )
        assert t.oid == 23
        assert t.typname == "int4"
        assert t.typcategory == "N"
        assert t.typbyval is True


# ---------------------------------------------------------------------------
# PgTypeEmulator — initialization
# ---------------------------------------------------------------------------


class TestPgTypeEmulatorInit:
    def test_types_populated(self, emulator):
        types = emulator.get_all()
        assert len(types) == len(PgTypeEmulator.TYPES)

    def test_all_types_are_pg_type(self, emulator):
        for t in emulator.get_all():
            assert isinstance(t, PgType)

    def test_typnamespace_is_11(self, emulator):
        for t in emulator.get_all():
            assert t.typnamespace == 11

    def test_typowner_is_10(self, emulator):
        for t in emulator.get_all():
            assert t.typowner == 10

    def test_typtype_is_b(self, emulator):
        for t in emulator.get_all():
            assert t.typtype == "b"

    def test_typisdefined_true(self, emulator):
        for t in emulator.get_all():
            assert t.typisdefined is True

    def test_typdelim_comma(self, emulator):
        for t in emulator.get_all():
            assert t.typdelim == ","

    def test_typnotnull_false(self, emulator):
        for t in emulator.get_all():
            assert t.typnotnull is False

    def test_typbyval_true_for_small_types(self, emulator):
        """Types with 0 < typlen <= 8 should have typbyval=True."""
        for t in emulator.get_all():
            if 0 < t.typlen <= 8:
                assert t.typbyval is True

    def test_typbyval_false_for_variable_types(self, emulator):
        """Types with typlen=-1 should have typbyval=False."""
        for t in emulator.get_all():
            if t.typlen == -1:
                assert t.typbyval is False

    def test_input_output_names_derived_from_typname(self, emulator):
        for t in emulator.get_all():
            assert t.typinput == f"{t.typname}in"
            assert t.typoutput == f"{t.typname}out"


# ---------------------------------------------------------------------------
# get_by_name
# ---------------------------------------------------------------------------


class TestGetByName:
    def test_found_existing_type(self, emulator):
        t = emulator.get_by_name("int4")
        assert t is not None
        assert t.typname == "int4"
        assert t.oid == 23

    def test_not_found_returns_none(self, emulator):
        assert emulator.get_by_name("nonexistent_type") is None

    def test_all_type_names_findable(self, emulator):
        for name, oid, _, _ in PgTypeEmulator.TYPES:
            t = emulator.get_by_name(name)
            assert t is not None
            assert t.oid == oid


# ---------------------------------------------------------------------------
# get_by_oid
# ---------------------------------------------------------------------------


class TestGetByOid:
    def test_found_by_oid(self, emulator):
        t = emulator.get_by_oid(23)
        assert t is not None
        assert t.typname == "int4"

    def test_not_found_returns_none(self, emulator):
        assert emulator.get_by_oid(99999) is None

    def test_all_oids_findable(self, emulator):
        for name, oid, _, _ in PgTypeEmulator.TYPES:
            t = emulator.get_by_oid(oid)
            assert t is not None
            assert t.typname == name


# ---------------------------------------------------------------------------
# get_all_as_rows
# ---------------------------------------------------------------------------


class TestGetAllAsRows:
    def test_row_count_matches_types(self, emulator):
        rows = emulator.get_all_as_rows()
        assert len(rows) == len(PgTypeEmulator.TYPES)

    def test_each_row_is_tuple(self, emulator):
        for row in emulator.get_all_as_rows():
            assert isinstance(row, tuple)

    def test_row_length_matches_columns(self, emulator):
        cols = PgTypeEmulator.get_column_definitions()
        for row in emulator.get_all_as_rows():
            assert len(row) == len(cols)

    def test_first_element_is_oid(self, emulator):
        rows = emulator.get_all_as_rows()
        for row in rows:
            assert isinstance(row[0], int)

    def test_second_element_is_typname(self, emulator):
        rows = emulator.get_all_as_rows()
        for row in rows:
            assert isinstance(row[1], str)


# ---------------------------------------------------------------------------
# get_oid_for_iris_type
# ---------------------------------------------------------------------------


class TestGetOidForIrisType:
    @pytest.mark.parametrize("iris_type,expected_oid", [
        ("BOOLEAN", 16),
        ("INTEGER", 23),
        ("BIGINT", 20),
        ("VARCHAR", 1043),
        ("DOUBLE", 701),
        ("TIMESTAMP", 1114),
        ("DATE", 1082),
        ("VECTOR", 16388),
    ])
    def test_known_type_returns_correct_oid(self, emulator, iris_type, expected_oid):
        assert emulator.get_oid_for_iris_type(iris_type) == expected_oid

    def test_unknown_type_returns_text_oid(self, emulator):
        assert emulator.get_oid_for_iris_type("UNKNOWN_TYPE") == 25

    def test_case_insensitive(self, emulator):
        assert emulator.get_oid_for_iris_type("integer") == 23
        assert emulator.get_oid_for_iris_type("Integer") == 23


# ---------------------------------------------------------------------------
# get_column_definitions
# ---------------------------------------------------------------------------


class TestGetColumnDefinitions:
    def test_returns_17_columns(self):
        cols = PgTypeEmulator.get_column_definitions()
        assert len(cols) == 17

    def test_first_column_is_oid(self):
        cols = PgTypeEmulator.get_column_definitions()
        assert cols[0]["name"] == "oid"

    def test_all_cols_have_name_type_oid_type_name(self):
        for col in PgTypeEmulator.get_column_definitions():
            assert "name" in col
            assert "type_oid" in col
            assert "type_name" in col


# ---------------------------------------------------------------------------
# Specific type spot-checks
# ---------------------------------------------------------------------------


class TestSpecificTypes:
    def test_bool(self, emulator):
        t = emulator.get_by_name("bool")
        assert t.oid == 16
        assert t.typcategory == "B"
        assert t.typlen == 1

    def test_text(self, emulator):
        t = emulator.get_by_name("text")
        assert t.oid == 25
        assert t.typcategory == "S"
        assert t.typlen == -1

    def test_varchar(self, emulator):
        t = emulator.get_by_name("varchar")
        assert t.oid == 1043

    def test_timestamp(self, emulator):
        t = emulator.get_by_name("timestamp")
        assert t.typcategory == "D"

    def test_uuid(self, emulator):
        t = emulator.get_by_name("uuid")
        assert t.oid == 2950
        assert t.typlen == 16

    def test_vector(self, emulator):
        t = emulator.get_by_name("vector")
        assert t.oid == 16388
