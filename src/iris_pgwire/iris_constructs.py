"""
IRIS-Specific SQL Constructs Translation

Handles translation of IRIS-specific SQL syntax, functions, and data types
to PostgreSQL equivalents for wire protocol compatibility.
"""

import logging
import re
import time
from enum import Enum
from typing import Any

from .debug_tracer import TraceLevel, get_tracer
from .performance_monitor import get_monitor

logger = logging.getLogger(__name__)


class IRISConstructType(Enum):
    """Types of IRIS constructs we handle"""

    SYSTEM_FUNCTION = "system_function"
    SQL_EXTENSION = "sql_extension"
    DATA_TYPE = "data_type"
    IRIS_FUNCTION = "iris_function"
    JSON_FUNCTION = "json_function"


# ---------------------------------------------------------------------------
# Shared helper: compile function-call regex patterns
# ---------------------------------------------------------------------------


def _compile_func_patterns(func_map: dict[str, str]) -> dict[str, re.Pattern]:
    """Compile regex patterns for matching IRIS function calls."""
    patterns = {}
    for iris_func in func_map:
        escaped = re.escape(iris_func)
        patterns[iris_func] = re.compile(rf"(?<!\w){escaped}\s*\(\s*([^)]*)\s*\)", re.IGNORECASE)
    return patterns


def _translate_functions(
    sql: str, func_map: dict[str, str], patterns: dict[str, re.Pattern]
) -> str:
    """Replace IRIS function calls with PostgreSQL equivalents."""
    result = sql
    for iris_func, pg_func in func_map.items():

        def replace_func(match, _pg=pg_func):
            params = match.group(1)
            return f"{_pg}({params})"

        result = patterns[iris_func].sub(replace_func, result)
    return result


# ---------------------------------------------------------------------------
# System function translator
# ---------------------------------------------------------------------------


class IRISSystemFunctionTranslator:
    """Translates IRIS %SYSTEM.* functions to PostgreSQL equivalents"""

    SYSTEM_FUNCTION_MAP = {
        "%SYSTEM.Version.%GetNumber": "version()",
        "%SYSTEM.Version.GetNumber": "version()",
        "%SYSTEM.Security.%GetUser": "current_user",
        "%SYSTEM.Security.GetUser": "current_user",
        "%SYSTEM.SQL.%GetStatement": "current_query()",
        "%SYSTEM.SQL.GetStatement": "current_query()",
        "%SYSTEM.ML.%ModelExists": "iris_ml_model_exists",
        "%SYSTEM.ML.ModelExists": "iris_ml_model_exists",
        "%SYSTEM.ML.%GetModelList": "iris_ml_get_model_list",
        "%SYSTEM.ML.GetModelList": "iris_ml_get_model_list",
        "%SYSTEM.SQL.%PARALLEL": "iris_sql_parallel_info",
        "%SYSTEM.SQL.PARALLEL": "iris_sql_parallel_info",
    }

    def __init__(self):
        self.patterns = _compile_func_patterns(self.SYSTEM_FUNCTION_MAP)

    def translate(self, sql: str) -> str:
        """Translate IRIS system functions in SQL."""
        result = sql
        for iris_func, pg_func in self.SYSTEM_FUNCTION_MAP.items():

            def replace_func(match, _pg=pg_func):
                params = match.group(1).strip() if match.group(1) else ""
                if params:
                    return f"{_pg}({params})"
                return _pg if _pg.endswith("()") else f"{_pg}()"

            result = self.patterns[iris_func].sub(replace_func, result)
        return result


# ---------------------------------------------------------------------------
# SQL extension translator
# ---------------------------------------------------------------------------


class IRISSQLExtensionTranslator:
    """Translates IRIS SQL extensions to PostgreSQL equivalents"""

    def __init__(self):
        self.top_pattern = re.compile(r"\bSELECT\s+TOP\s+(\d+)(?:\s+PERCENT)?\s+", re.IGNORECASE)
        self.top_percent_pattern = re.compile(r"\bSELECT\s+TOP\s+(\d+)\s+PERCENT\s+", re.IGNORECASE)
        self.full_outer_join_pattern = re.compile(r"%FULL\s+OUTER\s+JOIN", re.IGNORECASE)

    def translate_top_clause(self, sql: str) -> str:
        """Translate TOP clause to LIMIT."""
        if self.top_percent_pattern.search(sql):
            logger.warning("TOP n PERCENT not fully supported, converting to approximate LIMIT")
            percent_match = re.search(r"TOP\s+(\d+)\s+PERCENT", sql, re.IGNORECASE)
            sql = self.top_percent_pattern.sub("SELECT * FROM (SELECT ", sql)
            if percent_match:
                sql += f" LIMIT {int(percent_match.group(1))}"

        match = self.top_pattern.search(sql)
        if match:
            limit_value = match.group(1)
            sql = self.top_pattern.sub("SELECT ", sql)
            if not re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
                sql += f" LIMIT {limit_value}"

        return sql

    def translate_joins(self, sql: str) -> str:
        """Translate IRIS-specific JOIN syntax."""
        return self.full_outer_join_pattern.sub("FULL OUTER JOIN", sql)

    def translate(self, sql: str) -> str:
        """Apply all SQL extension translations."""
        sql = self.translate_top_clause(sql)
        sql = self.translate_joins(sql)
        return sql


