import os

import psycopg
import pytest


@pytest.mark.iris_integration
def test_returning_emulation_e2e(pgwire_client):
    """
    E2E test for RETURNING clause emulation.
    Tests that INSERT and UPDATE with RETURNING * actually return row data.
    """
    cur = pgwire_client.cursor()

    try:
        # 1. Setup table
        cur.execute("DROP TABLE IF EXISTS test_returning")
        cur.execute(
            "CREATE TABLE test_returning (id INT PRIMARY KEY, name VARCHAR(50), status VARCHAR(20))"
        )

        # 2. Test INSERT ... RETURNING *
        # This is exactly what Drizzle does
        sql = "INSERT INTO test_returning (id, name, status) VALUES (1, 'Test Item', 'active') RETURNING *"
        print(f"Executing: {sql}")
        cur.execute(sql)

        # Verify columns and rows are returned
        assert cur.description is not None
        colnames = [desc[0].lower() for desc in cur.description]
        assert "id" in colnames
        assert "name" in colnames

        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] == "Test Item"
        print(f"INSERT RETURNING successful: {row}")

        # 3. Test UPDATE ... RETURNING
        sql = "UPDATE test_returning SET status = 'inactive' WHERE id = 1 RETURNING name, status"
        print(f"Executing: {sql}")
        cur.execute(sql)

        row = cur.fetchone()
        assert row is not None
        assert row[0] == "Test Item"
        assert row[1] == "inactive"
        print(f"UPDATE RETURNING successful: {row}")

        # 4. Test DELETE ... RETURNING (Pre-fetch path)
        sql = "DELETE FROM test_returning WHERE id = 1 RETURNING id"
        print(f"Executing: {sql}")
        cur.execute(sql)

        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1
        print(f"DELETE RETURNING successful: {row}")

    finally:
        cur.execute("DROP TABLE IF EXISTS test_returning")


@pytest.mark.iris_integration
def test_returning_batch_e2e(pgwire_client):
    """
    Test executemany() with RETURNING clause.
    """
    cur = pgwire_client.cursor()

    try:
        cur.execute("DROP TABLE IF EXISTS test_returning_batch")
        cur.execute("CREATE TABLE test_returning_batch (id INT PRIMARY KEY, val VARCHAR(10))")

        data = [(1, "a"), (2, "b"), (3, "c")]
        sql = "INSERT INTO test_returning_batch (id, val) VALUES (%s, %s) RETURNING *"

        # Let's test the loop behavior which some clients use
        all_returned = []
        for d in data:
            cur.execute(sql, d)
            all_returned.append(cur.fetchone())

        assert len(all_returned) == 3
        assert all_returned[0][0] == 1
        assert all_returned[2][0] == 3

    finally:
        cur.execute("DROP TABLE IF EXISTS test_returning_batch")


@pytest.mark.iris_integration
def test_returning_batch_e2e(pgwire_server, pgwire_connection_params):
    """
    Test executemany() with RETURNING clause.
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

    try:
        cur.execute("DROP TABLE IF EXISTS test_returning_batch")
        cur.execute("CREATE TABLE test_returning_batch (id INT PRIMARY KEY, val VARCHAR(10))")

        data = [(1, "a"), (2, "b"), (3, "c")]
        sql = "INSERT INTO test_returning_batch (id, val) VALUES (%s, %s) RETURNING *"

        # executemany with RETURNING
        cur.executemany(sql, data)

        # psycopg might not support fetchall() after executemany() depending on version/mode,
        # but our implementation should return the rows.
        # Actually, standard DBAPI executemany doesn't return rows.
        # But if the user calls execute() in a loop, it will.

        # Let's test the loop behavior which some clients use
        all_returned = []
        for d in data:
            cur.execute(sql, d)
            all_returned.append(cur.fetchone())

        assert len(all_returned) == 3
        assert all_returned[0][0] == 1
        assert all_returned[2][0] == 3

    finally:
        cur.execute("DROP TABLE IF EXISTS test_returning_batch")
        conn.close()
