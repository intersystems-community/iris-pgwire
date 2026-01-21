"""
TDD Test Suite for HNSW Indexing DDL Translation.
Validates translation of 'CREATE INDEX ... USING hnsw' to IRIS-native format.
"""

import psycopg
import pytest

from iris_pgwire.schema_mapper import IRIS_SCHEMA
from iris_pgwire.sql_translator.normalizer import SQLTranslator


@pytest.fixture
def translator():
    return SQLTranslator()


def test_hnsw_cosine_translation(translator):
    """Verify 'USING hnsw (... vector_cosine_ops)' translation."""
    sql = "CREATE INDEX idx_hnsw ON hnswtest USING hnsw (v vector_cosine_ops)"
    optimized_sql = translator.normalize_sql(sql)
    assert "AS HNSW" in optimized_sql
    assert "USING hnsw" not in optimized_sql
    assert "vector_cosine_ops" not in optimized_sql


def test_hnsw_dot_product_translation(translator):
    """Verify 'USING hnsw (... vector_ip_ops)' translation."""
    sql = "CREATE INDEX idx_hnsw_ip ON test_table USING hnsw (embedding vector_ip_ops)"
    optimized_sql = translator.normalize_sql(sql)
    assert "AS HNSW" in optimized_sql
    assert "USING hnsw" not in optimized_sql


def test_hnsw_case_insensitivity(translator):
    """Verify translation handles mixed case."""
    sql = "create index IDX_Mixed on MY_TABLE using HNSW (VEC vector_cosine_ops)"
    optimized_sql = translator.normalize_sql(sql)
    assert "AS HNSW" in optimized_sql


def test_hnsw_l2_rejection(translator):
    """Verify 'vector_l2_ops' is rejected as IRIS doesn't support it for HNSW."""
    sql = "CREATE INDEX idx_l2 ON test USING hnsw (v vector_l2_ops)"
    with pytest.raises(ValueError) as excinfo:
        translator.normalize_sql(sql)
    assert "L2/Euclidean distance" in str(excinfo.value)


def test_btree_index_untouched(translator):
    """Verify standard btree indexes are not modified."""
    sql = "CREATE INDEX idx_btree ON my_table (name)"
    optimized_sql = translator.normalize_sql(sql)
    assert "CREATE INDEX IDX_BTREE ON" in optimized_sql
    assert "(NAME)" in optimized_sql


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
                f"SELECT IndexName FROM %Dictionary.IndexDefinition WHERE parent = '{IRIS_SCHEMA}.IntegrationHnsw' AND IndexName = 'idx_integration_hnsw'"
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0].lower() == "idx_integration_hnsw"

    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE IntegrationHnsw")
            iris_connection.commit()
