import os

import psycopg
import pytest


@pytest.mark.iris_integration
def test_drizzle_style_pg_type_introspection(pgwire_server, pgwire_connection_params):
    """
    Test that pg_type can be queried using a standard PostgreSQL client,
    mimicking Drizzle ORM's introspection pattern.
    """
    conn = psycopg.connect(
        host=pgwire_connection_params["host"],
        port=pgwire_connection_params["port"],
        user=pgwire_connection_params["user"],
        password=pgwire_connection_params["password"],
        dbname=pgwire_connection_params["dbname"],
        autocommit=True,
    )
    cur = conn.cursor()

    # Drizzle pattern: SELECT from pg_catalog.pg_type with specific columns
    sql = """
        SELECT oid, typname, typnamespace, typtype, typcategory 
        FROM pg_catalog.pg_type 
        WHERE typname = 'int4'
    """

    cur.execute(sql)
    row = cur.fetchone()

    assert row is not None
    assert row[1] == "int4"
    assert row[0] == 23  # standard OID for int4
    assert row[2] == 11  # standard OID for pg_catalog

    conn.close()


@pytest.mark.iris_integration
def test_pg_extension_interception(pgwire_server, pgwire_connection_params):
    """
    Test that pg_extension returns empty results instead of 'table not found'.
    """
    conn = psycopg.connect(
        host=pgwire_connection_params["host"],
        port=pgwire_connection_params["port"],
        user=pgwire_connection_params["user"],
        password=pgwire_connection_params["password"],
        dbname=pgwire_connection_params["dbname"],
        autocommit=True,
    )
    cur = conn.cursor()

    # Should not raise "Table not found"
    cur.execute("SELECT * FROM pg_catalog.pg_extension")
    rows = cur.fetchall()

    assert len(rows) == 0

    conn.close()
