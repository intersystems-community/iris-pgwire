"""
E2E test: <=> cosine distance ordering semantics.

pgvector <=> is cosine *distance* (0.0 = identical, 2.0 = opposite).
ORDER BY embedding <=> query ASC must return the most-similar row first.

Before the fix, IRIS VECTOR_COSINE (similarity, 1.0 = identical) was used
bare — ORDER BY ... ASC returned the *least*-similar row first.

This test would have caught that bug: it inserts three vectors where one is
identical to the query and verifies it is returned first.

Regression anchor: if this test fails the (1 - VECTOR_COSINE(...)) wrapper
has been removed or broken.
"""

import psycopg
import pytest


# ---------------------------------------------------------------------------
# Fixture: psycopg connection through pgwire
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(pgwire_connection_params, pgwire_server):
    """Module-scoped psycopg connection to PGWire."""
    _ = pgwire_server
    p = pgwire_connection_params
    conn_str = (
        f"host={p['host']} port={p['port']} "
        f"user={p['user']} password={p['password']} dbname={p['dbname']}"
    )
    c = psycopg.connect(conn_str)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def vector_table(conn):
    """Create and populate a 3-row vector table; drop it afterwards."""
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS e2e_cosine_order_test")
        cur.execute(
            "CREATE TABLE e2e_cosine_order_test (id INT, label VARCHAR(50), emb VECTOR(DOUBLE, 3))"
        )
        # id=1: identical to query vector → distance 0.0, similarity 1.0
        cur.execute(
            "INSERT INTO e2e_cosine_order_test VALUES (1, 'identical', TO_VECTOR('[0.1,0.2,0.9]', DOUBLE))"
        )
        # id=2: orthogonal-ish → high distance
        cur.execute(
            "INSERT INTO e2e_cosine_order_test VALUES (2, 'dissimilar', TO_VECTOR('[0.9,0.2,0.1]', DOUBLE))"
        )
        # id=3: moderately similar
        cur.execute(
            "INSERT INTO e2e_cosine_order_test VALUES (3, 'moderate', TO_VECTOR('[0.1,0.9,0.2]', DOUBLE))"
        )
    conn.commit()
    yield
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS e2e_cosine_order_test")
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCosineDistanceOrdering:
    """Verify that <=> ORDER BY ASC returns most-similar rows first."""

    def test_most_similar_returned_first(self, conn, vector_table):
        """
        ORDER BY embedding <=> query_vec LIMIT 1 must return the identical vector (id=1).

        Before the (1 - VECTOR_COSINE(...)) fix, id=2 (least similar) was returned
        first because VECTOR_COSINE ASC sorts by lowest *similarity* first.
        """
        query_vec = "[0.1,0.2,0.9]"
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, label FROM e2e_cosine_order_test "
                f"ORDER BY emb <=> '{query_vec}' LIMIT 1"
            )
            row = cur.fetchone()

        assert row is not None, "Query returned no rows"
        returned_id, returned_label = row
        assert returned_id == 1, (
            f"Most-similar row (id=1, identical) should be first, "
            f"but got id={returned_id} ({returned_label}). "
            f"This indicates <=> is still using bare VECTOR_COSINE (similarity) "
            f"instead of (1 - VECTOR_COSINE) (distance)."
        )

    def test_full_ordering_most_to_least_similar(self, conn, vector_table):
        """
        Full ORDER BY must return rows in most→least similar order:
        id=1 (identical) → id=3 (moderate) → id=2 (dissimilar).
        """
        query_vec = "[0.1,0.2,0.9]"
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM e2e_cosine_order_test ORDER BY emb <=> '{query_vec}'")
            ids = [row[0] for row in cur.fetchall()]

        assert ids[0] == 1, (
            f"First result must be most-similar (id=1), got id={ids[0]}. Full order: {ids}"
        )
        assert ids[-1] == 2, (
            f"Last result must be least-similar (id=2), got id={ids[-1]}. Full order: {ids}"
        )

    def test_distance_value_for_identical_vector_is_near_zero(self, conn, vector_table):
        """
        The distance of an identical vector must be near 0.0 (not near 0.0 similarity = 1.0).

        This pins the numeric semantics: distance = 1 - cosine_similarity.
        An identical vector has cosine_similarity=1.0 → distance=0.0.
        """
        query_vec = "[0.1,0.2,0.9]"
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT emb <=> '{query_vec}' AS dist FROM e2e_cosine_order_test WHERE id = 1"
            )
            row = cur.fetchone()

        assert row is not None
        distance = float(row[0])
        assert distance < 0.01, (
            f"Distance of identical vector must be ~0.0 (cosine distance), "
            f"got {distance:.6f}. If this is ~0.0 similarity was returned instead."
        )

    def test_parameterized_cosine_ordering(self, conn, vector_table):
        """
        Parameterized query (Extended Query Protocol) must also return most-similar first.
        This exercises the full psycopg → pgwire → IRIS round-trip with params.
        """
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM e2e_cosine_order_test ORDER BY emb <=> %s::vector LIMIT 1",
                ("[0.1,0.2,0.9]",),
            )
            row = cur.fetchone()

        assert row is not None, "Parameterized query returned no rows"
        assert row[0] == 1, (
            f"Parameterized <=> must return most-similar row (id=1) first, got id={row[0]}"
        )
