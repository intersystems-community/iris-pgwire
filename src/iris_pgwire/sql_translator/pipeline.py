"""
SQL Pipeline - Unified transformation pipeline for IRIS compatibility (Feature 036)

This orchestrates the various stages of SQL translation:
1. Schema Mapping (public -> {IRIS_SCHEMA})
2. Statement Filtering (skipping unsupported DDL)
3. Parameter Translation ($n -> ?)
4. Refinement (ORDER BY alias fixes, etc.)
5. Optimization (pgvector -> HNSW)
6. Normalization (Identifiers, dates, booleans, enums)
"""

import logging
from dataclasses import dataclass
from typing import Any

from .models import PerformanceStats, TranslationResult
from .normalizer import SQLTranslator
from .refiner import SQLRefiner

logger = logging.getLogger("iris_pgwire.sql_translator.pipeline")


class SQLPipeline:
    """
    Orchestrates the complete SQL transformation process.
    """

    def __init__(self, translator: SQLTranslator | None = None):
        self.translator = translator or SQLTranslator()
        self.refiner = SQLRefiner()

    def process(
        self, sql: str, params: list | None = None, session_id: str | None = None
    ) -> tuple[str, list | None, TranslationResult]:
        """
        Process SQL and parameters through the full pipeline.
        """
        if not sql:
            perf_stats = PerformanceStats(0.0, False, 0, 0)
            return (
                sql,
                params,
                TranslationResult(
                    translated_sql="", construct_mappings=[], performance_stats=perf_stats
                ),
            )

        result = self.translator.normalize_sql_with_result(sql)

        if result.was_skipped:
            return "", params, result

        processed_sql = result.translated_sql
        processed_params = params

        processed_sql = self.refiner.refine(processed_sql)

        return processed_sql, processed_params, result
