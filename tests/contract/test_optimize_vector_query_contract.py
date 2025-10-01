#!/usr/bin/env python3
"""
Contract tests for optimize_vector_query() function

These tests define the expected behavior of the vector query optimizer.
They MUST be written before implementation and MUST fail initially (TDD).
"""

import pytest
import base64
import struct
import random
import time
from iris_pgwire.vector_optimizer import optimize_vector_query


class TestOptimizeVectorQueryContract:
    """Contract tests for optimize_vector_query() transformation logic"""

    def test_base64_vector_transformation(self):
        """
        T004: GIVEN base64 vector parameter
        WHEN optimized
        THEN JSON array literal replaces parameter
        """
        # Generate base64-encoded vector (psycopg2 default format)
        vec = [random.gauss(0, 1) for _ in range(128)]
        norm = sum(x*x for x in vec) ** 0.5
        vec = [x/norm for x in vec]
        vec_bytes = struct.pack(f'{len(vec)}f', *vec)
        vec_base64 = "base64:" + base64.b64encode(vec_bytes).decode('ascii')

        sql = "SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5"
        params = [vec_base64]

        # Execute optimization
        optimized_sql, remaining = optimize_vector_query(sql, params)

        # Assertions
        assert "TO_VECTOR('[" in optimized_sql, \
            "Optimized SQL should contain JSON array literal in TO_VECTOR"
        assert vec_base64 not in optimized_sql, \
            "Base64 parameter should be replaced, not present in SQL"
        assert remaining == [] or remaining is None, \
            "Vector parameter should be consumed, no params remaining"
        assert "ORDER BY VECTOR_COSINE" in optimized_sql, \
            "ORDER BY clause should be preserved"

    def test_multi_parameter_preservation(self):
        """
        T005: GIVEN query with vector + non-vector params
        WHEN optimized
        THEN only vector transformed, others preserved
        """
        # Generate base64 vector
        vec = [random.gauss(0, 1) for _ in range(128)]
        norm = sum(x*x for x in vec) ** 0.5
        vec = [x/norm for x in vec]
        vec_bytes = struct.pack(f'{len(vec)}f', *vec)
        vec_base64 = "base64:" + base64.b64encode(vec_bytes).decode('ascii')

        sql = "SELECT TOP %s * FROM t ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) LIMIT %s"
        params = [10, vec_base64, 5]

        # Execute optimization
        optimized_sql, remaining = optimize_vector_query(sql, params)

        # Assertions
        assert "TO_VECTOR('[" in optimized_sql, \
            "Vector parameter should be transformed to JSON array literal"
        assert vec_base64 not in optimized_sql, \
            "Base64 parameter should be replaced"
        assert remaining == [10, 5], \
            f"TOP and LIMIT parameters should be preserved, got {remaining}"
        assert optimized_sql.count('%s') == 2, \
            "Should have 2 remaining placeholders (TOP and LIMIT)"

    def test_json_array_passthrough(self):
        """
        T004 variant: GIVEN JSON array vector parameter
        WHEN optimized
        THEN JSON array is preserved (pass-through)
        """
        vec_json = "[" + ",".join([str(random.gauss(0, 1)) for _ in range(128)]) + "]"

        sql = "SELECT * FROM t ORDER BY VECTOR_L2(vec, TO_VECTOR(%s, FLOAT)) LIMIT 5"
        params = [vec_json]

        # Execute optimization
        optimized_sql, remaining = optimize_vector_query(sql, params)

        # Assertions
        assert vec_json in optimized_sql or "TO_VECTOR('[" in optimized_sql, \
            "JSON array should be preserved or transformed to literal"
        assert remaining == [] or remaining is None, \
            "Vector parameter should be consumed"

    def test_unknown_format_graceful_degradation(self):
        """
        T006: GIVEN unknown vector format
        WHEN optimized
        THEN pass through unchanged (graceful degradation)
        """
        sql = "SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))"
        params = ["unknown_format_xyz"]

        # Execute optimization
        optimized_sql, remaining = optimize_vector_query(sql, params)

        # Assertions (graceful degradation)
        assert optimized_sql == sql, \
            "SQL should be unchanged for unknown format"
        assert remaining == params, \
            "Parameters should be unchanged for unknown format"

    def test_performance_sla_compliance(self):
        """
        T007: GIVEN large vector (4096 dims)
        WHEN optimized
        THEN completes within 10ms budget
        """
        # Generate large vector (4096 dimensions)
        vec = [random.gauss(0, 1) for _ in range(4096)]
        norm = sum(x*x for x in vec) ** 0.5
        vec = [x/norm for x in vec]
        vec_bytes = struct.pack(f'{len(vec)}f', *vec)
        vec_base64 = "base64:" + base64.b64encode(vec_bytes).decode('ascii')

        sql = "SELECT * FROM t ORDER BY VECTOR_L2(vec, TO_VECTOR(%s, FLOAT))"
        params = [vec_base64]

        # Measure transformation time
        start = time.perf_counter()
        optimized_sql, remaining = optimize_vector_query(sql, params)
        duration_ms = (time.perf_counter() - start) * 1000

        # Assertions
        assert duration_ms < 10.0, \
            f"Transformation should complete within 10ms budget, took {duration_ms:.2f}ms"
        assert "TO_VECTOR('[" in optimized_sql, \
            "Even large vectors should be transformed"

    def test_no_order_by_passthrough(self):
        """
        T006 variant: GIVEN query without ORDER BY
        WHEN optimized
        THEN pass through unchanged
        """
        sql = "SELECT * FROM t WHERE id = %s"
        params = [123]

        # Execute optimization
        optimized_sql, remaining = optimize_vector_query(sql, params)

        # Assertions
        assert optimized_sql == sql, \
            "SQL without ORDER BY should be unchanged"
        assert remaining == params, \
            "Parameters should be unchanged"

    def test_no_to_vector_passthrough(self):
        """
        T006 variant: GIVEN ORDER BY without TO_VECTOR
        WHEN optimized
        THEN pass through unchanged
        """
        sql = "SELECT * FROM t ORDER BY created_date DESC LIMIT %s"
        params = [10]

        # Execute optimization
        optimized_sql, remaining = optimize_vector_query(sql, params)

        # Assertions
        assert optimized_sql == sql, \
            "SQL with ORDER BY but no TO_VECTOR should be unchanged"
        assert remaining == params, \
            "Parameters should be unchanged"

    def test_multiple_vector_functions(self):
        """
        Edge case: GIVEN ORDER BY with multiple vector functions
        WHEN optimized
        THEN all vector parameters transformed
        """
        # Generate two vectors
        vec1 = [random.gauss(0, 1) for _ in range(64)]
        vec1_bytes = struct.pack(f'{len(vec1)}f', *vec1)
        vec1_base64 = "base64:" + base64.b64encode(vec1_bytes).decode('ascii')

        vec2 = [random.gauss(0, 1) for _ in range(64)]
        vec2_bytes = struct.pack(f'{len(vec2)}f', *vec2)
        vec2_base64 = "base64:" + base64.b64encode(vec2_bytes).decode('ascii')

        sql = "SELECT * FROM t ORDER BY VECTOR_COSINE(v1, TO_VECTOR(%s)), VECTOR_DOT_PRODUCT(v2, TO_VECTOR(%s))"
        params = [vec1_base64, vec2_base64]

        # Execute optimization
        optimized_sql, remaining = optimize_vector_query(sql, params)

        # Assertions
        assert optimized_sql.count("TO_VECTOR('[") >= 2, \
            "Should transform both vector parameters"
        assert vec1_base64 not in optimized_sql, \
            "First base64 parameter should be replaced"
        assert vec2_base64 not in optimized_sql, \
            "Second base64 parameter should be replaced"
        assert remaining == [] or remaining is None, \
            "All vector parameters should be consumed"


