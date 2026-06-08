"""
Vector query optimizer for IRIS HNSW compatibility

Transforms parameterized vector queries into literal form to enable HNSW index optimization.
This is a server-side workaround for IRIS's requirement that vectors in ORDER BY clauses
must be literals, not parameters.
"""

import base64
import re
import struct
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Maximum literal size IRIS can compile in ORDER BY clauses
_MAX_ORDER_BY_LITERAL_BYTES = 1048576  # 1MB
# Maximum literal size IRIS can compile in TO_VECTOR() generally
_MAX_TO_VECTOR_LITERAL_BYTES = 3000

# DDL statements that should skip vector optimization
_DDL_KEYWORDS = ("CREATE TABLE", "DROP TABLE", "ALTER TABLE", "CREATE INDEX", "DROP INDEX")


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
    """Optimizes vector queries for IRIS HNSW performance.

    Converts parameterized TO_VECTOR() calls in ORDER BY clauses to literal form.
    """

    CONSTITUTIONAL_SLA_MS = 5.0

    def __init__(self):
        self.enabled = True
        self.metrics_history: list[OptimizationMetrics] = []
        self.sla_violations = 0
        self.total_optimizations = 0

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def optimize_query(self, sql: str, params: list | None = None) -> tuple[str, list | None]:
        """Transform parameterized vector queries into literal form for HNSW optimization.

        Args:
            sql: SQL query string
            params: Query parameters

        Returns:
            Tuple of (optimized_sql, remaining_params)
        """
        start_time = time.perf_counter()
        sql_length_before = len(sql) if sql else 0
        params_count_before = len(params) if params else 0

        sql = self._validate_and_prepare(sql, params)
        if sql is None:
            return "", params

        if not self.enabled:
            return sql, params

        # Strip trailing semicolons (IRIS rejects them on all statements)
        sql = sql.rstrip(";").strip()

        # Convert LIMIT to TOP (IRIS bug: ORDER BY aliases don't work with LIMIT)
        sql = self._convert_limit_to_top(sql)

        # Rewrite pgvector operators to IRIS vector functions
        sql = self._rewrite_pgvector_operators(sql)

        if "->" in sql:
            sql = self._translate_nested_json_operators(sql)

        sql_upper = sql.upper()

        # Handle INSERT/UPDATE with vector patterns
        if self._is_vector_dml(sql, sql_upper):
            optimized = self._optimize_insert_vectors(sql, start_time)
            return self._fix_order_by_aliases(optimized), params

        # Only optimize ORDER BY + TO_VECTOR queries from here
        if "ORDER BY" not in sql_upper or "TO_VECTOR" not in sql_upper:
            return sql, params

        # Literal vectors (no params) vs parameterized vectors
        if not params:
            return self._optimize_literal_vectors(sql, start_time)

        return self._optimize_parameterized_vectors(
            sql,
            params,
            start_time,
            sql_length_before,
            params_count_before,
        )

    def _validate_and_prepare(self, sql: str | None, params: list | None) -> str | None:
        """Validate SQL input, returning None for invalid inputs."""
        if sql is None:
            logger.warning("optimize_query called with None SQL")
            return None
        if not isinstance(sql, str):
            logger.error(f"optimize_query called with non-string SQL: type={type(sql).__name__}")
            return str(sql)
        return sql

    @staticmethod
    def _is_vector_dml(sql: str, sql_upper: str) -> bool:
        """Check if SQL is an INSERT/UPDATE with vector patterns."""
        if "INSERT" not in sql_upper and "UPDATE" not in sql_upper:
            return False
        return "TO_VECTOR" in sql_upper or bool(re.search(r"'[\[\{][\d.,\s\-eE]+[\]\}]'", sql))

    # ------------------------------------------------------------------
    # Parameterized vector optimization
    # ------------------------------------------------------------------

    def _optimize_parameterized_vectors(
        self,
        sql: str,
        params: list,
        start_time: float,
        sql_length_before: int,
        params_count_before: int,
    ) -> tuple[str, list | None]:
        """Optimize queries with parameterized TO_VECTOR calls in ORDER BY."""
        order_by_pattern = re.compile(
            r"(VECTOR_(?:COSINE|DOT_PRODUCT|L2))\s*\(\s*"
            r"((?:\"[^\"]+\"|[\w\.]+))\s*,\s*"
            r"(TO_VECTOR\s*\(\s*['\"]?([?%]s?|\$\d+)['\"]?\s*(?:,\s*(\w+))?\s*\))",
            re.IGNORECASE,
        )

        try:
            matches = list(order_by_pattern.finditer(sql))
        except Exception as e:
            logger.error(f"Regex matching failed: {e}, sql_length={len(sql)}")
            return sql, params

        if not matches:
            return sql, params

        logger.info(
            f"Vector query optimization triggered: {len(matches)} pattern matches, "
            f"{len(params)} params"
        )

        optimized_sql, params_used, remaining_params = self._substitute_vector_params(
            sql,
            params,
            matches,
        )

        # Remove used parameters (reverse order to maintain indices)
        for idx in sorted(params_used, reverse=True):
            if 0 <= idx < len(remaining_params):
                remaining_params.pop(idx)

        # Record metrics
        elapsed = (time.perf_counter() - start_time) * 1000
        self._record_metrics(
            OptimizationMetrics(
                transformation_time_ms=elapsed,
                vector_params_found=len(matches),
                vector_params_transformed=len(params_used),
                sql_length_before=sql_length_before,
                sql_length_after=len(optimized_sql),
                params_count_before=params_count_before,
                params_count_after=len(remaining_params),
                constitutional_sla_compliant=(elapsed <= self.CONSTITUTIONAL_SLA_MS),
            )
        )

        optimized_sql = self._fix_order_by_aliases(optimized_sql)
        return optimized_sql, remaining_params if remaining_params else None

    def _substitute_vector_params(
        self,
        sql: str,
        params: list,
        matches: list[re.Match],
    ) -> tuple[str, list[int], list]:
        """Substitute vector parameters with literals in SQL.

        Returns:
            (optimized_sql, params_used_indices, remaining_params)
        """
        optimized_sql = sql
        params_used: list[int] = []
        remaining_params = list(params)

        for match in reversed(matches):
            data_type = match.group(5) or "FLOAT"
            param_index = len(re.findall(r"\?|%s|\$\d+", sql[: match.start()]))

            if param_index >= len(remaining_params):
                logger.warning(
                    f"Parameter index out of range: index={param_index}, "
                    f"total_params={len(remaining_params)}"
                )
                continue

            vector_param = remaining_params[param_index]
            vector_literal = self._convert_vector_to_literal(vector_param)

            if vector_literal is None:
                logger.warning(
                    f"Could not convert vector parameter: param_index={param_index}, "
                    f"param_type={type(vector_param).__name__}"
                )
                continue

            # Check if literal is too large for IRIS SQL compilation
            if len(vector_literal) > _MAX_ORDER_BY_LITERAL_BYTES:
                logger.info(
                    f"Vector too large for literal ({len(vector_literal)} bytes). "
                    f"Keeping as parameter but transforming base64 → JSON array."
                )
                remaining_params[param_index] = vector_literal
                continue

            # Replace TO_VECTOR(...) with literal form
            new_to_vector = f"TO_VECTOR('{vector_literal}', {data_type})"
            optimized_sql = (
                optimized_sql[: match.start(3)] + new_to_vector + optimized_sql[match.end(3) :]
            )
            params_used.append(param_index)

        return optimized_sql, params_used, remaining_params

    # ------------------------------------------------------------------
    # pgvector operator rewriting
    # ------------------------------------------------------------------

    def _rewrite_pgvector_operators(self, sql: str) -> str:
        """Rewrite pgvector operators (<=> / <#>) to IRIS vector functions.

        For DDL containing HNSW index syntax, translates to IRIS-native form instead
        of rewriting operators.

        Raises:
            NotImplementedError: If L2 distance operator (<->) is found.
        """
        if not sql:
            return sql

        sql_upper = sql.upper()
        if any(kw in sql_upper for kw in _DDL_KEYWORDS):
            # Translate pgvector HNSW DDL (CREATE INDEX … USING hnsw) to IRIS syntax
            translated = self._translate_hnsw_index_ddl(sql)
            if translated != sql:
                logger.info("HNSW DDL translated", translated=translated[:200])
            return translated

        return self._rewrite_operators_in_text(sql)

    def _rewrite_operators_in_text(self, sql: str) -> str:
        """Rewrite pgvector distance operators in SQL text."""
        operand = (
            r'(?:"[^"]+(?:"\s*\.\s*"[^"]+)*"|[\w\.]+(?:\([^)]*\))?'
            r"|'[^']*'|\[[^\]]+\]|\?|%s|\$\d+)(?:::\w+)?"
        )

        if "<=>" in sql:
            pattern = rf"({operand})\s*<=>\s*({operand})"
            sql = re.sub(
                pattern,
                lambda m: self._build_vector_call(
                    "VECTOR_COSINE", m.group(1), m.group(2), negate=False, wrap_prefix="1 - "
                ),
                sql,
            )

        if "<->" in sql:
            raise NotImplementedError(
                "L2 distance operator (<->) is not supported by IRIS. "
                "IRIS only supports VECTOR_COSINE (use <=> operator) and "
                "VECTOR_DOT_PRODUCT (use <#> operator). "
                "Please rewrite your query to use one of these supported distance functions."
            )

        if "<#>" in sql:
            pattern = rf"({operand})\s*<#>\s*({operand})"
            sql = re.sub(
                pattern,
                lambda m: self._build_vector_call(
                    "VECTOR_DOT_PRODUCT", m.group(1), m.group(2), negate=True
                ),
                sql,
            )

        return sql

    def _build_vector_call(
        self,
        func: str,
        left: str,
        right: str,
        negate: bool = False,
        wrap_prefix: str = "",
    ) -> str:
        """Build an IRIS vector function call from two operands.

        Handles parameter placeholders, literals, and column names.
        """
        left_is_param = left in ("?", "%s") or left.startswith("$")
        right_is_param = right in ("?", "%s") or right.startswith("$")

        # Already has TO_VECTOR
        if "TO_VECTOR" in left.upper() or "TO_VECTOR" in right.upper():
            inner = f"{func}({left}, {right})"
            return f"(-{inner})" if negate else f"({wrap_prefix}{inner})"

        # Wrap operands as needed
        left_expr = self._wrap_operand(left, left_is_param)
        right_expr = self._wrap_operand(right, right_is_param)

        inner = f"{func}({left_expr}, {right_expr})"
        return f"(-{inner})" if negate else f"({wrap_prefix}{inner})"

    def _wrap_operand(self, operand: str, is_param: bool) -> str:
        """Wrap an operand in TO_VECTOR if it's a param or literal."""
        if is_param:
            return f"TO_VECTOR({operand}, DOUBLE)"
        if operand.startswith("'") or operand.startswith("["):
            opt = self._optimize_vector_literal(operand)
            return f"TO_VECTOR('{opt}', DOUBLE)"
        return operand  # Column name — no wrapping needed

    # ------------------------------------------------------------------
    # LIMIT → TOP conversion
    # ------------------------------------------------------------------

    def _convert_limit_to_top(self, sql: str) -> str:
        """Convert PostgreSQL LIMIT to IRIS TOP syntax.

        IRIS bug: ORDER BY with aliases doesn't work with LIMIT, only with TOP.
        """
        limit_pattern = re.compile(r"\s+LIMIT\s+(\d+)(?:\s+OFFSET\s+(\d+))?\s*(;?)$", re.IGNORECASE)
        match = limit_pattern.search(sql)
        if not match:
            return sql

        limit_value = match.group(1)
        offset_value = match.group(2)

        if offset_value:
            logger.warning(f"OFFSET {offset_value} ignored — IRIS TOP does not support OFFSET.")

        sql_without_limit = sql[: match.start()] + match.group(3)
        select_pattern = re.compile(r"(SELECT\s+(?:DISTINCT\s+)?)", re.IGNORECASE)
        result = select_pattern.sub(
            lambda m: f"{m.group(1)}TOP {limit_value} ",
            sql_without_limit,
            count=1,
        )

        logger.info(f"Converted LIMIT {limit_value} to TOP {limit_value}")
        return result

    def _fix_order_by_aliases(self, sql: str) -> str:
        """Pass-through for ORDER BY alias handling."""
        return sql

    # ------------------------------------------------------------------
    # Vector literal helpers
    # ------------------------------------------------------------------

    def _optimize_vector_literal(self, literal: str) -> str:
        """Ensure vector literal has brackets for IRIS TO_VECTOR compatibility."""
        clean = literal.strip("'\"")
        if not (clean.startswith("[") and clean.endswith("]")):
            clean = f"[{clean}]"
        return clean

    def bind_vector_parameter(self, vector: list[float], data_type: str = "DECIMAL") -> str:
        """Convert Python list to IRIS TO_VECTOR format for DBAPI backend.

        Args:
            vector: List of floats representing vector dimensions
            data_type: IRIS vector type ('DECIMAL', 'FLOAT', or 'INT')

        Returns:
            TO_VECTOR SQL fragment

        Raises:
            ValueError: If vector is empty or exceeds 2048 dimensions
            TypeError: If vector contains non-numeric values
        """
        if not vector:
            raise ValueError("Vector cannot be empty")
        if len(vector) > 2048:
            raise ValueError(f"Vector dimensions ({len(vector)}) exceed maximum (2048)")

        try:
            vector_json = "[" + ",".join(str(float(v)) for v in vector) + "]"
        except (TypeError, ValueError) as e:
            raise TypeError(f"Vector contains non-numeric values: {e}") from e

        return f"TO_VECTOR('{vector_json}', {data_type.upper()})"

    def _convert_vector_to_literal(self, vector_param: str) -> str | None:
        """Convert vector parameter to IRIS-compatible JSON array format.

        Supports: base64:..., [1,2,3], comma-delimited, and {1,2,3} formats.
        Returns None if conversion fails.
        """
        if vector_param is None or not isinstance(vector_param, str) or not vector_param:
            return None

        # Already in JSON array format
        if vector_param.startswith("[") and vector_param.endswith("]"):
            return vector_param

        # Base64 format
        if vector_param.startswith("base64:"):
            return self._decode_base64_vector(vector_param[7:])

        # Comma-delimited: wrap in brackets
        if "," in vector_param:
            return f"[{vector_param}]"

        logger.warning(f"Unknown vector format: {vector_param[:50]}")
        return None

    def _decode_base64_vector(self, b64_data: str) -> str | None:
        """Decode base64 binary data to JSON array of floats."""
        if not b64_data:
            return None

        try:
            binary_data = base64.b64decode(b64_data)
        except Exception as e:
            logger.error(f"Base64 decode failed: {e}")
            return None

        if len(binary_data) % 4 != 0:
            logger.warning(f"Base64 data not aligned to 4 bytes: length={len(binary_data)}")
            return None

        num_floats = len(binary_data) // 4
        if num_floats == 0 or num_floats > 65536:
            logger.warning(f"Invalid vector dimension count: {num_floats}")
            return None

        floats = struct.unpack(f"{num_floats}f", binary_data)
        return "[" + ",".join(str(float(v)) for v in floats) + "]"

    # ------------------------------------------------------------------
    # INSERT/UPDATE vector optimization
    # ------------------------------------------------------------------

    def _optimize_insert_vectors(self, sql: str, start_time: float) -> str:
        """Wrap raw vector literals in INSERT/UPDATE with TO_VECTOR()."""

        def replace_literal(m):
            if m.group(1):  # Already inside TO_VECTOR
                return m.group(0)
            content = m.group(2)
            if content.startswith("{") and content.endswith("}"):
                content = "[" + content[1:-1] + "]"
            return f"TO_VECTOR('{content}', DOUBLE)"

        optimized = re.sub(r"(?i)(TO_VECTOR\s*\(\s*)?'([\[\{][^']+?[\]\}])'", replace_literal, sql)

        if optimized != sql:
            logger.info("Wrapped raw vector literal in TO_VECTOR")

        elapsed = (time.perf_counter() - start_time) * 1000
        logger.info(f"INSERT/UPDATE optimization complete: time={elapsed:.2f}ms")
        return optimized

    # ------------------------------------------------------------------
    # Literal vector optimization
    # ------------------------------------------------------------------

    def _optimize_literal_vectors(
        self,
        sql: str,
        start_time: float,
    ) -> tuple[str, list | None]:
        """Optimize queries with literal base64 vectors already embedded in SQL."""
        literal_pattern = re.compile(
            r"TO_VECTOR\s*\(\s*'(base64:[^']+|\[[0-9.,\s-]+\]|[0-9.,\s-]+)'"
            r"(?:\s*,\s*(\w+))?\s*\)",
            re.IGNORECASE,
        )

        matches = list(literal_pattern.finditer(sql))
        if not matches:
            return sql, None

        logger.info(
            f"Found {len(matches)} literal vector strings (client-side interpolation detected)"
        )

        optimized_sql = sql
        transformations = 0

        for match in reversed(matches):
            converted = self._convert_vector_to_literal(match.group(1))
            if converted is None:
                continue

            data_type = match.group(2) or "FLOAT"
            new_call = f"TO_VECTOR('{converted}', {data_type})"
            optimized_sql = optimized_sql[: match.start()] + new_call + optimized_sql[match.end() :]
            transformations += 1

        if transformations > 0:
            elapsed = (time.perf_counter() - start_time) * 1000
            self._record_metrics(
                OptimizationMetrics(
                    transformation_time_ms=elapsed,
                    vector_params_found=len(matches),
                    vector_params_transformed=transformations,
                    sql_length_before=len(sql),
                    sql_length_after=len(optimized_sql),
                    params_count_before=0,
                    params_count_after=0,
                    constitutional_sla_compliant=(elapsed <= self.CONSTITUTIONAL_SLA_MS),
                )
            )
            logger.info(f"Literal vector optimization: {transformations} vectors transformed")

        return self._fix_order_by_aliases(optimized_sql), None

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _record_metrics(self, metrics: OptimizationMetrics):
        """Record optimization metrics and track SLA compliance."""
        self.total_optimizations += 1

        if not metrics.constitutional_sla_compliant:
            self.sla_violations += 1
            logger.error(
                f"CONSTITUTIONAL SLA VIOLATION: {metrics.transformation_time_ms:.2f}ms "
                f"(exceeds {self.CONSTITUTIONAL_SLA_MS}ms). "
                f"Violation {self.sla_violations}/{self.total_optimizations}"
            )

        self.metrics_history.append(metrics)
        if len(self.metrics_history) > 100:
            self.metrics_history.pop(0)

        logger.info(f"Optimization metrics: {metrics.to_dict()}")

    def get_performance_stats(self) -> dict[str, Any]:
        """Get performance statistics for monitoring."""
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
        compliance_rate = (
            (self.total_optimizations - self.sla_violations) / self.total_optimizations * 100
            if self.total_optimizations > 0
            else 100.0
        )

        return {
            "total_optimizations": self.total_optimizations,
            "sla_violations": self.sla_violations,
            "sla_compliance_rate": round(compliance_rate, 2),
            "avg_transformation_time_ms": round(sum(recent_times) / len(recent_times), 2),
            "min_transformation_time_ms": round(min(recent_times), 2),
            "max_transformation_time_ms": round(max(recent_times), 2),
            "constitutional_sla_ms": self.CONSTITUTIONAL_SLA_MS,
            "recent_sample_size": len(recent_times),
        }


    # ------------------------------------------------------------------
    # HNSW index DDL translation (pgvector → IRIS)
    # ------------------------------------------------------------------

    _HNSW_DDL_RE = re.compile(
        r"""
        CREATE\s+INDEX\s+                    # CREATE INDEX
        (?:IF\s+NOT\s+EXISTS\s+)?            # optional IF NOT EXISTS
        (\w+)\s+                             # index name (group 1)
        ON\s+(\w+(?:\.\w+)?)\s+             # ON table (group 2; schema.table ok)
        USING\s+hnsw\s*                      # USING hnsw
        \(\s*(\w+)(?:\s+(\w+))?\s*\)        # (column [inline_op_class]) groups 3,4
        (?:\s+WITH\s*\(([^)]*)\))?           # optional WITH (options) group 5
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    _DISTANCE_MAP = {
        "vector_cosine_ops": "Cosine",
        "vector_ip_ops": "DotProduct",
        "vector_l2_ops": None,
    }

    def _translate_hnsw_index_ddl(self, sql: str) -> str:
        """Translate pgvector HNSW index DDL to IRIS-native HNSW syntax."""

        def _replace(m: re.Match) -> str:
            idx_name = m.group(1)
            table = m.group(2)
            col = m.group(3)
            inline_ops = m.group(4) or ""
            with_clause = m.group(5) or ""
            distance = "Cosine"
            ops_source = inline_ops or ""
            ops_match = re.search(r"op_class\s*=\s*(\w+)", with_clause, re.IGNORECASE)
            if ops_match:
                ops_source = ops_match.group(1)
            if ops_source:
                mapped = self._DISTANCE_MAP.get(ops_source.lower())
                if mapped is None:
                    raise NotImplementedError(
                        "IRIS does not support L2 distance (vector_l2_ops) in HNSW indexes. "
                        "Use Cosine or DotProduct."
                    )
                distance = mapped
            iris_ddl = f"CREATE INDEX {idx_name} ON {table} ({col}) AS HNSW(Distance={distance}"
            m_opts = re.search(r"\bm\s*=\s*(\d+)", with_clause, re.IGNORECASE)
            ef_opts = re.search(r"ef_construction\s*=\s*(\d+)", with_clause, re.IGNORECASE)
            if m_opts:
                iris_ddl += f", M={m_opts.group(1)}"
            if ef_opts:
                iris_ddl += f", efConstruction={ef_opts.group(1)}"
            iris_ddl += ")"
            return iris_ddl

        return self._HNSW_DDL_RE.sub(_replace, sql)

    # ------------------------------------------------------------------
    # PostgreSQL JSON operators → IRIS JSON_VALUE / JSON_QUERY
    # ------------------------------------------------------------------

    _JSON_CHAIN_RE = re.compile(
        r"(\w+(?:\.\w+)?)"
        r"((?:\s*->>\s*'[^']+'"
        r"|\s*->\s*'[^']+')+)",
        re.IGNORECASE,
    )

    def _translate_nested_json_operators(self, sql: str) -> str:
        """Translate PostgreSQL -> / ->> chains to IRIS JSON_VALUE / JSON_QUERY."""

        def _replace(m: re.Match) -> str:
            col = m.group(1)
            chain = m.group(2)
            text_extract = "->>" in chain
            keys = re.findall(r"->>?\s*'([^']+)'", chain)
            path = "." + ".".join(keys)
            if text_extract:
                return f"JSON_VALUE({col}, '${path}')"
            return f"JSON_QUERY({col}, '${path}')"

        return self._JSON_CHAIN_RE.sub(_replace, sql)

    # ------------------------------------------------------------------
    # IF NOT EXISTS error classification (Feature 026)
    # ------------------------------------------------------------------

    _IRIS_DUPLICATE_CODES = frozenset({
        "5016",
        "5019",
        "5002",
        "SQLCODE: <-5016>",
        "SQLCODE: <-5019>",
        "SQLCODE: <-5002>",
    })

    @staticmethod
    def is_duplicate_object_error(error_msg: str) -> bool:
        """Return True if error_msg indicates an object-already-exists SQLCODE."""
        return any(code in error_msg for code in VectorQueryOptimizer._IRIS_DUPLICATE_CODES)

    @staticmethod
    def sql_has_if_not_exists(sql: str) -> bool:
        """Return True if sql contains an IF NOT EXISTS clause."""
        return bool(re.search(r"\bIF\s+NOT\s+EXISTS\b", sql, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Module-level API
# ---------------------------------------------------------------------------

_optimizer = VectorQueryOptimizer()


def optimize_vector_query(sql: str, params: list | None = None) -> tuple[str, list | None]:
    """Convenience function to optimize vector queries.

    Pipeline order in iris_executor.py:
    1. Transaction translation (Feature 022) — BEGIN → START TRANSACTION
    2. SQL normalization (Feature 021) — Identifiers/DATE literals
    3. Vector optimization (this function) — Parameter optimization
    """
    return _optimizer.optimize_query(sql, params)


def enable_optimization(enabled: bool = True):
    """Enable or disable vector query optimization."""
    _optimizer.enabled = enabled
    logger.info(f"Vector query optimization: enabled={enabled}")


def get_performance_stats() -> dict[str, Any]:
    """Get performance statistics for constitutional compliance monitoring."""
    return _optimizer.get_performance_stats()


def get_sla_compliance_report() -> str:
    """Generate human-readable SLA compliance report."""
    stats = get_performance_stats()
    status = "COMPLIANT" if stats["sla_compliance_rate"] >= 95 else "NON-COMPLIANT"

    return f"""Vector Query Optimizer - Constitutional Compliance Report
=========================================================
Total Optimizations: {stats["total_optimizations"]}
SLA Violations: {stats["sla_violations"]}
SLA Compliance Rate: {stats["sla_compliance_rate"]}%
Constitutional SLA: {stats["constitutional_sla_ms"]}ms

Performance Metrics (last {stats.get("recent_sample_size", 0)} operations):
  Average: {stats.get("avg_transformation_time_ms", 0)}ms
  Minimum: {stats.get("min_transformation_time_ms", 0)}ms
  Maximum: {stats.get("max_transformation_time_ms", 0)}ms

Status: {status}"""
