"""
Vector data generator for benchmark testing (T007).

Generates reproducible normalized random vectors for production-scale testing.
Per FR-008: All three database methods use identical test data.
"""

import numpy as np
from typing import Optional


def generate_test_vectors(
    count: int,
    dimensions: int = 1024,
    seed: int = 42,
    normalize: bool = True
) -> np.ndarray:
    """
    Generate reproducible random vectors for benchmark testing.

    Args:
        count: Number of vectors to generate
        dimensions: Vector dimensionality (default 1024 per FR-003)
        seed: Random seed for reproducibility (default 42 per data-model.md)
        normalize: Whether to L2-normalize vectors (default True for similarity tests)

    Returns:
        numpy array of shape (count, dimensions) with float32 dtype

    Constitutional Compliance:
    - Production scale: Supports 100K-1M vectors (Principle VI)
    - Reproducible: Fixed seed ensures identical data across methods (FR-008)
    - Memory efficient: Uses float32 to reduce memory footprint

    Example:
        >>> vectors = generate_test_vectors(100000, dimensions=1024, seed=42)
        >>> vectors.shape
        (100000, 1024)
        >>> vectors.dtype
        dtype('float32')
    """
    np.random.seed(seed)

    # Generate uniform random vectors in [-1.0, 1.0]
    vectors = np.random.uniform(-1.0, 1.0, size=(count, dimensions)).astype(np.float32)

    if normalize:
        # L2 normalization: v / ||v||_2
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        # Avoid division by zero (though unlikely with random data)
        norms = np.where(norms == 0, 1.0, norms)
        vectors = vectors / norms

    return vectors


def vector_to_text(vector: np.ndarray) -> str:
    """
    Convert numpy vector to IRIS/PostgreSQL text format.

    Args:
        vector: 1D numpy array

    Returns:
        String in format "[val1,val2,val3,...]" for database insertion

    Example:
        >>> vec = np.array([0.1, 0.2, 0.3])
        >>> vector_to_text(vec)
        '[0.1,0.2,0.3]'
    """
    values = ','.join(str(v) for v in vector)
    return f'[{values}]'


def generate_query_vector(dimensions: int = 1024, seed: Optional[int] = None) -> np.ndarray:
    """
    Generate a single query vector for similarity search.

    Args:
        dimensions: Vector dimensionality
        seed: Optional random seed (defaults to random)

    Returns:
        Normalized vector for query operations
    """
    if seed is not None:
        np.random.seed(seed)

    vector = np.random.uniform(-1.0, 1.0, size=dimensions).astype(np.float32)
    norm = np.linalg.norm(vector)
    return vector / norm if norm > 0 else vector
