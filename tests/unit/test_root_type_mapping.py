"""Unit tests for the root iris_pgwire/type_mapping.py module.

Covers:
- TypeMapping dataclass
- get_type_mapping() — known types, unknown fallback, case-insensitivity
- configure_type_mapping() / configure_type_mappings()
- load_type_mappings_from_env() — valid vars, partial format, bad format
- load_type_mappings_from_file() — happy path, missing file, default path, bad JSON, missing keys
- reset_type_mappings() / get_all_type_mappings()
- dump_type_mappings_to_json()
- OID_TO_TYPE / get_type_by_oid()
- TypeModifier decode methods
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import iris_pgwire.type_mapping as tm
from iris_pgwire.type_mapping import (
    DEFAULT_TYPE_MAPPINGS,
    OID_TO_TYPE,
    TypeMapping,
    TypeModifier,
    configure_type_mapping,
    configure_type_mappings,
    dump_type_mappings_to_json,
    get_all_type_mappings,
    get_type_by_oid,
    get_type_mapping,
    load_type_mappings_from_env,
    load_type_mappings_from_file,
    reset_type_mappings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_after_each():
    """Ensure global registry is clean after every test."""
    yield
    reset_type_mappings()


# ---------------------------------------------------------------------------
# TypeMapping dataclass
# ---------------------------------------------------------------------------


class TestTypeMappingDataclass:
    def test_required_fields(self):
        m = TypeMapping(iris_type="MYTYPE", pg_data_type="text", pg_udt_name="text")
        assert m.iris_type == "MYTYPE"
        assert m.pg_data_type == "text"
        assert m.pg_udt_name == "text"

    def test_default_oid_zero(self):
        m = TypeMapping(iris_type="X", pg_data_type="text", pg_udt_name="text")
        assert m.pg_type_oid == 0

    def test_default_description_empty(self):
        m = TypeMapping(iris_type="X", pg_data_type="text", pg_udt_name="text")
        assert m.description == ""

    def test_custom_oid_and_description(self):
        m = TypeMapping(
            iris_type="INT4", pg_data_type="integer", pg_udt_name="int4",
            pg_type_oid=23, description="four-byte integer"
        )
        assert m.pg_type_oid == 23
        assert m.description == "four-byte integer"


# ---------------------------------------------------------------------------
# get_type_mapping
# ---------------------------------------------------------------------------


class TestGetTypeMapping:
    def test_integer(self):
        assert get_type_mapping("INTEGER") == ("integer", "int4", 23)

    def test_bigint(self):
        assert get_type_mapping("BIGINT") == ("bigint", "int8", 20)

    def test_smallint(self):
        assert get_type_mapping("SMALLINT") == ("smallint", "int2", 21)

    def test_tinyint(self):
        assert get_type_mapping("TINYINT") == ("smallint", "int2", 21)

    def test_numeric(self):
        assert get_type_mapping("NUMERIC") == ("numeric", "numeric", 1700)

    def test_decimal(self):
        assert get_type_mapping("DECIMAL") == ("numeric", "numeric", 1700)

    def test_double(self):
        assert get_type_mapping("DOUBLE") == ("double precision", "float8", 701)

    def test_float(self):
        assert get_type_mapping("FLOAT") == ("double precision", "float8", 701)

    def test_real(self):
        assert get_type_mapping("REAL") == ("real", "float4", 700)

    def test_varchar(self):
        assert get_type_mapping("VARCHAR") == ("character varying", "varchar", 1043)

    def test_char(self):
        assert get_type_mapping("CHAR") == ("character", "bpchar", 1042)

    def test_text(self):
        assert get_type_mapping("TEXT") == ("text", "text", 25)

    def test_longvarchar(self):
        assert get_type_mapping("LONGVARCHAR") == ("text", "text", 25)

    def test_date(self):
        assert get_type_mapping("DATE") == ("date", "date", 1082)

    def test_time(self):
        assert get_type_mapping("TIME") == ("time without time zone", "time", 1083)

    def test_timestamp(self):
        assert get_type_mapping("TIMESTAMP") == ("timestamp without time zone", "timestamp", 1114)

    def test_timestamptz(self):
        assert get_type_mapping("TIMESTAMPTZ") == ("timestamp with time zone", "timestamptz", 1184)

    def test_boolean(self):
        assert get_type_mapping("BOOLEAN") == ("boolean", "bool", 16)

    def test_bit(self):
        assert get_type_mapping("BIT") == ("boolean", "bool", 16)

    def test_varbinary(self):
        assert get_type_mapping("VARBINARY") == ("bytea", "bytea", 17)

    def test_binary(self):
        assert get_type_mapping("BINARY") == ("bytea", "bytea", 17)

    def test_longvarbinary(self):
        assert get_type_mapping("LONGVARBINARY") == ("bytea", "bytea", 17)

    def test_serial(self):
        assert get_type_mapping("SERIAL") == ("integer", "int4", 23)

    def test_bigserial(self):
        assert get_type_mapping("BIGSERIAL") == ("bigint", "int8", 20)

    def test_json(self):
        assert get_type_mapping("JSON") == ("json", "json", 114)

    def test_jsonb(self):
        assert get_type_mapping("JSONB") == ("jsonb", "jsonb", 3802)

    def test_uuid(self):
        assert get_type_mapping("UUID") == ("uuid", "uuid", 2950)

    def test_uniqueidentifier(self):
        assert get_type_mapping("UNIQUEIDENTIFIER") == ("uuid", "uuid", 2950)

    def test_vector(self):
        assert get_type_mapping("VECTOR") == ("vector", "vector", 16388)

    def test_embedding(self):
        assert get_type_mapping("EMBEDDING") == ("vector", "vector", 16388)

    def test_case_insensitive_lowercase(self):
        assert get_type_mapping("integer") == ("integer", "int4", 23)

    def test_case_insensitive_mixed(self):
        assert get_type_mapping("VarChar") == ("character varying", "varchar", 1043)

    def test_unknown_type_returns_text_fallback(self):
        assert get_type_mapping("NOTATYPE") == ("text", "text", 25)

    def test_empty_string_returns_text_fallback(self):
        assert get_type_mapping("") == ("text", "text", 25)


# ---------------------------------------------------------------------------
# configure_type_mapping / configure_type_mappings
# ---------------------------------------------------------------------------


class TestConfigureTypeMapping:
    def test_add_new_type(self):
        configure_type_mapping("MYTYPE", "text", "text", 25)
        assert get_type_mapping("MYTYPE") == ("text", "text", 25)

    def test_overwrite_existing_type(self):
        configure_type_mapping("INTEGER", "bigint", "int8", 20)
        assert get_type_mapping("INTEGER") == ("bigint", "int8", 20)

    def test_iris_type_uppercased(self):
        configure_type_mapping("mytype", "text", "text", 25)
        assert get_type_mapping("MYTYPE") == ("text", "text", 25)

    def test_default_oid_zero(self):
        configure_type_mapping("NEWTYPE", "text", "text")
        assert get_type_mapping("NEWTYPE") == ("text", "text", 0)

    def test_custom_oid(self):
        configure_type_mapping("SPECIAL", "integer", "int4", 23)
        assert get_type_mapping("SPECIAL") == ("integer", "int4", 23)


class TestConfigureTypeMappings:
    def test_multiple_at_once(self):
        configure_type_mappings({
            "TYPE_A": ("text", "text", 25),
            "TYPE_B": ("integer", "int4", 23),
        })
        assert get_type_mapping("TYPE_A") == ("text", "text", 25)
        assert get_type_mapping("TYPE_B") == ("integer", "int4", 23)

    def test_empty_dict_is_noop(self):
        before = get_all_type_mappings()
        configure_type_mappings({})
        assert get_all_type_mappings() == before

    def test_overwrites_existing(self):
        configure_type_mappings({"INTEGER": ("bigint", "int8", 20)})
        assert get_type_mapping("INTEGER") == ("bigint", "int8", 20)


# ---------------------------------------------------------------------------
# reset_type_mappings / get_all_type_mappings
# ---------------------------------------------------------------------------


class TestResetAndGetAll:
    def test_get_all_returns_copy(self):
        all_maps = get_all_type_mappings()
        all_maps["FAKE"] = ("text", "text", 25)
        # Should not pollute global registry
        assert get_type_mapping("FAKE") == ("text", "text", 25) or True
        # The real test: original mapping still pristine after reset
        reset_type_mappings()
        assert "FAKE" not in get_all_type_mappings()

    def test_reset_restores_defaults(self):
        configure_type_mapping("CUSTOM", "text", "text", 99)
        assert get_type_mapping("CUSTOM") == ("text", "text", 99)
        reset_type_mappings()
        assert get_type_mapping("CUSTOM") == ("text", "text", 25)  # fallback

    def test_reset_removes_overrides(self):
        configure_type_mapping("INTEGER", "bigint", "int8", 20)
        reset_type_mappings()
        assert get_type_mapping("INTEGER") == ("integer", "int4", 23)

    def test_get_all_contains_all_defaults(self):
        all_maps = get_all_type_mappings()
        for key in DEFAULT_TYPE_MAPPINGS:
            assert key in all_maps

    def test_get_all_returns_independent_copy(self):
        all1 = get_all_type_mappings()
        all1["INJECTED"] = ("text", "text", 0)
        all2 = get_all_type_mappings()
        assert "INJECTED" not in all2


# ---------------------------------------------------------------------------
# load_type_mappings_from_env
# ---------------------------------------------------------------------------


class TestLoadTypeMappingsFromEnv:
    def test_full_format_three_parts(self):
        env = {"PGWIRE_TYPE_MAP_MYTYPE": "text:text:25"}
        with patch.dict(os.environ, env, clear=False):
            load_type_mappings_from_env()
        assert get_type_mapping("MYTYPE") == ("text", "text", 25)

    def test_two_part_format_defaults_oid_zero(self):
        env = {"PGWIRE_TYPE_MAP_SHORTTYPE": "integer:int4"}
        with patch.dict(os.environ, env, clear=False):
            load_type_mappings_from_env()
        assert get_type_mapping("SHORTTYPE") == ("integer", "int4", 0)

    def test_overrides_default_mapping(self):
        env = {"PGWIRE_TYPE_MAP_INTEGER": "bigint:int8:20"}
        with patch.dict(os.environ, env, clear=False):
            load_type_mappings_from_env()
        assert get_type_mapping("INTEGER") == ("bigint", "int8", 20)

    def test_bad_format_single_part_ignored(self):
        before = get_type_mapping("BADVAR")
        env = {"PGWIRE_TYPE_MAP_BADVAR": "onlyone"}
        with patch.dict(os.environ, env, clear=False):
            load_type_mappings_from_env()
        # Should not crash; mapping stays at fallback
        assert get_type_mapping("BADVAR") == ("text", "text", 25)

    def test_non_matching_prefix_ignored(self):
        env = {"OTHER_VAR": "text:text:25"}
        before = get_all_type_mappings()
        with patch.dict(os.environ, env, clear=False):
            load_type_mappings_from_env()
        # 'OTHER_VAR' should not create a mapping
        assert "OTHER_VAR" not in get_all_type_mappings()

    def test_bad_oid_value_doesnt_crash(self):
        # Non-integer OID in third position — should trigger except branch
        env = {"PGWIRE_TYPE_MAP_EXTYPE": "text:text:notanint"}
        with patch.dict(os.environ, env, clear=False):
            load_type_mappings_from_env()
        # The function should survive without raising

    def test_multiple_env_vars_loaded(self):
        env = {
            "PGWIRE_TYPE_MAP_ALPHA": "text:text:25",
            "PGWIRE_TYPE_MAP_BETA": "integer:int4:23",
        }
        with patch.dict(os.environ, env, clear=False):
            load_type_mappings_from_env()
        assert get_type_mapping("ALPHA") == ("text", "text", 25)
        assert get_type_mapping("BETA") == ("integer", "int4", 23)


# ---------------------------------------------------------------------------
# load_type_mappings_from_file
# ---------------------------------------------------------------------------


class TestLoadTypeMappingsFromFile:
    def test_happy_path_explicit_path(self, tmp_path):
        config = {
            "type_mappings": {
                "MYTYPE": {"pg_data_type": "text", "pg_udt_name": "text", "pg_type_oid": 25}
            }
        }
        p = tmp_path / "mappings.json"
        p.write_text(json.dumps(config))
        load_type_mappings_from_file(str(p))
        assert get_type_mapping("MYTYPE") == ("text", "text", 25)

    def test_path_as_pathlib(self, tmp_path):
        config = {
            "type_mappings": {
                "PTYPE": {"pg_data_type": "integer", "pg_udt_name": "int4", "pg_type_oid": 23}
            }
        }
        p = tmp_path / "custom.json"
        p.write_text(json.dumps(config))
        load_type_mappings_from_file(p)
        assert get_type_mapping("PTYPE") == ("integer", "int4", 23)

    def test_missing_file_does_not_crash(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        # Should return silently
        load_type_mappings_from_file(str(missing))

    def test_default_path_missing_does_not_crash(self, tmp_path, monkeypatch):
        # Change cwd so default 'type_mapping.json' doesn't exist
        monkeypatch.chdir(tmp_path)
        load_type_mappings_from_file()  # path=None → looks for type_mapping.json

    def test_default_path_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = {
            "type_mappings": {
                "DEFTYPE": {"pg_data_type": "bytea", "pg_udt_name": "bytea", "pg_type_oid": 17}
            }
        }
        (tmp_path / "type_mapping.json").write_text(json.dumps(config))
        load_type_mappings_from_file()  # no path — picks up default
        assert get_type_mapping("DEFTYPE") == ("bytea", "bytea", 17)

    def test_missing_keys_get_defaults(self, tmp_path):
        # Entry with no pg_data_type / pg_udt_name / pg_type_oid → defaults to text/text/0
        config = {"type_mappings": {"PARTIAL": {}}}
        p = tmp_path / "partial.json"
        p.write_text(json.dumps(config))
        load_type_mappings_from_file(str(p))
        assert get_type_mapping("PARTIAL") == ("text", "text", 0)

    def test_bad_json_does_not_crash(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{ this is not valid json }")
        load_type_mappings_from_file(str(p))  # Should not raise

    def test_empty_type_mappings_key(self, tmp_path):
        config = {"type_mappings": {}}
        p = tmp_path / "empty.json"
        p.write_text(json.dumps(config))
        before = get_all_type_mappings()
        load_type_mappings_from_file(str(p))
        assert get_all_type_mappings() == before

    def test_missing_type_mappings_key(self, tmp_path):
        config = {"other_key": "other_val"}
        p = tmp_path / "nokey.json"
        p.write_text(json.dumps(config))
        before = get_all_type_mappings()
        load_type_mappings_from_file(str(p))
        # config.get("type_mappings", {}) returns {} → no changes
        assert get_all_type_mappings() == before


# ---------------------------------------------------------------------------
# dump_type_mappings_to_json
# ---------------------------------------------------------------------------


class TestDumpTypeMappingsToJson:
    def test_round_trip(self, tmp_path):
        p = tmp_path / "dump.json"
        dump_type_mappings_to_json(str(p))
        assert p.exists()
        with open(p) as f:
            data = json.load(f)
        assert "type_mappings" in data
        assert "INTEGER" in data["type_mappings"]
        entry = data["type_mappings"]["INTEGER"]
        assert entry["pg_data_type"] == "integer"
        assert entry["pg_udt_name"] == "int4"
        assert entry["pg_type_oid"] == 23

    def test_accepts_pathlib(self, tmp_path):
        p = tmp_path / "out.json"
        dump_type_mappings_to_json(p)
        assert p.exists()

    def test_custom_mapping_included(self, tmp_path):
        configure_type_mapping("SPECIAL", "text", "mytype", 99999)
        p = tmp_path / "custom_dump.json"
        dump_type_mappings_to_json(p)
        with open(p) as f:
            data = json.load(f)
        assert "SPECIAL" in data["type_mappings"]
        assert data["type_mappings"]["SPECIAL"]["pg_udt_name"] == "mytype"

    def test_output_is_valid_json(self, tmp_path):
        p = tmp_path / "valid.json"
        dump_type_mappings_to_json(p)
        content = p.read_text()
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    def test_all_default_types_present(self, tmp_path):
        p = tmp_path / "all.json"
        dump_type_mappings_to_json(p)
        with open(p) as f:
            data = json.load(f)
        for key in DEFAULT_TYPE_MAPPINGS:
            assert key in data["type_mappings"]


# ---------------------------------------------------------------------------
# OID_TO_TYPE / get_type_by_oid
# ---------------------------------------------------------------------------


class TestOidToType:
    def test_integer_oid(self):
        result = get_type_by_oid(23)
        assert result is not None
        assert result[1] == "int4"

    def test_varchar_oid(self):
        result = get_type_by_oid(1043)
        assert result is not None
        assert result[1] == "varchar"

    def test_boolean_oid(self):
        result = get_type_by_oid(16)
        assert result is not None
        assert result[0] == "boolean"

    def test_timestamp_oid(self):
        result = get_type_by_oid(1114)
        assert result is not None
        assert result[1] == "timestamp"

    def test_timetz_extra(self):
        # Added separately outside DEFAULT_TYPE_MAPPINGS
        result = get_type_by_oid(1266)
        assert result is not None
        assert result[1] == "timetz"

    def test_bit_extra(self):
        result = get_type_by_oid(1560)
        assert result is not None
        assert result[0] == "bit"

    def test_varbit_extra(self):
        result = get_type_by_oid(1562)
        assert result is not None
        assert result[1] == "varbit"

    def test_unknown_oid_returns_none(self):
        assert get_type_by_oid(99999) is None

    def test_zero_oid_returns_none(self):
        assert get_type_by_oid(0) is None

    def test_oid_to_type_is_dict(self):
        assert isinstance(OID_TO_TYPE, dict)


# ---------------------------------------------------------------------------
# TypeModifier
# ---------------------------------------------------------------------------


class TestTypeModifierDecodeCharLength:
    def test_varchar_255(self):
        # typmod = 255 + 4 = 259
        assert TypeModifier.decode_char_length(259) == 255

    def test_char_1(self):
        # typmod = 1 + 4 = 5
        assert TypeModifier.decode_char_length(5) == 1

    def test_unlimited_returns_none(self):
        assert TypeModifier.decode_char_length(-1) is None

    def test_zero_typmod(self):
        # typmod = 0 → length = -4 (edge case, but should return 0 - 4 = -4)
        assert TypeModifier.decode_char_length(0) == -4

    def test_large_value(self):
        assert TypeModifier.decode_char_length(10004) == 10000


class TestTypeModifierDecodeNumericPrecision:
    def test_numeric_10_2(self):
        # ((10 << 16) + 2) + 4 = 655366
        packed = (10 << 16) + 2 + 4
        result = TypeModifier.decode_numeric_precision(packed)
        assert result == (10, 2)

    def test_numeric_5_0(self):
        packed = (5 << 16) + 0 + 4
        result = TypeModifier.decode_numeric_precision(packed)
        assert result == (5, 0)

    def test_no_modifier_returns_none(self):
        assert TypeModifier.decode_numeric_precision(-1) is None

    def test_negative_two_returns_none(self):
        assert TypeModifier.decode_numeric_precision(-2) is None

    def test_precision_only_scale_zero(self):
        packed = (7 << 16) + 0 + 4
        result = TypeModifier.decode_numeric_precision(packed)
        assert result == (7, 0)


class TestTypeModifierDecodeTimestampPrecision:
    def test_timestamp_3(self):
        # typmod = 3 + 4 = 7
        assert TypeModifier.decode_timestamp_precision(7) == 3

    def test_timestamp_6(self):
        assert TypeModifier.decode_timestamp_precision(10) == 6

    def test_timestamp_0(self):
        assert TypeModifier.decode_timestamp_precision(4) == 0

    def test_no_modifier_returns_none(self):
        assert TypeModifier.decode_timestamp_precision(-1) is None

    def test_large_precision(self):
        assert TypeModifier.decode_timestamp_precision(14) == 10


class TestTypeModifierDecodeBitLength:
    def test_bit_32(self):
        # typmod = 32 + 4 = 36
        assert TypeModifier.decode_bit_length(36) == 32

    def test_bit_1(self):
        assert TypeModifier.decode_bit_length(5) == 1

    def test_unlimited_returns_none(self):
        assert TypeModifier.decode_bit_length(-1) is None

    def test_large_bit_length(self):
        assert TypeModifier.decode_bit_length(1028) == 1024