# ---------------------------------------------------------------------------
# IRIS function translator
# ---------------------------------------------------------------------------


class IRISFunctionTranslator:
    """Translates IRIS-specific functions to PostgreSQL equivalents"""

    FUNCTION_MAP = {
        "%SQLUPPER": "UPPER",
        "%SQLLOWER": "LOWER",
        "SQLUPPER": "UPPER",
        "SQLLOWER": "LOWER",
        "DATEDIFF_MICROSECONDS": "iris_datediff_microseconds",
        "DATEPART_TIMEZONE": "iris_datepart_timezone",
        "%HOROLOG": "iris_horolog",
        "HOROLOG": "iris_horolog",
        "%EXTERNAL": "iris_external_format",
        "%INTERNAL": "iris_internal_format",
        "EXTERNAL": "iris_external_format",
        "INTERNAL": "iris_internal_format",
        "%PATTERN.MATCH": "iris_pattern_match",
        "PATTERN.MATCH": "iris_pattern_match",
        "%EXACT": "iris_exact_match",
        "EXACT": "iris_exact_match",
    }

    def __init__(self):
        self.patterns = _compile_func_patterns(self.FUNCTION_MAP)

    def translate(self, sql: str) -> str:
        """Translate IRIS functions to PostgreSQL equivalents."""
        return _translate_functions(sql, self.FUNCTION_MAP, self.patterns)


# ---------------------------------------------------------------------------
# Data type translator
# ---------------------------------------------------------------------------


class IRISDataTypeTranslator:
    """Translates IRIS data types to PostgreSQL equivalents"""

    TYPE_MAP = {
        "SERIAL": "SERIAL",
        "ROWVERSION": "BIGINT",
        "%List": "BYTEA",
        "%Stream": "BYTEA",
        "MONEY": "NUMERIC(19,4)",
        "POSIXTIME": "TIMESTAMP",
        "%TimeStamp": "TIMESTAMP",
        "%Date": "DATE",
        "%Time": "TIME",
        "VECTOR": "VECTOR",
        "EMBEDDING": "VECTOR",
    }

    def __init__(self):
        self.type_patterns = {}
        for iris_type in self.TYPE_MAP:
            escaped = re.escape(iris_type)
            self.type_patterns[iris_type] = re.compile(
                rf"(?<!\w){escaped}(?:\s*\([^)]+\))?(?!\w)", re.IGNORECASE
            )

    def translate(self, sql: str) -> str:
        """Translate IRIS data types in DDL statements."""
        if not re.search(r"\b(CREATE\s+TABLE|ALTER\s+TABLE)\b", sql, re.IGNORECASE):
            return sql

        result = sql
        for iris_type, pg_type in self.TYPE_MAP.items():
            result = self.type_patterns[iris_type].sub(pg_type, result)
        return result


# ---------------------------------------------------------------------------
# JSON function translator
# ---------------------------------------------------------------------------


