"""
Integration Tests for ORM Introspection.
Validates SQLAlchemy reflection against IRIS via PGWire.
"""

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect


def test_sqlalchemy_reflection(pgwire_server, iris_connection):
    # Create table via IRIS
    with iris_connection.cursor() as cur:
        cur.execute("CREATE TABLE OrmTest (id INT PRIMARY KEY, name VARCHAR(100))")
        iris_connection.commit()

    try:
        # Connect via SQLAlchemy
        engine = create_engine("postgresql+psycopg://test_user@localhost:5432/USER")
        inspector = inspect(engine)

        # Reflect table
        tables = inspector.get_table_names()
        assert "ormtest" in [t.lower() for t in tables]

        columns = inspector.get_columns("ormtest")
        col_names = {c["name"].lower() for c in columns}
        assert "id" in col_names
        assert "name" in col_names

    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE OrmTest")
            iris_connection.commit()


def test_sqlalchemy_metadata_reflect(pgwire_server, iris_connection):
    # Create table via IRIS
    with iris_connection.cursor() as cur:
        cur.execute("CREATE TABLE MetadataTest (id INT PRIMARY KEY, val VARCHAR(10))")
        iris_connection.commit()

    try:
        engine = create_engine("postgresql+psycopg://test_user@localhost:5432/USER")
        metadata = MetaData()
        metadata.reflect(bind=engine, only=["metadatatest"])

        table = metadata.tables["metadatatest"]
        assert len(table.columns) == 2
        assert isinstance(table.c.id.type, Integer)

    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE MetadataTest")
            iris_connection.commit()
