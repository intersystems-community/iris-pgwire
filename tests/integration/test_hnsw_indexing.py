"""
TDD Test Suite for HNSW Indexing DDL Translation.
Validates translation of 'CREATE INDEX ... USING hnsw' to IRIS-native format.
"""

import psycopg
import pytest

from iris_pgwire.vector_optimizer import VectorQueryOptimizer


@pytest.fixture
def optimizer():
    return VectorQueryOptimizer()


def test_hnsw_cosine_translation(optimizer):
    """Verify 'USING hnsw (... vector_cosine_ops)' translation."""
    sql = "CREATE INDEX idx_hnsw ON hnswtest USING hnsw (v vector_cosine_ops)"
    # Note: VectorQueryOptimizer.optimize_query is the main entry point
    # We'll check the internal logic first or the main entry point
    optimized_sql, _ = optimizer.optimize_query(sql)
    assert "AS HNSW(Distance='Cosine')" in optimized_sql
    assert "USING hnsw" not in optimized_sql
    assert "vector_cosine_ops" not in optimized_sql


def test_hnsw_dot_product_translation(optimizer):
    """Verify 'USING hnsw (... vector_ip_ops)' translation."""
    sql = "CREATE INDEX idx_hnsw_ip ON test_table USING hnsw (embedding vector_ip_ops)"
    optimized_sql, _ = optimizer.optimize_query(sql)
    assert "AS HNSW(Distance='DotProduct')" in optimized_sql
    assert "USING hnsw" not in optimized_sql


def test_hnsw_case_insensitivity(optimizer):
    """Verify translation handles mixed case."""
    sql = "create index IDX_Mixed on MY_TABLE using HNSW (VEC vector_cosine_ops)"
    optimized_sql, _ = optimizer.optimize_query(sql)
    assert "AS HNSW(Distance='Cosine')" in optimized_sql


def test_hnsw_l2_rejection(optimizer):
    """Verify 'vector_l2_ops' is rejected as IRIS doesn't support it for HNSW."""
    sql = "CREATE INDEX idx_l2 ON test USING hnsw (v vector_l2_ops)"
    with pytest.raises(NotImplementedError) as excinfo:
        optimizer.optimize_query(sql)
    assert "L2 distance" in str(excinfo.value)


def test_btree_index_untouched(optimizer):
    """Verify standard btree indexes are not modified."""
    sql = "CREATE INDEX idx_btree ON my_table (name)"
    optimized_sql, _ = optimizer.optimize_query(sql)
    assert optimized_sql == sql


def test_integration_hnsw_creation(pgwire_client, iris_connection):
    """
    Real integration test: Create HNSW index via PGWire and verify it exists in IRIS.
    """
    with iris_connection.cursor() as cur:
        cur.execute("CREATE TABLE IntegrationHnsw (id INT, v VECTOR(DOUBLE, 3))")
        iris_connection.commit()

    try:
        with pgwire_client.cursor() as cur:
            cur.execute(
                "CREATE INDEX idx_integration_hnsw ON IntegrationHnsw USING hnsw (v vector_cosine_ops)"
            )
            pgwire_client.commit()

        with iris_connection.cursor() as cur:
            cur.execute(
                "SELECT IndexName FROM %Dictionary.IndexDefinition WHERE parent = 'SQLUser.IntegrationHnsw' AND IndexName = 'idx_integration_hnsw'"
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0].lower() == "idx_integration_hnsw"

    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE IntegrationHnsw")
            iris_connection.commit()