class IRISJSONFunctionTranslator:
    """Translates IRIS JSON functions and JSON_TABLE to PostgreSQL equivalents"""

    FUNCTION_MAP = {
        "JSON_OBJECT": "json_build_object",
        "JSON_ARRAY": "json_build_array",
        "JSON_SET": "jsonb_set",
        "JSON_GET": "jsonb_extract_path_text",
        "JSON_VALUE": "jsonb_extract_path_text",
        "JSON_QUERY": "jsonb_extract_path",
        "JSON_EXISTS": "jsonb_path_exists",
        "JSON_MODIFY": "jsonb_set",
        "JSON_REMOVE": "jsonb_path_delete",
        "JSON_LENGTH": "jsonb_array_length",
        "JSON_KEYS": "jsonb_object_keys",
        "JSON_EACH": "jsonb_each",
        "JSON_EACH_TEXT": "jsonb_each_text",
        "JSON_EXTRACT": "jsonb_path_query",
        "JSON_EXTRACT_SCALAR": "jsonb_path_query_first",
        "JSON_SEARCH": "jsonb_path_query",
        "JSON_CONTAINS": "jsonb_path_match",
        "JSON_CONTAINS_PATH": "jsonb_path_exists",
        "JSON_TYPE": "jsonb_typeof",
        "JSON_VALID": "iris_json_valid",
        "JSON_ARRAYAGG": "json_agg",
        "JSON_OBJECTAGG": "json_object_agg",
    }

    def __init__(self):
        self.patterns = _compile_func_patterns(self.FUNCTION_MAP)

        self.json_table_pattern = re.compile(
            r'\bJSON_TABLE\s*\(\s*([^,]+),\s*([\'"][^\'\"]*[\'"])\s+COLUMNS\s*\(\s*([^)]+)\s*\)\s*\)',
            re.IGNORECASE | re.DOTALL,
        )

        self.json_table_collection_pattern = re.compile(
            r'\bJSON_TABLE\s*\(\s*(\w+)\s+FORMAT\s+COLLECTION,\s*([\'"][^\'\"]*[\'"])\s+COLUMNS\s*\(\s*([^)]+)\s*\)\s*\)',
            re.IGNORECASE | re.DOTALL,
        )

        self.docdb_filter_pattern = re.compile(
            r"(\w+)\s*->\s*'([^']+)'\s*(=|!=|<|>|<=|>=|LIKE|CONTAINS)\s*(.+)", re.IGNORECASE
        )

    def translate_json_table(self, sql: str) -> str:
        """Translate IRIS JSON_TABLE to PostgreSQL equivalents."""

        def replace_json_table(match):
            json_data = match.group(1).strip()
            json_path = match.group(2).strip().strip("'\"")
            columns_def = match.group(3).strip()

            column_entries = self._parse_json_table_columns(columns_def)
            pg_columns = ", ".join(column_entries) if column_entries else columns_def

            if json_path == "$":
                return f"SELECT * FROM jsonb_to_recordset({json_data}) AS ({pg_columns})"
            return f"SELECT * FROM jsonb_to_recordset(jsonb_path_query_array({json_data}, '{json_path}')) AS ({pg_columns})"

        def replace_collection_table(match):
            collection_name = match.group(1).strip()
            json_path = match.group(2).strip().strip("'\"")
            return f"SELECT * FROM {collection_name}_collection WHERE jsonb_path_exists(document, '{json_path}')"

        result = self.json_table_pattern.sub(replace_json_table, sql)
        return self.json_table_collection_pattern.sub(replace_collection_table, result)

    @staticmethod
    def _parse_json_table_columns(columns_def: str) -> list[str]:
        """Parse JSON_TABLE COLUMNS definition into column entries."""
        entries = []
        for entry in columns_def.split(","):
            parts = entry.strip().split()
            if len(parts) >= 4 and "PATH" in parts:
                entries.append(f"{parts[0]} {parts[1]}")
        return entries

    def translate_docdb_filters(self, sql: str) -> str:
        """Translate IRIS Document Database filter operations."""

        def replace_docdb_filter(match):
            column, path, operator, value = (
                match.group(1),
                match.group(2),
                match.group(3),
                match.group(4).strip(),
            )
            pg_path = "{" + ",".join(path.split(".")) + "}"

            if operator.upper() == "CONTAINS":
                return f"{column} @> {value}"
            if operator.upper() == "LIKE":
                return f"({column} #>> '{pg_path}') LIKE {value}"
            return f"({column} #>> '{pg_path}') {operator} {value}"

        result = self.docdb_filter_pattern.sub(replace_docdb_filter, sql)

        # Handle JSON array filtering: column[*].field op value
        array_filter_pattern = re.compile(
            r"(\w+)\[\*\]\.(\w+)\s*(=|!=|<|>|<=|>=)\s*(.+)", re.IGNORECASE
        )

        def replace_array_filter(match):
            column, field = match.group(1), match.group(2)
            operator, value = match.group(3), match.group(4).strip()
            return f"jsonb_path_exists({column}, '$[*].{field} ? (@ {operator} {value})')"

        return array_filter_pattern.sub(replace_array_filter, result)

    def translate_json_path_operators(self, sql: str) -> str:
        """Translate IRIS JSON path operators to PostgreSQL equivalents."""
        simple_path_pattern = re.compile(r"(\w+)\.(\w+)(?!\s*\()", re.IGNORECASE)

        def replace_simple_path(match):
            return f"{match.group(1)}->>{match.group(2)}"

        return simple_path_pattern.sub(replace_simple_path, sql)

    def translate(self, sql: str) -> str:
        """Translate IRIS JSON functions, JSON_TABLE, and Document DB operations."""
        result = self.translate_json_table(sql)
        result = self.translate_docdb_filters(result)
        result = self.translate_json_path_operators(result)

        # Regular JSON function replacement with special JSON_LENGTH handling
        for iris_func, pg_func in self.FUNCTION_MAP.items():

            def replace_func(match, _iris=iris_func, _pg=pg_func):
                params = match.group(1)
                if _iris == "JSON_LENGTH":
                    return (
                        f"CASE WHEN jsonb_typeof({params}) = 'array' "
                        f"THEN jsonb_array_length({params}) "
                        f"ELSE jsonb_object_keys({params}) END"
                    )
                return f"{_pg}({params})"

            result = self.patterns[iris_func].sub(replace_func, result)

        return result


