"""
Vector query optimizer for IRIS HNSW compatibility

Transforms parameterized vector queries into literal form to enable HNSW index optimization.
This is a server-side workaround for IRIS's requirement that vectors in ORDER BY clauses
must be literals, not parameters.
"""

import base64
import logging
import re
import struct
import time
from dataclasses import dataclass, field
from typing import Any

# Feature 021: PostgreSQL→IRIS SQL normalization

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

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary for logging"""
        return {
            "transformation_time_ms": round(self.transformation_time_ms, 2),
            "vector_params_found": self.vector_params_found,
            "vector_params_transformed": self.vector_params_transformed,
            "sql_length_before": self.sql_length_before,
            "sql_length_after": self.sql_length_after,
            "params_count_before": self.params_count_before,
            "params_count_after": self.params_count_after,
            "constitutional_sla_compliant": self.constitutional_sla_compliant,
            "sla_threshold_ms": 5.0,
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
        self.metrics_history: list[OptimizationMetrics] = []
        self.sla_violations = 0
        self.total_optimizations = 0

    def optimize_query(self, sql: str, params: list | None = None) -> tuple[str, list | None]:
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

        # STEP 0: Strip trailing semicolons from incoming SQL
        # PostgreSQL clients send queries with semicolons, but IRIS expects them without
        # This is critical since protocol.py bypasses the translator where this was fixed
        # CRITICAL: IRIS rejects semicolons on ALL statements (SELECT, CREATE TABLE, INSERT, etc.)
        sql = sql.rstrip(";").strip()
        logger.debug("Stripped semicolons from SQL")

        # STEP 1: Convert PostgreSQL LIMIT to IRIS TOP
        # IRIS bug: ORDER BY aliases don't work with LIMIT, only with TOP
        sql = self._convert_limit_to_top(sql)

        # STEP 2: Rewrite pgvector operators to IRIS vector functions
        # This must happen BEFORE other optimizations
        sql = self._rewrite_pgvector_operators(sql)

        # Handle INSERT/UPDATE statements with vectors (TO_VECTOR or raw '[...]' / '{...}' literals)
        sql_upper = sql.upper()
        # Check for vector patterns: explicit TO_VECTOR() OR raw pgvector-style '[...]' or '{...}'
        has_vector_pattern = "TO_VECTOR" in sql_upper or re.search(
            r"'[\[\{][\d.,\s\-eE]+[\]\}]'", sql
        )
        if ("INSERT" in sql_upper or "UPDATE" in sql_upper) and has_vector_pattern:
            # For INSERT/UPDATE, ensure raw vector literals are wrapped with TO_VECTOR()
            optimized_sql = self._optimize_insert_vectors(sql, start_time)

            # Fix ORDER BY aliases if present
            optimized_sql = self._fix_order_by_aliases(optimized_sql)

            return optimized_sql, params

        # Check if this is a vector similarity query with ORDER BY
        if "ORDER BY" not in sql_upper or "TO_VECTOR" not in sql_upper:
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
                r"(VECTOR_(?:COSINE|DOT_PRODUCT|L2))\s*\(\s*"
                r"((?:\"[^\"]+\"|[\w\.]+))\s*,\s*"
                r"(TO_VECTOR\s*\(\s*['\"]?([?%]s?|\$\d+)['\"]?\s*(?:,\s*(\w+))?\s*\))",
                re.IGNORECASE,
            )
        except re.error as e:
            logger.error(f"Regex compilation failed: {str(e)}")
            return sql, params

        try:
            matches = list(order_by_pattern.finditer(sql))
            if not matches:
                return sql, params
        except Exception as e:
            logger.error(f"Regex matching failed: {str(e)}, sql_length={len(sql)}")
            return sql, params

        logger.info(
            f"Vector query optimization triggered: {len(matches)} pattern matches, {len(params) if params else 0} params"
        )

        # Process matches in reverse order to maintain string positions
        optimized_sql = sql
        params_used = []
        remaining_params = list(params) if params else []

        logger.debug(
            f"Starting vector transformation: {len(matches)} matches, {len(remaining_params)} total params"
        )

        for match in reversed(matches):
            vector_func = match.group(1)  # VECTOR_COSINE, etc
            column_name = match.group(2)  # column name
            match.group(3)  # Full TO_VECTOR(...) call
            match.group(4)  # ? or %s
            data_type = match.group(5) or "FLOAT"  # FLOAT, INT, etc

            # Find which parameter this corresponds to
            # Count how many parameters appear before this position
            param_index = len(re.findall(r"\?|%s|\$\d+", sql[: match.start()]))

            logger.debug(
                f"Processing match: func={vector_func}, column={column_name}, param_index={param_index}"
            )

            if param_index >= len(remaining_params):
                logger.warning(
                    f"Parameter index out of range: index={param_index}, total_params={len(remaining_params)}"
                )
                continue

            # Get the vector parameter
            vector_param = remaining_params[param_index]
            logger.debug(
                f"Vector param at index {param_index}: type={type(vector_param).__name__}, length={len(str(vector_param)) if vector_param else 0}"
            )

            # Convert to JSON array format
            vector_literal = self._convert_vector_to_literal(vector_param)

            if vector_literal is None:
                logger.warning(
                    f"Could not convert vector parameter to literal: param_index={param_index}, param_type={type(vector_param).__name__}"
                )
                continue

            logger.debug(
                f"Converted vector to literal: length={len(vector_literal)}, preview={vector_literal[:50]}..."
            )

            # CRITICAL: Check if literal is too large for IRIS SQL compilation
            # IRIS cannot compile SQL with string literals >3KB in ORDER BY clauses
            # However, for HNSW optimization to trigger, it MUST be a literal.
            # We use a 1MB limit which covers most vectors.
            MAX_LITERAL_SIZE_BYTES = 1048576
            if len(vector_literal) > MAX_LITERAL_SIZE_BYTES:
                logger.info(
                    f"Vector too large for literal ({len(vector_literal)} bytes > {MAX_LITERAL_SIZE_BYTES} limit). "
                    f"Keeping as parameter but transforming base64 → JSON array for iris.sql.exec() compatibility."
                )
                # Don't substitute into SQL, but DO transform the parameter value
                # iris.sql.exec() accepts JSON array parameters but not base64
                remaining_params[param_index] = vector_literal
                # Don't mark as used - keep it as a parameter
                logger.debug(
                    f"Parameter {param_index} transformed to JSON array (kept as parameter, not substituted)"
                )
                continue

            # Build the replacement - only replace the TO_VECTOR(...) part
            # CONFIRMED: TO_VECTOR accepts FLOAT as unquoted keyword, not string literal
            # Both single param and two params (with FLOAT keyword) work
            new_to_vector = f"TO_VECTOR('{vector_literal}', {data_type})"

            # Find the TO_VECTOR call within the match and replace just that part
            to_vector_start = match.start(3)  # Start of TO_VECTOR group
            to_vector_end = match.end(3)  # End of TO_VECTOR group

            logger.debug(f"Replacing TO_VECTOR at positions {to_vector_start}-{to_vector_end}")

            try:
                optimized_sql = (
                    optimized_sql[:to_vector_start] + new_to_vector + optimized_sql[to_vector_end:]
                )
            except Exception as e:
                logger.error(
                    f"SQL substitution failed: {str(e)}, positions={to_vector_start}-{to_vector_end}, sql_length={len(optimized_sql)}"
                )
                continue

            # Mark this parameter as used (we'll remove it later)
            params_used.append(param_index)

            logger.debug(
                f"Vector parameter substituted: vector_func={vector_func}, param_index={param_index}, literal_length={len(vector_literal)}"
            )

        # Remove used parameters (in reverse order to maintain indices)
        try:
            for idx in sorted(params_used, reverse=True):
                if 0 <= idx < len(remaining_params):
                    remaining_params.pop(idx)
                else:
                    logger.warning(
                        f"Cannot remove param at invalid index: idx={idx}, params_length={len(remaining_params)}"
                    )
        except Exception as e:
            logger.error(
                f"Parameter removal failed: {str(e)}, params_used={params_used}, params_length={len(remaining_params)}"
            )

        sql_preview = optimized_sql[:200] + "..." if len(optimized_sql) > 200 else optimized_sql
        logger.info(
            f"Vector query optimized: params_substituted={len(params_used)}, params_remaining={len(remaining_params)}, sql_preview={sql_preview}"
        )

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
            constitutional_sla_compliant=sla_compliant,
        )

        self._record_metrics(metrics)

        # CRITICAL: Fix ORDER BY aliases AFTER all other optimizations
        # IRIS doesn't support ORDER BY on SELECT clause aliases
        optimized_sql = self._fix_order_by_aliases(optimized_sql)

        return optimized_sql, remaining_params if remaining_params else None

    def _rewrite_pgvector_operators(self, sql: str) -> str:
        """
        Rewrite pgvector operators to IRIS vector functions.

        Transforms:
        - column <=> '[1,2,3]' → VECTOR_COSINE(column, TO_VECTOR('[1,2,3]', FLOAT))
        - column <#> '[1,2,3]' → (-VECTOR_DOT_PRODUCT(column, TO_VECTOR('[1,2,3]', FLOAT)))

        REJECTS (Constitutional requirement):
        - column <-> '[1,2,3]' → NotImplementedError (L2 distance not supported by IRIS)

        Args:
            sql: SQL with pgvector operators

        Returns:
            SQL with IRIS vector functions

        Raises:
            NotImplementedError: If L2 distance operator (<->) is found in query
        """
        if not sql:
            return sql

        # CRITICAL FIX: Skip vector optimization for DDL statements (CREATE/DROP/ALTER TABLE)
        # DDL doesn't contain vector operators, and multi-statement SQL breaks the regex parsing
        sql_upper = sql.upper()
        ddl_keywords = ["CREATE TABLE", "DROP TABLE", "ALTER TABLE", "CREATE INDEX", "DROP INDEX"]
        if any(keyword in sql_upper for keyword in ddl_keywords):
            return sql

        # Rewrite operators in the entire SQL statement
        # This handles SELECT, ORDER BY, and INSERT/UPDATE clauses consistently
        result = self._rewrite_operators_in_text(sql)
        return result

    def _optimize_vector_literal(self, literal: str) -> str:
        """
        Optimize vector literal for IRIS compatibility.

        IRIS requires vector literals in TO_VECTOR to have brackets.

        Args:
            literal: Vector literal like '[1,2,3]' or '1,2,3'

        Returns:
            Optimized literal WITH brackets
        """
        # Remove quotes if present
        clean = literal.strip("'\"")
        # Ensure brackets are present
        if not (clean.startswith("[") and clean.endswith("]")):
            clean = f"[{clean}]"
        return clean

    def _rewrite_operators_in_text(self, sql: str) -> str:
        """Helper to rewrite operators in a given text"""
        # Improved operand pattern to handle more cases robustly (placeholders, literals, functions)
        operand = r'(?:"[^"]+(?:"\s*\.\s*"[^"]+)*"|[\w\.]+(?:\([^)]*\))?|\'[^\']*\'|\[[^\]]+\]|\?|%s|\$\d+)(?:::\w+)?'

        # <=> operator (cosine distance) -> 1 - VECTOR_COSINE
        if "<=>" in sql:
            pattern = rf"({operand})\s*<=>\s*({operand})"

            def replace_cosine_distance(match):
                left, right = match.groups()

                # Check if either side is a parameter placeholder
                left_is_param = left in ("?", "%s") or left.startswith("$")
                right_is_param = right in ("?", "%s") or right.startswith("$")

                # If either side already has TO_VECTOR, use as-is
                if "TO_VECTOR" in left.upper() or "TO_VECTOR" in right.upper():
                    return f"(1 - VECTOR_COSINE({left}, {right}))"

                # Handle placeholders
                if left_is_param and right_is_param:
                    return f"(1 - VECTOR_COSINE(TO_VECTOR({left}, DOUBLE), TO_VECTOR({right}, DOUBLE)))"
                if left_is_param:
                    opt_right = self._optimize_vector_literal(right)
                    return f"(1 - VECTOR_COSINE(TO_VECTOR({left}, DOUBLE), TO_VECTOR('{opt_right}', DOUBLE)))"
                if right_is_param:
                    return f"(1 - VECTOR_COSINE({left}, TO_VECTOR({right}, DOUBLE)))"

                # Handle literals on both sides
                if left.startswith("'") or left.startswith("["):
                    opt_left = self._optimize_vector_literal(left)
                    opt_right = self._optimize_vector_literal(right)
                    return f"(1 - VECTOR_COSINE(TO_VECTOR('{opt_left}', DOUBLE), TO_VECTOR('{opt_right}', DOUBLE)))"

                # Left is likely a column name
                opt_right = self._optimize_vector_literal(right)
                return f"(1 - VECTOR_COSINE({left}, TO_VECTOR('{opt_right}', DOUBLE)))"

            sql = re.sub(pattern, replace_cosine_distance, sql)

        # <-> operator (L2 distance) - NOT SUPPORTED BY IRIS
        # Constitutional requirement: REJECT with NOT IMPLEMENTED error
        if "<->" in sql:
            error_msg = (
                "L2 distance operator (<->) is not supported by IRIS. "
                "IRIS only supports VECTOR_COSINE (use <=> operator) and VECTOR_DOT_PRODUCT (use <#> operator). "
                "Please rewrite your query to use one of these supported distance functions."
            )
            logger.error(f"❌ L2 distance operator rejected: {error_msg}")
            raise NotImplementedError(error_msg)

        # <#> operator (negative inner product) -> -VECTOR_DOT_PRODUCT
        if "<#>" in sql:
            pattern = rf"({operand})\s*<#>\s*({operand})"

            def replace_inner_product(match):
                left, right = match.groups()

                # Check if either side is a parameter placeholder
                left_is_param = left in ("?", "%s") or left.startswith("$")
                right_is_param = right in ("?", "%s") or right.startswith("$")

                if "TO_VECTOR" in left.upper() or "TO_VECTOR" in right.upper():
                    return f"(-VECTOR_DOT_PRODUCT({left}, {right}))"

                if left_is_param and right_is_param:
                    return f"(-VECTOR_DOT_PRODUCT(TO_VECTOR({left}, DOUBLE), TO_VECTOR({right}, DOUBLE)))"
                if left_is_param:
                    opt_right = self._optimize_vector_literal(right)
                    return f"(-VECTOR_DOT_PRODUCT(TO_VECTOR({left}, DOUBLE), TO_VECTOR('{opt_right}', DOUBLE)))"
                if right_is_param:
                    return f"(-VECTOR_DOT_PRODUCT({left}, TO_VECTOR({right}, DOUBLE)))"

                if left.startswith("'") or left.startswith("["):
                    opt_left = self._optimize_vector_literal(left)
                    opt_right = self._optimize_vector_literal(right)
                    return f"(-VECTOR_DOT_PRODUCT(TO_VECTOR('{opt_left}', DOUBLE), TO_VECTOR('{opt_right}', DOUBLE)))"

                opt_right = self._optimize_vector_literal(right)
                return f"(-VECTOR_DOT_PRODUCT({left}, TO_VECTOR('{opt_right}', DOUBLE)))"

            sql = re.sub(pattern, replace_inner_product, sql)

        return sql

    def _convert_limit_to_top(self, sql: str) -> str:
        """
        Convert PostgreSQL LIMIT syntax to IRIS TOP syntax.

        IRIS Bug: ORDER BY with aliases does NOT work with LIMIT, only with TOP.

        Examples:
        - ❌ SELECT ... AS distance ORDER BY distance LIMIT 5  (Field 'DISTANCE' not found)
        - ✅ SELECT TOP 5 ... AS distance ORDER BY distance    (Works correctly)

        Transforms:
            SELECT ... LIMIT N              → SELECT TOP N ...
            SELECT ... LIMIT N OFFSET M     → SELECT TOP N ... (with warning - IRIS doesn't support OFFSET with TOP)

        Args:
            sql: SQL with PostgreSQL LIMIT syntax

        Returns:
            SQL with IRIS TOP syntax
        """
        # Pattern: LIMIT <number> [OFFSET <number>]
        # Must match at end of query or before semicolon
        limit_pattern = re.compile(r"\s+LIMIT\s+(\d+)(?:\s+OFFSET\s+(\d+))?\s*(;?)$", re.IGNORECASE)

        match = limit_pattern.search(sql)

        if not match:
            return sql

        limit_value = match.group(1)
        offset_value = match.group(2)
        semicolon = match.group(3)

        if offset_value:
            logger.warning(
                f"OFFSET {offset_value} ignored - IRIS TOP does not support OFFSET. "
                f"Results will start from first row, not row {offset_value}."
            )

        # Remove the LIMIT clause from the end
        sql_without_limit = sql[: match.start()] + semicolon

        # Add TOP after SELECT
        # Pattern: SELECT [DISTINCT] ... → SELECT [DISTINCT] TOP N ...
        select_pattern = re.compile(r"(SELECT\s+(?:DISTINCT\s+)?)", re.IGNORECASE)

        def add_top(m):
            return f"{m.group(1)}TOP {limit_value} "

        result = select_pattern.sub(add_top, sql_without_limit, count=1)

        logger.info(f"Converted LIMIT {limit_value} to TOP {limit_value}")

        return result

    def _fix_order_by_aliases(self, sql: str) -> str:
        """
        IRIS requires aliases in ORDER BY when combined with LIMIT/TOP.
        This function is kept as a pass-through to avoid breaking existing logic.
        """
        return sql

    def bind_vector_parameter(self, vector: list[float], data_type: str = "DECIMAL") -> str:
        """
        Convert Python list to IRIS TO_VECTOR format for DBAPI backend.

        This method supports the DBAPI backend by converting Python lists
        directly to IRIS TO_VECTOR() syntax suitable for parameter binding.

        Args:
            vector: List of floats representing vector dimensions
            data_type: IRIS vector type ('DECIMAL', 'FLOAT', or 'INT')

        Returns:
            TO_VECTOR SQL fragment like "TO_VECTOR('[0.1,0.2,0.3]', DECIMAL)"

        Raises:
            ValueError: If vector is empty or exceeds 2048 dimensions
            TypeError: If vector contains non-numeric values

        Example:
            >>> optimizer.bind_vector_parameter([0.1, 0.2, 0.3])
            "TO_VECTOR('[0.1,0.2,0.3]', DECIMAL)"
        """
        # Validate input
        if not vector:
            raise ValueError("Vector cannot be empty")

        if len(vector) > 2048:
            raise ValueError(f"Vector dimensions ({len(vector)}) exceed maximum (2048)")

        # Validate all elements are numeric
        try:
            # Convert to JSON array format
            vector_json = "[" + ",".join(str(float(v)) for v in vector) + "]"
        except (TypeError, ValueError) as e:
            raise TypeError(f"Vector contains non-numeric values: {e}") from e

        # Generate TO_VECTOR syntax with unquoted keyword
        # CRITICAL: data_type must be unquoted (DECIMAL not 'DECIMAL')
        return f"TO_VECTOR('{vector_json}', {data_type.upper()})"

    def _convert_vector_to_literal(self, vector_param: str) -> str | None:
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
            logger.warning(
                f"_convert_vector_to_literal called with non-string: type={type(vector_param).__name__}"
            )
            return None

        # Edge case: Handle empty string
        if not vector_param or len(vector_param) == 0:
            logger.warning("_convert_vector_to_literal called with empty string")
            return None

        # Already in JSON array format
        if vector_param.startswith("[") and vector_param.endswith("]"):
            logger.debug(f"Vector already in JSON array format, length={len(vector_param)}")
            return vector_param

        # Base64 format: "base64:..."
        if vector_param.startswith("base64:"):
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
                    logger.warning(
                        f"Base64 binary data not aligned to 4 bytes: length={len(binary_data)}"
                    )
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

                floats = struct.unpack(f"{num_floats}f", binary_data)

                # Convert to JSON array string (IRIS requires brackets for TO_VECTOR)
                result = "[" + ",".join(str(float(v)) for v in floats) + "]"
                logger.debug(f"Base64 decoded to {num_floats} floats, JSON length={len(result)}")
                return result

            except Exception as e:
                logger.error(
                    f"Failed to decode base64 vector: {str(e)}, prefix: {vector_param[:30]}"
                )
                return None

        # Comma-delimited format: "1.0,2.0,3.0,..."
        if "," in vector_param and not vector_param.startswith("["):
            logger.debug("Vector in comma-delimited format, wrapping in brackets")
            return f"[{vector_param}]"

        # Already in bracketed format
        if vector_param.startswith("[") and vector_param.endswith("]"):
            return vector_param

        # Unknown format
        sample = vector_param[:50] if len(vector_param) > 50 else vector_param
        logger.warning(f"Unknown vector parameter format: {sample}")
        return None

    def _optimize_insert_vectors(self, sql: str, start_time: float) -> str:
        """
        Optimize INSERT/UPDATE statements for IRIS vector compatibility.
        """
        optimized_sql = sql

        def replace_literal(m):
            if m.group(1):
                return m.group(0)

            literal_content = m.group(2)
            if literal_content.startswith("{") and literal_content.endswith("}"):
                literal_content = "[" + literal_content[1:-1] + "]"

            return f"TO_VECTOR('{literal_content}', DOUBLE)"

        sql_with_v = re.sub(
            r"(?i)(TO_VECTOR\s*\(\s*)?'([\[\{][^']+?[\]\}])'", replace_literal, optimized_sql
        )

        if sql_with_v != optimized_sql:
            optimized_sql = sql_with_v
            logger.info("Wrapped raw vector literal in TO_VECTOR")

        # Record metrics
        transformation_time_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"INSERT/UPDATE optimization complete: time={transformation_time_ms:.2f}ms")

        return optimized_sql

    def _optimize_literal_vectors(self, sql: str, start_time: float) -> tuple[str, list | None]:
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

        # Pattern: TO_VECTOR('base64:...')  or TO_VECTOR('[1.0,2.0,...]')  or TO_VECTOR('1.0,2.0,...')
        literal_pattern = re.compile(
            r"TO_VECTOR\s*\(\s*'(base64:[^']+|\[[0-9.,\s-]+\]|[0-9.,\s-]+)'(?:\s*,\s*(\w+))?\s*\)",
            re.IGNORECASE,
        )

        matches = list(literal_pattern.finditer(sql))

        if not matches:
            logger.debug("No literal base64/vector strings found in SQL")
            return sql, None

        logger.info(
            f"Found {len(matches)} literal vector strings in SQL (client-side interpolation detected)"
        )

        optimized_sql = sql
        transformations = 0

        # Process in reverse to maintain string positions
        for match in reversed(matches):
            vector_literal = match.group(1)  # 'base64:...' or '1.0,2.0,...'
            data_type = match.group(2) or "FLOAT"

            # Convert to JSON array format
            converted = self._convert_vector_to_literal(vector_literal)

            if converted is None:
                logger.warning(f"Could not convert literal vector: {vector_literal[:50]}...")
                continue

            # Check if result would be too large for IRIS TO_VECTOR() to handle
            if len(converted) > MAX_LITERAL_SIZE_BYTES:
                logger.info(
                    f"Large vector detected ({len(converted)} bytes > {MAX_LITERAL_SIZE_BYTES} limit). "
                    f"IRIS may reject this literal."
                )
                # DO NOT strip brackets, as IRIS now requires them for TO_VECTOR
                # Even if it exceeds 3KB, we must keep brackets if we use TO_VECTOR
                new_call = f"TO_VECTOR('{converted}', {data_type})"
                optimized_sql = (
                    optimized_sql[: match.start()] + new_call + optimized_sql[match.end() :]
                )
                transformations += 1
                continue

            # Replace the entire TO_VECTOR call
            # Use FLOAT as unquoted keyword (not string literal)
            new_call = f"TO_VECTOR('{converted}', {data_type})"
            optimized_sql = optimized_sql[: match.start()] + new_call + optimized_sql[match.end() :]
            transformations += 1

            logger.debug(
                f"Transformed literal vector: {vector_literal[:30]}... → {converted[:30]}..."
            )

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
                constitutional_sla_compliant=(transformation_time_ms <= self.CONSTITUTIONAL_SLA_MS),
            )
            self._record_metrics(metrics)

            logger.info(
                f"Literal vector optimization complete: {transformations} vectors transformed"
            )

        # CRITICAL: Fix ORDER BY aliases AFTER all other optimizations
        # IRIS doesn't support ORDER BY on SELECT clause aliases
        optimized_sql = self._fix_order_by_aliases(optimized_sql)

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
            logger.debug(
                f"✅ SLA compliant: {metrics.transformation_time_ms:.2f}ms < {self.CONSTITUTIONAL_SLA_MS}ms"
            )

        # Store metrics (keep last 100 for analysis)
        self.metrics_history.append(metrics)
        if len(self.metrics_history) > 100:
            self.metrics_history.pop(0)

        # Log detailed metrics
        logger.info(f"Optimization metrics: {metrics.to_dict()}")

    def get_performance_stats(self) -> dict[str, Any]:
        """Get performance statistics for monitoring"""
        if not self.metrics_history:
            return {
                "total_optimizations": 0,
                "sla_violations": 0,
                "sla_compliance_rate": 100.0,
                "constitutional_sla_ms": self.CONSTITUTIONAL_SLA_MS,
                "avg_transformation_time_ms": 0,
                "min_transformation_time_ms": 0,
                "max_transformation_time_ms": 0,
                "recent_sample_size": 0,
            }

        recent_times = [m.transformation_time_ms for m in self.metrics_history[-50:]]
        avg_time = sum(recent_times) / len(recent_times)
        max_time = max(recent_times)
        min_time = min(recent_times)

        sla_compliance_rate = (
            (self.total_optimizations - self.sla_violations) / self.total_optimizations * 100
            if self.total_optimizations > 0
            else 100.0
        )

        return {
            "total_optimizations": self.total_optimizations,
            "sla_violations": self.sla_violations,
            "sla_compliance_rate": round(sla_compliance_rate, 2),
            "avg_transformation_time_ms": round(avg_time, 2),
            "min_transformation_time_ms": round(min_time, 2),
            "max_transformation_time_ms": round(max_time, 2),
            "constitutional_sla_ms": self.CONSTITUTIONAL_SLA_MS,
            "recent_sample_size": len(recent_times),
        }


# Global instance
_optimizer = VectorQueryOptimizer()


def optimize_vector_query(sql: str, params: list | None = None) -> tuple[str, list | None]:
    """
    Convenience function to optimize vector queries.

    Feature 022 Note: PostgreSQL transaction verb translation (BEGIN → START TRANSACTION)
    is applied by iris_executor.py BEFORE Feature 021 normalization, per FR-010.

    Feature 021 Note: SQL normalization is applied by iris_executor.py BEFORE calling
    this function. We should NOT normalize again here to avoid double-wrapping DATE literals
    and other normalization issues (FR-012 compliance is achieved at executor layer).

    Pipeline order in iris_executor.py:
    1. Transaction translation (Feature 022) - BEGIN → START TRANSACTION
    2. SQL normalization (Feature 021) - Identifiers/DATE literals
    3. Vector optimization (this function) - Parameter optimization

    Args:
        sql: SQL query string (already transaction-translated and normalized by executor)
        params: Query parameters

    Returns:
        Tuple of (optimized_sql, remaining_params)
    """
    # Feature 022: Transaction translation already applied by iris_executor
    # Feature 021: SQL normalization already applied by iris_executor
    # Do NOT translate or normalize again - just apply vector optimization
    return _optimizer.optimize_query(sql, params)


def enable_optimization(enabled: bool = True):
    """Enable or disable vector query optimization."""
    _optimizer.enabled = enabled
    logger.info(f"Vector query optimization: enabled={enabled}")


def get_performance_stats() -> dict[str, Any]:
    """Get performance statistics for constitutional compliance monitoring"""
    return _optimizer.get_performance_stats()


def get_sla_compliance_report() -> str:
    """Generate human-readable SLA compliance report"""
    stats = get_performance_stats()

    report = f"""
Vector Query Optimizer - Constitutional Compliance Report
=========================================================
Total Optimizations: {stats["total_optimizations"]}
SLA Violations: {stats["sla_violations"]}
SLA Compliance Rate: {stats["sla_compliance_rate"]}%
Constitutional SLA: {stats["constitutional_sla_ms"]}ms

Performance Metrics (last {stats.get("recent_sample_size", 0)} operations):
  Average: {stats.get("avg_transformation_time_ms", 0)}ms
  Minimum: {stats.get("min_transformation_time_ms", 0)}ms
  Maximum: {stats.get("max_transformation_time_ms", 0)}ms

Status: {"✅ COMPLIANT" if stats["sla_compliance_rate"] >= 95 else "⚠️ NON-COMPLIANT"}
"""
    return report.strip()
