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

from ..schema_mapper import translate_input_schema
from .date_translator import DATETranslator
from .identifier_normalizer import IdentifierNormalizer


class SQLTranslator:
    """
    Main SQL normalization orchestrator.

    Implements the contract defined in:
    specs/021-postgresql-compatible-sql/contracts/sql_translator_interface.py

    Combines:
    - Identifier case normalization (unquoted → UPPERCASE, quoted → preserve)
    - DATE literal translation ('YYYY-MM-DD' → TO_DATE(...))
    """

    def __init__(self):
        """Initialize SQL translator with component normalizers"""
        self.identifier_normalizer = IdentifierNormalizer()
        self.date_translator = DATETranslator()

        # Metrics tracking for last normalization
        self._last_metrics = {
            "normalization_time_ms": 0.0,
            "identifier_count": 0,
            "date_literal_count": 0,
            "sla_violated": False,
        }

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
                "sla_violated": False,
            }
            return sql

        # Step 0: Schema mapping (public → SQLUser) - Feature 030
        normalized_sql = translate_input_schema(sql)

        # Step 1: Normalize identifiers (unquoted → UPPERCASE)
        normalized_sql, identifier_count = self.identifier_normalizer.normalize(normalized_sql)

        # Step 2: Translate DATE literals ('YYYY-MM-DD' → TO_DATE(...))
        normalized_sql, date_count = self.date_translator.translate(normalized_sql)

        # Calculate performance metrics
        end_time = time.perf_counter()
        normalization_time_ms = (end_time - start_time) * 1000
        sla_violated = normalization_time_ms > 5.0

        # Store metrics
        self._last_metrics = {
            "normalization_time_ms": normalization_time_ms,
            "identifier_count": identifier_count,
            "date_literal_count": date_count,
            "sla_violated": sla_violated,
        }

        return normalized_sql

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
