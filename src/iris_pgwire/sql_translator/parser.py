"""
SQL Parser Implementation

Parses SQL statements to identify IRIS constructs and prepare for translation.
Uses sqlparse for basic parsing with custom extensions for IRIS-specific syntax.

Constitutional Compliance: Accurate parsing within 5ms SLA requirement.
"""

import re
from dataclasses import dataclass
from typing import Any

import sqlparse
from sqlparse import tokens as T

from .models import (
    ConstructType,
    DebugTrace,
    ErrorCode,
    PerformanceTimer,
    SourceLocation,
    TranslationError,
)


@dataclass
class ParsedConstruct:
    """A parsed IRIS construct found in SQL"""

    construct_type: ConstructType
    original_text: str
    location: SourceLocation
    parameters: list[str]
    metadata: dict[str, Any]


class IRISSQLParser:
    """Parser for IRIS SQL statements with construct identification"""

    def __init__(self):
        self._function_patterns = self._compile_function_patterns()
        self._construct_patterns = self._compile_construct_patterns()
        self._system_function_patterns = self._compile_system_function_patterns()

    def _compile_function_patterns(self) -> dict[str, re.Pattern]:
        """Compile regex patterns for IRIS function detection"""
        patterns = {}

        # SQL functions with % prefix
        sql_functions = [
            "SQLUPPER",
            "SQLLOWER",
            "SQLSTRING",
            "SQLSUBSTRING",
            "SQLLENGTH",
            "SQLREPLACE",
            "SQLTRIM",
            "SQLLPAD",
            "SQLRPAD",
            "SQLABS",
            "SQLCEILING",
            "SQLFLOOR",
            "SQLROUND",
            "SQLSQRT",
            "SQLPOWER",
            "SQLLOG",
            "SQLEXP",
            "SQLSIN",
            "SQLCOS",
            "SQLTAN",
            "SQLCAST",
            "SQLCONVERT",
            "SQLISNULL",
            "SQLNULLIF",
            "SQLCOUNT",
            "SQLSUM",
            "SQLAVG",
            "SQLMIN",
            "SQLMAX",
            "SQLSTDEV",
            "SQLVAR",
        ]

        for func in sql_functions:
            # Use negative lookbehind to avoid word boundary issues with %
            pattern = rf"(?<!\w)%{func}\s*\(\s*([^)]*)\s*\)"
            patterns[f"%{func}"] = re.compile(pattern, re.IGNORECASE)

        # JSON functions
        json_functions = [
            "JSON_OBJECT",
            "JSON_EXTRACT",
            "JSON_ARRAY",
            "JSON_TABLE",
            "JSON_ARRAY_LENGTH",
            "JSON_ARRAY_ELEMENTS",
            "JSON_EXISTS",
            "JSON_QUERY",
            "JSON_VALUE",
        ]
        for func in json_functions:
            pattern = rf"\b{func}\s*\(\s*([^)]*)\s*\)"
            patterns[func] = re.compile(pattern, re.IGNORECASE)

        return patterns

    def _compile_system_function_patterns(self) -> dict[str, re.Pattern]:
        """Compile regex patterns for IRIS system function detection"""
        patterns = {}

        # Common IRIS system functions
        system_functions = [
            "%SYSTEM.Version.GetNumber",
            "%SYSTEM.Security.GetUser",
            "%SYSTEM.SQL.GETDATE",
            "%SYSTEM.Process.GetPID",
            "%SYSTEM.SQL.GetStatement",
        ]

        for func in system_functions:
            # Escape dots for regex and use negative lookbehind
            escaped_func = func.replace(".", r"\.")
            pattern = rf"(?<!\w){escaped_func}\s*\(\s*([^)]*)\s*\)"
            patterns[func] = re.compile(pattern, re.IGNORECASE)

        return patterns

    def _compile_construct_patterns(self) -> dict[str, re.Pattern]:
        """Compile regex patterns for IRIS SQL construct detection"""
        patterns = {}

        # TOP clause patterns
        patterns["TOP_BASIC"] = re.compile(r"\bSELECT\s+TOP\s+(\d+)\s+", re.IGNORECASE)
        patterns["TOP_PERCENT"] = re.compile(
            r"\bSELECT\s+TOP\s+(\d+(?:\.\d+)?)\s+PERCENT\s+", re.IGNORECASE
        )
        patterns["TOP_WITH_TIES"] = re.compile(
            r"\bSELECT\s+TOP\s+(\d+)\s+WITH\s+TIES\s+", re.IGNORECASE
        )

        # Other IRIS constructs
        patterns["ROWNUM"] = re.compile(r"\b%ROWNUM\b", re.IGNORECASE)
        patterns["DECODE"] = re.compile(r"\bDECODE\s*\(", re.IGNORECASE)
        patterns["IIF"] = re.compile(r"\bIIF\s*\(", re.IGNORECASE)
        patterns["MINUS"] = re.compile(r"\bMINUS\b", re.IGNORECASE)
        patterns["INDEX_IF_NOT_EXISTS"] = re.compile(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS", re.IGNORECASE
        )

        # Data type patterns
        patterns["IRIS_TYPES"] = re.compile(r"\b%\w+\b", re.IGNORECASE)

        return patterns

    def parse(
        self, sql: str, debug_mode: bool = False
    ) -> tuple[list[ParsedConstruct], DebugTrace | None]:
        """
        Parse SQL statement and identify IRIS constructs

        Args:
            sql: SQL statement to parse
            debug_mode: Whether to generate debug trace

        Returns:
            Tuple of (parsed_constructs, debug_trace)
        """
        debug_trace = DebugTrace() if debug_mode else None
        constructs = []

        try:
            with PerformanceTimer() as timer:
                # Step 1: Basic SQL parsing with sqlparse
                if debug_mode:
                    debug_trace.add_parsing_step(
                        "basic_parsing", sql, sql, 0.0, input_length=len(sql)
                    )

                parsed_statements = sqlparse.parse(sql)

                if not parsed_statements:
                    return constructs, debug_trace

                # Step 2: Identify IRIS functions
                constructs.extend(self._identify_functions(sql, debug_trace))

                # Step 3: Identify IRIS system functions
                constructs.extend(self._identify_system_functions(sql, debug_trace))

                # Step 4: Identify IRIS SQL constructs
                constructs.extend(self._identify_sql_constructs(sql, debug_trace))

                # Step 5: Identify data types
                constructs.extend(self._identify_data_types(sql, debug_trace))

                # Step 6: Validate parsing completeness
                self._validate_parsing(sql, constructs, debug_trace)

            if debug_mode:
                debug_trace.add_parsing_step(
                    "parsing_complete", sql, sql, timer.elapsed_ms, constructs_found=len(constructs)
                )

        except Exception as e:
            error_msg = f"SQL parsing failed: {str(e)}"
            if debug_trace:
                debug_trace.add_warning(error_msg)
            raise TranslationError(
                error_code=ErrorCode.PARSE_ERROR, message=error_msg, original_sql=sql
            )

        return constructs, debug_trace

    def _identify_functions(
        self, sql: str, debug_trace: DebugTrace | None
    ) -> list[ParsedConstruct]:
        """Identify IRIS functions in SQL"""
        constructs = []

        for func_name, pattern in self._function_patterns.items():
            matches = pattern.finditer(sql)

            for match in matches:
                location = self._create_source_location(sql, match)
                parameters = self._parse_function_parameters(match.group(1))

                # Determine construct type based on function name
                # JSON functions that are document operations should be DOCUMENT_FILTER
                document_filter_functions = {
                    "JSON_EXTRACT",
                    "JSON_ARRAY_LENGTH",
                    "JSON_ARRAY_ELEMENTS",
                    "JSON_EXISTS",
                    "JSON_QUERY",
                    "JSON_VALUE",
                }

                if func_name in document_filter_functions:
                    construct_type = ConstructType.DOCUMENT_FILTER
                elif func_name.startswith("JSON_"):
                    construct_type = ConstructType.JSON_FUNCTION
                else:
                    construct_type = ConstructType.FUNCTION

                construct = ParsedConstruct(
                    construct_type=construct_type,
                    original_text=match.group(0),
                    location=location,
                    parameters=parameters,
                    metadata={"function_name": func_name, "parameter_count": len(parameters)},
                )
                constructs.append(construct)

                if debug_trace:
                    debug_trace.add_parsing_step(
                        f"function_detected_{func_name}",
                        match.group(0),
                        match.group(0),
                        0.1,
                        function_name=func_name,
                        parameter_count=len(parameters),
                    )

        return constructs

    def _identify_system_functions(
        self, sql: str, debug_trace: DebugTrace | None
    ) -> list[ParsedConstruct]:
        """Identify IRIS system functions in SQL"""
        constructs = []

        for func_name, pattern in self._system_function_patterns.items():
            matches = pattern.finditer(sql)

            for match in matches:
                location = self._create_source_location(sql, match)
                parameters = self._parse_function_parameters(match.group(1))

                construct = ParsedConstruct(
                    construct_type=ConstructType.SYSTEM_FUNCTION,
                    original_text=match.group(0),
                    location=location,
                    parameters=parameters,
                    metadata={
                        "system_function_name": func_name,
                        "parameter_count": len(parameters),
                    },
                )
                constructs.append(construct)

                if debug_trace:
                    debug_trace.add_parsing_step(
                        f"system_function_detected_{func_name.replace('.', '_')}",
                        match.group(0),
                        match.group(0),
                        0.1,
                        system_function_name=func_name,
                        parameter_count=len(parameters),
                    )

        return constructs

    def _identify_sql_constructs(
        self, sql: str, debug_trace: DebugTrace | None
    ) -> list[ParsedConstruct]:
        """Identify IRIS SQL syntax constructs"""
        constructs = []

        for construct_name, pattern in self._construct_patterns.items():
            matches = pattern.finditer(sql)

            for match in matches:
                location = self._create_source_location(sql, match)

                # Extract parameters based on construct type
                parameters = []
                if construct_name.startswith("TOP"):
                    if match.groups():
                        parameters = [match.group(1)]

                construct_type = self._determine_construct_type(construct_name)

                construct = ParsedConstruct(
                    construct_type=construct_type,
                    original_text=match.group(0),
                    location=location,
                    parameters=parameters,
                    metadata={"construct_name": construct_name, "pattern_matched": True},
                )
                constructs.append(construct)

                if debug_trace:
                    debug_trace.add_parsing_step(
                        f"construct_detected_{construct_name}",
                        match.group(0),
                        match.group(0),
                        0.1,
                        construct_name=construct_name,
                        parameter_count=len(parameters),
                    )

        return constructs

    def _identify_data_types(
        self, sql: str, debug_trace: DebugTrace | None
    ) -> list[ParsedConstruct]:
        """Identify IRIS data types in SQL"""
        constructs = []

        # Look for IRIS-specific data types (starting with %)
        iris_type_pattern = self._construct_patterns["IRIS_TYPES"]
        matches = iris_type_pattern.finditer(sql)

        for match in matches:
            type_text = match.group(0)

            # Skip if it's already identified as a function
            if any(
                type_text.upper().endswith(f) for f in ["(", "SQLUPPER", "SQLLOWER", "SQLSTRING"]
            ):
                continue

            # Check if it looks like a data type
            if self._is_iris_data_type(type_text):
                location = self._create_source_location(sql, match)

                construct = ParsedConstruct(
                    construct_type=ConstructType.DATA_TYPE,
                    original_text=type_text,
                    location=location,
                    parameters=[],
                    metadata={"type_name": type_text, "iris_specific": True},
                )
                constructs.append(construct)

                if debug_trace:
                    debug_trace.add_parsing_step(
                        f"datatype_detected_{type_text}",
                        type_text,
                        type_text,
                        0.1,
                        type_name=type_text,
                    )

        # Also look for standard SQL types that need translation to PostgreSQL
        standard_types_pattern = re.compile(
            r"\b(LONGVARCHAR|LONGVARBINARY|VARBINARY|CLOB|BLOB|TINYINT|REAL|DOUBLE)\b",
            re.IGNORECASE,
        )

        for match in standard_types_pattern.finditer(sql):
            type_text = match.group(0).upper()

            # Check if this type has a mapping in the datatype registry
            # Import here to avoid circular imports
            from .mappings.datatypes import get_datatype_registry

            registry = get_datatype_registry()

            if registry.has_mapping(type_text):
                location = self._create_source_location(sql, match)

                construct = ParsedConstruct(
                    construct_type=ConstructType.DATA_TYPE,
                    original_text=type_text,
                    location=location,
                    parameters=[],
                    metadata={
                        "type_name": type_text,
                        "iris_specific": False,
                        "standard_sql_type": True,
                    },
                )
                constructs.append(construct)

                if debug_trace:
                    debug_trace.add_parsing_step(
                        f"standard_datatype_detected_{type_text}",
                        type_text,
                        type_text,
                        0.1,
                        type_name=type_text,
                        standard_sql_type=True,
                    )

        return constructs

    def _create_source_location(self, sql: str, match: re.Match) -> SourceLocation:
        """Create source location from regex match"""
        start_pos = match.start()
        text_before = sql[:start_pos]

        line = text_before.count("\n") + 1
        column = len(text_before.split("\n")[-1]) + 1
        length = len(match.group(0))

        return SourceLocation(line=line, column=column, length=length, original_text=match.group(0))

    def _parse_function_parameters(self, param_str: str) -> list[str]:
        """Parse function parameters from parameter string"""
        if not param_str or not param_str.strip():
            return []

        # Simple parameter parsing - split by commas outside parentheses
        parameters = []
        paren_depth = 0
        current_param = ""

        for char in param_str:
            if char == "(":
                paren_depth += 1
                current_param += char
            elif char == ")":
                paren_depth -= 1
                current_param += char
            elif char == "," and paren_depth == 0:
                parameters.append(current_param.strip())
                current_param = ""
            else:
                current_param += char

        if current_param.strip():
            parameters.append(current_param.strip())

        return parameters

    def _determine_construct_type(self, construct_name: str) -> ConstructType:
        """Determine construct type from construct name"""
        if construct_name.startswith("TOP"):
            return ConstructType.SYNTAX
        elif construct_name in ["DECODE", "IIF"]:
            return ConstructType.FUNCTION
        elif construct_name in ["MINUS", "INDEX_IF_NOT_EXISTS"]:
            return ConstructType.SYNTAX
        elif construct_name == "ROWNUM":
            return ConstructType.SYNTAX
        else:
            return ConstructType.UNKNOWN

    def _is_iris_data_type(self, type_text: str) -> bool:
        """Check if text represents an IRIS data type"""
        iris_types = {
            "%String",
            "%Text",
            "%Date",
            "%Time",
            "%TimeStamp",
            "%Boolean",
            "%Binary",
            "%List",
            "%ArrayOfDataTypes",
            "%Stream",
            "%Status",
            "%Oid",
            "%GlobalCharacterStream",
            "%GlobalBinaryStream",
        }

        return type_text in iris_types

    def _validate_parsing(
        self, sql: str, constructs: list[ParsedConstruct], debug_trace: DebugTrace | None
    ):
        """Validate parsing results and add warnings if needed"""
        # Check for potential missed constructs
        if "%" in sql and not any(
            c.construct_type in [ConstructType.FUNCTION, ConstructType.SYSTEM_FUNCTION]
            for c in constructs
        ):
            warning = (
                "SQL contains '%' characters but no IRIS functions detected - possible parsing miss"
            )
            if debug_trace:
                debug_trace.add_warning(warning)

        # Check for TOP clauses
        if "TOP" in sql.upper() and not any(
            c.metadata.get("construct_name", "").startswith("TOP") for c in constructs
        ):
            warning = "SQL contains 'TOP' keyword but no TOP construct detected"
            if debug_trace:
                debug_trace.add_warning(warning)

    def get_construct_summary(self, constructs: list[ParsedConstruct]) -> dict[str, Any]:
        """Get summary of parsed constructs"""
        summary = {
            "total_constructs": len(constructs),
            "by_type": {},
            "functions": [],
            "system_functions": [],
            "syntax_constructs": [],
            "data_types": [],
        }

        for construct in constructs:
            # Count by type
            type_name = construct.construct_type.value
            summary["by_type"][type_name] = summary["by_type"].get(type_name, 0) + 1

            # Categorize by type
            if construct.construct_type == ConstructType.FUNCTION:
                summary["functions"].append(
                    construct.metadata.get("function_name", construct.original_text)
                )
            elif construct.construct_type == ConstructType.SYSTEM_FUNCTION:
                summary["system_functions"].append(
                    construct.metadata.get("system_function_name", construct.original_text)
                )
            elif construct.construct_type == ConstructType.SYNTAX:
                summary["syntax_constructs"].append(
                    construct.metadata.get("construct_name", construct.original_text)
                )
            elif construct.construct_type == ConstructType.DATA_TYPE:
                summary["data_types"].append(
                    construct.metadata.get("type_name", construct.original_text)
                )

        return summary

    def extract_tables(self, sql: str) -> list[str]:
        """Extract table names from SQL statement"""
        tables = []

        try:
            parsed = sqlparse.parse(sql)[0]

            # Simple table extraction - real implementation would be more sophisticated
            from_seen = False
            for token in parsed.flatten():
                if from_seen and token.ttype is None and isinstance(token, sqlparse.sql.Token):
                    token_value = str(token).strip()
                    if token_value and token_value.upper() not in [
                        "WHERE",
                        "GROUP",
                        "ORDER",
                        "HAVING",
                        "LIMIT",
                    ]:
                        tables.append(token_value)
                        from_seen = False

                if token.ttype is T.Keyword and token.value.upper() == "FROM":
                    from_seen = True

        except Exception:
            pass  # Fall back to regex if sqlparse fails

        return tables

    def is_select_statement(self, sql: str) -> bool:
        """Check if SQL is a SELECT statement"""
        sql_clean = sql.strip().upper()
        return sql_clean.startswith("SELECT") or sql_clean.startswith("WITH")

    def is_show_statement(self, sql: str) -> bool:
        """Check if SQL is a SHOW statement"""
        return sql.strip().upper().startswith("SHOW")

    def is_dml_statement(self, sql: str) -> bool:
        """Check if SQL is a DML statement (INSERT, UPDATE, DELETE, MERGE)"""
        sql_clean = sql.strip().upper()
        return any(sql_clean.startswith(stmt) for stmt in ["INSERT", "UPDATE", "DELETE", "MERGE"])

    def has_returning_clause(self, sql: str) -> bool:
        """Check if SQL has a RETURNING clause"""
        return "RETURNING" in sql.upper()

    def is_ddl_statement(self, sql: str) -> bool:
        """Check if SQL is a DDL statement"""
        sql_clean = sql.strip().upper()
        return any(sql_clean.startswith(stmt) for stmt in ["CREATE", "ALTER", "DROP", "TRUNCATE"])

    def validate_sql_syntax(self, sql: str) -> dict[str, Any]:
        """Basic SQL syntax validation"""
        issues = []
        warnings = []

        try:
            # Try to parse with sqlparse
            parsed = sqlparse.parse(sql)
            if not parsed:
                issues.append("SQL could not be parsed")

            # Check for basic SQL injection patterns
            dangerous_patterns = [
                r";\s*--",  # SQL comment after statement
                r"/\*.*?\*/",  # Block comments
                r"\bxp_\w+",  # Extended procedures
                r"\bsp_\w+",  # Stored procedures
                r"\bexec\s+",  # Execute statements
            ]

            for pattern in dangerous_patterns:
                if re.search(pattern, sql, re.IGNORECASE):
                    warnings.append(f"Potentially dangerous pattern detected: {pattern}")

            # Check for unbalanced parentheses
            if sql.count("(") != sql.count(")"):
                issues.append("Unbalanced parentheses")

            # Check for unbalanced quotes
            single_quotes = sql.count("'")
            if single_quotes % 2 != 0:
                issues.append("Unbalanced single quotes")

        except Exception as e:
            issues.append(f"Validation error: {str(e)}")

        return {"valid": len(issues) == 0, "issues": issues, "warnings": warnings}


# Global parser instance
_parser = IRISSQLParser()


def get_parser() -> IRISSQLParser:
    """Get the global parser instance"""
    return _parser


def parse_sql(
    sql: str, debug_mode: bool = False
) -> tuple[list[ParsedConstruct], DebugTrace | None]:
    """Parse SQL statement and identify IRIS constructs (convenience function)"""
    return _parser.parse(sql, debug_mode)


def validate_sql(sql: str) -> dict[str, Any]:
    """Validate SQL syntax (convenience function)"""
    return _parser.validate_sql_syntax(sql)


# Export main components
__all__ = ["IRISSQLParser", "ParsedConstruct", "get_parser", "parse_sql", "validate_sql"]
