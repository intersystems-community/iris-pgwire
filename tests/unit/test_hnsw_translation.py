"""
Unit tests for HNSW index translation.
"""

import pytest

from iris_pgwire.conversions.vector_syntax import HnswIndexSpec


def test_hnsw_parse_cosine():
    sql = "CREATE INDEX idx_vec ON documents USING hnsw (embedding vector_cosine_ops)"
    spec = HnswIndexSpec.from_postgres_sql(sql)
    assert spec is not None
    assert spec.index_name == "idx_vec"
    assert spec.table_name == "documents"
    assert spec.column_name == "embedding"
    assert spec.distance_metric == "COSINE"
    assert spec.if_not_exists is False


def test_hnsw_parse_ip():
    sql = "CREATE INDEX IF NOT EXISTS idx_ip ON vectors USING hnsw (vec vector_ip_ops)"
    spec = HnswIndexSpec.from_postgres_sql(sql)
    assert spec is not None
    assert spec.index_name == "idx_ip"
    assert spec.table_name == "vectors"
    assert spec.column_name == "vec"
    assert spec.distance_metric == "DOT_PRODUCT"
    assert spec.if_not_exists is True


def test_hnsw_parse_l2_raises_error():
    sql = "CREATE INDEX idx_l2 ON items USING hnsw (val vector_l2_ops)"
    with pytest.raises(ValueError) as excinfo:
        HnswIndexSpec.from_postgres_sql(sql)
    assert "IRIS does not support L2/Euclidean distance" in str(excinfo.value)


def test_hnsw_to_iris_sql():
    spec = HnswIndexSpec(
        index_name="my_idx", table_name="my_table", column_name="my_col", distance_metric="COSINE"
    )
    # IRIS syntax: CREATE INDEX idx ON table (col) AS HNSW
    assert spec.to_iris_sql() == "CREATE INDEX my_idx ON my_table (my_col) AS HNSW"


def test_hnsw_parse_unsupported_operator():
    sql = "CREATE INDEX idx ON tab USING hnsw (col some_other_ops)"
    with pytest.raises(ValueError) as excinfo:
        HnswIndexSpec.from_postgres_sql(sql)
    assert "Unsupported vector operator for HNSW" in str(excinfo.value)


def test_hnsw_parse_no_match():
    sql = "CREATE INDEX idx ON tab (col)"
    spec = HnswIndexSpec.from_postgres_sql(sql)
    assert spec is None
