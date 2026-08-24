"""E2E tests for surp lint and ERD support (feature 047).

Constitution §II: real PostgreSQL client against real IRIS. No mocks.

Tests run against the iris-pgwire server started by the pgwire_server fixture.
All catalog views (pg_depend, pg_extension, pg_index, pg_policy, pg_rewrite)
and SQL functions (FORMAT2, FORMAT3, JSONB_BUILD_OBJECT4, JSONB_BUILD_OBJECT6)
must be installed in IRIS for these tests to pass; the server installs them at
startup.

Constitution §IV: dual-backend. The @pytest.mark.parametrize("backend") marker
runs each test against both embedded and DBAPI backends when IRIS_DBAPI_DSN is
set. DBAPI tests are skipped if that env var is absent.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import psycopg
import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connect(pgwire_connection_params: dict) -> psycopg.Connection:
    return psycopg.connect(
        host=pgwire_connection_params["host"],
        port=pgwire_connection_params["port"],
        dbname=pgwire_connection_params["dbname"],
        user=pgwire_connection_params["user"],
        password=pgwire_connection_params["password"],
        connect_timeout=30,
    )


def _execute(conn: psycopg.Connection, sql: str) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall() if cur.description else []


# ---------------------------------------------------------------------------
# T018 — US1: lint checks no_primary_key and extension_in_public
# ---------------------------------------------------------------------------


def test_lint_no_primary_key(pgwire_server, pgwire_connection_params):
    """no_primary_key CTE branch executes without error; result parseable as JSON."""
    sql = """
    WITH no_primary_key AS (
        SELECT
            jsonb_build_object('type', 'lint', 'check_id', 'no_primary_key') AS result,
            format('%I', c.relname) AS name,
            c.oid
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_catalog.pg_index i
            ON i.indrelid = c.oid AND i.indisprimary = 1
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND c.relkind = 'r'
          AND i.indexrelid IS NULL
    )
    SELECT result, name, oid FROM no_primary_key
    """
    conn = _connect(pgwire_connection_params)
    try:
        rows = _execute(conn, sql)
        # Result may be empty (all tables have PKs) or non-empty — both are valid
        for row in rows:
            parsed = json.loads(row[0])
            assert parsed.get("check_id") == "no_primary_key"
            assert parsed.get("type") == "lint"
    finally:
        conn.close()


def test_lint_extension_in_public(pgwire_server, pgwire_connection_params):
    """extension_in_public returns zero rows (IRIS has no extensions) without error."""
    sql = """
    SELECT
        jsonb_build_object('type', 'lint', 'check_id', 'extension_in_public') AS result,
        e.extname AS name,
        e.oid
    FROM pg_catalog.pg_extension e
    JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace
    WHERE n.nspname = 'public'
    """
    conn = _connect(pgwire_connection_params)
    try:
        rows = _execute(conn, sql)
        assert rows == [], "pg_extension is always empty on IRIS"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T022 — US2: ERD FK relationship
# ---------------------------------------------------------------------------


def test_erd_fk_relationship(pgwire_server, pgwire_connection_params):
    """ERD query returns FK rows for tables with FK constraints."""
    conn = _connect(pgwire_connection_params)
    try:
        # Create test tables
        _execute(conn, "DROP TABLE IF EXISTS pgwire_test_orders")
        _execute(conn, "DROP TABLE IF EXISTS pgwire_test_customers")
        conn.commit()
        _execute(
            conn,
            "CREATE TABLE pgwire_test_customers (id INTEGER PRIMARY KEY, name VARCHAR(100))",
        )
        _execute(
            conn,
            "CREATE TABLE pgwire_test_orders "
            "(id INTEGER PRIMARY KEY, customer_id INTEGER, "
            "FOREIGN KEY (customer_id) REFERENCES pgwire_test_customers(id))",
        )
        conn.commit()

        # surp ERD FK query (simplified — the full query uses ANY(con.conkey))
        erd_sql = """
        SELECT
            format('%I', fk_class.relname) AS fk_table,
            format('%I', pk_class.relname) AS pk_table,
            format('%I', fk_att.attname)   AS fk_column,
            format('%I', pk_att.attname)   AS pk_column
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class fk_class ON fk_class.oid = con.conrelid
        JOIN pg_catalog.pg_class pk_class ON pk_class.oid = con.confrelid
        JOIN pg_catalog.pg_attribute fk_att
            ON fk_att.attrelid = con.conrelid
           AND fk_att.attnum = ANY(con.conkey)
        JOIN pg_catalog.pg_attribute pk_att
            ON pk_att.attrelid = con.confrelid
           AND pk_att.attnum = ANY(con.confkey)
        WHERE con.contype = 'f'
        """
        rows = _execute(conn, erd_sql)

        fk_tables = [row[0] for row in rows]
        assert any("pgwire_test_orders" in t for t in fk_tables), (
            f"Expected pgwire_test_orders FK row; got: {rows}"
        )
    finally:
        try:
            _execute(conn, "DROP TABLE IF EXISTS pgwire_test_orders")
            _execute(conn, "DROP TABLE IF EXISTS pgwire_test_customers")
            conn.commit()
        except Exception:
            pass
        conn.close()


# ---------------------------------------------------------------------------
# T026 — US3: full splinter excerpt, no crash, translation timing
# ---------------------------------------------------------------------------


def test_full_splinter_no_crash(pgwire_server, pgwire_connection_params):
    """Full splinter excerpt executes without error; JSON column parseable;
    translation-only overhead ≤ 10 ms (constitution V deviation: lint SQL is a
    15-branch multi-CTE UNION; 10 ms agreed ceiling — see plan.md Complexity Tracking).
    """
    sql_file = FIXTURES_DIR / "splinter_excerpt.sql"
    if not sql_file.exists():
        pytest.skip(f"Fixture not found: {sql_file}")
    sql = sql_file.read_text()

    # Measure translation overhead in isolation (rewrite passes only, no IRIS round-trip)
    from iris_pgwire.sql_translator.array_literal import rewrite_array_literals
    from iris_pgwire.sql_translator.array_params import (
        expand_array_literals,
        rewrite_any_col_to_instr,
        rewrite_any_to_inlist,
    )
    from iris_pgwire.sql_translator.pg_functions import rewrite_pg_function_calls

    t0 = time.perf_counter()
    _translated = rewrite_any_col_to_instr(
        expand_array_literals(
            rewrite_any_to_inlist(
                rewrite_pg_function_calls(
                    rewrite_array_literals(sql)
                )
            )
        )
    )
    translation_ms = (time.perf_counter() - t0) * 1000
    assert translation_ms <= 10.0, (
        f"Translation overhead {translation_ms:.2f} ms exceeds 10 ms budget"
    )

    # Execute against real IRIS — no ErrorResponse
    conn = _connect(pgwire_connection_params)
    try:
        rows = _execute(conn, sql)
        assert isinstance(rows, list), "Expected list of rows, got non-list"
        # Each returned row's first column should be valid JSON
        check_ids = set()
        for row in rows:
            if row[0]:
                parsed = json.loads(row[0])
                check_ids.add(parsed.get("check_id"))
        # May be empty if all checks return zero rows — that is correct behaviour
        # (FR-008: unsupported checks return empty, not error)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T018 additional: FORMAT2/FORMAT3 ObjectScript behavior via real IRIS
# ---------------------------------------------------------------------------


def test_format2_behavior(pgwire_server, pgwire_connection_params):
    """PGWire.FORMAT2 produces correct output for %I and %L modes.

    Note: FORMAT2('%s', ...) is not tested here because the pgwire SQL normalizer
    replaces bare %s in SQL text with ? (pre-existing behaviour for psycopg2-style
    queries). Surp uses %I and %L, which are unaffected.
    """
    conn = _connect(pgwire_connection_params)
    try:
        rows = _execute(
            conn,
            "SELECT PGWire.FORMAT2('%I', 'my table'), "
            "PGWire.FORMAT2('%L', 'it''s fine')",
        )
        assert len(rows) == 1
        ident, literal = rows[0]
        assert ident == '"my table"'
        assert literal == "'it''s fine'"
    finally:
        conn.close()


def test_jsonb_build_object4_behavior(pgwire_server, pgwire_connection_params):
    """PGWire.JSONB_BUILD_OBJECT4 returns valid JSON with correct keys/values."""
    conn = _connect(pgwire_connection_params)
    try:
        rows = _execute(
            conn,
            "SELECT PGWire.JSONB_BUILD_OBJECT4('type', 'lint', 'check_id', 'no_pk')",
        )
        assert len(rows) == 1
        parsed = json.loads(rows[0][0])
        assert parsed == {"type": "lint", "check_id": "no_pk"}
    finally:
        conn.close()
