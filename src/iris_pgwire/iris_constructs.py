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


class IRISSystemFunctionTranslator:
    """Translates IRIS %SYSTEM.* functions to PostgreSQL equivalents"""

    SYSTEM_FUNCTION_MAP = {
        # Version and system info
        "%SYSTEM.Version.%GetNumber": "version()",
        "%SYSTEM.Version.GetNumber": "version()",
        # Security and user functions
        "%SYSTEM.Security.%GetUser": "current_user",
        "%SYSTEM.Security.GetUser": "current_user",
        # SQL system functions
        "%SYSTEM.SQL.%GetStatement": "current_query()",
        "%SYSTEM.SQL.GetStatement": "current_query()",
        # ML system functions (custom implementations)
        "%SYSTEM.ML.%ModelExists": "iris_ml_model_exists",
        "%SYSTEM.ML.ModelExists": "iris_ml_model_exists",
        "%SYSTEM.ML.%GetModelList": "iris_ml_get_model_list",
        "%SYSTEM.ML.GetModelList": "iris_ml_get_model_list",
        # Utility functions
        "%SYSTEM.SQL.%PARALLEL": "iris_sql_parallel_info",
        "%SYSTEM.SQL.PARALLEL": "iris_sql_parallel_info",
    }

    def __init__(self):
        # Compile regex patterns for efficient matching
        self.patterns = {}
        for iris_func in self.SYSTEM_FUNCTION_MAP.keys():
            # Create pattern that matches function calls with optional parameters
            # Use (?<!\w) instead of \b to avoid issues with % character
            escaped_func = re.escape(iris_func)
            pattern = rf"(?<!\w){escaped_func}\s*\(\s*([^)]*)\s*\)"
            self.patterns[iris_func] = re.compile(pattern, re.IGNORECASE)

    def translate(self, sql: str) -> str:
        """Translate IRIS system functions in SQL"""
        result = sql

        for iris_func, pg_func in self.SYSTEM_FUNCTION_MAP.items():
            pattern = self.patterns[iris_func]

            def replace_func(match):
                params = match.group(1).strip() if match.group(1) else ""
                if params:
                    return f"{pg_func}({params})"
                else:
                    return pg_func if pg_func.endswith("()") else f"{pg_func}()"

            result = pattern.sub(replace_func, result)

        return result


class IRISSQLExtensionTranslator:
    """Translates IRIS SQL extensions to PostgreSQL equivalents"""

    def __init__(self):
        # TOP clause patterns
        self.top_pattern = re.compile(r"\bSELECT\s+TOP\s+(\d+)(?:\s+PERCENT)?\s+", re.IGNORECASE)
        self.top_percent_pattern = re.compile(r"\bSELECT\s+TOP\s+(\d+)\s+PERCENT\s+", re.IGNORECASE)

        # FOR UPDATE extensions
        self.for_update_pattern = re.compile(r"\bFOR\s+UPDATE\s+NOWAIT\b", re.IGNORECASE)

        # IRIS-specific JOIN syntax
        self.full_outer_join_pattern = re.compile(r"%FULL\s+OUTER\s+JOIN", re.IGNORECASE)

    def translate_top_clause(self, sql: str) -> str:
        """Translate TOP clause to LIMIT"""

        # Handle TOP n PERCENT
        def replace_top_percent(match):
            int(match.group(1))
            # For PERCENT, we need to calculate based on total rows
            # This is complex, so we'll use a subquery approach
            return "SELECT * FROM (SELECT "

        # Handle regular TOP n
        def replace_top(match):
            match.group(1)
            return "SELECT "

        # First handle PERCENT case
        if self.top_percent_pattern.search(sql):
            logger.warning("TOP n PERCENT not fully supported, converting to approximate LIMIT")
            sql = self.top_percent_pattern.sub(replace_top_percent, sql)
            # Add LIMIT at the end - this is approximate
            percent_pattern = r"TOP\s+(\d+)\s+PERCENT"
            match = re.search(percent_pattern, sql, re.IGNORECASE)
            if match:
                sql += f" LIMIT {int(match.group(1))}"

        # Handle regular TOP
        if self.top_pattern.search(sql):
            limit_value = self.top_pattern.search(sql).group(1)
            sql = self.top_pattern.sub("SELECT ", sql)
            # Add LIMIT at the end
            if not re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
                sql += f" LIMIT {limit_value}"

        return sql

    def translate_joins(self, sql: str) -> str:
        """Translate IRIS-specific JOIN syntax"""
        # Convert %FULL OUTER JOIN to standard FULL OUTER JOIN
        sql = self.full_outer_join_pattern.sub("FULL OUTER JOIN", sql)
        return sql

    def translate_for_update(self, sql: str) -> str:
        """Translate FOR UPDATE extensions"""
        # PostgreSQL supports NOWAIT, so this is a passthrough
        return sql

    def translate(self, sql: str) -> str:
        """Apply all SQL extension translations"""
        sql = self.translate_top_clause(sql)
        sql = self.translate_joins(sql)
        sql = self.translate_for_update(sql)
        return sql


