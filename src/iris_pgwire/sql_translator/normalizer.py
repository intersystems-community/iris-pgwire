"""
SQL Normalizer - Main Orchestrator (Feature 021)

Combines identifier normalization and DATE translation for PostgreSQL compatibility.
This is the SQLTranslator class that implements the contract interface.

Constitutional Requirements:
- < 5ms normalization overhead for 50 identifier references
- < 10% total execution time increase vs baseline

Feature 030 Extension:
- PostgreSQL schema mapping (public → SQLUser)
"""

import time
import re

from ..conversions.json_path import JsonPathBuilder
from ..schema_mapper import translate_input_schema
from .date_translator import DATETranslator
from .identifier_normalizer import IdentifierNormalizer
from .default_values import DefaultValuesTranslator


class SQLTranslator:
    """
    Main SQL normalization orchestrator.

    Implements the contract defined in:
    specs/021-postgresql-compatible-sql/contracts/sql_translator_interface.py

    Combines:
    - Identifier case normalization (unquoted → UPPERCASE, quoted → preserve)
    - DATE literal translation ('YYYY-MM-DD' → TO_DATE(...))
    - JSON operator translation (->, ->> → JSON_VALUE/JSON_QUERY)
    - DEFAULT-in-VALUES rewrite for IRIS compatibility
    """

    def __init__(self):
        """Initialize SQL translator with component normalizers"""
        self.identifier_normalizer = IdentifierNormalizer()
        self.date_translator = DATETranslator()
        self.default_values_translator = DefaultValuesTranslator()

        # Recursive JSON operator pattern
        self._json_pattern = re.compile(
            r"(\w+)(?:->>?['\"]\w+['\"]|->>?\d+|\[['\"]\w+['\"]\]|\[\d+\])+", re.IGNORECASE
        )

        # Metrics tracking for last normalization
        self._last_metrics = {
            "normalization_time_ms": 0.0,
            "identifier_count": 0,
            "date_literal_count": 0,
            "json_operator_count": 0,
            "sla_violated": False,
        }

    def translate_postgres_parameters(self, sql: str) -> str:
        """
        Translate PostgreSQL parameter placeholders and type casts to IRIS syntax.

        Args:
            sql: SQL query with PostgreSQL $1, $2, $3 placeholders and :: type casts

        Returns:
            SQL query with IRIS ? placeholders and CAST() expressions
        """
        if "$" not in sql and "::" not in sql:
            return sql

        # Step 1: Replace $1, $2, $3, ... with ? for IRIS parameter binding
        if "$" in sql:
            sql = re.sub(r"\$\d+", "?", sql)

        # Step 2: Translate PostgreSQL :: type cast to IRIS CAST() function
        if "::" in sql:
            type_map = {
                "int": "INTEGER",
                "int4": "INTEGER",
                "int8": "BIGINT",
                "text": "VARCHAR",
                "varchar": "VARCHAR",
                "float": "DOUBLE",
                "float8": "DOUBLE",
                "bool": "BIT",
                "boolean": "BIT",
            }

            def replace_typecast(match):
                expr = match.group(1)
                pg_type = match.group(2).lower()
                iris_type = type_map.get(pg_type, pg_type.upper())
                return f"CAST({expr} AS {iris_type})"

            sql = re.sub(r"(\?|'[^']*'|\d+)::([\w]+)", replace_typecast, sql)

        return sql

    def normalize_sql(self, sql: str, execution_path: str = "direct") -> str:
        """
        Normalize SQL for IRIS compatibility.

        Args:
            sql: Original SQL from PostgreSQL client
            execution_path: Execution context - one of:
                - "direct": Direct IRIS execution via iris.sql.exec()
                - "vector": Vector-optimized execution path
                - "external": External DBAPI connection

        Returns:
            Normalized SQL ready for IRIS execution

        Constitutional Requirements:
        - Normalization MUST complete in < 5ms for 50 identifier references
        - MUST be idempotent (normalizing twice yields same result)
        """
        start_time = time.perf_counter()

        # Handle empty SQL
        if not sql or not sql.strip():
            self._last_metrics = {
                "normalization_time_ms": 0.0,
                "identifier_count": 0,
                "date_literal_count": 0,
                "json_operator_count": 0,
                "sla_violated": False,
            }
            return sql

        # Step -1: Translate PostgreSQL parameters ($n -> ?) and type casts (::type -> CAST)
        # This MUST happen before normalization to avoid issues with placeholders
        normalized_sql = self.translate_postgres_parameters(sql)

        # Step 0: Schema mapping (public → SQLUser) - Feature 030
        normalized_sql = translate_input_schema(normalized_sql)

        # Step 1: Normalize identifiers (unquoted → UPPERCASE)
        normalized_sql, identifier_count = self.identifier_normalizer.normalize(normalized_sql)

        # Step 2: Translate DATE literals ('YYYY-MM-DD' → TO_DATE(...))
        normalized_sql, date_count = self.date_translator.translate(normalized_sql)

        # Step 3: Translate JSON operators
        normalized_sql, json_count = self._translate_json_operators(normalized_sql)

        # Step 4: Translate VECTOR types (VECTOR(128) -> VECTOR(DOUBLE, 128))
        normalized_sql = self._translate_vector_types(normalized_sql)

        # Step 5: Rewrite DEFAULT in VALUES
        normalized_sql = self.default_values_translator.translate(normalized_sql)

        # Calculate performance metrics
        end_time = time.perf_counter()
        normalization_time_ms = (end_time - start_time) * 1000
        sla_violated = normalization_time_ms > 5.0

        # Store metrics
        self._last_metrics = {
            "normalization_time_ms": normalization_time_ms,
            "identifier_count": identifier_count,
            "date_literal_count": date_count,
            "json_operator_count": json_count,
            "sla_violated": sla_violated,
        }

        return normalized_sql

    def _translate_json_operators(self, sql: str) -> tuple[str, int]:
        """Translate PostgreSQL JSON operators to IRIS JSON_VALUE/JSON_QUERY"""
        count = 0

        def replace_json(match):
            nonlocal count
            try:
                _, builder = JsonPathBuilder.parse(match.group(0))
                count += 1
                return builder.build()
            except Exception:
                return match.group(0)

        # We must be careful not to translate inside already translated parts or string literals
        # SQLTranslator already avoids string literals in other steps, but we should be robust
        result = self._json_pattern.sub(replace_json, sql)
        return result, count

    def _translate_vector_types(self, sql: str) -> str:
        """
        Translate PostgreSQL VECTOR types to IRIS format.
        VECTOR(128) -> VECTOR(DOUBLE, 128)
        """
        # Match VECTOR(dims) but not VECTOR(type, dims)
        # Matches: VECTOR(128), vector(512), "VECTOR"(1024)
        # Replaces with: VECTOR(DOUBLE,128) - no space after comma for maximum compatibility

        def replace_vector(match):
            dims = match.group(1)
            return f"VECTOR(DOUBLE,{dims})"

        # Pattern: \bVECTOR\s*\(\s*(\d+)\s*\)
        result = re.sub(r"\bVECTOR\s*\(\s*(\d+)\s*\)", replace_vector, sql, flags=re.IGNORECASE)
        return result

    def normalize_identifiers(self, sql: str) -> str:
        """
        Normalize SQL identifiers only (no DATE translation).

        Args:
            sql: Original SQL with mixed-case identifiers

        Returns:
            SQL with normalized identifiers
        """
        normalized_sql, _ = self.identifier_normalizer.normalize(sql)
        return normalized_sql

    def translate_dates(self, sql: str) -> str:
        """
        Translate DATE literals only (no identifier normalization).

        Args:
            sql: Original SQL with PostgreSQL DATE literals

        Returns:
            SQL with DATE literals translated to TO_DATE() calls
        """
        translated_sql, _ = self.date_translator.translate(sql)
        return translated_sql

    def get_normalization_metrics(self) -> dict:
        """
        Get performance metrics for the last normalization operation.

        Returns:
            Dictionary with performance metrics:
            {
                'normalization_time_ms': float,
                'identifier_count': int,
                'date_literal_count': int,
                'sla_violated': bool  # True if > 5ms
            }
        """
        return self._last_metrics.copy()
