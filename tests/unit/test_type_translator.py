"""Unit tests for TypeTranslator (sql_translator/type_translator.py).

No IRIS container required — pure logic tests.
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.ddl_parser import ColumnDefinition
from iris_pgwire.sql_translator.ddl_translator import DDLTranslationError
from iris_pgwire.sql_translator.type_translator import (
    DDL_TYPE_MAPPINGS,
    TYPE_PRECISION_LIMITS,
    TypeMappingEntry,
    TypeTranslator,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def translator() -> TypeTranslator:
    return TypeTranslator()


@pytest.fixture
def alter_translator() -> TypeTranslator:
    return TypeTranslator(use_alter_table_syntax=True)


# ---------------------------------------------------------------------------
# TypeMappingEntry dataclass
# ---------------------------------------------------------------------------


class TestTypeMappingEntry:
    def test_frozen(self):
        entry = TypeMappingEntry("text", "VARCHAR(32767)")
        with pytest.raises((AttributeError, TypeError)):
            entry.pg_type = "other"  # type: ignore[misc]

    def test_defaults(self):
        entry = TypeMappingEntry("text", "VARCHAR(32767)")
        assert entry.requires_precision is False
        assert entry.max_precision is None
        assert entry.max_scale is None

    def test_full_construction(self):
        entry = TypeMappingEntry("numeric", "NUMERIC", True, 38, 19)
        assert entry.requires_precision is True
        assert entry.max_precision == 38
        assert entry.max_scale == 19


# ---------------------------------------------------------------------------
# DDL_TYPE_MAPPINGS constant
# ---------------------------------------------------------------------------


class TestDDLTypeMappings:
    def test_key_types_present(self):
        for key in ("text", "integer", "bigint", "boolean", "uuid", "jsonb", "varchar", "bytea"):
            assert key in DDL_TYPE_MAPPINGS

    def test_numeric_has_precision(self):
        assert DDL_TYPE_MAPPINGS["numeric"].requires_precision is True

    def test_text_no_precision(self):
        assert DDL_TYPE_MAPPINGS["text"].requires_precision is False


# ---------------------------------------------------------------------------
# translate_type — simple types
# ---------------------------------------------------------------------------


class TestTranslateTypeSimple:
    def test_text(self, translator):
        assert translator.translate_type("text") == "VARCHAR(32767)"

    def test_integer(self, translator):
        assert translator.translate_type("integer") == "INTEGER"

    def test_int_alias(self, translator):
        assert translator.translate_type("int") == "INTEGER"

    def test_int4_alias(self, translator):
        assert translator.translate_type("int4") == "INTEGER"

    def test_bigint(self, translator):
        assert translator.translate_type("bigint") == "BIGINT"

    def test_smallint(self, translator):
        assert translator.translate_type("smallint") == "SMALLINT"

    def test_boolean(self, translator):
        assert translator.translate_type("boolean") == "BIT"

    def test_date(self, translator):
        assert translator.translate_type("date") == "DATE"

    def test_time(self, translator):
        assert translator.translate_type("time") == "TIME"

    def test_timestamp(self, translator):
        assert translator.translate_type("timestamp") == "TIMESTAMP"

    def test_timestamptz(self, translator):
        assert translator.translate_type("timestamptz") == "TIMESTAMP"

    def test_timestamp_without_time_zone(self, translator):
        assert translator.translate_type("timestamp without time zone") == "TIMESTAMP"

    def test_timestamp_with_time_zone(self, translator):
        assert translator.translate_type("timestamp with time zone") == "TIMESTAMP"

    def test_double_precision(self, translator):
        assert translator.translate_type("double precision") == "DOUBLE"

    def test_real(self, translator):
        assert translator.translate_type("real") == "REAL"

    def test_float4(self, translator):
        assert translator.translate_type("float4") == "REAL"

    def test_float8(self, translator):
        assert translator.translate_type("float8") == "DOUBLE"

    def test_interval(self, translator):
        assert translator.translate_type("interval") == "INTERVAL"

    def test_bit(self, translator):
        assert translator.translate_type("bit") == "BIT"


# ---------------------------------------------------------------------------
# translate_type — JSON/UUID → native class types
# ---------------------------------------------------------------------------


class TestTranslateTypeNativeClasses:
    def test_jsonb_maps_to_dynamic_object(self, translator):
        assert translator.translate_type("jsonb") == "%Library.DynamicObject"

    def test_json_maps_to_dynamic_object(self, translator):
        assert translator.translate_type("json") == "%Library.DynamicObject"

    def test_uuid_maps_to_unique_identifier(self, translator):
        assert translator.translate_type("uuid") == "%Library.UniqueIdentifier"


# ---------------------------------------------------------------------------
# translate_type — types requiring precision/length
# ---------------------------------------------------------------------------


class TestTranslateTypeWithPrecision:
    def test_varchar_with_length(self, translator):
        assert translator.translate_type("varchar(100)") == "VARCHAR(100)"

    def test_varchar_no_length(self, translator):
        # No precision supplied → no parens added by translate_type
        assert translator.translate_type("varchar") == "VARCHAR"

    def test_char_with_length(self, translator):
        assert translator.translate_type("char(10)") == "CHAR(10)"

    def test_character_varying(self, translator):
        assert translator.translate_type("character varying(50)") == "VARCHAR(50)"

    def test_character(self, translator):
        assert translator.translate_type("character(5)") == "CHAR(5)"

    def test_numeric_with_precision_scale(self, translator):
        assert translator.translate_type("numeric(10,2)") == "NUMERIC(10,2)"

    def test_numeric_precision_only(self, translator):
        assert translator.translate_type("numeric(15)") == "NUMERIC(15)"

    def test_decimal_with_precision_scale(self, translator):
        assert translator.translate_type("decimal(8,3)") == "NUMERIC(8,3)"

    def test_bytea(self, translator):
        # bytea → VARBINARY; requires_precision but no parens supplied → no parens
        result = translator.translate_type("bytea")
        assert result == "VARBINARY"

    def test_varbinary_with_length(self, translator):
        assert translator.translate_type("varbinary(500)") == "VARBINARY(500)"

    def test_bit_varying_with_length(self, translator):
        assert translator.translate_type("bit varying(64)") == "VARBINARY(64)"

    def test_jsonpath(self, translator):
        # jsonpath → VARCHAR(*) which hits JSON path only if iris_type == "JSON"; here it won't
        result = translator.translate_type("jsonpath")
        # jsonpath maps to VARCHAR(*); no precision → VARCHAR(*)
        assert result == "VARCHAR(*)"

    def test_varchar_star_precision(self, translator):
        # VARCHAR(*) special case in _extract_precision
        result = translator.translate_type("varchar(*)")
        assert result == "VARCHAR(32767)"

    def test_money(self, translator):
        assert translator.translate_type("money") == "NUMERIC"


# ---------------------------------------------------------------------------
# translate_type — IDENTITY types (serial variants)
# ---------------------------------------------------------------------------


class TestIdentityTypes:
    def test_serial(self, translator):
        assert translator.translate_type("serial") == "INTEGER IDENTITY(1,1)"

    def test_smallserial(self, translator):
        assert translator.translate_type("smallserial") == "SMALLINT IDENTITY(1,1)"

    def test_bigserial(self, translator):
        assert translator.translate_type("bigserial") == "BIGINT IDENTITY(1,1)"


# ---------------------------------------------------------------------------
# translate_type — case-insensitive input
# ---------------------------------------------------------------------------


class TestCaseInsensitivity:
    def test_uppercase_integer(self, translator):
        assert translator.translate_type("INTEGER") == "INTEGER"

    def test_mixed_case_varchar(self, translator):
        assert translator.translate_type("VARCHAR(50)") == "VARCHAR(50)"

    def test_mixed_case_boolean(self, translator):
        assert translator.translate_type("BOOLEAN") == "BIT"

    def test_mixed_case_timestamp(self, translator):
        assert translator.translate_type("TIMESTAMP") == "TIMESTAMP"

    def test_mixed_case_bigint(self, translator):
        assert translator.translate_type("BigInt") == "BIGINT"


# ---------------------------------------------------------------------------
# translate_type — unknown type raises DDLTranslationError
# ---------------------------------------------------------------------------


class TestUnknownType:
    def test_unknown_type_raises(self, translator):
        with pytest.raises(DDLTranslationError) as exc_info:
            translator.translate_type("xml")
        err = exc_info.value
        assert err.error_code == "UNSUPPORTED_TYPE"
        assert "xml" in err.message.lower()

    def test_unknown_type_suggested_fix(self, translator):
        with pytest.raises(DDLTranslationError) as exc_info:
            translator.translate_type("citext")
        assert exc_info.value.suggested_fix is not None

    def test_empty_type_after_strip_raises(self, translator):
        with pytest.raises(DDLTranslationError):
            translator.translate_type("totally_unknown_type")


# ---------------------------------------------------------------------------
# translate_type — precision validation errors
# ---------------------------------------------------------------------------


class TestPrecisionValidation:
    def test_numeric_precision_exceeded(self, translator):
        with pytest.raises(DDLTranslationError) as exc_info:
            translator.translate_type("numeric(100,2)")
        assert exc_info.value.error_code == "PRECISION_EXCEEDED"

    def test_numeric_scale_exceeded(self, translator):
        with pytest.raises(DDLTranslationError) as exc_info:
            translator.translate_type("numeric(20,25)")
        assert exc_info.value.error_code == "SCALE_EXCEEDED"

    def test_varchar_length_exceeded(self, translator):
        with pytest.raises(DDLTranslationError) as exc_info:
            translator.translate_type("varchar(99999)")
        assert exc_info.value.error_code == "LENGTH_EXCEEDED"

    def test_char_length_exceeded(self, translator):
        with pytest.raises(DDLTranslationError) as exc_info:
            translator.translate_type("char(99999)")
        assert exc_info.value.error_code == "LENGTH_EXCEEDED"

    def test_varbinary_length_exceeded(self, translator):
        with pytest.raises(DDLTranslationError) as exc_info:
            translator.translate_type("varbinary(99999)")
        assert exc_info.value.error_code == "LENGTH_EXCEEDED"

    def test_numeric_at_max_precision_ok(self, translator):
        result = translator.translate_type("numeric(38,19)")
        assert result == "NUMERIC(38,19)"

    def test_varchar_at_max_length_ok(self, translator):
        result = translator.translate_type("varchar(32767)")
        assert result == "VARCHAR(32767)"


# ---------------------------------------------------------------------------
# use_alter_table_syntax — VARCHAR → %Library.String
# ---------------------------------------------------------------------------


class TestAlterTableSyntax:
    def test_varchar_n_becomes_library_string(self, alter_translator):
        result = alter_translator.translate_type("varchar(255)")
        assert result == "%Library.String(MAXLEN=255)"

    def test_varchar_star_becomes_library_string_maxlen(self, alter_translator):
        result = alter_translator.translate_type("varchar(*)")
        assert result == "%Library.String(MAXLEN=32767)"

    def test_text_becomes_library_string(self, alter_translator):
        # text → VARCHAR(32767) → then alter rewrite
        result = alter_translator.translate_type("text")
        assert result == "%Library.String(MAXLEN=32767)"

    def test_integer_unaffected_by_alter_flag(self, alter_translator):
        assert alter_translator.translate_type("integer") == "INTEGER"

    def test_standard_translator_no_rewrite(self, translator):
        # Sanity: standard translator leaves VARCHAR(255) alone
        assert translator.translate_type("varchar(255)") == "VARCHAR(255)"


# ---------------------------------------------------------------------------
# translate_column
# ---------------------------------------------------------------------------


class TestTranslateColumn:
    def _make_col(self, pg_type: str, name: str = "col") -> ColumnDefinition:
        return ColumnDefinition(
            name=name,
            pg_type=pg_type,
            iris_type="",
            nullable=True,
            default=None,
            is_primary_key=False,
        )

    def test_translate_column_integer(self, translator):
        col = self._make_col("integer", "user_id")
        result = translator.translate_column(col)
        assert result.iris_type == "INTEGER"
        assert result.name == "user_id"
        assert result.pg_type == "integer"
        assert result.nullable is True

    def test_translate_column_text(self, translator):
        col = self._make_col("text", "description")
        result = translator.translate_column(col)
        assert result.iris_type == "VARCHAR(32767)"

    def test_translate_column_preserves_pk(self, translator):
        col = ColumnDefinition(
            name="id",
            pg_type="bigint",
            iris_type="",
            nullable=False,
            default=None,
            is_primary_key=True,
        )
        result = translator.translate_column(col)
        assert result.is_primary_key is True
        assert result.iris_type == "BIGINT"

    def test_translate_column_varchar_precision(self, translator):
        col = self._make_col("varchar(64)", "username")
        result = translator.translate_column(col)
        assert result.iris_type == "VARCHAR(64)"

    def test_translate_column_with_default(self, translator):
        col = ColumnDefinition(
            name="status",
            pg_type="text",
            iris_type="",
            nullable=True,
            default="'active'",
            is_primary_key=False,
        )
        result = translator.translate_column(col)
        assert result.default == "'active'"


# ---------------------------------------------------------------------------
# Internal helpers (_extract_base_type, _extract_precision)
# ---------------------------------------------------------------------------


class TestExtractBaseType:
    def test_no_parens(self, translator):
        assert translator._extract_base_type("integer") == "integer"

    def test_strips_precision(self, translator):
        assert translator._extract_base_type("varchar(100)") == "varchar"

    def test_strips_whitespace(self, translator):
        assert translator._extract_base_type("  bigint  ") == "bigint"

    def test_multi_word(self, translator):
        assert translator._extract_base_type("double precision") == "double precision"

    def test_uppercased_becomes_lower(self, translator):
        assert translator._extract_base_type("INTEGER") == "integer"


class TestExtractPrecision:
    def test_no_parens(self, translator):
        assert translator._extract_precision("integer") == (None, None)

    def test_single_precision(self, translator):
        assert translator._extract_precision("varchar(255)") == (255, None)

    def test_precision_and_scale(self, translator):
        assert translator._extract_precision("numeric(10,2)") == (10, 2)

    def test_star_precision(self, translator):
        p, s = translator._extract_precision("varchar(*)")
        assert p == 32767
        assert s is None

    def test_empty_parens(self, translator):
        assert translator._extract_precision("varchar()") == (None, None)

    def test_non_numeric_precision_ignored(self, translator):
        p, s = translator._extract_precision("varchar(abc)")
        assert p is None


# ---------------------------------------------------------------------------
# TYPE_PRECISION_LIMITS constant
# ---------------------------------------------------------------------------


class TestTypePrecisionLimits:
    def test_numeric_limits(self):
        assert TYPE_PRECISION_LIMITS["NUMERIC"]["max_precision"] == 38
        assert TYPE_PRECISION_LIMITS["NUMERIC"]["max_scale"] == 19

    def test_varchar_limit(self):
        assert TYPE_PRECISION_LIMITS["VARCHAR"]["max_length"] == 32767

    def test_char_limit(self):
        assert TYPE_PRECISION_LIMITS["CHAR"]["max_length"] == 32767

    def test_varbinary_limit(self):
        assert TYPE_PRECISION_LIMITS["VARBINARY"]["max_length"] == 32767