class TestConvertVectorToLiteralContract:
    """Contract tests for _convert_vector_to_literal() helper function"""

    def test_base64_conversion(self):
        """
        T008: GIVEN base64-encoded vector
        WHEN converted
        THEN returns JSON array string
        """
        from iris_pgwire.vector_optimizer import VectorQueryOptimizer

        optimizer = VectorQueryOptimizer()

        # Generate base64 vector
        vec = [1.0, 2.0, 3.0, 4.0, 5.0]
        vec_bytes = struct.pack(f'{len(vec)}f', *vec)
        vec_base64 = "base64:" + base64.b64encode(vec_bytes).decode('ascii')

        # Convert
        result = optimizer._convert_vector_to_literal(vec_base64)

        # Assertions
        assert result is not None, \
            "Conversion should succeed for valid base64"
        assert result.startswith('['), \
            "Result should start with ["
        assert result.endswith(']'), \
            "Result should end with ]"
        assert ',' in result, \
            "Result should contain comma-separated values"

    def test_json_array_passthrough(self):
        """
        T008: GIVEN JSON array format
        WHEN converted
        THEN returns as-is (pass-through)
        """
        from iris_pgwire.vector_optimizer import VectorQueryOptimizer

        optimizer = VectorQueryOptimizer()

        vec_json = "[1.0,2.0,3.0,4.0,5.0]"

        # Convert
        result = optimizer._convert_vector_to_literal(vec_json)

        # Assertions
        assert result == vec_json, \
            "JSON array should pass through unchanged"

    def test_comma_delimited_wrapping(self):
        """
        T008: GIVEN comma-delimited format
        WHEN converted
        THEN wraps in brackets
        """
        from iris_pgwire.vector_optimizer import VectorQueryOptimizer

        optimizer = VectorQueryOptimizer()

        vec_delimited = "1.0,2.0,3.0,4.0,5.0"

        # Convert
        result = optimizer._convert_vector_to_literal(vec_delimited)

        # Assertions
        assert result == f"[{vec_delimited}]", \
            "Comma-delimited should be wrapped in brackets"

    def test_invalid_base64_returns_none(self):
        """
        T008: GIVEN invalid base64
        WHEN converted
        THEN returns None (graceful failure)
        """
        from iris_pgwire.vector_optimizer import VectorQueryOptimizer

        optimizer = VectorQueryOptimizer()

        vec_invalid = "base64:INVALID!@#$%"

        # Convert
        result = optimizer._convert_vector_to_literal(vec_invalid)

        # Assertions
        assert result is None, \
            "Invalid base64 should return None (graceful degradation)"

    def test_unknown_format_returns_none(self):
        """
        T008: GIVEN unknown format
        WHEN converted
        THEN returns None (graceful failure)
        """
        from iris_pgwire.vector_optimizer import VectorQueryOptimizer

        optimizer = VectorQueryOptimizer()

        vec_unknown = "unknown_format_xyz"

        # Convert
        result = optimizer._convert_vector_to_literal(vec_unknown)

        # Assertions
        assert result is None, \
            "Unknown format should return None (graceful degradation)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
