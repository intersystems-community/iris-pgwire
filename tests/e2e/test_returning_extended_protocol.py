"""
E2E regression test: INSERT/UPDATE ... RETURNING via Extended Query Protocol.

Bug: In handle_describe_message (protocol.py), RETURNING detection used
translated_query (which has RETURNING stripped because IRIS doesn't support it)
instead of original_query. This caused has_returning=False → send_no_data()
during the Describe phase. Clients like postgres.js/Drizzle ORM that use the
Extended Query Protocol (Parse→Describe→Bind→Execute) then discarded all rows
returned at Execute time, making .returning() always produce [].

Fix: Use original_query for ReturningPlan detection in both the "Describe
Statement" and "Describe Portal" branches of handle_describe_message.

Regression anchors:
- If this test fails, the original_query fix has been reverted or broken.
- Uses psycopg prepare=True to force Extended Query Protocol.
"""

import psycopg
import pytest


# ---------------------------------------------------------------------------
# Fixture: autocommit connection via pgwire
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(pgwire_connection_params, pgwire_server):
    """Autocommit psycopg connection to PGWire."""
    _ = pgwire_server
    p = pgwire_connection_params
    c = psycopg.connect(
        host=p["host"],
        port=p["port"],
        user=p["user"],
        password=p["password"],
        dbname=p["dbname"],
        autocommit=True,
    )
    yield c
    c.close()


@pytest.fixture(autouse=True)
def returning_table(conn):
    """Create a simple table for RETURNING tests; drop afterwards."""
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS e2e_returning_ext_test")
        cur.execute(
            "CREATE TABLE e2e_returning_ext_test "
            "(id INT PRIMARY KEY, name VARCHAR(100), status VARCHAR(20))"
        )
    yield
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS e2e_returning_ext_test")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReturningExtendedProtocol:
    """
    RETURNING clauses must return rows when using Extended Query Protocol.

    psycopg uses Extended Query Protocol for parameterized queries by default
    (prepare=True / binary=True), which exercises Parse→Describe→Bind→Execute.
    """

    def test_insert_returning_star_extended(self, conn, returning_table):
        """
        INSERT ... RETURNING * via Extended Query Protocol returns the inserted row.

        Before the fix, Describe sent NoData (RETURNING stripped from translated_query)
        and clients discarded the rows returned at Execute time.
        """
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO e2e_returning_ext_test (id, name, status) "
                "VALUES (%s, %s, %s) RETURNING *",
                (1, "Alice", "active"),
                prepare=True,
            )
            row = cur.fetchone()

        assert row is not None, (
            "INSERT ... RETURNING * returned no rows via Extended Query Protocol. "
            "Likely Describe sent NoData because translated_query lacks RETURNING."
        )
        assert row[0] == 1, f"Expected id=1, got id={row[0]}"
        assert row[1] == "Alice", f"Expected name='Alice', got '{row[1]}'"
        assert row[2] == "active", f"Expected status='active', got '{row[2]}'"

    def test_insert_returning_specific_columns_extended(self, conn, returning_table):
        """
        INSERT ... RETURNING id, name (not *) via Extended Query Protocol returns columns.
        """
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO e2e_returning_ext_test (id, name, status) "
                "VALUES (%s, %s, %s) RETURNING id, name",
                (2, "Bob", "pending"),
                prepare=True,
            )
            row = cur.fetchone()

        assert row is not None, (
            "INSERT ... RETURNING id, name returned no rows via Extended Query Protocol."
        )
        assert row[0] == 2
        assert row[1] == "Bob"

    @pytest.mark.xfail(
        reason=(
            "UPDATE ... RETURNING emulation via Extended Query Protocol returns 0 rows. "
            "RowDescription is sent correctly (our Describe fix works), but the UPDATE "
            "emulation path does not yet populate rows. Pre-existing limitation; "
            "tracked separately from the INSERT RETURNING Describe bug."
        ),
        strict=True,
    )
    def test_update_returning_extended(self, conn, returning_table):
        """
        UPDATE ... RETURNING via Extended Query Protocol returns updated row.
        """
        with conn.cursor() as cur:
            # seed a row first (Simple Query Protocol ok here)
            cur.execute(
                "INSERT INTO e2e_returning_ext_test (id, name, status) VALUES (3, 'Carol', 'active')"
            )

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE e2e_returning_ext_test SET status = %s WHERE id = %s RETURNING id, status",
                ("inactive", 3),
                prepare=True,
            )
            row = cur.fetchone()

        assert row is not None, "UPDATE ... RETURNING returned no rows via Extended Query Protocol."
        assert row[0] == 3
        assert row[1] == "inactive"

    def test_insert_returning_multiple_rows(self, conn, returning_table):
        """
        Multiple INSERTs with RETURNING must each return a row.
        Simulates how ORMs like Drizzle issue individual inserts with prepare=True.
        """
        inserts = [(10, "Dan", "active"), (11, "Eve", "active"), (12, "Frank", "active")]
        returned_ids = []

        with conn.cursor() as cur:
            for row_data in inserts:
                cur.execute(
                    "INSERT INTO e2e_returning_ext_test (id, name, status) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    row_data,
                    prepare=True,
                )
                row = cur.fetchone()
                assert row is not None, (
                    f"No row returned for INSERT id={row_data[0]} via Extended Query Protocol."
                )
                returned_ids.append(row[0])

        assert returned_ids == [10, 11, 12], (
            f"Expected returned ids [10, 11, 12], got {returned_ids}"
        )

    def test_describe_statement_sends_row_description_not_no_data(self, conn, returning_table):
        """
        When a prepared statement with RETURNING is Described, the server must
        send RowDescription (not NoData). Verified indirectly: psycopg will raise
        ProgrammingError / return None description if NoData was sent.

        This is the *root cause* scenario from the bug report.
        """
        with conn.cursor() as cur:
            # Prepare the statement explicitly — triggers Parse + Describe Statement
            cur.execute(
                "INSERT INTO e2e_returning_ext_test (id, name, status) "
                "VALUES (%s, %s, %s) RETURNING id, name, status",
                (20, "Grace", "active"),
                prepare=True,
            )
            # description is set only if RowDescription was received (not NoData)
            assert cur.description is not None, (
                "cur.description is None after INSERT ... RETURNING prepare=True. "
                "Describe phase sent NoData instead of RowDescription — "
                "original_query fix may be missing."
            )
            col_names = [d.name.lower() for d in cur.description]
            assert "id" in col_names, f"'id' not in description columns: {col_names}"

            row = cur.fetchone()
            assert row is not None
            assert row[0] == 20
