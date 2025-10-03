"""
Vector query optimizer for IRIS HNSW compatibility

Transforms parameterized vector queries into literal form to enable HNSW index optimization.
This is a server-side workaround for IRIS's requirement that vectors in ORDER BY clauses
must be literals, not parameters.
"""

import re
import base64
import struct
import time
from typing import Tuple, List, Optional, Dict, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class OptimizationMetrics:
    """Performance metrics for vector query optimization"""
    transformation_time_ms: float
    vector_params_found: int
    vector_params_transformed: int
    sql_length_before: int
    sql_length_after: int
    params_count_before: int
    params_count_after: int
    constitutional_sla_compliant: bool
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for logging"""
        return {
            'transformation_time_ms': round(self.transformation_time_ms, 2),
            'vector_params_found': self.vector_params_found,
            'vector_params_transformed': self.vector_params_transformed,
            'sql_length_before': self.sql_length_before,
            'sql_length_after': self.sql_length_after,
            'params_count_before': self.params_count_before,
            'params_count_after': self.params_count_after,
            'constitutional_sla_compliant': self.constitutional_sla_compliant,
            'sla_threshold_ms': 5.0
        }


class VectorQueryOptimizer:
    """
    Optimizes vector queries for IRIS HNSW performance by converting
    parameterized TO_VECTOR() calls in ORDER BY clauses to literal form.
    """

    # Constitutional SLA requirement: 5ms maximum transformation time
    CONSTITUTIONAL_SLA_MS = 5.0

    def __init__(self):
        self.enabled = True
        self.metrics_history: List[OptimizationMetrics] = []
        self.sla_violations = 0
        self.total_optimizations = 0

    def optimize_query(self, sql: str, params: Optional[List] = None) -> Tuple[str, Optional[List]]:
        """
        Transform parameterized vector queries into literal form for HNSW optimization.

        Pattern to detect:
            ORDER BY VECTOR_COSINE(column, TO_VECTOR(%s)) or TO_VECTOR(?)

        Transform to:
            ORDER BY VECTOR_COSINE(column, TO_VECTOR('1.0,2.0,3.0,...', FLOAT))

        Note: FLOAT must be unquoted keyword, not string literal (confirmed via test_vector_syntax.py)

        Args:
            sql: SQL query string
            params: Query parameters

        Returns:
            Tuple of (optimized_sql, remaining_params)
        """
        # Start performance tracking
        start_time = time.perf_counter()
        sql_length_before = len(sql) if sql else 0
        params_count_before = len(params) if params else 0

        # Edge case: Handle None or empty inputs gracefully
        if sql is None:
            logger.warning("optimize_query called with None SQL")
            return "", params

        if not isinstance(sql, str):
            logger.error(f"optimize_query called with non-string SQL: type={type(sql).__name__}")
            return str(sql), params

        if not self.enabled:
            return sql, params

        # Check if this is a vector similarity query with ORDER BY
        if 'ORDER BY' not in sql.upper() or 'TO_VECTOR' not in sql.upper():
            return sql, params

        # Handle two cases:
        # 1. Parameterized queries: TO_VECTOR(%s) with params list
        # 2. Literal queries: TO_VECTOR('base64:...') already in SQL (client-side interpolation)
        if not params:
            # No parameters - check if SQL contains literal base64/vector strings
            return self._optimize_literal_vectors(sql, start_time)

        # Pattern: Find TO_VECTOR calls with parameters in ORDER BY clause
        # Match: VECTOR_FUNCTION(column, TO_VECTOR(?, FLOAT))
        try:
            order_by_pattern = re.compile(
                r'(VECTOR_(?:COSINE|DOT_PRODUCT|L2))\s*\(\s*'
                r'(\w+)\s*,\s*'
                r'(TO_VECTOR\s*\(\s*([?%]s?)\s*(?:,\s*(\w+))?\s*\))',
                re.IGNORECASE
            )
        except re.error as e:
            logger.error(f"Regex compilation failed: {str(e)}")
            return sql, params

        try:
            matches = list(order_by_pattern.finditer(sql))
        except Exception as e:
            logger.error(f"Regex matching failed: {str(e)}, sql_length={len(sql)}")
            return sql, params

        if not matches:
            return sql, params

        logger.info(f"Vector query optimization triggered: {len(matches)} pattern matches, {len(params) if params else 0} params")

        # Process matches in reverse order to maintain string positions
        optimized_sql = sql
        params_used = []
        remaining_params = list(params) if params else []

        logger.debug(f"Starting vector transformation: {len(matches)} matches, {len(remaining_params)} total params")

        for match in reversed(matches):
            vector_func = match.group(1)  # VECTOR_COSINE, etc
            column_name = match.group(2)  # column name
            to_vector_call = match.group(3)  # Full TO_VECTOR(...) call
            param_placeholder = match.group(4)  # ? or %s
            data_type = match.group(5) or 'FLOAT'  # FLOAT, INT, etc

            # Find which parameter this corresponds to
            # Count how many parameters appear before this position
            param_index = sql[:match.start()].count('?') + sql[:match.start()].count('%s')

            logger.debug(f"Processing match: func={vector_func}, column={column_name}, param_index={param_index}")

            if param_index >= len(remaining_params):
                logger.warning(f"Parameter index out of range: index={param_index}, total_params={len(remaining_params)}")
                continue

            # Get the vector parameter
            vector_param = remaining_params[param_index]
            logger.debug(f"Vector param at index {param_index}: type={type(vector_param).__name__}, length={len(str(vector_param)) if vector_param else 0}")

            # Convert to JSON array format
            vector_literal = self._convert_vector_to_literal(vector_param)

            if vector_literal is None:
                logger.warning(f"Could not convert vector parameter to literal: param_index={param_index}, param_type={type(vector_param).__name__}")
                continue

            logger.debug(f"Converted vector to literal: length={len(vector_literal)}, preview={vector_literal[:50]}...")

            # CRITICAL: Check if literal is too large for IRIS SQL compilation
            # IRIS cannot compile SQL with string literals >3KB in ORDER BY clauses
            MAX_LITERAL_SIZE_BYTES = 3000
            if len(vector_literal) > MAX_LITERAL_SIZE_BYTES:
                logger.info(
                    f"Vector too large for literal ({len(vector_literal)} bytes > {MAX_LITERAL_SIZE_BYTES} limit). "
                    f"Keeping as parameter but transforming base64 → JSON array for iris.sql.exec() compatibility."
                )
                # Don't substitute into SQL, but DO transform the parameter value
                # iris.sql.exec() accepts JSON array parameters but not base64
                remaining_params[param_index] = vector_literal
                # Don't mark as used - keep it as a parameter
                logger.debug(f"Parameter {param_index} transformed to JSON array (kept as parameter, not substituted)")
                continue

            # Build the replacement - only replace the TO_VECTOR(...) part
            # CONFIRMED: TO_VECTOR accepts FLOAT as unquoted keyword, not string literal
            # Both single param and two params (with FLOAT keyword) work
            new_to_vector = f"TO_VECTOR('{vector_literal}', {data_type})"

            # Find the TO_VECTOR call within the match and replace just that part
            to_vector_start = match.start(3)  # Start of TO_VECTOR group
            to_vector_end = match.end(3)      # End of TO_VECTOR group

            logger.debug(f"Replacing TO_VECTOR at positions {to_vector_start}-{to_vector_end}")

            try:
                optimized_sql = optimized_sql[:to_vector_start] + new_to_vector + optimized_sql[to_vector_end:]
            except Exception as e:
                logger.error(f"SQL substitution failed: {str(e)}, positions={to_vector_start}-{to_vector_end}, sql_length={len(optimized_sql)}")
                continue

            # Mark this parameter as used (we'll remove it later)
            params_used.append(param_index)

            logger.debug(f"Vector parameter substituted: vector_func={vector_func}, param_index={param_index}, literal_length={len(vector_literal)}")

        # Remove used parameters (in reverse order to maintain indices)
        try:
            for idx in sorted(params_used, reverse=True):
                if 0 <= idx < len(remaining_params):
                    remaining_params.pop(idx)
                else:
                    logger.warning(f"Cannot remove param at invalid index: idx={idx}, params_length={len(remaining_params)}")
        except Exception as e:
            logger.error(f"Parameter removal failed: {str(e)}, params_used={params_used}, params_length={len(remaining_params)}")

        sql_preview = optimized_sql[:200] + "..." if len(optimized_sql) > 200 else optimized_sql
        logger.info(f"Vector query optimized: params_substituted={len(params_used)}, params_remaining={len(remaining_params)}, sql_preview={sql_preview}")

        # Record performance metrics
        transformation_time_ms = (time.perf_counter() - start_time) * 1000
        sla_compliant = transformation_time_ms <= self.CONSTITUTIONAL_SLA_MS

        metrics = OptimizationMetrics(
            transformation_time_ms=transformation_time_ms,
            vector_params_found=len(matches),
            vector_params_transformed=len(params_used),
            sql_length_before=sql_length_before,
            sql_length_after=len(optimized_sql),
            params_count_before=params_count_before,
            params_count_after=len(remaining_params),
            constitutional_sla_compliant=sla_compliant
        )

        self._record_metrics(metrics)

        return optimized_sql, remaining_params if remaining_params else None

    def _convert_vector_to_literal(self, vector_param: str) -> Optional[str]:
        """
        Convert vector parameter to IRIS-compatible format.

        CONFIRMED (test_vector_syntax.py): Both formats work with TO_VECTOR:
        - Comma-separated: "1.0,2.0,3.0" with TO_VECTOR('...', FLOAT)
        - JSON array: "[1.0,2.0,3.0]" with TO_VECTOR('[...]', FLOAT)

        CRITICAL: FLOAT must be unquoted keyword, not 'FLOAT' string literal!
        - ✅ TO_VECTOR('0.1,0.2', FLOAT) works
        - ❌ TO_VECTOR('0.1,0.2', 'FLOAT') fails

        We use comma-separated format to minimize SQL length.

        Supports:
        - base64:... format → decode and convert to comma-separated
        - [1.0,2.0,3.0] format → strip brackets to comma-separated
        - comma-delimited: 1.0,2.0,3.0 → pass through

        Args:
            vector_param: Vector parameter (string)

        Returns:
            Comma-separated string like '1.0,2.0,3.0' or None if conversion fails
        """
        # Edge case: Handle None or non-string inputs
        if vector_param is None:
            logger.warning("_convert_vector_to_literal called with None")
            return None

        if not isinstance(vector_param, str):
            logger.warning(f"_convert_vector_to_literal called with non-string: type={type(vector_param).__name__}")
            return None

        # Edge case: Handle empty string
        if not vector_param or len(vector_param) == 0:
            logger.warning("_convert_vector_to_literal called with empty string")
            return None

        # Already in JSON array format
        if vector_param.startswith('[') and vector_param.endswith(']'):
            logger.debug(f"Vector already in JSON array format, length={len(vector_param)}")
            return vector_param

        # Base64 format: "base64:..."
        if vector_param.startswith('base64:'):
            logger.debug(f"Decoding base64 vector, prefix={vector_param[:30]}")
            try:
                # Decode base64 to floats
                b64_data = vector_param[7:]  # Remove "base64:" prefix

                # Edge case: Handle empty base64 data
                if not b64_data:
                    logger.warning("Empty base64 data after prefix removal")
                    return None

                binary_data = base64.b64decode(b64_data)

                # Edge case: Validate binary data length
                if len(binary_data) % 4 != 0:
                    logger.warning(f"Base64 binary data not aligned to 4 bytes: length={len(binary_data)}")
                    return None

                # Convert to float array (assuming float32)
                num_floats = len(binary_data) // 4

                # Edge case: Validate vector has reasonable size
                if num_floats == 0:
                    logger.warning("Base64 decoding resulted in zero floats")
                    return None

                if num_floats > 65536:  # Sanity check: max 64k dimensions
                    logger.warning(f"Suspiciously large vector: {num_floats} dimensions")
                    return None

                floats = struct.unpack(f'{num_floats}f', binary_data)

                # Convert to comma-separated string (NO brackets for IRIS)
                result = ','.join(str(float(v)) for v in floats)
                logger.debug(f"Base64 decoded to {num_floats} floats, CSV length={len(result)}")
                return result

            except base64.binascii.Error as e:
                logger.error(f"Invalid base64 encoding: {str(e)}, prefix: {vector_param[:30]}")
                return None
            except struct.error as e:
                logger.error(f"Binary unpacking failed: {str(e)}, binary_length={len(binary_data) if 'binary_data' in locals() else 'unknown'}")
                return None
            except Exception as e:
                logger.error(f"Failed to decode base64 vector: {str(e)}, prefix: {vector_param[:30]}")
                return None

        # Comma-delimited format: "1.0,2.0,3.0,..."
        if ',' in vector_param and not vector_param.startswith('['):
            logger.debug(f"Vector already in comma-delimited format, length={len(vector_param)}")
            return vector_param  # Already in correct format for IRIS

        # Unknown format
        sample = vector_param[:50] if len(vector_param) > 50 else vector_param
        logger.warning(f"Unknown vector parameter format: {sample}")
        return None

    def _optimize_literal_vectors(self, sql: str, start_time: float) -> Tuple[str, Optional[List]]:
        """
        Optimize queries with literal base64 vectors already embedded in SQL.

        Handles case where psycopg2 does client-side parameter interpolation:
        TO_VECTOR('base64:ABC123...', FLOAT) → TO_VECTOR('[1.0,2.0,...]', FLOAT)

        LIMITATION: IRIS cannot handle very long string literals (>3KB) in SQL.
        Vectors >256 dimensions will be skipped to avoid IRIS compilation errors.

        Args:
            sql: SQL with literal vector strings
            start_time: Performance tracking start time

        Returns:
            Tuple of (optimized_sql, None) - no params since they're in SQL
        """
        # IRIS SQL compilation fails with literals >3KB
        # Skip optimization for large vectors to avoid errors
        MAX_LITERAL_SIZE_BYTES = 3000

        # Pattern: TO_VECTOR('base64:...')  or TO_VECTOR('1.0,2.0,...')
        literal_pattern = re.compile(
            r"TO_VECTOR\s*\(\s*'(base64:[^']+|[0-9.,\s-]+)'(?:\s*,\s*(\w+))?\s*\)",
            re.IGNORECASE
        )

        matches = list(literal_pattern.finditer(sql))

        if not matches:
            logger.debug("No literal base64/vector strings found in SQL")
            return sql, None

        logger.info(f"Found {len(matches)} literal vector strings in SQL (client-side interpolation detected)")

        optimized_sql = sql
        transformations = 0

        # Process in reverse to maintain string positions
        for match in reversed(matches):
            vector_literal = match.group(1)  # 'base64:...' or '1.0,2.0,...'
            data_type = match.group(2) or 'FLOAT'

            # Convert to JSON array format
            converted = self._convert_vector_to_literal(vector_literal)

            if converted is None:
                logger.warning(f"Could not convert literal vector: {vector_literal[:50]}...")
                continue

            # Check if result would be too large for IRIS to handle
            if len(converted) > MAX_LITERAL_SIZE_BYTES:
                logger.warning(
                    f"Skipping literal optimization: vector too large ({len(converted)} bytes > {MAX_LITERAL_SIZE_BYTES} limit). "
                    f"IRIS SQL compilation fails with long literals. Vector will be passed as-is (HNSW not used)."
                )
                continue

            # Replace the entire TO_VECTOR call
            # Use FLOAT as unquoted keyword (not string literal)
            new_call = f"TO_VECTOR('{converted}', {data_type})"
            optimized_sql = optimized_sql[:match.start()] + new_call + optimized_sql[match.end():]
            transformations += 1

            logger.debug(f"Transformed literal vector: {vector_literal[:30]}... → {converted[:30]}...")

        if transformations > 0:
            # Record metrics
            transformation_time_ms = (time.perf_counter() - start_time) * 1000
            metrics = OptimizationMetrics(
                transformation_time_ms=transformation_time_ms,
                vector_params_found=len(matches),
                vector_params_transformed=transformations,
                sql_length_before=len(sql),
                sql_length_after=len(optimized_sql),
                params_count_before=0,
                params_count_after=0,
                constitutional_sla_compliant=(transformation_time_ms <= self.CONSTITUTIONAL_SLA_MS)
            )
            self._record_metrics(metrics)

            logger.info(f"Literal vector optimization complete: {transformations} vectors transformed")

        return optimized_sql, None

    def _record_metrics(self, metrics: OptimizationMetrics):
        """Record optimization metrics and track SLA compliance"""
        self.total_optimizations += 1

        # Track SLA violations
        if not metrics.constitutional_sla_compliant:
            self.sla_violations += 1
            logger.error(
                f"⚠️ CONSTITUTIONAL SLA VIOLATION: Optimization took {metrics.transformation_time_ms:.2f}ms "
                f"(exceeds {self.CONSTITUTIONAL_SLA_MS}ms requirement). "
                f"Violation {self.sla_violations}/{self.total_optimizations}"
            )
        else:
            logger.debug(f"✅ SLA compliant: {metrics.transformation_time_ms:.2f}ms < {self.CONSTITUTIONAL_SLA_MS}ms")

        # Store metrics (keep last 100 for analysis)
        self.metrics_history.append(metrics)
        if len(self.metrics_history) > 100:
            self.metrics_history.pop(0)

        # Log detailed metrics
        logger.info(f"Optimization metrics: {metrics.to_dict()}")

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics for monitoring"""
        if not self.metrics_history:
            return {
                'total_optimizations': 0,
                'sla_violations': 0,
                'sla_compliance_rate': 100.0,
                'constitutional_sla_ms': self.CONSTITUTIONAL_SLA_MS,
                'avg_transformation_time_ms': 0,
                'min_transformation_time_ms': 0,
                'max_transformation_time_ms': 0,
                'recent_sample_size': 0
            }

        recent_times = [m.transformation_time_ms for m in self.metrics_history[-50:]]
        avg_time = sum(recent_times) / len(recent_times)
        max_time = max(recent_times)
        min_time = min(recent_times)

        sla_compliance_rate = ((self.total_optimizations - self.sla_violations) / self.total_optimizations * 100
                              if self.total_optimizations > 0 else 100.0)

        return {
            'total_optimizations': self.total_optimizations,
            'sla_violations': self.sla_violations,
            'sla_compliance_rate': round(sla_compliance_rate, 2),
            'avg_transformation_time_ms': round(avg_time, 2),
            'min_transformation_time_ms': round(min_time, 2),
            'max_transformation_time_ms': round(max_time, 2),
            'constitutional_sla_ms': self.CONSTITUTIONAL_SLA_MS,
            'recent_sample_size': len(recent_times)
        }


