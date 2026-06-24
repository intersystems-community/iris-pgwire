"""
Unit tests for conversions/vector_syntax.py — HnswIndexSpec, helpers.
Goal: ≥85% coverage.
"""

import pytest

from iris_pgwire.conversions.vector_syntax import (
    HnswIndexSpec,
    _parse_distance_from_with,
    _parse_with_options,
    normalize_vector,
)


# ---------------------------------------------------------------------------
# normalize_vector
# ---------------------------------------------------------------------------


class TestNormalizeVector:
    def test_int_list_to_floats(self):
        result = normalize_vector([1, 2, 3])
        assert result == [1.0, 2.0, 3.0]
        assert all(isinstance(x, float) for x in result)

    def test_already_floats(self):
        result = normalize_vector([0.1, 0.5, 0.9])
        assert result == [0.1, 0.5, 0.9]

    def test_empty_list(self):
        assert normalize_vector([]) == []

    def test_mixed_types(self):
        result = normalize_vector([1, 2.5, "3"])
        assert result == [1.0, 2.5, 3.0]


# ---------------------------------------------------------------------------
# _parse_with_options
# ---------------------------------------------------------------------------


class TestParseWithOptions:
    def test_m_only(self):
        m, ef = _parse_with_options("m=32")
        assert m == 32
        assert ef is None

    def test_ef_construction(self):
        m, ef = _parse_with_options("ef_construction=128")
        assert m is None
        assert ef == 128

    def test_efconstruction_no_underscore(self):
        m, ef = _parse_with_options("efconstruction=64")
        assert ef == 64

    def test_m_and_ef(self):
        m, ef = _parse_with_options("m=16, ef_construction=64")
        assert m == 16
        assert ef == 64

    def test_empty_string(self):
        m, ef = _parse_with_options("")
        assert m is None
        assert ef is None

    def test_unknown_keys_ignored(self, ):
        m, ef = _parse_with_options("lists=100, probes=10")
        assert m is None
        assert ef is None

    def test_whitespace_around_kv(self):
        m, ef = _parse_with_options("  m = 8 ,  ef_construction = 50 ")
        assert m == 8
        assert ef == 50


# ---------------------------------------------------------------------------
# _parse_distance_from_with
# ---------------------------------------------------------------------------


class TestParseDistanceFromWith:
    def test_cosine(self):
        assert _parse_distance_from_with("Distance='Cosine'") == "Cosine"

    def test_cosine_no_quotes(self):
        assert _parse_distance_from_with("Distance=Cosine") == "Cosine"

    def test_dotproduct(self):
        assert _parse_distance_from_with("Distance='DotProduct'") == "DotProduct"

    def test_dot_product_with_underscore(self):
        assert _parse_distance_from_with("Distance='dot_product'") == "DotProduct"

    def test_inner_product(self):
        assert _parse_distance_from_with("Distance='innerproduct'") == "DotProduct"

    def test_inner_product_with_underscore(self):
        assert _parse_distance_from_with("Distance='inner_product'") == "DotProduct"

    def test_default_when_missing(self):
        assert _parse_distance_from_with("") == "Cosine"

    def test_cosine_uppercase(self):
        assert _parse_distance_from_with("DISTANCE='COSINE'") == "Cosine"


# ---------------------------------------------------------------------------
# HnswIndexSpec.to_iris_sql
# ---------------------------------------------------------------------------


class TestHnswIndexSpecToIrisSql:
    def test_basic_cosine(self):
        spec = HnswIndexSpec(
            index_name="idx",
            table_name="MyTable",
            column_name="embedding",
            distance_metric="Cosine",
        )
        sql = spec.to_iris_sql()
        assert sql == "CREATE INDEX idx ON MyTable (embedding) AS HNSW(Distance='Cosine')"

    def test_with_m_and_ef(self):
        spec = HnswIndexSpec(
            index_name="idx",
            table_name="t",
            column_name="vec",
            distance_metric="DotProduct",
            m=32,
            ef_construction=128,
        )
        sql = spec.to_iris_sql()
        assert "Distance='DotProduct'" in sql
        assert "M=32" in sql
        assert "efConstruction=128" in sql

    def test_m_none_not_emitted(self):
        spec = HnswIndexSpec(
            index_name="idx",
            table_name="t",
            column_name="vec",
            distance_metric="Cosine",
            m=None,
            ef_construction=64,
        )
        sql = spec.to_iris_sql()
        assert "M=" not in sql
        assert "efConstruction=64" in sql

    def test_ef_none_not_emitted(self):
        spec = HnswIndexSpec(
            index_name="idx",
            table_name="t",
            column_name="vec",
            distance_metric="Cosine",
            m=16,
            ef_construction=None,
        )
        sql = spec.to_iris_sql()
        assert "M=16" in sql
        assert "efConstruction" not in sql

    def test_schema_qualified_table(self):
        spec = HnswIndexSpec(
            index_name="idx",
            table_name="SQLUser.Embeddings",
            column_name="vec",
            distance_metric="Cosine",
        )
        sql = spec.to_iris_sql()
        assert "ON SQLUser.Embeddings" in sql