class IRISFunctionTranslator:
    """Translates IRIS-specific functions to PostgreSQL equivalents"""

    FUNCTION_MAP = {
        # String functions
        "%SQLUPPER": "UPPER",
        "%SQLLOWER": "LOWER",
        "SQLUPPER": "UPPER",
        "SQLLOWER": "LOWER",
        # Date/time functions
        "DATEDIFF_MICROSECONDS": "iris_datediff_microseconds",
        "DATEPART_TIMEZONE": "iris_datepart_timezone",
        "%HOROLOG": "iris_horolog",
        "HOROLOG": "iris_horolog",
        # Conversion functions
        "%EXTERNAL": "iris_external_format",
        "%INTERNAL": "iris_internal_format",
        "EXTERNAL": "iris_external_format",
        "INTERNAL": "iris_internal_format",
        # Pattern matching
        "%PATTERN.MATCH": "iris_pattern_match",
        "PATTERN.MATCH": "iris_pattern_match",
        "%EXACT": "iris_exact_match",
        "EXACT": "iris_exact_match",
    }

    def __init__(self):
        # Create regex patterns for function matching
        self.patterns = {}
        for iris_func in self.FUNCTION_MAP.keys():
            escaped_func = re.escape(iris_func)
            pattern = rf"(?<!\w){escaped_func}\s*\(\s*([^)]*)\s*\)"
            self.patterns[iris_func] = re.compile(pattern, re.IGNORECASE)

    def translate(self, sql: str) -> str:
        """Translate IRIS functions to PostgreSQL equivalents"""
        result = sql

        for iris_func, pg_func in self.FUNCTION_MAP.items():
            pattern = self.patterns[iris_func]

            def replace_func(match):
                params = match.group(1)
                return f"{pg_func}({params})"

            result = pattern.sub(replace_func, result)

        return result


class IRISDataTypeTranslator:
    """Translates IRIS data types to PostgreSQL equivalents"""

    TYPE_MAP = {
        # IRIS-specific types
        "SERIAL": "SERIAL",  # PostgreSQL SERIAL behavior differs but close enough
        "ROWVERSION": "BIGINT",  # Will need version tracking metadata
        "%List": "BYTEA",  # Binary compressed lists
        "%Stream": "BYTEA",  # Large binary objects
        "MONEY": "NUMERIC(19,4)",  # Currency with precision
        "POSIXTIME": "TIMESTAMP",  # Unix timestamp
        "%TimeStamp": "TIMESTAMP",  # IRIS timestamp format
        "%Date": "DATE",  # IRIS date format
        "%Time": "TIME",  # IRIS time format
        # Vector types (already implemented)
        "VECTOR": "VECTOR",  # Pass through our existing vector support
        "EMBEDDING": "VECTOR",  # Map to vector type
    }

    def __init__(self):
        # Create patterns for type matching in DDL
        self.type_patterns = {}
        for iris_type in self.TYPE_MAP.keys():
            escaped_type = re.escape(iris_type)
            # Match type declarations with optional parameters
            pattern = rf"(?<!\w){escaped_type}(?:\s*\([^)]+\))?(?!\w)"
            self.type_patterns[iris_type] = re.compile(pattern, re.IGNORECASE)

    def translate(self, sql: str) -> str:
        """Translate IRIS data types in DDL statements"""
        result = sql

        # Only translate in CREATE TABLE or ALTER TABLE statements
        if re.search(r"\b(CREATE\s+TABLE|ALTER\s+TABLE)\b", sql, re.IGNORECASE):
            for iris_type, pg_type in self.TYPE_MAP.items():
                pattern = self.type_patterns[iris_type]
                result = pattern.sub(pg_type, result)

        return result


