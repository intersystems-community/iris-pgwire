"""
Unit tests for iris_pgwire.catalog.pg_attrdef

Targets uncovered branches to push coverage from 80% → ≥85%.
No live IRIS connection required.
"""

import pytest

from iris_pgwire.catalog.oid_generator import OIDGenerator
from iris_pgwire.catalog.pg_attrdef import PgAttrdef, PgAttrdefEmulator
from iris_pgwire.schema_mapper import IRIS_SCHEMA


@pytest.fixture
def oid_gen():
    return OIDGenerator()


@pytest.fixture
def emulator(oid_gen):
    return PgAttrdefEmulator(oid_gen)


# ---------------------------------------------------------------------------
# PgAttrdef dataclass
# ---------------------------------------------------------------------------


class TestPgAttrdefDataclass:
    def test_fields_accessible(self, oid_gen):
        table_oid = oid_gen.get_table_oid("users")
        a = PgAttrdef(oid=100, adrelid=table_oid, adnum=1, adbin="42")
        assert a.oid == 100
        assert a.adrelid == table_oid
        assert a.adnum == 1
        assert a.adbin == "42"


# ---------------------------------------------------------------------------
# PgAttrdefEmulator — from_iris_default
# ---------------------------------------------------------------------------


class TestFromIrisDefault:
    def test_identity_default_maps_to_nextval(self, emulator):
        d = emulator.from_iris_default("users", "id", 1, "$IDENTITY")
        assert "nextval" in d.adbin
        assert "users_id_seq" in d.adbin

    def test_identity_keyword_variant(self, emulator):
        d = emulator.from_iris_default("orders", "order_id", 1, "IDENTITY")
        assert "nextval" in d.adbin

    def test_current_timestamp_default(self, emulator):
        d = emulator.from_iris_default("t", "created_at", 2, "CURRENT_TIMESTAMP")
        assert d.adbin == "CURRENT_TIMESTAMP"

    def test_now_default(self, emulator):
        d = emulator.from_iris_default("t", "ts", 2, "NOW()")
        assert d.adbin == "CURRENT_TIMESTAMP"

    def test_getdate_default(self, emulator):
        d = emulator.from_iris_default("t", "ts", 2, "GETDATE()")
        assert d.adbin == "CURRENT_TIMESTAMP"

    def test_sysdate_default(self, emulator):
        d = emulator.from_iris_default("t", "ts", 2, "SYSDATE")
        assert d.adbin == "CURRENT_TIMESTAMP"

    def test_current_date_default(self, emulator):
        d = emulator.from_iris_default("t", "d", 1, "CURRENT_DATE")
        assert d.adbin == "CURRENT_DATE"

    def test_current_time_default(self, emulator):
        d = emulator.from_iris_default("t", "ti", 1, "CURRENT_TIME")
        assert d.adbin == "CURRENT_TIME"

    def test_null_default(self, emulator):
        d = emulator.from_iris_default("t", "col", 1, "NULL")
        assert d.adbin == "NULL"

    def test_string_literal_preserved(self, emulator):
        d = emulator.from_iris_default("t", "status", 1, "'active'")
        assert d.adbin == "'active'"

    def test_numeric_default_preserved(self, emulator):
        d = emulator.from_iris_default("t", "score", 1, "0")
        assert d.adbin == "0"

    def test_float_default_preserved(self, emulator):
        d = emulator.from_iris_default("t", "weight", 1, "1.5")
        assert d.adbin == "1.5"

    def test_true_keyword_maps_to_lowercase_true(self, emulator):
        d = emulator.from_iris_default("t", "flag", 1, "TRUE")
        assert d.adbin == "true"

    def test_false_keyword_maps_to_lowercase_false(self, emulator):
        d = emulator.from_iris_default("t", "flag", 1, "FALSE")
        assert d.adbin == "false"

    def test_legacy_1_preserved_as_string_literal(self, emulator):
        # "'1'" starts and ends with ' so it is returned as-is (string literal path
        # is reached before the TRUE/'1' boolean check in _translate_default)
        d = emulator.from_iris_default("t", "flag", 1, "'1'")
        assert d.adbin == "'1'"

    def test_legacy_0_preserved_as_string_literal(self, emulator):
        d = emulator.from_iris_default("t", "flag", 1, "'0'")
        assert d.adbin == "'0'"

    def test_unknown_expression_returned_as_is(self, emulator):
        d = emulator.from_iris_default("t", "col", 1, "some_func()")
        assert d.adbin == "some_func()"

    def test_empty_default_returns_empty_string(self, emulator):
        d = emulator.from_iris_default("t", "col", 1, "")
        assert d.adbin == ""

    def test_whitespace_default_returns_empty_string(self, emulator):
        d = emulator.from_iris_default("t", "col", 1, "   ")
        # strip() leaves empty, which passes the empty check
        assert d.adbin == ""

    def test_oid_is_int(self, emulator):
        d = emulator.from_iris_default("t", "col", 1, "42")
        assert isinstance(d.oid, int)

    def test_adrelid_matches_table_oid(self, emulator, oid_gen):
        d = emulator.from_iris_default("users", "id", 1, "42")
        expected = oid_gen.get_table_oid("users", IRIS_SCHEMA)
        assert d.adrelid == expected

    def test_adnum_matches_column_position(self, emulator):
        d = emulator.from_iris_default("t", "c", 5, "0")
        assert d.adnum == 5


# ---------------------------------------------------------------------------
# PgAttrdefEmulator — add_default / get_all
# ---------------------------------------------------------------------------


