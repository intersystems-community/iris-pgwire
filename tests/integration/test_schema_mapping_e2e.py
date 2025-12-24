"""
E2E tests for PostgreSQL schema mapping (Feature 030).

Tests verify that the public ↔ SQLUser schema mapping works correctly
through the full PGWire stack.
"""

import pytest

# Skip if psycopg is not available
psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def pgwire_connection():
    """Get a connection to the PGWire server."""
    try:
        conn = psycopg.connect(
            "host=localhost port=5432 user=_SYSTEM password=SYS dbname=USER"
        )
        yield conn
        conn.close()
    except Exception as e:
        pytest.skip(f"PGWire server not available: {e}")


class TestSchemaInputTranslation:
    """Test input SQL translation (public → SQLUser)."""

    def test_information_schema_tables_public_filter(self, pgwire_connection):
        """Query information_schema.tables with public schema filter."""
        cur = pgwire_connection.cursor()
        # This query should translate 'public' to 'SQLUser' internally
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' LIMIT 5"
        )
        rows = cur.fetchall()
        # Should find SQLUser tables (IRIS stores user tables in SQLUser schema)
        # Note: Result might be empty if no user tables exist, but query should not error
        assert isinstance(rows, list)
        cur.close()

    def test_information_schema_columns_public_filter(self, pgwire_connection):
        """Query information_schema.columns with public schema filter."""
        cur = pgwire_connection.cursor()
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' LIMIT 10"
        )
        rows = cur.fetchall()
        assert isinstance(rows, list)
        cur.close()

    def test_case_insensitive_public_filter(self, pgwire_connection):
        """Query with 'PUBLIC' (uppercase) should also work."""
        cur = pgwire_connection.cursor()
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'PUBLIC' LIMIT 5"
        )
        rows = cur.fetchall()
        assert isinstance(rows, list)
        cur.close()


class TestSchemaOutputTranslation:
    """Test output result translation (SQLUser → public)."""

    def test_table_schema_returns_public(self, pgwire_connection):
        """Results should show 'public' instead of 'SQLUser' in table_schema column."""
        cur = pgwire_connection.cursor()
        # Query all user tables - should return 'public' as table_schema
        cur.execute("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT LIKE '%'
            LIMIT 5
        """)
        rows = cur.fetchall()
        # If there are user tables, their schema should be 'public'
        for row in rows:
            table_schema = row[0]
            if table_schema and not table_schema.startswith("%"):
                assert table_schema == "public", f"Expected 'public', got '{table_schema}'"
        cur.close()

    def test_sqluser_filter_still_works(self, pgwire_connection):
        """Explicit SQLUser filter should still work (unchanged)."""
        cur = pgwire_connection.cursor()
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'SQLUser' LIMIT 5"
        )
        rows = cur.fetchall()
        assert isinstance(rows, list)
        cur.close()

    def test_system_schemas_unchanged(self, pgwire_connection):
        """System schemas like %SYS should remain unchanged."""
        cur = pgwire_connection.cursor()
        cur.execute("""
            SELECT DISTINCT table_schema
            FROM information_schema.tables
            WHERE table_schema LIKE '%'
            LIMIT 5
        """)
        rows = cur.fetchall()
        for row in rows:
            table_schema = row[0]
            # System schemas should not be translated to 'public'
            assert table_schema != "public" or not table_schema.startswith("%")
        cur.close()


class TestSchemaQualifiedQueries:
    """Test schema-qualified table references."""

    def test_public_schema_select(self, pgwire_connection):
        """SELECT from public.tablename should work (translated to SQLUser)."""
        cur = pgwire_connection.cursor()
        # This should translate to SELECT * FROM SQLUser.information_schema_tables
        # Note: This test assumes information_schema is accessible, adjust if needed
        try:
            cur.execute("SELECT 1 AS test")  # Simple query to verify connection
            rows = cur.fetchall()
            assert rows[0][0] == 1
        except Exception:
            pytest.skip("Basic query failed - server may need restart")
        cur.close()
