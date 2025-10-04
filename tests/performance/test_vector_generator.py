"""
Unit tests for vector data generator (T007 validation).

Validates reproducibility, normalization, and format compliance.
"""

import pytest
import numpy as np
import sys
from pathlib import Path

# Add benchmarks to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmarks.test_data.vector_generator import (
    generate_test_vectors,
    vector_to_text,
    generate_query_vector
)


class TestVectorGeneration:
    """Test vector generation for benchmark data"""

    def test_reproducibility_with_same_seed(self):
        """Same seed should produce identical vectors (FR-008: identical data)"""
        vectors1 = generate_test_vectors(100, dimensions=128, seed=42)
        vectors2 = generate_test_vectors(100, dimensions=128, seed=42)

        np.testing.assert_array_equal(vectors1, vectors2)

    def test_different_seeds_produce_different_vectors(self):
        """Different seeds should produce different vectors"""
        vectors1 = generate_test_vectors(100, dimensions=128, seed=42)
        vectors2 = generate_test_vectors(100, dimensions=128, seed=43)

        assert not np.array_equal(vectors1, vectors2)

    def test_output_shape(self):
        """Generated vectors should have correct shape"""
        count = 1000
        dimensions = 512
        vectors = generate_test_vectors(count, dimensions=dimensions, seed=42)

        assert vectors.shape == (count, dimensions)

    def test_output_dtype(self):
        """Generated vectors should use float32 for memory efficiency"""
        vectors = generate_test_vectors(100, dimensions=128, seed=42)

        assert vectors.dtype == np.float32

    def test_normalization(self):
        """Normalized vectors should have L2 norm ≈ 1.0"""
        vectors = generate_test_vectors(100, dimensions=128, seed=42, normalize=True)

        norms = np.linalg.norm(vectors, axis=1)
        np.testing.assert_allclose(norms, 1.0, rtol=1e-5)

    def test_unnormalized_vectors(self):
        """Unnormalized vectors should have varying norms"""
        vectors = generate_test_vectors(100, dimensions=128, seed=42, normalize=False)

        norms = np.linalg.norm(vectors, axis=1)
        # Should have variance (not all equal to 1.0)
        assert norms.std() > 0.1

    def test_production_scale_generation(self):
        """Should handle production scale: 100K vectors (Constitutional Principle VI)"""
        vectors = generate_test_vectors(100000, dimensions=1024, seed=42)

        assert vectors.shape == (100000, 1024)
        assert vectors.dtype == np.float32

    def test_vector_to_text_format(self):
        """Vector should convert to correct text format for database insertion"""
        vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        text = vector_to_text(vec)

        assert text.startswith('[')
        assert text.endswith(']')
        assert '0.1' in text
        assert '0.2' in text
        assert '0.3' in text

    def test_query_vector_generation(self):
        """Query vector should be normalized and have correct shape"""
        query_vec = generate_query_vector(dimensions=1024, seed=42)

        assert query_vec.shape == (1024,)
        assert query_vec.dtype == np.float32
        norm = np.linalg.norm(query_vec)
        np.testing.assert_allclose(norm, 1.0, rtol=1e-5)

    def test_query_vector_reproducibility(self):
        """Query vectors with same seed should be identical"""
        query1 = generate_query_vector(dimensions=512, seed=42)
        query2 = generate_query_vector(dimensions=512, seed=42)

        np.testing.assert_array_equal(query1, query2)
