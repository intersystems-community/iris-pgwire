import pytest
import psycopg


def test_vector_cosine_with_cast_reproduction(pgwire_client, iris_connection):
    """
    Reproduces the issue where <=> operator fails when used with $1::vector.
    The failure happens because the Normalizer replaces $1::vector with TO_VECTOR(?, DOUBLE),
    leaving <=> in the SQL, which IRIS doesn't support.
    """
    # Create table with vector column
    with iris_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS VectorRepro")
        cur.execute("CREATE TABLE VectorRepro (id INT, embedding VECTOR(DOUBLE, 3))")
        cur.execute("INSERT INTO VectorRepro VALUES (1, TO_VECTOR('[1,0,0]', DOUBLE))")
        iris_connection.commit()

    try:
        # Use psycopg to send a query with $1::vector cast and <=> operator
        # We use a raw string to ensure $1 is sent to the server
        query = "SELECT id, embedding <=> %s::vector as dist FROM VectorRepro"
        vector_data = [1.0, 0.0, 0.0]

        with pgwire_client.cursor() as cur:
            # This should trigger the translation logic
            # We use a string representation because IRIS TO_VECTOR expects a string/binary
            cur.execute(query, (str(vector_data),))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 1
            assert float(row[1]) == 0.0

    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS VectorRepro")
            iris_connection.commit()


def test_vector_cosine_with_quoted_placeholder_reproduction(pgwire_client, iris_connection):
    """
    Reproduces the issue where Drizzle-ORM (or some other layer) might send '$1'::vector.
    """
    # Create table with vector column
    with iris_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS VectorRepro2")
        cur.execute("CREATE TABLE VectorRepro2 (id INT, embedding VECTOR(DOUBLE, 3))")
        cur.execute("INSERT INTO VectorRepro2 VALUES (1, TO_VECTOR('[1,0,0]', DOUBLE))")
        iris_connection.commit()

    try:
        # Some ORMs or drivers might send '$1'::vector if they think they are doing string replacement
        # or if they are misconfigured.
        # However, protocol-level parameters don't usually look like '$1'.
        # If the server receives literally '$1' inside quotes, it might be a problem.

        # We'll try to simulate what the user described.
        # Note: psycopg might not even allow sending '$1' as a parameter.
        # We use a literal string here to see if the server handles it.
        query = "SELECT id, embedding <=> '$1'::vector as dist FROM VectorRepro2"
        # Since '$1' is a literal, we don't pass params here,
        # or we pass them and see if they are ignored.

        with pgwire_client.cursor() as cur:
            # This should probably fail if the server doesn't handle '$1' specifically,
            # but let's see if it triggers the reported syntax error.
            try:
                cur.execute(query)
                cur.fetchall()
            except Exception as e:
                print(f"Caught expected or unexpected error: {e}")
                # The error might be a syntax error if translation failed,
                # or a parameter error if translation succeeded but no param was provided.
                assert (
                    "Input ('>') encountered" in str(e)
                    or "syntax error" in str(e).lower()
                    or "number of parameters" in str(e).lower()
                )

    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS VectorRepro2")
            iris_connection.commit()


def test_vector_ordering_by_alias_reproduction(pgwire_client, iris_connection):
    """
    Tests the query SELECT id, embedding <=> '[1,0,0]' as dist FROM VectorTest ORDER BY dist
    which was reported to fail with a trailing bracket error.
    """
    # Create table with vector column
    with iris_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS VectorTest")
        cur.execute("CREATE TABLE VectorTest (id INT, embedding VECTOR(DOUBLE, 3))")
        cur.execute("INSERT INTO VectorTest VALUES (1, TO_VECTOR('[1,0,0]', DOUBLE))")
        cur.execute("INSERT INTO VectorTest VALUES (2, TO_VECTOR('[0,1,0]', DOUBLE))")
        iris_connection.commit()

    try:
        # This query uses <=> operator, an alias 'dist', and ORDER BY that alias.
        # It should be translated to use VECTOR_COSINE and IRIS TOP syntax.
        query = "SELECT id, embedding <=> '[1,0,0]' as dist FROM VectorTest ORDER BY dist"

        with pgwire_client.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            assert len(rows) == 2
            # Row 1 should be id=1 with distance 0.0
            assert rows[0][0] == 1
            assert float(rows[0][1]) == 0.0
    except Exception as e:
        pytest.fail(f"Query failed: {e}")
    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS VectorTest")
            iris_connection.commit()
