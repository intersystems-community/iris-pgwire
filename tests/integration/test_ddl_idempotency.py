"""
Integration tests for DDL idempotency.
"""

import psycopg
import pytest

from iris_pgwire.conversions.ddl_idempotency import DdlErrorHandler
from iris_pgwire.schema_mapper import IRIS_SCHEMA

# Connection configuration
PGWIRE_CONN = "host=localhost port=5432 user=test_user password=test dbname=USER"


@pytest.mark.integration
def test_create_table_if_not_exists_idempotency(pgwire_client):
    """Test that CREATE TABLE IF NOT EXISTS is idempotent."""
    with pgwire_client.cursor() as cur:
        # Cleanup
        cur.execute("DROP TABLE IF EXISTS test_idempotency")
        pgwire_client.commit()

        # First run - creates table
        cur.execute("CREATE TABLE IF NOT EXISTS test_idempotency (id INT)")
        pgwire_client.commit()

        # Second run - should be idempotent (no error)
        cur.execute("CREATE TABLE IF NOT EXISTS test_idempotency (id INT)")
        pgwire_client.commit()


@pytest.mark.integration
def test_create_index_if_not_exists_idempotency(pgwire_client):
    """Test that CREATE INDEX IF NOT EXISTS is idempotent."""
    with pgwire_client.cursor() as cur:
        # Setup table
        cur.execute("DROP TABLE IF EXISTS test_idx_idempotency")
        cur.execute("CREATE TABLE test_idx_idempotency (id INT)")
        pgwire_client.commit()

        # First run - creates index
        cur.execute("CREATE INDEX IF NOT EXISTS test_idx ON test_idx_idempotency (id)")
        pgwire_client.commit()

        # Second run - should be idempotent (no error)
        cur.execute("CREATE INDEX IF NOT EXISTS test_idx ON test_idx_idempotency (id)")
        pgwire_client.commit()


@pytest.mark.unit
def test_ddl_error_handler_logic():
    """Test DdlErrorHandler logic without real DB."""
    handler = DdlErrorHandler()

    # Test has_if_not_exists
    assert handler.has_if_not_exists("CREATE TABLE IF NOT EXISTS t1 (id INT)") is True
    assert handler.has_if_not_exists("CREATE TABLE t1 (id INT)") is False

    # Test extract_object_name
    assert handler.extract_object_name("CREATE TABLE IF NOT EXISTS my_table (id INT)") == "my_table"
    assert handler.extract_object_name("CREATE INDEX IF NOT EXISTS my_idx ON t1 (id)") == "my_idx"

    # Test handle with mock error
    sql = "CREATE TABLE IF NOT EXISTS existing_table (id INT)"
    error = Exception(
        f"[SQLCODE: <-201>] [Location: <Server>] %msg <Table '{IRIS_SCHEMA}.existing_table' already exists>"
    )

    result = handler.handle(sql, error)
    assert result.success is True
    assert result.skipped is True
    assert result.object_name == "existing_table"