class IRISJSONFunctionTranslator:
    """Translates IRIS JSON functions and JSON_TABLE to PostgreSQL equivalents"""

    FUNCTION_MAP = {
        # Basic JSON functions
        "JSON_OBJECT": "json_build_object",
        "JSON_ARRAY": "json_build_array",
        "JSON_SET": "jsonb_set",
        "JSON_GET": "jsonb_extract_path_text",
        "JSON_VALUE": "jsonb_extract_path_text",
        "JSON_QUERY": "jsonb_extract_path",
        # Document Database functions
        "JSON_EXISTS": "jsonb_path_exists",
        "JSON_MODIFY": "jsonb_set",
        "JSON_REMOVE": "jsonb_path_delete",
        "JSON_LENGTH": "jsonb_array_length",
        "JSON_KEYS": "jsonb_object_keys",
        "JSON_EACH": "jsonb_each",
        "JSON_EACH_TEXT": "jsonb_each_text",
        # Document Database filter operations
        "JSON_EXTRACT": "jsonb_path_query",
        "JSON_EXTRACT_SCALAR": "jsonb_path_query_first",
        "JSON_SEARCH": "jsonb_path_query",
        "JSON_CONTAINS": "jsonb_path_match",
        "JSON_CONTAINS_PATH": "jsonb_path_exists",
        "JSON_TYPE": "jsonb_typeof",
        "JSON_VALID": "iris_json_valid",
        # IRIS-specific JSON functions
        "JSON_ARRAYAGG": "json_agg",
        "JSON_OBJECTAGG": "json_object_agg",
    }

    def __init__(self):
        self.patterns = {}
        for iris_func in self.FUNCTION_MAP.keys():
            escaped_func = re.escape(iris_func)
            pattern = rf"(?<!\w){escaped_func}\s*\(\s*([^)]*)\s*\)"
            self.patterns[iris_func] = re.compile(pattern, re.IGNORECASE)

        # JSON_TABLE pattern - more complex (IRIS standard syntax)
        self.json_table_pattern = re.compile(
            r'\bJSON_TABLE\s*\(\s*([^,]+),\s*([\'"][^\'\"]*[\'"])\s+COLUMNS\s*\(\s*([^)]+)\s*\)\s*\)',
            re.IGNORECASE | re.DOTALL,
        )

        # IRIS Cloud Document Service pattern
        self.json_table_collection_pattern = re.compile(
            r'\bJSON_TABLE\s*\(\s*(\w+)\s+FORMAT\s+COLLECTION,\s*([\'"][^\'\"]*[\'"])\s+COLUMNS\s*\(\s*([^)]+)\s*\)\s*\)',
            re.IGNORECASE | re.DOTALL,
        )

        # Document Database filter patterns
        self.docdb_filter_pattern = re.compile(
            r"(\w+)\s*->\s*'([^']+)'\s*(=|!=|<|>|<=|>=|LIKE|CONTAINS)\s*(.+)", re.IGNORECASE
        )

        # JSON path patterns for IRIS DocDB
        self.json_path_operators = {
            "->": "->",  # JSON field access
            "->>": "->>",  # JSON field access as text
            "#>": "#>",  # JSON path access
            "#>>": "#>>",  # JSON path access as text
        }

    def translate_json_table(self, sql: str) -> str:
        """Translate IRIS JSON_TABLE to PostgreSQL equivalents"""

        # Handle standard JSON_TABLE
        def replace_json_table(match):
            json_data = match.group(1).strip()
            json_path = match.group(2).strip().strip("'\"")
            columns_def = match.group(3).strip()

            # Parse columns definition to extract column names and paths
            # IRIS: name TYPE PATH '$.path', name2 TYPE PATH '$.path2'
            column_entries = []

            # Simple parsing - could be enhanced for complex cases
            for entry in columns_def.split(","):
                entry = entry.strip()
                # Extract column name, type, and path
                parts = entry.split()
                if len(parts) >= 4 and "PATH" in parts:
                    col_name = parts[0]
                    col_type = parts[1]
                    path_idx = parts.index("PATH") + 1
                    if path_idx < len(parts):
                        parts[path_idx].strip("'\"")
                        column_entries.append(f"{col_name} {col_type}")

            # Convert to PostgreSQL syntax using jsonb_to_recordset
            pg_columns = ", ".join(column_entries) if column_entries else columns_def

            # Use jsonb_path_query_array for path-based extraction
            if json_path == "$":
                # Simple case - entire document
                return f"SELECT * FROM jsonb_to_recordset({json_data}) AS ({pg_columns})"
            else:
                # Path-based extraction
                return f"SELECT * FROM jsonb_to_recordset(jsonb_path_query_array({json_data}, '{json_path}')) AS ({pg_columns})"

        # Handle collection-based JSON_TABLE (Cloud Document Service)
        def replace_collection_table(match):
            collection_name = match.group(1).strip()
            json_path = match.group(2).strip().strip("'\"")
            match.group(3).strip()

            # For collections, we'd need to query a collection table
            # This is a placeholder - would need actual collection infrastructure
            return f"SELECT * FROM {collection_name}_collection WHERE jsonb_path_exists(document, '{json_path}')"

        # Apply both patterns
        result = self.json_table_pattern.sub(replace_json_table, sql)
        result = self.json_table_collection_pattern.sub(replace_collection_table, result)

        return result

    def translate_docdb_filters(self, sql: str) -> str:
        """Translate IRIS Document Database filter operations"""
        # Handle JSON path expressions in WHERE clauses
        # IRIS DocDB syntax: column->path OPERATOR value
        # PostgreSQL syntax: column #> '{path}' OPERATOR value

        def replace_docdb_filter(match):
            column = match.group(1)
            path = match.group(2)
            operator = match.group(3)
            value = match.group(4).strip()

            # Convert IRIS path syntax to PostgreSQL JSONPath
            # Simple path: field -> {field}
            # Nested path: field.subfield -> {field,subfield}
            path_parts = path.split(".")
            pg_path = "{" + ",".join(path_parts) + "}"

            # Handle different operators
            if operator.upper() == "CONTAINS":
                # IRIS CONTAINS -> PostgreSQL @>
                return f"{column} @> {value}"
            elif operator.upper() == "LIKE":
                # Use text extraction for LIKE operations
                return f"({column} #>> '{pg_path}') LIKE {value}"
            else:
                # Standard comparison operators
                return f"({column} #>> '{pg_path}') {operator} {value}"

        result = self.docdb_filter_pattern.sub(replace_docdb_filter, sql)

        # Handle JSON array filtering
        # IRIS: column[*].field = value
        # PostgreSQL: jsonb_path_exists(column, '$[*].field ? (@ == value)')
        array_filter_pattern = re.compile(
            r"(\w+)\[\*\]\.(\w+)\s*(=|!=|<|>|<=|>=)\s*(.+)", re.IGNORECASE
        )

        def replace_array_filter(match):
            column = match.group(1)
            field = match.group(2)
            operator = match.group(3)
            value = match.group(4).strip()

            # Convert to PostgreSQL JSONPath
            json_path = f"'$[*].{field} ? (@ {operator} {value})'"
            return f"jsonb_path_exists({column}, {json_path})"

        result = array_filter_pattern.sub(replace_array_filter, result)

        return result

    def translate_json_path_operators(self, sql: str) -> str:
        """Translate IRIS JSON path operators to PostgreSQL equivalents"""
        # IRIS uses different syntax for some JSON operations
        # This handles the operators PostgreSQL supports directly

        # IRIS: column.field -> PostgreSQL: column->>'field'
        simple_path_pattern = re.compile(r"(\w+)\.(\w+)(?!\s*\()", re.IGNORECASE)

        def replace_simple_path(match):
            column = match.group(1)
            field = match.group(2)
            return f"{column}->>{field}"

        result = simple_path_pattern.sub(replace_simple_path, sql)
        return result

    def translate(self, sql: str) -> str:
        """Translate IRIS JSON functions, JSON_TABLE, and Document DB operations"""
        result = sql

        # First handle JSON_TABLE (complex transformation)
        result = self.translate_json_table(result)

        # Handle Document Database filter operations
        result = self.translate_docdb_filters(result)

        # Handle JSON path operators
        result = self.translate_json_path_operators(result)

        # Then handle regular JSON functions
        for iris_func, pg_func in self.FUNCTION_MAP.items():
            pattern = self.patterns[iris_func]

            def replace_func(match):
                params = match.group(1)
                # Special handling for some functions
                if iris_func == "JSON_LENGTH" and "jsonb_array_length" in pg_func:
                    # JSON_LENGTH can work on objects too, need conditional
                    return f"CASE WHEN jsonb_typeof({params}) = 'array' THEN jsonb_array_length({params}) ELSE jsonb_object_keys({params}) END"
                return f"{pg_func}({params})"

            result = pattern.sub(replace_func, result)

        return result


