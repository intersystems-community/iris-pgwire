import pytest

from iris_pgwire.sql_translator.normalizer import SQLTranslator
from iris_pgwire.vector_optimizer import optimize_vector_query


@pytest.fixture
def translator():
    return SQLTranslator()


def test_vector_operator_with_cast(translator):
    sql = "SELECT * FROM items ORDER BY embedding <=> $1::vector"
    sql = translator.normalize_sql(sql)

    optimized_sql, _ = optimize_vector_query(sql, ["[1,2,3]"])

    assert "VECTOR_COSINE" in optimized_sql
    assert "TO_VECTOR" in optimized_sql
    assert "(1 - VECTOR_COSINE" in optimized_sql
    assert "::" not in optimized_sql


def test_vector_operator_with_quoted_placeholder(translator):
    sql = "SELECT * FROM items ORDER BY embedding <=> '$1'::vector"
    sql = translator.normalize_sql(sql)
    assert "TO_VECTOR(?, DOUBLE)" in sql

    optimized_sql, _ = optimize_vector_query(sql, ["[1,2,3]"])
    assert "VECTOR_COSINE" in optimized_sql
    assert "TO_VECTOR('[1,2,3]', DOUBLE)" in optimized_sql
    assert "(1 - VECTOR_COSINE" in optimized_sql


def test_vector_operator_case_insensitive(translator):
    sql = "SELECT * FROM items ORDER BY EMBEDDING <=> $1::VECTOR"
    sql = translator.normalize_sql(sql)
    assert "TO_VECTOR(?, DOUBLE)" in sql

    optimized_sql, _ = optimize_vector_query(sql, ["[1,2,3]"])
    assert "VECTOR_COSINE" in optimized_sql
    assert "(1 - VECTOR_COSINE" in optimized_sql


def test_vector_operator_already_wrapped(translator):
    sql = "SELECT * FROM items ORDER BY embedding <=> TO_VECTOR($1, DOUBLE)"
    sql = translator.normalize_sql(sql)

    optimized_sql, _ = optimize_vector_query(sql, ["[1,2,3]"])
    assert "VECTOR_COSINE" in optimized_sql
    assert "TO_VECTOR('[1,2,3]', DOUBLE)" in optimized_sql
    assert "(1 - VECTOR_COSINE" in optimized_sql


def test_vector_dot_product_operator(translator):
    sql = "SELECT * FROM items ORDER BY embedding <#> $1::vector"
    sql = translator.normalize_sql(sql)

    optimized_sql, _ = optimize_vector_query(sql, ["[1,2,3]"])
    assert "VECTOR_DOT_PRODUCT" in optimized_sql
    assert "(-VECTOR_DOT_PRODUCT" in optimized_sql
