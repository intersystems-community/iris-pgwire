"""Integration tests for JSONB containment operator (@>, <@) — Feature 050.

Tests run against a live iris-pgwire-db container.  Skip when IRIS_HOST is not
set so CI runs cleanly without Docker.

Note: psycopg3 uses %s placeholders; the server translates them to ? before
sending to IRIS.
"""

from __future__ import annotations

import json
import os

import pytest

IRIS_HOST = os.environ.get("IRIS_HOST")
IRIS_PORT = int(os.environ.get("IRIS_PORT", "5432"))
IRIS_USER = os.environ.get("IRIS_USER", "_SYSTEM")
IRIS_PASS = os.environ.get("IRIS_PASS", "SYS")
IRIS_DB = os.environ.get("IRIS_DB", "user")

skip_no_iris = pytest.mark.skipif(
    not IRIS_HOST,
    reason="IRIS_HOST not set — skipping live-container tests",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _conn():
    import psycopg

    return psycopg.connect(
        host=IRIS_HOST,
        port=IRIS_PORT,
        user=IRIS_USER,
        password=IRIS_PASS,
        dbname=IRIS_DB,
    )


def _setup_table(cur, table: str) -> None:
    cur.execute(f"DROP TABLE IF EXISTS {table}")
    cur.execute(
        f"""
        CREATE TABLE {table} (
            id INTEGER,
            payload VARCHAR(65535)
        )
        """
    )


# ---------------------------------------------------------------------------
# US1 — @> in WHERE clause
# ---------------------------------------------------------------------------


@skip_no_iris
def test_at_gt_simple_key_value():
    """SELECT with @> filters row whose payload contains expected key/value."""
    with _conn() as conn:
        with conn.cursor() as cur:
            _setup_table(cur, "pgwire_jsonb_test")
            cur.execute(
                "INSERT INTO pgwire_jsonb_test (id, payload) VALUES (1, %s)",
                ['{"role": "admin", "active": true}'],
            )
            cur.execute(
                "INSERT INTO pgwire_jsonb_test (id, payload) VALUES (2, %s)",
                ['{"role": "user", "active": true}'],
            )
            cur.execute(
                "SELECT id FROM pgwire_jsonb_test WHERE payload::jsonb @> %s::jsonb",
                ['{"role": "admin"}'],
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 1


@skip_no_iris
def test_at_gt_returns_nothing_when_no_match():
    """@> returns empty result when no row contains the filter JSON."""
    with _conn() as conn:
        with conn.cursor() as cur:
            _setup_table(cur, "pgwire_jsonb_test2")
            cur.execute(
                "INSERT INTO pgwire_jsonb_test2 (id, payload) VALUES (1, %s)",
                ['{"role": "user"}'],
            )
            cur.execute(
                "SELECT id FROM pgwire_jsonb_test2 WHERE payload::jsonb @> %s::jsonb",
                ['{"role": "admin"}'],
            )
            rows = cur.fetchall()
    assert rows == []


@skip_no_iris
def test_at_gt_nested_object():
    """@> works when the filter includes nested JSON structure."""
    with _conn() as conn:
        with conn.cursor() as cur:
            _setup_table(cur, "pgwire_jsonb_test3")
            cur.execute(
                "INSERT INTO pgwire_jsonb_test3 (id, payload) VALUES (1, %s)",
                ['{"user": {"name": "alice", "level": 5}}'],
            )
            cur.execute(
                "INSERT INTO pgwire_jsonb_test3 (id, payload) VALUES (2, %s)",
                ['{"user": {"name": "bob"}}'],
            )
            cur.execute(
                "SELECT id FROM pgwire_jsonb_test3 WHERE payload::jsonb @> %s::jsonb",
                ['{"user": {"name": "alice"}}'],
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 1


@skip_no_iris
def test_at_gt_multiple_matches():
    """@> returns all matching rows, not just the first."""
    with _conn() as conn:
        with conn.cursor() as cur:
            _setup_table(cur, "pgwire_jsonb_test4")
            for i in range(1, 4):
                cur.execute(
                    "INSERT INTO pgwire_jsonb_test4 (id, payload) VALUES (%s, %s)",
                    [i, json.dumps({"active": True, "seq": i})],
                )
            cur.execute(
                "SELECT id FROM pgwire_jsonb_test4 WHERE payload::jsonb @> %s::jsonb ORDER BY id",
                ['{"active": true}'],
            )
            rows = cur.fetchall()
    assert [r[0] for r in rows] == [1, 2, 3]


# ---------------------------------------------------------------------------
# US2 — @> in JOIN ON clause
# ---------------------------------------------------------------------------


@skip_no_iris
def test_at_gt_in_join():
    """@> works as a join predicate between two tables."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS pgwire_jsonb_left")
            cur.execute("DROP TABLE IF EXISTS pgwire_jsonb_right")
            cur.execute(
                "CREATE TABLE pgwire_jsonb_left (id INTEGER, tags VARCHAR(65535))"
            )
            cur.execute(
                "CREATE TABLE pgwire_jsonb_right (id INTEGER, required_tag VARCHAR(65535))"
            )
            cur.execute(
                "INSERT INTO pgwire_jsonb_left (id, tags) VALUES (1, %s)",
                ['{"env": "prod", "team": "platform"}'],
            )
            cur.execute(
                "INSERT INTO pgwire_jsonb_left (id, tags) VALUES (2, %s)",
                ['{"env": "dev"}'],
            )
            cur.execute(
                "INSERT INTO pgwire_jsonb_right (id, required_tag) VALUES (10, %s)",
                ['{"env": "prod"}'],
            )
            cur.execute(
                """
                SELECT l.id, r.id
                FROM pgwire_jsonb_left l
                JOIN pgwire_jsonb_right r ON l.tags::jsonb @> r.required_tag::jsonb
                ORDER BY l.id
                """
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0] == (1, 10)
