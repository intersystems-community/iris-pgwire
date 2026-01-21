import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

from iris_pgwire.sql_translator.identifier_normalizer import IdentifierNormalizer
from iris_pgwire.vector_optimizer import VectorQueryOptimizer


def test_vector_quoted_identifier():
    normalizer = IdentifierNormalizer()
    optimizer = VectorQueryOptimizer()

    sql = 'SELECT * FROM items ORDER BY "embedding" <=> %s'
    params = ["[0.1,0.2,0.3]"]

    normalized_sql, _ = normalizer.normalize(sql)
    assert '"embedding"' in normalized_sql

    optimized_sql, remaining_params = optimizer.optimize_query(normalized_sql, params)

    assert "VECTOR_COSINE" in optimized_sql
    assert '"embedding"' in optimized_sql
    assert "TO_VECTOR" in optimized_sql
    assert "[0.1,0.2,0.3]" in optimized_sql
    assert remaining_params is None or len(remaining_params) == 0


def test_vector_qualified_quoted_identifier():
    normalizer = IdentifierNormalizer()
    optimizer = VectorQueryOptimizer()

    sql = 'SELECT * FROM items ORDER BY "public"."items"."embedding" <=> %s'
    params = ["[0.1,0.2,0.3]"]

    normalized_sql, _ = normalizer.normalize(sql)
    assert '"public"."items"."embedding"' in normalized_sql

    optimized_sql, remaining_params = optimizer.optimize_query(normalized_sql, params)

    assert "VECTOR_COSINE" in optimized_sql
    assert '"public"."items"."embedding"' in optimized_sql
    assert "TO_VECTOR" in optimized_sql


def test_percent_s_preservation():
    normalizer = IdentifierNormalizer()

    sql = "SELECT * FROM items WHERE name = %s"

    normalized_sql, _ = normalizer.normalize(sql)

    assert "%s" in normalized_sql
    assert "%S" not in normalized_sql


def test_vector_negative_inner_product_quoted():
    optimizer = VectorQueryOptimizer()

    sql = 'SELECT * FROM items ORDER BY "embedding" <#> %s'
    params = ["[0.1,0.2,0.3]"]

    optimized_sql, _ = optimizer.optimize_query(sql, params)

    assert "VECTOR_DOT_PRODUCT" in optimized_sql
    assert '"embedding"' in optimized_sql
    assert "TO_VECTOR" in optimized_sql
    assert "[0.1,0.2,0.3]" in optimized_sql
    assert remaining_params is None or len(remaining_params) == 0


def test_vector_qualified_quoted_identifier():
    normalizer = IdentifierNormalizer()
    optimizer = VectorQueryOptimizer()

    sql = 'SELECT * FROM items ORDER BY "public"."items"."embedding" <=> %s'
    params = ["[0.1, 0.2, 0.3]"]

    normalized_sql, _ = normalizer.normalize(sql)
    assert '"public"."items"."embedding"' in normalized_sql

    optimized_sql, remaining_params = optimizer.optimize_query(normalized_sql, params)

    assert "VECTOR_COSINE" in optimized_sql
    assert '"public"."items"."embedding"' in optimized_sql
    assert "TO_VECTOR" in optimized_sql


def test_percent_s_preservation():
    normalizer = IdentifierNormalizer()

    sql = "SELECT * FROM items WHERE name = %s"

    normalized_sql, _ = normalizer.normalize(sql)

    assert "%s" in normalized_sql
    assert "%S" not in normalized_sql


def test_vector_negative_inner_product_quoted():
    optimizer = VectorQueryOptimizer()

    sql = 'SELECT * FROM items ORDER BY "embedding" <#> %s'
    params = ["[0.1, 0.2, 0.3]"]

    optimized_sql, _ = optimizer.optimize_query(sql, params)

    assert "VECTOR_DOT_PRODUCT" in optimized_sql
    assert '"embedding"' in optimized_sql
    assert "TO_VECTOR" in optimized_sql
    assert "[0.1,0.2,0.3]" in optimized_sql
    assert remaining_params is None or len(remaining_params) == 0


def test_vector_qualified_quoted_identifier():
    normalizer = IdentifierNormalizer()
    optimizer = VectorQueryOptimizer()

    sql = 'SELECT * FROM items ORDER BY "public"."items"."embedding" <=> %s'
    params = [[0.1, 0.2, 0.3]]

    normalized_sql, _ = normalizer.normalize(sql)
    assert '"public"."items"."embedding"' in normalized_sql

    optimized_sql, remaining_params = optimizer.optimize_query(normalized_sql, params)

    assert "VECTOR_COSINE" in optimized_sql
    assert '"public"."items"."embedding"' in optimized_sql
    assert "TO_VECTOR" in optimized_sql


def test_percent_s_preservation():
    normalizer = IdentifierNormalizer()

    sql = "SELECT * FROM items WHERE name = %s"

    normalized_sql, _ = normalizer.normalize(sql)

    assert "%s" in normalized_sql
    assert "%S" not in normalized_sql


def test_vector_negative_inner_product_quoted():
    optimizer = VectorQueryOptimizer()

    sql = 'SELECT * FROM items ORDER BY "embedding" <#> %s'
    params = [[0.1, 0.2, 0.3]]

    optimized_sql, _ = optimizer.optimize_query(sql, params)

    assert "VECTOR_DOT_PRODUCT" in optimized_sql
    assert '"embedding"' in optimized_sql
    assert "TO_VECTOR" in optimized_sql
