"""
Contract Test: Vector Optimizer Syntax Preservation (FR-001)

REQUIREMENT: System MUST preserve vector literal formatting (brackets) when optimizing
pgvector operators to IRIS vector functions.

EXPECTED: These tests MUST FAIL before implementation (TDD).
"""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from iris_pgwire.vector_optimizer import VectorQueryOptimizer


class TestVectorOptimizerSyntax:
    """Contract tests for bracket preservation in vector literals"""

    def setup_method(self):
        """Initialize optimizer for each test"""
        self.optimizer = VectorQueryOptimizer()

    def test_cosine_operator_preserves_brackets(self):
        """Cosine distance operator MUST wrap as (1 - VECTOR_COSINE(...)) and preserve brackets (FR-001)"""
        sql = "SELECT id, embedding <=> '[0.1,0.2,0.3]' AS distance FROM vectors"

        optimized_sql, params = self.optimizer.optimize_query(sql)

        # MUST use VECTOR_COSINE wrapped as cosine distance
        assert "1 - VECTOR_COSINE(embedding, TO_VECTOR" in optimized_sql, (
            f"(1 - VECTOR_COSINE) not found! Got: {optimized_sql}"
        )

        # MUST contain TO_VECTOR with brackets and DOUBLE type
        assert "TO_VECTOR('[0.1,0.2,0.3]', DOUBLE)" in optimized_sql, (
            f"Brackets or DOUBLE type missing! Got: {optimized_sql}"
        )

        # MUST NOT have brackets stripped
        assert "TO_VECTOR('0.1,0.2,0.3'" not in optimized_sql, (
            f"Brackets were stripped! Got: {optimized_sql}"
        )

    def test_l2_operator_preserves_brackets(self):
        """L2 distance operator (<->) is unsupported — MUST raise NotImplementedError"""
        sql = "SELECT id, embedding <-> '[1.0,2.0,3.0]' AS distance FROM vectors"

        with pytest.raises(NotImplementedError, match="L2 distance operator"):
            self.optimizer.optimize_query(sql)

    def test_inner_product_operator_preserves_brackets(self):
        """Inner product operator MUST preserve brackets (FR-001)"""
        sql = "SELECT id, (embedding <#> '[0.5,0.5,0.5]') * -1 AS similarity FROM vectors"

        optimized_sql, params = self.optimizer.optimize_query(sql)

        assert "TO_VECTOR('[0.5,0.5,0.5]', DOUBLE)" in optimized_sql, (
            f"Brackets or DOUBLE type missing in inner product! Got: {optimized_sql}"
        )
        assert "VECTOR_DOT_PRODUCT(embedding, TO_VECTOR" in optimized_sql

    def test_large_vector_preserves_brackets(self):
        """Large vectors (1024D) MUST preserve brackets (FR-001)"""
        vector_1024d = "[" + ",".join(["0.1"] * 1024) + "]"
        sql = f"SELECT id, embedding <=> '{vector_1024d}' AS distance FROM vectors"

        optimized_sql, params = self.optimizer.optimize_query(sql)

        # Brackets MUST be preserved (DOUBLE type)
        assert f"TO_VECTOR('{vector_1024d}', DOUBLE)" in optimized_sql, (
            f"Brackets missing in 1024D vector! Got: {optimized_sql[:200]}..."
        )

        # MUST be wrapped as cosine distance
        assert "1 - VECTOR_COSINE" in optimized_sql, (
            f"Missing (1 - VECTOR_COSINE) wrapper! Got: {optimized_sql[:200]}"
        )

        # MUST NOT have brackets stripped
        vector_no_brackets = vector_1024d[1:-1]
        assert f"TO_VECTOR('{vector_no_brackets}'" not in optimized_sql, (
            "Brackets were stripped from 1024D vector!"
        )

    def test_order_by_preserves_brackets(self):
        """ORDER BY with vector operator MUST produce (1 - VECTOR_COSINE(...)) and preserve brackets (FR-001)"""
        sql = "SELECT id FROM vectors ORDER BY embedding <=> '[0.1,0.2,0.3]' LIMIT 5"

        optimized_sql, params = self.optimizer.optimize_query(sql)

        # Brackets in ORDER BY clause with DOUBLE type
        assert "TO_VECTOR('[0.1,0.2,0.3]', DOUBLE)" in optimized_sql, (
            f"Brackets or DOUBLE type missing in ORDER BY! Got: {optimized_sql}"
        )

        # Wrapped as cosine distance so ASC = most similar first
        assert "1 - VECTOR_COSINE" in optimized_sql, (
            f"Missing distance wrapper! Got: {optimized_sql}"
        )

        # ORDER BY should be preserved
        assert "ORDER BY" in optimized_sql


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