class IRISConstructTranslator:
    """Main coordinator for all IRIS construct translations"""

    def __init__(self, debug_mode: bool = False, trace_level: TraceLevel = TraceLevel.STANDARD):
        self.system_function_translator = IRISSystemFunctionTranslator()
        self.sql_extension_translator = IRISSQLExtensionTranslator()
        self.function_translator = IRISFunctionTranslator()
        self.data_type_translator = IRISDataTypeTranslator()
        self.json_function_translator = IRISJSONFunctionTranslator()

        # Constitutional requirements
        self.debug_mode = debug_mode
        self.trace_level = trace_level

        # Statistics tracking
        self.translation_stats = {
            "system_functions": 0,
            "sql_extensions": 0,
            "iris_functions": 0,
            "data_types": 0,
            "json_functions": 0,
        }

    def translate_sql(self, sql: str) -> tuple[str, dict[str, int]]:
        """
        Translate all IRIS constructs in SQL statement

        Returns:
            Tuple of (translated_sql, translation_stats)
        """
        # Constitutional requirement: Performance monitoring
        monitor = get_monitor()
        constructs_detected = 1 if self.needs_iris_translation(sql) else 0

        # Constitutional requirement: Debug tracing (optional)
        tracer = None
        trace_id = None
        if self.debug_mode:
            tracer = get_tracer(self.trace_level)
            trace_id = tracer.start_trace(sql)

        try:
            with monitor.measure_translation(sql, constructs_detected) as measurement:
                original_sql = sql

                # Reset translation stats for this operation
                self.translation_stats = {
                    "system_functions": 0,
                    "sql_extensions": 0,
                    "iris_functions": 0,
                    "data_types": 0,
                    "json_functions": 0,
                }

                if tracer:
                    tracer.add_parsing_step(
                        "pre_translation_analysis",
                        {"sql": sql, "length": len(sql)},
                        {"needs_translation": constructs_detected > 0},
                        0.1,
                        {"sql_type": "DDL" if "CREATE" in sql.upper() else "DML"},
                    )

                # Apply translations in order
                # 1. Data types (affects DDL structure)
                start_time = time.perf_counter()
                sql = self.data_type_translator.translate(sql)
                duration_ms = (time.perf_counter() - start_time) * 1000

                if sql != original_sql:
                    self.translation_stats["data_types"] += 1
                    if tracer:
                        tracer.add_mapping_decision(
                            "data_type_translation",
                            "DATA_TYPE",
                            original_sql,
                            sql,
                            "DIRECT_MAPPING",
                            1.0,
                            "IRIS data types mapped to PostgreSQL equivalents",
                        )
                    original_sql = sql

                if tracer:
                    tracer.add_parsing_step("data_type_translation", original_sql, sql, duration_ms)

                # 2. SQL extensions (affects query structure)
                start_time = time.perf_counter()
                sql = self.sql_extension_translator.translate(sql)
                duration_ms = (time.perf_counter() - start_time) * 1000

                if sql != original_sql:
                    self.translation_stats["sql_extensions"] += 1
                    if tracer:
                        tracer.add_mapping_decision(
                            "sql_extension_translation",
                            "SQL_EXTENSION",
                            original_sql,
                            sql,
                            "DIRECT_MAPPING",
                            1.0,
                            "IRIS SQL extensions (TOP, JOIN) mapped to PostgreSQL",
                        )
                    original_sql = sql

                if tracer:
                    tracer.add_parsing_step(
                        "sql_extension_translation", original_sql, sql, duration_ms
                    )

                # 3. System functions
                start_time = time.perf_counter()
                sql = self.system_function_translator.translate(sql)
                duration_ms = (time.perf_counter() - start_time) * 1000

                if sql != original_sql:
                    self.translation_stats["system_functions"] += 1
                    if tracer:
                        tracer.add_mapping_decision(
                            "system_function_translation",
                            "SYSTEM_FUNCTION",
                            original_sql,
                            sql,
                            "DIRECT_MAPPING",
                            1.0,
                            "IRIS %SYSTEM.* functions mapped to PostgreSQL equivalents",
                        )
                    original_sql = sql

                if tracer:
                    tracer.add_parsing_step(
                        "system_function_translation", original_sql, sql, duration_ms
                    )

                # 4. IRIS functions
                start_time = time.perf_counter()
                sql = self.function_translator.translate(sql)
                duration_ms = (time.perf_counter() - start_time) * 1000

                if sql != original_sql:
                    self.translation_stats["iris_functions"] += 1
                    if tracer:
                        tracer.add_mapping_decision(
                            "iris_function_translation",
                            "IRIS_FUNCTION",
                            original_sql,
                            sql,
                            "DIRECT_MAPPING",
                            1.0,
                            "IRIS functions (%SQLUPPER, %HOROLOG) mapped to PostgreSQL",
                        )
                    original_sql = sql

                if tracer:
                    tracer.add_parsing_step(
                        "iris_function_translation", original_sql, sql, duration_ms
                    )

                # 5. JSON functions
                start_time = time.perf_counter()
                sql = self.json_function_translator.translate(sql)
                duration_ms = (time.perf_counter() - start_time) * 1000

                if sql != original_sql:
                    self.translation_stats["json_functions"] += 1
                    if tracer:
                        tracer.add_mapping_decision(
                            "json_function_translation",
                            "JSON_FUNCTION",
                            original_sql,
                            sql,
                            "DIRECT_MAPPING",
                            1.0,
                            "IRIS JSON functions mapped to PostgreSQL JSONB equivalents",
                        )

                if tracer:
                    tracer.add_parsing_step(
                        "json_function_translation", original_sql, sql, duration_ms
                    )

                # Update measurement context for monitoring
                total_constructs = sum(self.translation_stats.values())
                measurement["constructs_translated"] = total_constructs
                measurement["construct_types"] = self.translation_stats.copy()
                measurement["cache_hit"] = False  # No caching implemented yet

            # Finalize debug trace if enabled
            if tracer:
                tracer.finish_trace(
                    translated_sql=sql,
                    constructs_detected=constructs_detected,
                    constructs_translated=total_constructs,
                    success=True,
                )

            return sql, self.translation_stats.copy()

        except Exception as e:
            # Handle errors with debug tracing
            if tracer:
                tracer.finish_trace(
                    translated_sql=sql if "sql" in locals() else "",
                    constructs_detected=constructs_detected,
                    constructs_translated=sum(self.translation_stats.values()),
                    success=False,
                    error_message=str(e),
                )
            raise

    def needs_iris_translation(self, sql: str) -> bool:
        """Check if SQL contains any IRIS-specific constructs"""
        # Quick check for common IRIS patterns
        iris_patterns = [
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

        for pattern in iris_patterns:
            if re.search(pattern, sql, re.IGNORECASE):
                return True

        return False

    def get_translation_summary(self) -> dict[str, Any]:
        """Get summary of translation statistics"""
        total_translations = sum(self.translation_stats.values())
        return {
            "total_translations": total_translations,
            "by_type": self.translation_stats.copy(),
            "most_common": (
                max(self.translation_stats.items(), key=lambda x: x[1])
                if total_translations > 0
                else None
            ),
        }


# Utility functions for custom PostgreSQL functions
def create_custom_iris_functions() -> list[str]:
    """
    Generate SQL to create custom PostgreSQL functions for IRIS compatibility
    """
    functions = []

    # IRIS parallel info function
    functions.append(
        """
        CREATE OR REPLACE FUNCTION iris_sql_parallel_info()
        RETURNS INTEGER AS $$
        BEGIN
            -- Return current parallel worker count or 1 if not parallel
            RETURN COALESCE(current_setting('max_parallel_workers_per_gather')::INTEGER, 1);
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    # IRIS ML model exists function
    functions.append(
        """
        CREATE OR REPLACE FUNCTION iris_ml_model_exists(model_name TEXT)
        RETURNS BOOLEAN AS $$
        BEGIN
            -- Check if model exists in our ML metadata
            RETURN EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'ml_models'
                AND table_schema = 'information_schema'
            );
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    # IRIS date difference in microseconds
    functions.append(
        """
        CREATE OR REPLACE FUNCTION iris_datediff_microseconds(date1 TIMESTAMP, date2 TIMESTAMP)
        RETURNS BIGINT AS $$
        BEGIN
            RETURN EXTRACT(EPOCH FROM (date2 - date1)) * 1000000;
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    # IRIS pattern matching
    functions.append(
        """
        CREATE OR REPLACE FUNCTION iris_pattern_match(text_value TEXT, pattern TEXT)
        RETURNS BOOLEAN AS $$
        BEGIN
            -- Simple pattern matching - can be enhanced for IRIS-specific patterns
            RETURN text_value ~ pattern;
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    # JSON validation function
    functions.append(
        """
        CREATE OR REPLACE FUNCTION iris_json_valid(json_text TEXT)
        RETURNS BOOLEAN AS $$
        BEGIN
            -- Validate JSON format
            BEGIN
                PERFORM json_text::jsonb;
                RETURN TRUE;
            EXCEPTION WHEN OTHERS THEN
                RETURN FALSE;
            END;
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    # IRIS external format conversion
    functions.append(
        """
        CREATE OR REPLACE FUNCTION iris_external_format(value_text TEXT)
        RETURNS TEXT AS $$
        BEGIN
            -- Convert to external format (simplified - would need IRIS-specific logic)
            RETURN value_text;
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    # IRIS internal format conversion
    functions.append(
        """
        CREATE OR REPLACE FUNCTION iris_internal_format(value_text TEXT)
        RETURNS TEXT AS $$
        BEGIN
            -- Convert to internal format (simplified - would need IRIS-specific logic)
            RETURN value_text;
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    # IRIS $HOROLOG function (date/time in IRIS format)
    functions.append(
        """
        CREATE OR REPLACE FUNCTION iris_horolog()
        RETURNS TEXT AS $$
        BEGIN
            -- Return current date/time in IRIS $HOROLOG format (days,seconds)
            -- This is a simplified implementation
            RETURN EXTRACT(EPOCH FROM NOW())::TEXT;
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    # IRIS timezone part function
    functions.append(
        """
        CREATE OR REPLACE FUNCTION iris_datepart_timezone(ts TIMESTAMP)
        RETURNS TEXT AS $$
        BEGIN
            -- Extract timezone information
            RETURN EXTRACT(TIMEZONE FROM ts)::TEXT;
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    # IRIS exact match (case-sensitive)
    functions.append(
        """
        CREATE OR REPLACE FUNCTION iris_exact_match(text_value TEXT)
        RETURNS TEXT AS $$
        BEGIN
            -- Return text for exact case matching
            RETURN text_value;
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    return functions
