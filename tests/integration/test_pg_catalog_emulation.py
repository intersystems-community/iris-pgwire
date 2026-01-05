"""
Integration Tests for pg_catalog Emulation.
Uses iris-devtester infrastructure.
"""

import pytest
import psycopg


def test_pg_type_emulation(pgwire_client):
    """
    Verify pg_catalog.pg_type contains common PostgreSQL types.
    """
    with pgwire_client.cursor() as cur:
        cur.execute(
            "SELECT typname FROM pg_catalog.pg_type WHERE typname IN ('int4', 'varchar', 'bool')"
        )
        types = {row[0] for row in cur.fetchall()}
        assert "int4" in types
        assert "varchar" in types
        assert "bool" in types


def test_pg_class_emulation(pgwire_client, iris_connection):
    """
    Verify that creating a table in IRIS makes it visible in pg_catalog.pg_class.
    """
    # Create table via IRIS connection
    with iris_connection.cursor() as cur:
        cur.execute("CREATE TABLE PgCatalogTest (id INT)")
        iris_connection.commit()

    try:
        # Check pg_class via PGWire
        with pgwire_client.cursor() as cur:
            cur.execute("SELECT relname FROM pg_catalog.pg_class WHERE relname = 'pgcatalogtest'")
            row = cur.fetchone()
            assert row is not None
            assert row[0].lower() == "pgcatalogtest"
    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE PgCatalogTest")
            iris_connection.commit()


def test_current_database_function(pgwire_client):
    """
    Verify current_database() returns the active namespace.
    """
    with pgwire_client.cursor() as cur:
        cur.execute("SELECT current_database()")
        row = cur.fetchone()
        assert row[0].upper() == "USER"
