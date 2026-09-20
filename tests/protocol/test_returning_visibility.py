import os
import time

import psycopg
import pytest


def test_repro_returning_failure(pgwire_client):
    """
    Reproduces Issue #1: RETURNING clause fails with SQLCODE -25.
    """
    with pgwire_client.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS test_returning")
        cur.execute("CREATE TABLE test_returning (id SERIAL PRIMARY KEY, name TEXT)")

        # This is expected to fail with SQLCODE -25 if not fixed
        try:
            cur.execute("INSERT INTO test_returning (name) VALUES ('test') RETURNING id")
            row = cur.fetchone()
            assert row is not None
            assert row[0] > 0
        except Exception as e:
            pytest.fail(f"RETURNING failed: {e}")


def test_repro_transaction_visibility(pgwire_client, iris_connection):
    """
    Reproduces Issue #2: Transaction visibility broken.
    INSERT succeeds, but SELECT in same session returns EMPTY.
    """
    # Use a unique table name to avoid interference
    table_name = f"test_vis_{int(time.time())}"

    with pgwire_client.cursor() as cur:
        cur.execute(f"CREATE TABLE {table_name} (id INT PRIMARY KEY, val TEXT)")

        # INSERT (this will be buffered by pgwire if it's a DML without RETURNING)
        cur.execute(f"INSERT INTO {table_name} (id, val) VALUES (1, 'secret')")

        # SELECT in SAME session (this should trigger a flush or see the data)
        cur.execute(f"SELECT val FROM {table_name} WHERE id = 1")
        row = cur.fetchone()

        if row is None:
            pytest.fail(
                "Data NOT visible after INSERT in same session (likely buffered and not flushed)"
            )

        assert row[0] == "secret"


def test_explicit_flush_select(pgwire_client):
    """
    Explicitly test that INSERT followed by SELECT in same session works.
    This verifies handle_execute_message calls flush_batch().
    """
    with pgwire_client.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS test_flush")
        cur.execute("CREATE TABLE test_flush (id INT PRIMARY KEY, name TEXT)")

        # This INSERT will be buffered
        cur.execute("INSERT INTO test_flush (id, name) VALUES (1, 'flushed')")

        # This SELECT should trigger an implicit flush of the INSERT
        cur.execute("SELECT name FROM test_flush WHERE id = 1")
        row = cur.fetchone()

        assert row is not None
        assert row[0] == "flushed"


def test_repro_cross_session_interference(pgwire_server, pgwire_connection_params):
    """
    Tests if multiple clients share the same IRIS connection/transaction.

    Two concurrent clients, which this needed and did not have: a second
    connection inserts a row and commits while the first holds an open
    transaction. If the two wire sessions were multiplexed onto one IRIS
    connection, the first session's ROLLBACK would discard the second's commit.

    Full isolation and locking coverage is in test_isolation_e2e.py.
    """
    table = f"test_xsession_{int(time.time())}"

    with psycopg.connect(**pgwire_connection_params) as setup:
        setup.autocommit = True
        with setup.cursor() as cur:
            cur.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, owner TEXT)")

    try:
        with psycopg.connect(**pgwire_connection_params) as first:
            with first.cursor() as cur:
                cur.execute(f"INSERT INTO {table} (id, owner) VALUES (1, 'first')")

            with psycopg.connect(**pgwire_connection_params) as second:
                with second.cursor() as cur:
                    cur.execute(f"INSERT INTO {table} (id, owner) VALUES (2, 'second')")
                second.commit()

            first.rollback()

            with first.cursor() as cur:
                cur.execute(f"SELECT owner FROM {table} ORDER BY id")
                owners = [r[0] for r in cur.fetchall()]

        assert owners == ["second"], (
            f"expected only the committed row to survive, got {owners} — "
            "sessions are sharing a transaction"
        )
    finally:
        with psycopg.connect(**pgwire_connection_params) as cleanup:
            cleanup.autocommit = True
            with cleanup.cursor() as cur:
                cur.execute(f"DROP TABLE {table}")
