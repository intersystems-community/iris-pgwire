"""
Unit tests for recursive JSON path building.
"""

import pytest

from iris_pgwire.conversions.json_path import JsonPathBuilder


def test_json_path_simple():
    sql = "data->>'name'"
    remaining, builder = JsonPathBuilder.parse(sql)
    assert remaining == ""
    assert builder.base_column == "data"
    assert builder.return_type == "text"
    assert builder.build() == "JSON_VALUE(data, '$.name')"


def test_json_path_nested():
    sql = "data->'user'->>'name' rest_of_sql"
    remaining, builder = JsonPathBuilder.parse(sql)
    assert remaining == "rest_of_sql"
    assert builder.base_column == "data"
    assert builder.return_type == "text"
    assert builder.build() == "JSON_VALUE(data, '$.user.name')"


def test_json_path_deeply_nested():
    sql = "data->'a'->'b'->'c'->>'d'"
    remaining, builder = JsonPathBuilder.parse(sql)
    assert builder.build() == "JSON_VALUE(data, '$.a.b.c.d')"


def test_json_path_array_index():
    sql = "data->'items'->0->>'name'"
    remaining, builder = JsonPathBuilder.parse(sql)
    assert builder.build() == "JSON_VALUE(data, '$.items[0].name')"


def test_json_path_returns_json():
    sql = "data->'profile'"
    remaining, builder = JsonPathBuilder.parse(sql)
    assert builder.return_type == "json"
    assert builder.build() == "JSON_QUERY(data, '$.profile')"


def test_json_path_multiple_json_returns():
    sql = "data->'a'->'b'"
    remaining, builder = JsonPathBuilder.parse(sql)
    assert builder.build() == "JSON_QUERY(data, '$.a.b')"


def test_json_path_mixed_index_and_key():
    sql = "data->0->'key'->>1"
    remaining, builder = JsonPathBuilder.parse(sql)
    # Note: my current parser breaks at ->>
    assert builder.build() == "JSON_VALUE(data, '$[0].key[1]')"


def test_json_path_invalid_raises_error():
    sql = "not_json_access"
    with pytest.raises(ValueError) as excinfo:
        JsonPathBuilder.parse(sql)
    assert "Invalid JSON access expression" in str(excinfo.value)