class TestAddDefaultAndGetAll:
    def test_initially_empty(self, emulator):
        assert emulator.get_all() == []

    def test_add_default_appends(self, emulator):
        d = emulator.from_iris_default("t", "c", 1, "0")
        emulator.add_default(d)
        assert len(emulator.get_all()) == 1

    def test_multiple_defaults_stored(self, emulator):
        for i in range(3):
            d = emulator.from_iris_default("t", f"col{i}", i + 1, str(i))
            emulator.add_default(d)
        assert len(emulator.get_all()) == 3


# ---------------------------------------------------------------------------
# PgAttrdefEmulator — get_all_as_rows
# ---------------------------------------------------------------------------


class TestGetAllAsRows:
    def test_rows_match_defaults_count(self, emulator):
        for i in range(4):
            emulator.add_default(emulator.from_iris_default("t", f"c{i}", i + 1, str(i)))
        rows = emulator.get_all_as_rows()
        assert len(rows) == 4

    def test_each_row_is_tuple_of_4(self, emulator):
        emulator.add_default(emulator.from_iris_default("t", "c", 1, "0"))
        rows = emulator.get_all_as_rows()
        for row in rows:
            assert isinstance(row, tuple)
            assert len(row) == 4

    def test_row_values_match_attrdef(self, emulator):
        d = emulator.from_iris_default("t", "col", 3, "99")
        emulator.add_default(d)
        rows = emulator.get_all_as_rows()
        row = rows[-1]
        assert row[0] == d.oid
        assert row[1] == d.adrelid
        assert row[2] == d.adnum
        assert row[3] == d.adbin


# ---------------------------------------------------------------------------
# PgAttrdefEmulator — get_by_table_oid
# ---------------------------------------------------------------------------


class TestGetByTableOid:
    def test_empty_returns_empty_list(self, emulator, oid_gen):
        fake_oid = oid_gen.get_table_oid("ghost_table")
        assert emulator.get_by_table_oid(fake_oid) == []

    def test_returns_defaults_for_table(self, emulator, oid_gen):
        d1 = emulator.from_iris_default("orders", "id", 1, "$IDENTITY")
        d2 = emulator.from_iris_default("orders", "status", 2, "'pending'")
        emulator.add_default(d1)
        emulator.add_default(d2)

        table_oid = oid_gen.get_table_oid("orders", IRIS_SCHEMA)
        results = emulator.get_by_table_oid(table_oid)
        assert len(results) == 2

    def test_does_not_cross_contaminate_tables(self, emulator, oid_gen):
        d1 = emulator.from_iris_default("t1", "col", 1, "0")
        d2 = emulator.from_iris_default("t2", "col", 1, "1")
        emulator.add_default(d1)
        emulator.add_default(d2)

        t1_oid = oid_gen.get_table_oid("t1", IRIS_SCHEMA)
        t2_oid = oid_gen.get_table_oid("t2", IRIS_SCHEMA)
        assert len(emulator.get_by_table_oid(t1_oid)) == 1
        assert len(emulator.get_by_table_oid(t2_oid)) == 1


# ---------------------------------------------------------------------------
# PgAttrdefEmulator — get_by_table_oid_as_rows
# ---------------------------------------------------------------------------


class TestGetByTableOidAsRows:
    def test_returns_rows_for_table(self, emulator, oid_gen):
        d = emulator.from_iris_default("items", "price", 1, "0.0")
        emulator.add_default(d)
        table_oid = oid_gen.get_table_oid("items", IRIS_SCHEMA)
        rows = emulator.get_by_table_oid_as_rows(table_oid)
        assert len(rows) == 1
        assert isinstance(rows[0], tuple)

    def test_returns_empty_for_unknown_table(self, emulator, oid_gen):
        unknown_oid = oid_gen.get_table_oid("nonexistent_table")
        assert emulator.get_by_table_oid_as_rows(unknown_oid) == []


# ---------------------------------------------------------------------------
# PgAttrdefEmulator — get_by_column
# ---------------------------------------------------------------------------


class TestGetByColumn:
    def test_returns_none_when_not_found(self, emulator, oid_gen):
        fake_oid = oid_gen.get_table_oid("phantom")
        assert emulator.get_by_column(fake_oid, 1) is None

    def test_returns_correct_attrdef(self, emulator, oid_gen):
        d = emulator.from_iris_default("products", "price", 2, "0.0")
        emulator.add_default(d)
        table_oid = oid_gen.get_table_oid("products", IRIS_SCHEMA)
        result = emulator.get_by_column(table_oid, 2)
        assert result is not None
        assert result.adnum == 2

    def test_wrong_column_num_returns_none(self, emulator, oid_gen):
        d = emulator.from_iris_default("products", "price", 2, "0.0")
        emulator.add_default(d)
        table_oid = oid_gen.get_table_oid("products", IRIS_SCHEMA)
        assert emulator.get_by_column(table_oid, 99) is None


# ---------------------------------------------------------------------------
# PgAttrdefEmulator — get_column_definitions
# ---------------------------------------------------------------------------


class TestGetColumnDefinitions:
    def test_returns_4_columns(self):
        cols = PgAttrdefEmulator.get_column_definitions()
        assert len(cols) == 4

    def test_column_names(self):
        cols = PgAttrdefEmulator.get_column_definitions()
        names = [c["name"] for c in cols]
        assert names == ["oid", "adrelid", "adnum", "adbin"]

    def test_all_cols_have_type_oid(self):
        for col in PgAttrdefEmulator.get_column_definitions():
            assert "type_oid" in col
            assert "type_name" in col
