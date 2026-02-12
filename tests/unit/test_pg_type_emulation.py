from unittest.mock import MagicMock

import pytest

from iris_pgwire.catalog.catalog_router import CatalogRouter
from iris_pgwire.catalog.oid_generator import OIDGenerator
from iris_pgwire.catalog.pg_type import PgTypeEmulator


@pytest.mark.asyncio
async def test_pg_type_emulation_comprehensive_list():
    """
    Test that handle_catalog_query returns the full list of 21 standard types
    when querying pg_type.
    """
    oid_gen = OIDGenerator()
    router = CatalogRouter(oid_gen)

    # Mock executor
    executor = MagicMock()

    sql = "SELECT * FROM pg_catalog.pg_type"
    result = await router.handle_catalog_query(sql, session_id="test-session", executor=executor)

    assert result is not None
    assert result["success"] is True

    rows = result["rows"]
    # We expect at least the 21 types defined in PgTypeEmulator
    assert len(rows) >= 21

    # Verify some specific types
    type_names = [row[1] for row in rows]
    expected_types = ["bool", "int4", "varchar", "text", "timestamp", "vector"]
    for t in expected_types:
        assert t in type_names


@pytest.mark.asyncio
async def test_pg_type_filtering_by_name():
    """
    Test that pg_type can be filtered by typname.
    """
    oid_gen = OIDGenerator()
    router = CatalogRouter(oid_gen)
    executor = MagicMock()

    sql = "SELECT oid, typname FROM pg_catalog.pg_type WHERE typname = 'int4'"
    result = await router.handle_catalog_query(sql, session_id="test-session", executor=executor)

    assert result is not None
    rows = result["rows"]
    assert len(rows) == 1
    assert rows[0][1] == "int4"
    assert rows[0][0] == 23


import time


@pytest.mark.asyncio
async def test_pg_type_performance_overhead():
    """
    Test that handle_catalog_query executes within the performance goal (<5ms).
    """
    oid_gen = OIDGenerator()
    router = CatalogRouter(oid_gen)
    executor = MagicMock()

    sql = "SELECT * FROM pg_catalog.pg_type WHERE typname = 'int4'"

    start_time = time.perf_counter()
    await router.handle_catalog_query(sql, session_id="perf-test", executor=executor)
    end_time = time.perf_counter()

    duration_ms = (end_time - start_time) * 1000
    print(f"Catalog query duration: {duration_ms:.2f}ms")
    assert duration_ms < 5.0


@pytest.mark.asyncio
async def test_pg_extension_interception_empty():
    """
    Test that pg_extension returns an empty result set.
    """
    oid_gen = OIDGenerator()
    router = CatalogRouter(oid_gen)
    executor = MagicMock()

    sql = "SELECT * FROM pg_catalog.pg_extension"
    result = await router.handle_catalog_query(sql, session_id="test-session", executor=executor)

    assert result is not None
    assert result["success"] is True
    assert len(result["rows"]) == 0
    # Should have some column metadata even if empty
    assert len(result["columns"]) > 0