# ---------------------------------------------------------------------------
# Main coordinator
# ---------------------------------------------------------------------------

# Translation steps: (stat_key, translator_attr, construct_type, description)
_TRANSLATION_STEPS = [
    (
        "data_types",
        "data_type_translator",
        "DATA_TYPE",
        "IRIS data types mapped to PostgreSQL equivalents",
    ),
    (
        "sql_extensions",
        "sql_extension_translator",
        "SQL_EXTENSION",
        "IRIS SQL extensions (TOP, JOIN) mapped to PostgreSQL",
    ),
    (
        "system_functions",
        "system_function_translator",
        "SYSTEM_FUNCTION",
        "IRIS %SYSTEM.* functions mapped to PostgreSQL equivalents",
    ),
    (
        "iris_functions",
        "function_translator",
        "IRIS_FUNCTION",
        "IRIS functions (%SQLUPPER, %HOROLOG) mapped to PostgreSQL",
    ),
    (
        "json_functions",
        "json_function_translator",
        "JSON_FUNCTION",
        "IRIS JSON functions mapped to PostgreSQL JSONB equivalents",
    ),
]

# Quick-check patterns for IRIS constructs
_IRIS_DETECTION_PATTERNS = [
    r"%SYSTEM\.",
    r"\bTOP\s+\d+",
    r"%SQLUPPER|%SQLLOWER",
    r"DATEDIFF_MICROSECONDS",
    r"JSON_OBJECT|JSON_ARRAY|JSON_TABLE|JSON_VALUE|JSON_QUERY",
    r"JSON_EXISTS|JSON_MODIFY|JSON_REMOVE|JSON_LENGTH",
    r"JSON_ARRAYAGG|JSON_OBJECTAGG",
    r"\bSERIAL\b|\bROWVERSION\b|%List|%Stream",
    r"%PATTERN\.|%EXACT",
    r"%HOROLOG",
    r"%EXTERNAL|%INTERNAL",
]


