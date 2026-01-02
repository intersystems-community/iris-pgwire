"""
Integration Tests for Vector Optimized Operations.
Validates HNSW indexing and similarity operators.
"""

import pytest
import numpy as np


def test_vector_cosine_operator(pgwire_client, iris_connection):
    """
    Verify pgvector <=> operator translates to VECTOR_COSINE.
    """
    # Create table with vector column
    with iris_connection.cursor() as cur:
        cur.execute("CREATE TABLE VectorTest (id INT, embedding VECTOR(DOUBLE, 3))")
        cur.execute("INSERT INTO VectorTest VALUES (1, TO_VECTOR('[1,0,0]', DOUBLE))")
        cur.execute("INSERT INTO VectorTest VALUES (2, TO_VECTOR('[0,1,0]', DOUBLE))")
        iris_connection.commit()

    try:
        # Query via PGWire using <=> operator
        with pgwire_client.cursor() as cur:
            # pgvector <=> is cosine DISTANCE (1 - cosine similarity)
            # IRIS VECTOR_COSINE is similarity
            # Our translator should handle this
            cur.execute("SELECT id, embedding <=> '[1,0,0]' as dist FROM VectorTest ORDER BY dist")
            rows = cur.fetchall()

            assert rows[0][0] == 1
            assert rows[0][1] == 0.0  # Perfectly aligned
            assert rows[1][0] == 2
            assert rows[1][1] > 0.9  # Orthogonal

    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE VectorTest")
            iris_connection.commit()


def test_hnsw_index_creation(pgwire_client, iris_connection):
    """
    Verify HNSW index can be created via PGWire.
    """
    with iris_connection.cursor() as cur:
        cur.execute("CREATE TABLE HnswTest (id INT, v VECTOR(DOUBLE, 128))")
        iris_connection.commit()

    try:
        with pgwire_client.cursor() as cur:
            # CREATE INDEX ... USING hnsw
            cur.execute("CREATE INDEX idx_hnsw ON hnswtest USING hnsw (v vector_cosine_ops)")
            iris_connection.commit()

            # Verify index exists in pg_indexes (simulated)
            cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'hnswtest'")
            row = cur.fetchone()
            assert row is not None
            assert row[0].lower() == "idx_hnsw"

    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE HnswTest")
            iris_connection.commit()