# Global instance
_optimizer = VectorQueryOptimizer()


def optimize_vector_query(sql: str, params: Optional[List] = None) -> Tuple[str, Optional[List]]:
    """
    Convenience function to optimize vector queries.

    Args:
        sql: SQL query string
        params: Query parameters

    Returns:
        Tuple of (optimized_sql, remaining_params)
    """
    return _optimizer.optimize_query(sql, params)


def enable_optimization(enabled: bool = True):
    """Enable or disable vector query optimization."""
    _optimizer.enabled = enabled
    logger.info(f"Vector query optimization: enabled={enabled}")


def get_performance_stats() -> Dict[str, Any]:
    """Get performance statistics for constitutional compliance monitoring"""
    return _optimizer.get_performance_stats()


def get_sla_compliance_report() -> str:
    """Generate human-readable SLA compliance report"""
    stats = get_performance_stats()

    report = f"""
Vector Query Optimizer - Constitutional Compliance Report
=========================================================
Total Optimizations: {stats['total_optimizations']}
SLA Violations: {stats['sla_violations']}
SLA Compliance Rate: {stats['sla_compliance_rate']}%
Constitutional SLA: {stats['constitutional_sla_ms']}ms

Performance Metrics (last {stats.get('recent_sample_size', 0)} operations):
  Average: {stats.get('avg_transformation_time_ms', 0)}ms
  Minimum: {stats.get('min_transformation_time_ms', 0)}ms
  Maximum: {stats.get('max_transformation_time_ms', 0)}ms

Status: {'✅ COMPLIANT' if stats['sla_compliance_rate'] >= 95 else '⚠️ NON-COMPLIANT'}
"""
    return report.strip()