class IRISConstructTranslator:
    """Main coordinator for all IRIS construct translations"""

    def __init__(self, debug_mode: bool = False, trace_level: TraceLevel = TraceLevel.STANDARD):
        self.system_function_translator = IRISSystemFunctionTranslator()
        self.sql_extension_translator = IRISSQLExtensionTranslator()
        self.function_translator = IRISFunctionTranslator()
        self.data_type_translator = IRISDataTypeTranslator()
        self.json_function_translator = IRISJSONFunctionTranslator()
        self.debug_mode = debug_mode
        self.trace_level = trace_level
        self.translation_stats = self._empty_stats()

    @staticmethod
    def _empty_stats() -> dict[str, int]:
        return {step[0]: 0 for step in _TRANSLATION_STEPS}

    def translate_sql(self, sql: str) -> tuple[str, dict[str, int]]:
        """Translate all IRIS constructs in SQL statement.

        Returns:
            Tuple of (translated_sql, translation_stats)
        """
        monitor = get_monitor()
        constructs_detected = 1 if self.needs_iris_translation(sql) else 0

        tracer, trace_id = None, None
        if self.debug_mode:
            tracer = get_tracer(self.trace_level)
            trace_id = tracer.start_trace(sql)

        try:
            with monitor.measure_translation(sql, constructs_detected) as measurement:
                self.translation_stats = self._empty_stats()

                if tracer:
                    tracer.add_parsing_step(
                        "pre_translation_analysis",
                        {"sql": sql, "length": len(sql)},
                        {"needs_translation": constructs_detected > 0},
                        0.1,
                        {"sql_type": "DDL" if "CREATE" in sql.upper() else "DML"},
                    )

                sql = self._apply_translation_steps(sql, tracer)

                total_constructs = sum(self.translation_stats.values())
                measurement["constructs_translated"] = total_constructs
                measurement["construct_types"] = self.translation_stats.copy()
                measurement["cache_hit"] = False

            if tracer:
                tracer.finish_trace(
                    translated_sql=sql,
                    constructs_detected=constructs_detected,
                    constructs_translated=total_constructs,
                    success=True,
                )

            return sql, self.translation_stats.copy()

        except Exception as e:
            if tracer:
                tracer.finish_trace(
                    translated_sql=sql if "sql" in locals() else "",
                    constructs_detected=constructs_detected,
                    constructs_translated=sum(self.translation_stats.values()),
                    success=False,
                    error_message=str(e),
                )
            raise

    def _apply_translation_steps(self, sql: str, tracer: Any | None) -> str:
        """Apply each translation step in order, tracking stats and traces."""
        for stat_key, translator_attr, construct_type, description in _TRANSLATION_STEPS:
            translator = getattr(self, translator_attr)
            original = sql

            start_time = time.perf_counter()
            sql = translator.translate(sql)
            duration_ms = (time.perf_counter() - start_time) * 1000

            if sql != original:
                self.translation_stats[stat_key] += 1
                if tracer:
                    tracer.add_mapping_decision(
                        f"{stat_key}_translation",
                        construct_type,
                        original,
                        sql,
                        "DIRECT_MAPPING",
                        1.0,
                        description,
                    )

            if tracer:
                tracer.add_parsing_step(f"{stat_key}_translation", original, sql, duration_ms)

        return sql

    def needs_iris_translation(self, sql: str) -> bool:
        """Check if SQL contains any IRIS-specific constructs."""
        return any(re.search(p, sql, re.IGNORECASE) for p in _IRIS_DETECTION_PATTERNS)

    def get_translation_summary(self) -> dict[str, Any]:
        """Get summary of translation statistics."""
        total = sum(self.translation_stats.values())
        return {
            "total_translations": total,
            "by_type": self.translation_stats.copy(),
            "most_common": (
                max(self.translation_stats.items(), key=lambda x: x[1]) if total > 0 else None
            ),
        }


# ---------------------------------------------------------------------------
# Custom PostgreSQL function definitions for IRIS compatibility
# ---------------------------------------------------------------------------


def create_custom_iris_functions() -> list[str]:
    """Generate SQL to create custom PostgreSQL functions for IRIS compatibility."""
    return [
        """
        CREATE OR REPLACE FUNCTION iris_sql_parallel_info()
        RETURNS INTEGER AS $$
        BEGIN
            RETURN COALESCE(current_setting('max_parallel_workers_per_gather')::INTEGER, 1);
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE OR REPLACE FUNCTION iris_ml_model_exists(model_name TEXT)
        RETURNS BOOLEAN AS $$
        BEGIN
            RETURN EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'ml_models' AND table_schema = 'information_schema'
            );
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE OR REPLACE FUNCTION iris_datediff_microseconds(date1 TIMESTAMP, date2 TIMESTAMP)
        RETURNS BIGINT AS $$
        BEGIN
            RETURN EXTRACT(EPOCH FROM (date2 - date1)) * 1000000;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE OR REPLACE FUNCTION iris_pattern_match(text_value TEXT, pattern TEXT)
        RETURNS BOOLEAN AS $$
        BEGIN
            RETURN text_value ~ pattern;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE OR REPLACE FUNCTION iris_json_valid(json_text TEXT)
        RETURNS BOOLEAN AS $$
        BEGIN
            BEGIN
                PERFORM json_text::jsonb;
                RETURN TRUE;
            EXCEPTION WHEN OTHERS THEN
                RETURN FALSE;
            END;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE OR REPLACE FUNCTION iris_external_format(value_text TEXT)
        RETURNS TEXT AS $$
        BEGIN
            RETURN value_text;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE OR REPLACE FUNCTION iris_internal_format(value_text TEXT)
        RETURNS TEXT AS $$
        BEGIN
            RETURN value_text;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE OR REPLACE FUNCTION iris_horolog()
        RETURNS TEXT AS $$
        BEGIN
            RETURN EXTRACT(EPOCH FROM NOW())::TEXT;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE OR REPLACE FUNCTION iris_datepart_timezone(ts TIMESTAMP)
        RETURNS TEXT AS $$
        BEGIN
            RETURN EXTRACT(TIMEZONE FROM ts)::TEXT;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE OR REPLACE FUNCTION iris_exact_match(text_value TEXT)
        RETURNS TEXT AS $$
        BEGIN
            RETURN text_value;
        END;
        $$ LANGUAGE plpgsql;
        """,
    ]
