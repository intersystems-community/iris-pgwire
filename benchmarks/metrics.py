"""
Metrics calculation utilities for benchmark (T013).

Calculates performance metrics per FR-004:
- QPS (Queries Per Second)
- Latency percentiles (P50, P95, P99)
"""

import numpy as np
from typing import List, Dict


def calculate_metrics(timings: List[float]) -> Dict[str, float]:
    """
    Calculate performance metrics from timing measurements.

    Args:
        timings: List of query execution times in milliseconds

    Returns:
        Dictionary with metrics:
        - p50_ms: Median latency (50th percentile)
        - p95_ms: 95th percentile latency
        - p99_ms: 99th percentile latency
        - qps: Queries per second

    Constitutional Validation:
        Validates <5ms translation overhead requirement (Principle VI)

    Example:
        >>> timings = [10.0, 12.0, 15.0, 11.0, 13.0]
        >>> metrics = calculate_metrics(timings)
        >>> metrics['p50_ms']  # Median
        12.0
        >>> metrics['qps']  # Queries/second
        ~83.3
    """
    if not timings:
        return {
            'p50_ms': 0.0,
            'p95_ms': 0.0,
            'p99_ms': 0.0,
            'qps': 0.0,
            'count': 0
        }

    timings_array = np.array(timings)

    # Calculate percentiles
    p50 = float(np.percentile(timings_array, 50))
    p95 = float(np.percentile(timings_array, 95))
    p99 = float(np.percentile(timings_array, 99))

    # Calculate QPS (queries per second)
    # QPS = total_queries / total_time_seconds
    total_time_ms = sum(timings)
    total_time_s = total_time_ms / 1000.0
    qps = len(timings) / total_time_s if total_time_s > 0 else 0.0

    return {
        'p50_ms': p50,
        'p95_ms': p95,
        'p99_ms': p99,
        'qps': qps,
        'count': len(timings)
    }


def calculate_category_metrics(timings_by_category: Dict[str, List[float]]) -> Dict[str, Dict[str, float]]:
    """
    Calculate metrics for each query category.

    Args:
        timings_by_category: Dict mapping category name to list of timings

    Returns:
        Dict mapping category name to metrics dict

    Example:
        >>> timings = {
        ...     'simple': [5.0, 6.0, 5.5],
        ...     'vector': [10.0, 12.0, 11.0],
        ...     'complex': [20.0, 25.0, 22.0]
        ... }
        >>> metrics = calculate_category_metrics(timings)
        >>> metrics['simple']['p50_ms']
        5.5
    """
    return {
        category: calculate_metrics(timings)
        for category, timings in timings_by_category.items()
    }


def validate_constitutional_overhead(
    pgwire_timings: List[float],
    iris_dbapi_timings: List[float],
    threshold_ms: float = 5.0
) -> Dict[str, any]:
    """
    Validate translation overhead against constitutional requirement.

    Constitutional Principle VI: PGWire translation overhead must be <5ms

    Args:
        pgwire_timings: PGWire query timings
        iris_dbapi_timings: IRIS DBAPI query timings (baseline)
        threshold_ms: Constitutional threshold (default 5.0ms)

    Returns:
        Dictionary with validation results:
        - compliant: bool
        - overhead_p50_ms: Median overhead
        - overhead_p95_ms: P95 overhead
        - overhead_p99_ms: P99 overhead
    """
    if not pgwire_timings or not iris_dbapi_timings:
        return {
            'compliant': False,
            'reason': 'Insufficient data for validation',
            'overhead_p50_ms': None,
            'overhead_p95_ms': None,
            'overhead_p99_ms': None
        }

    pgwire = np.array(pgwire_timings)
    dbapi = np.array(iris_dbapi_timings)

    # Calculate overhead at each percentile
    # Overhead = PGWire_time - IRIS_DBAPI_time
    min_len = min(len(pgwire), len(dbapi))
    overhead = pgwire[:min_len] - dbapi[:min_len]

    overhead_p50 = float(np.percentile(overhead, 50))
    overhead_p95 = float(np.percentile(overhead, 95))
    overhead_p99 = float(np.percentile(overhead, 99))

    # Constitutional compliance: P95 overhead < threshold
    compliant = overhead_p95 < threshold_ms

    return {
        'compliant': compliant,
        'overhead_p50_ms': overhead_p50,
        'overhead_p95_ms': overhead_p95,
        'overhead_p99_ms': overhead_p99,
        'threshold_ms': threshold_ms,
        'status': '✅ Compliant' if compliant else f'⚠️ P95 overhead {overhead_p95:.2f}ms exceeds {threshold_ms}ms threshold'
    }
