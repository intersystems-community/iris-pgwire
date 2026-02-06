import pytest


def _setup_limit_param_table(iris_connection):
    with iris_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS limit_param_meta")
        cur.execute("CREATE TABLE limit_param_meta (id INT PRIMARY KEY, name VARCHAR(255))")
        cur.execute("INSERT INTO limit_param_meta (id, name) VALUES (1, 'First Row')")
        cur.execute("INSERT INTO limit_param_meta (id, name) VALUES (2, 'Second Row')")
        cur.execute("INSERT INTO limit_param_meta (id, name) VALUES (3, 'Third Row')")
        iris_connection.commit()


def _teardown_limit_param_table(iris_connection):
    with iris_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS limit_param_meta")
        iris_connection.commit()


def test_parameterized_limit_preserves_metadata(pgwire_client, iris_connection):
    _setup_limit_param_table(iris_connection)
    try:
        with pgwire_client.cursor() as cur:
            cur.execute("SELECT id, name FROM limit_param_meta LIMIT %s", (1,))
            row = cur.fetchone()
            assert row is not None
            assert cur.description is not None
            assert len(cur.description) == 2
            names = [desc[0].lower() for desc in cur.description]
            assert names == ["id", "name"]
    finally:
        _teardown_limit_param_table(iris_connection)


def test_parameterized_offset_preserves_metadata(pgwire_client, iris_connection):
    _setup_limit_param_table(iris_connection)
    try:
        with pgwire_client.cursor() as cur:
            cur.execute("SELECT id, name FROM limit_param_meta LIMIT %s OFFSET %s", (1, 1))
            row = cur.fetchone()
            assert row is not None
            assert cur.description is not None
            assert len(cur.description) == 2
            names = [desc[0].lower() for desc in cur.description]
            assert names == ["id", "name"]
    finally:
        _teardown_limit_param_table(iris_connection)
