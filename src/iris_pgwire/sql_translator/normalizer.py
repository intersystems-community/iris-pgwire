"""
SQL Normalizer - Main Orchestrator (Feature 021)

Combines identifier normalization and DATE translation for PostgreSQL compatibility.
This is the SQLTranslator class that implements the contract interface.

Constitutional Requirements:
- < 5ms normalization overhead for 50 identifier references
- < 10% total execution time increase vs baseline

Feature 030 Extension:
- PostgreSQL schema mapping (public → {IRIS_SCHEMA})

Feature 035 Extension:
- ENUM type handling (CREATE TYPE skip, column type translation)
- RLS statement handling (skip)
- Boolean default translation (true/false → 1/0)
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..conversions.json_path import JsonPathBuilder
from ..schema_mapper import translate_input_schema
from .boolean_translator import BooleanTranslator
from .date_translator import DATETranslator
from .default_values import DefaultValuesTranslator
from .enum_registry import EnumTypeRegistry
from .enum_translator import EnumTranslator
from .identifier_normalizer import IdentifierNormalizer
from .mappings import translate_document_filters, translate_sql_constructs
from .models import (
    ConstructMapping,
    ConstructType,
    PerformanceStats,
    SourceLocation,
    TranslationResult,
)
from .refiner import SQLRefiner
from .skipped_table_set import SkippedTableSet
from .statement_filter import SkipReason, StatementFilter


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
        self.identifier_normalizer = IdentifierNormalizer()
        self.date_translator = DATETranslator()
        self.default_values_translator = DefaultValuesTranslator()

        self.enum_registry = EnumTypeRegistry()
        self.skipped_tables = SkippedTableSet()
        self.statement_filter = StatementFilter(self.enum_registry, self.skipped_tables)
        self.enum_translator = EnumTranslator(self.enum_registry)
        self.boolean_translator = BooleanTranslator()
        self.sql_refiner = SQLRefiner()

        self._json_pattern = re.compile(
            r"(\w+)(?:->>?['\"]\w+['\"]|->>?\d+|\[['\"]\w+['\"]\]|\[\d+\])+", re.IGNORECASE
        )

        self._last_metrics = {
            "normalization_time_ms": 0.0,
            "identifier_count": 0,
            "date_literal_count": 0,
            "json_operator_count": 0,
            "boolean_translation_count": 0,
            "enum_translation_count": 0,
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
        if not any(marker in sql.upper() for marker in ("$", "::", "CAST", "%S")):
            return sql

        # Step 1: Replace PostgreSQL placeholders ($1, $2, %s) with IRIS ? syntax
        # This prevents IdentifierNormalizer from uppercasing %s to %S
        if "$" in sql:
            sql = re.sub(r"\$\d+", "?", sql)
        if "%s" in sql:
            sql = sql.replace("%s", "?")

        # Step 2: Translate PostgreSQL type casts to IRIS syntax
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
            "vector": "VECTOR",
        }

        def replace_typecast(match):
            expr = match.group(1).strip()
            pg_type = match.group(2).strip().lower()

            # Strip quotes from placeholders if they were quoted (e.g. '?'::int)
            if expr.startswith("'") and expr.endswith("'"):
                expr_content = expr[1:-1]
                if expr_content in ("?", "%s") or (
                    expr_content.startswith("$") and expr_content[1:].isdigit()
                ):
                    expr = expr_content

            # Special handling for vector casts
            if pg_type == "vector":
                # IRIS uses TO_VECTOR instead of CAST(? AS VECTOR)
                # We convert '::vector' or 'CAST(... AS vector)' to 'TO_VECTOR(..., DOUBLE)'
                return f"TO_VECTOR({expr}, DOUBLE)"

            iris_type = type_map.get(pg_type, pg_type.upper())
            return f"CAST({expr} AS {iris_type})"

        # Pattern 1: Shorthand ::type (handles ?, %s, 'literal', or 123)
        if "::" in sql:
            sql = re.sub(r"(\?|%s|'[^']*'|\d+)::(\w+)", replace_typecast, sql)

        # Pattern 2: Explicit CAST(expr AS type)
        if "CAST" in sql.upper():
            sql = re.sub(
                r"(?i)\bCAST\s*\(\s*(\?|%s|'[^']*'|\d+)\s+AS\s+(\w+)\s*\)",
                replace_typecast,
                sql,
            )

        return sql

    def normalize_sql(self, sql: str, execution_path: str = "direct") -> str:
        """
        Normalize SQL for IRIS compatibility.

        Args:
            sql: SQL query string
            execution_path: Path context (direct, prepared, etc.)

        Returns:
            Normalized SQL
        """
        result = self.normalize_sql_with_result(sql, execution_path)
        return result.translated_sql

    def normalize_sql_with_result(
        self, sql: str, execution_path: str = "direct"
    ) -> TranslationResult:
        """
        Normalize SQL for IRIS compatibility with full result info.

        Returns:
            TranslationResult with sql, was_skipped flag, and command_tag for skipped statements.
        """
        start_time = time.perf_counter()

        if not sql or not sql.strip():
            perf_stats = PerformanceStats(
                translation_time_ms=0.0,
                cache_hit=False,
                constructs_detected=0,
                constructs_translated=0,
            )
            return TranslationResult(
                translated_sql=sql or "",
                construct_mappings=[],
                performance_stats=perf_stats,
            )

        # FR-001: Strip leading/trailing comments and whitespace
        normalized_sql = sql.strip()
        while normalized_sql.startswith("--"):
            newline_pos = normalized_sql.find("\n")
            if newline_pos == -1:
                normalized_sql = ""
                break
            normalized_sql = normalized_sql[newline_pos + 1 :].strip()

        if not normalized_sql:
            perf_stats = PerformanceStats(0.0, False, 0, 0)
            return TranslationResult(
                translated_sql="", construct_mappings=[], performance_stats=perf_stats
            )

        normalized_sql = self.translate_postgres_parameters(normalized_sql)
        normalized_sql = translate_input_schema(normalized_sql)

        filter_result = self.statement_filter.check(normalized_sql)
        if filter_result.should_skip:
            if filter_result.extracted_type_name:
                self.enum_registry.register(filter_result.extracted_type_name)

            end_time = time.perf_counter()
            normalization_time_ms = (end_time - start_time) * 1000
            self._last_metrics = {
                "normalization_time_ms": normalization_time_ms,
                "identifier_count": 0,
                "date_literal_count": 0,
                "json_operator_count": 0,
                "boolean_translation_count": 0,
                "enum_translation_count": 0,
                "sla_violated": normalization_time_ms > 5.0,
                "cache_hit": False,
            }
            perf_stats = PerformanceStats(
                translation_time_ms=normalization_time_ms,
                cache_hit=False,
                constructs_detected=0,
                constructs_translated=0,
            )
            return TranslationResult(
                translated_sql="",
                construct_mappings=[],
                performance_stats=perf_stats,
                was_skipped=True,
                skip_reason=filter_result.reason,
                command_tag=filter_result.command_tag,
            )

        normalized_sql, enum_count = self.enum_translator.translate(normalized_sql)
        normalized_sql, bool_count = self.boolean_translator.translate(normalized_sql)

        normalized_sql, identifier_count = self.identifier_normalizer.normalize(normalized_sql)
        normalized_sql = self.sql_refiner.refine(normalized_sql)
        normalized_sql, date_count = self.date_translator.translate(normalized_sql)
        normalized_sql, json_count = self._translate_json_operators(normalized_sql)
        normalized_sql, vector_fn_count = self._translate_vector_functions(normalized_sql)
        normalized_sql = self._translate_vector_types(normalized_sql)
        normalized_sql = self.default_values_translator.translate(normalized_sql)

        # Call comprehensive mapping registries for HNSW and complex filters
        normalized_sql, construct_mappings = translate_sql_constructs(normalized_sql)
        construct_count = len(construct_mappings)

        normalized_sql, doc_filter_mappings = translate_document_filters(normalized_sql)
        doc_filter_count = len(doc_filter_mappings)

        end_time = time.perf_counter()
        normalization_time_ms = (end_time - start_time) * 1000

        self._last_metrics = {
            "normalization_time_ms": normalization_time_ms,
            "identifier_count": identifier_count,
            "date_literal_count": date_count,
            "json_operator_count": json_count,
            "vector_function_count": vector_fn_count,
            "boolean_translation_count": bool_count,
            "enum_translation_count": enum_count,
            "construct_count": construct_count,
            "doc_filter_count": doc_filter_count,
            "sla_violated": normalization_time_ms > 5.0,
            "cache_hit": False,
        }

        perf_stats = PerformanceStats(
            translation_time_ms=normalization_time_ms,
            cache_hit=False,
            constructs_detected=identifier_count
            + date_count
            + json_count
            + vector_fn_count
            + enum_count
            + bool_count
            + construct_count
            + doc_filter_count,
            constructs_translated=identifier_count
            + date_count
            + json_count
            + vector_fn_count
            + enum_count
            + bool_count
            + construct_count
            + doc_filter_count,
        )

        return TranslationResult(
            translated_sql=normalized_sql,
            construct_mappings=[],
            performance_stats=perf_stats,
            was_skipped=False,
            skip_reason=None,
            command_tag="",
        )

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

    def _translate_vector_functions(self, sql: str) -> tuple[str, int]:
        """Translate pgvector function names to IRIS equivalents"""
        count = 0
        vector_functions = {
            "vector_cosine_distance": "VECTOR_COSINE",
            "cosine_distance": "VECTOR_COSINE",
            "vector_l2_distance": "VECTOR_L2_DISTANCE",  # Error handled later if not supported
            "l2_distance": "VECTOR_L2_DISTANCE",
            "inner_product": "VECTOR_DOT_PRODUCT",
            "vector_dims": "VECTOR_DIM",
            "vector_norm": "VECTOR_NORM",
        }

        # Case-insensitive replacement
        for pg_func, iris_func in vector_functions.items():
            pattern = rf"\b{pg_func}\b"
            if re.search(pattern, sql, re.IGNORECASE):
                sql = re.sub(pattern, iris_func, sql, flags=re.IGNORECASE)
                count += 1

        return sql, count

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