# ---------------------------------------------------------------------------
# HnswIndexSpec.from_postgres_sql — Form 1 (USING hnsw before column list)
# ---------------------------------------------------------------------------


class TestFromPostgresSqlForm1:
    def test_cosine_ops(self):
        sql = "CREATE INDEX my_idx ON my_table USING hnsw (embedding vector_cosine_ops)"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec is not None
        assert spec.index_name == "my_idx"
        assert spec.table_name == "my_table"
        assert spec.column_name == "embedding"
        assert spec.distance_metric == "Cosine"

    def test_ip_ops(self):
        sql = "CREATE INDEX my_idx ON my_table USING hnsw (embedding vector_ip_ops)"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec is not None
        assert spec.distance_metric == "DotProduct"

    def test_l2_ops_raises(self):
        sql = "CREATE INDEX my_idx ON my_table USING hnsw (embedding vector_l2_ops)"
        with pytest.raises(ValueError, match="L2/Euclidean"):
            HnswIndexSpec.from_postgres_sql(sql)

    def test_unknown_op_raises(self):
        sql = "CREATE INDEX my_idx ON my_table USING hnsw (embedding vector_unknown_ops)"
        with pytest.raises(ValueError, match="Unsupported vector operator"):
            HnswIndexSpec.from_postgres_sql(sql)

    def test_with_m_ef(self):
        sql = (
            "CREATE INDEX idx ON t USING hnsw (vec vector_cosine_ops)"
            " WITH (m=32, ef_construction=128)"
        )
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec.m == 32
        assert spec.ef_construction == 128

    def test_if_not_exists(self):
        sql = "CREATE INDEX IF NOT EXISTS idx ON t USING hnsw (vec vector_cosine_ops)"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec.if_not_exists is True

    def test_without_if_not_exists(self):
        sql = "CREATE INDEX idx ON t USING hnsw (vec vector_cosine_ops)"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec.if_not_exists is False

    def test_unique_index(self):
        sql = "CREATE UNIQUE INDEX idx ON t USING hnsw (vec vector_cosine_ops)"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec is not None
        assert spec.index_name == "idx"


# ---------------------------------------------------------------------------
# HnswIndexSpec.from_postgres_sql — Form 2 (column list before USING)
# ---------------------------------------------------------------------------


class TestFromPostgresSqlForm2:
    def test_basic_form2(self):
        sql = "CREATE INDEX my_idx ON my_table (embedding) USING HNSW"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec is not None
        assert spec.index_name == "my_idx"
        assert spec.distance_metric == "Cosine"  # default

    def test_form2_with_distance(self):
        sql = "CREATE INDEX idx ON t (vec) USING HNSW WITH (Distance='DotProduct')"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec is not None
        assert spec.distance_metric == "DotProduct"

    def test_form2_with_m_ef(self):
        sql = "CREATE INDEX idx ON t (vec) USING HNSW WITH (m=8, ef_construction=32)"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec.m == 8
        assert spec.ef_construction == 32

    def test_form2_if_not_exists(self):
        sql = "CREATE INDEX IF NOT EXISTS idx ON t (vec) USING HNSW"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec.if_not_exists is True

    def test_schema_qualified_table_form2(self):
        sql = "CREATE INDEX idx ON SQLUser.MyTable (vec) USING HNSW"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        assert spec.table_name == "SQLUser.MyTable"


# ---------------------------------------------------------------------------
# Non-HNSW returns None
# ---------------------------------------------------------------------------


class TestNonHnswReturnsNone:
    def test_regular_create_index(self):
        sql = "CREATE INDEX idx ON t (col)"
        assert HnswIndexSpec.from_postgres_sql(sql) is None

    def test_btree_index(self):
        sql = "CREATE INDEX idx ON t USING btree (col)"
        assert HnswIndexSpec.from_postgres_sql(sql) is None

    def test_create_table(self):
        sql = "CREATE TABLE t (id INT)"
        assert HnswIndexSpec.from_postgres_sql(sql) is None

    def test_empty_string(self):
        assert HnswIndexSpec.from_postgres_sql("") is None


# ---------------------------------------------------------------------------
# Roundtrip: from_postgres_sql → to_iris_sql
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_form1_roundtrip(self):
        sql = "CREATE INDEX idx ON t USING hnsw (vec vector_cosine_ops)"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        iris_sql = spec.to_iris_sql()
        assert "CREATE INDEX idx ON t (vec) AS HNSW(Distance='Cosine')" == iris_sql

    def test_form2_roundtrip(self):
        sql = "CREATE INDEX idx ON t (vec) USING HNSW WITH (Distance='DotProduct', m=16)"
        spec = HnswIndexSpec.from_postgres_sql(sql)
        iris_sql = spec.to_iris_sql()
        assert "Distance='DotProduct'" in iris_sql
        assert "M=16" in iris_sql
