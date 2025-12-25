"""
Contract Tests: format_type() Function

Validates format_type(type_oid, typmod) behavior per contracts/format_type_contract.md

Tests cover:
- Basic types without typmod
- Parameterized types (varchar, numeric, timestamp, bit)
- Edge cases (unknown OIDs, NULL)
"""

import pytest

from iris_pgwire.catalog.catalog_functions import CatalogFunctionHandler
from iris_pgwire.catalog.oid_generator import OIDGenerator


@pytest.fixture
def catalog_handler():
    """Create CatalogFunctionHandler for testing."""
    oid_gen = OIDGenerator()
    # Mock executor - format_type doesn't need it
    return CatalogFunctionHandler(oid_gen, executor=None)


# ============================================================================
# Basic Types (no typmod)
# ============================================================================


def test_format_type_integer(catalog_handler):
    """Test format_type with integer type."""
    result = catalog_handler.format_type(23, -1)
    assert result == "integer"


def test_format_type_text(catalog_handler):
    """Test format_type with text type."""
    result = catalog_handler.format_type(25, -1)
    assert result == "text"


def test_format_type_boolean(catalog_handler):
    """Test format_type with boolean type."""
    result = catalog_handler.format_type(16, -1)
    assert result == "boolean"


def test_format_type_bigint(catalog_handler):
    """Test format_type with bigint type."""
    result = catalog_handler.format_type(20, -1)
    assert result == "bigint"


def test_format_type_smallint(catalog_handler):
    """Test format_type with smallint type."""
    result = catalog_handler.format_type(21, -1)
    assert result == "smallint"


def test_format_type_double(catalog_handler):
    """Test format_type with double precision type."""
    result = catalog_handler.format_type(701, -1)
    assert result == "double precision"


def test_format_type_real(catalog_handler):
    """Test format_type with real type."""
    result = catalog_handler.format_type(700, -1)
    assert result == "real"


def test_format_type_bytea(catalog_handler):
    """Test format_type with bytea type."""
    result = catalog_handler.format_type(17, -1)
    assert result == "bytea"


def test_format_type_date(catalog_handler):
    """Test format_type with date type."""
    result = catalog_handler.format_type(1082, -1)
    assert result == "date"


def test_format_type_uuid(catalog_handler):
    """Test format_type with uuid type."""
    result = catalog_handler.format_type(2950, -1)
    assert result == "uuid"


def test_format_type_jsonb(catalog_handler):
    """Test format_type with jsonb type."""
    result = catalog_handler.format_type(3802, -1)
    assert result == "jsonb"


def test_format_type_json(catalog_handler):
    """Test format_type with json type."""
    result = catalog_handler.format_type(114, -1)
    assert result == "json"


# ============================================================================
# Parameterized Types - Character
# ============================================================================


def test_format_type_varchar_255(catalog_handler):
    """Test format_type with varchar(255)."""
    # typmod = length + 4 = 255 + 4 = 259
    result = catalog_handler.format_type(1043, 259)
    assert result == "character varying(255)"


def test_format_type_varchar_unlimited(catalog_handler):
    """Test format_type with unlimited varchar."""
    result = catalog_handler.format_type(1043, -1)
    assert result == "character varying"


def test_format_type_char_10(catalog_handler):
    """Test format_type with char(10)."""
    # typmod = length + 4 = 10 + 4 = 14
    result = catalog_handler.format_type(1042, 14)
    assert result == "character(10)"


def test_format_type_varchar_1000(catalog_handler):
    """Test format_type with varchar(1000)."""
    # typmod = length + 4 = 1000 + 4 = 1004
    result = catalog_handler.format_type(1043, 1004)
    assert result == "character varying(1000)"


# ============================================================================
# Parameterized Types - Numeric
# ============================================================================


def test_format_type_numeric_10_2(catalog_handler):
    """Test format_type with numeric(10,2)."""
    # typmod = ((precision << 16) + scale) + 4
    # typmod = ((10 << 16) + 2) + 4 = (655360 + 2) + 4 = 655366
    result = catalog_handler.format_type(1700, 655366)
    assert result == "numeric(10,2)"


def test_format_type_numeric_18_6(catalog_handler):
    """Test format_type with numeric(18,6)."""
    # typmod = ((18 << 16) + 6) + 4 = (1179648 + 6) + 4 = 1179658
    result = catalog_handler.format_type(1700, 1179658)
    assert result == "numeric(18,6)"


def test_format_type_numeric_unlimited(catalog_handler):
    """Test format_type with unlimited numeric."""
    result = catalog_handler.format_type(1700, -1)
    assert result == "numeric"


def test_format_type_numeric_5_0(catalog_handler):
    """Test format_type with numeric(5,0)."""
    # typmod = ((5 << 16) + 0) + 4 = 327680 + 4 = 327684
    result = catalog_handler.format_type(1700, 327684)
    assert result == "numeric(5,0)"


# ============================================================================
# Parameterized Types - Timestamp/Time
# ============================================================================


def test_format_type_timestamp_default(catalog_handler):
    """Test format_type with timestamp (default precision)."""
    result = catalog_handler.format_type(1114, -1)
    assert result == "timestamp without time zone"


def test_format_type_timestamp_3(catalog_handler):
    """Test format_type with timestamp(3)."""
    # typmod = precision + 4 = 3 + 4 = 7
    result = catalog_handler.format_type(1114, 7)
    assert result == "timestamp(3) without time zone"


def test_format_type_timestamp_0(catalog_handler):
    """Test format_type with timestamp(0)."""
    # typmod = precision + 4 = 0 + 4 = 4
    result = catalog_handler.format_type(1114, 4)
    assert result == "timestamp(0) without time zone"


def test_format_type_timestamptz_3(catalog_handler):
    """Test format_type with timestamptz(3)."""
    result = catalog_handler.format_type(1184, 7)
    assert result == "timestamp(3) with time zone"


def test_format_type_time_without_tz(catalog_handler):
    """Test format_type with time without time zone."""
    result = catalog_handler.format_type(1083, -1)
    assert result == "time without time zone"


def test_format_type_time_with_tz(catalog_handler):
    """Test format_type with time with time zone."""
    result = catalog_handler.format_type(1266, -1)
    assert result == "time with time zone"


# ============================================================================
# Parameterized Types - Bit
# ============================================================================


def test_format_type_bit_32(catalog_handler):
    """Test format_type with bit(32)."""
    # typmod = length + 4 = 32 + 4 = 36
    result = catalog_handler.format_type(1560, 36)
    assert result == "bit(32)"


def test_format_type_bit_varying_unlimited(catalog_handler):
    """Test format_type with bit varying (unlimited)."""
    result = catalog_handler.format_type(1562, -1)
    assert result == "bit varying"


# ============================================================================
# Edge Cases
# ============================================================================


def test_format_type_unknown_oid(catalog_handler):
    """Test format_type with unknown OID returns None."""
    result = catalog_handler.format_type(99999, -1)
    assert result is None


def test_format_type_zero_oid(catalog_handler):
    """Test format_type with zero OID returns None."""
    result = catalog_handler.format_type(0, -1)
    assert result is None


def test_format_type_negative_oid(catalog_handler):
    """Test format_type with negative OID returns None."""
    result = catalog_handler.format_type(-1, -1)
    assert result is None


# ============================================================================
# Handler Integration
# ============================================================================


def test_format_type_via_handler(catalog_handler):
    """Test format_type through the handler interface."""
    result = catalog_handler.handle("format_type", ("23", "-1"))
    assert result.function_name == "format_type"
    assert result.result == "integer"
    assert result.error is None


def test_format_type_via_handler_with_typmod(catalog_handler):
    """Test format_type with typmod through handler."""
    result = catalog_handler.handle("format_type", ("1043", "259"))
    assert result.function_name == "format_type"
    assert result.result == "character varying(255)"
    assert result.error is None


def test_format_type_via_handler_unknown_oid(catalog_handler):
    """Test format_type with unknown OID through handler."""
    result = catalog_handler.handle("format_type", ("99999", "-1"))
    assert result.function_name == "format_type"
    assert result.result is None
    assert result.error is None


# ============================================================================
# IRIS Type Compatibility
# ============================================================================


def test_format_type_iris_integer(catalog_handler):
    """Test IRIS INTEGER → PostgreSQL integer mapping."""
    result = catalog_handler.format_type(23, -1)
    assert result == "integer"


def test_format_type_iris_varchar(catalog_handler):
    """Test IRIS VARCHAR → PostgreSQL character varying mapping."""
    result = catalog_handler.format_type(1043, -1)
    assert result == "character varying"


def test_format_type_iris_vector(catalog_handler):
    """Test IRIS VECTOR → PostgreSQL vector mapping."""
    result = catalog_handler.format_type(16388, -1)
    assert result == "vector"
