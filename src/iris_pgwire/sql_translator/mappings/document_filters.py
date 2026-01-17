"""
Document Database Filter Mappings

Mappings for IRIS Document Database filtering operations to PostgreSQL jsonb.
Handles JSON_TABLE, JSON_EXTRACT, JSON_EXISTS and other document operations.

Constitutional Compliance: Accurate document query translation preserving semantics.
"""

import logging
import re
from typing import Any

from ..models import ConstructMapping, ConstructType, SourceLocation

logger = logging.getLogger(__name__)


class IRISDocumentFilterRegistry:
    """Registry for IRIS Document Database filter to PostgreSQL jsonb mappings"""

    def __init__(self):
        self._filter_patterns: dict[str, dict] = {}
        self._path_patterns: dict[str, str] = {}
        self._initialize_filters()

    def _initialize_filters(self):
        """Initialize all document filter mappings"""
        self._add_json_table_filters()
        self._add_json_extract_filters()
        self._add_json_exists_filters()
        self._add_json_query_filters()
        self._add_document_access_patterns()
        self._add_array_operations()
        self._add_nested_operations()

    def _add_json_table_filters(self):
        """Add JSON_TABLE filter mappings"""

        # Basic JSON_TABLE with COLUMNS
        self.add_filter(
            name="JSON_TABLE_BASIC",
            pattern=r"\bJSON_TABLE\s*\(\s*([^,]+),\s*([^,]+)\s+COLUMNS\s*\(([^)]+)\)\s*\)",
            replacement=None,
            post_process=self._convert_json_table,
            confidence=0.8,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert JSON_TABLE to jsonb_to_recordset or lateral join",
        )

        # JSON_TABLE with nested paths
        self.add_filter(
            name="JSON_TABLE_NESTED",
            pattern=r"\bJSON_TABLE\s*\(\s*([^,]+),\s*([^,]+)\s+COLUMNS\s*\(([^)]+)\)\s+NESTED\s+PATH\s+([^)]+)\)",
            replacement=None,
            post_process=self._convert_json_table_nested,
            confidence=0.7,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert nested JSON_TABLE to complex jsonb operations",
        )

    def _add_json_extract_filters(self):
        """Add JSON_EXTRACT filter mappings"""

        # JSON_EXTRACT with JSONPath
        self.add_filter(
            name="JSON_EXTRACT_PATH",
            pattern=r'\bJSON_EXTRACT\s*\(\s*([^,]+),\s*[\'"]([^\'\"]+)[\'"]\s*\)',
            replacement=None,
            post_process=self._convert_json_extract,
            confidence=0.9,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert JSON_EXTRACT to PostgreSQL jsonb path operations",
        )

        # JSON_EXTRACT_SCALAR (returns text)
        self.add_filter(
            name="JSON_EXTRACT_SCALAR",
            pattern=r'\bJSON_EXTRACT_SCALAR\s*\(\s*([^,]+),\s*[\'"]([^\'\"]+)[\'"]\s*\)',
            replacement=None,
            post_process=self._convert_json_extract_scalar,
            confidence=0.9,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert JSON_EXTRACT_SCALAR to ->> operator",
        )

        # JSON_UNQUOTE function
        self.add_filter(
            name="JSON_UNQUOTE",
            pattern=r"\bJSON_UNQUOTE\s*\(\s*([^)]+)\s*\)",
            replacement=r"(\1)::text",
            confidence=0.9,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert JSON_UNQUOTE to text casting",
        )

    def _add_json_exists_filters(self):
        """Add JSON_EXISTS filter mappings"""

        # JSON_EXISTS with path
        self.add_filter(
            name="JSON_EXISTS_PATH",
            pattern=r'\bJSON_EXISTS\s*\(\s*([^,]+),\s*[\'"]([^\'\"]+)[\'"]\s*\)',
            replacement=None,
            post_process=self._convert_json_exists,
            confidence=0.9,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert JSON_EXISTS to jsonb path existence check",
        )

        # JSON_EXISTS with RETURNING clause
        self.add_filter(
            name="JSON_EXISTS_RETURNING",
            pattern=r'\bJSON_EXISTS\s*\(\s*([^,]+),\s*[\'"]([^\'\"]+)[\'"]\s+RETURNING\s+(\w+)\s*\)',
            replacement=None,
            post_process=self._convert_json_exists_returning,
            confidence=0.8,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert JSON_EXISTS with RETURNING to typed result",
        )

    def _add_json_query_filters(self):
        """Add JSON_QUERY filter mappings"""

        # JSON_QUERY for extracting objects/arrays
        self.add_filter(
            name="JSON_QUERY_PATH",
            pattern=r'\bJSON_QUERY\s*\(\s*([^,]+),\s*[\'"]([^\'\"]+)[\'"]\s*\)',
            replacement=None,
            post_process=self._convert_json_query,
            confidence=0.8,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert JSON_QUERY to jsonb #> operator",
        )

        # JSON_VALUE for scalar extraction
        self.add_filter(
            name="JSON_VALUE_PATH",
            pattern=r'\bJSON_VALUE\s*\(\s*([^,]+),\s*[\'"]([^\'\"]+)[\'"]\s*\)',
            replacement=None,
            post_process=self._convert_json_value,
            confidence=0.9,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert JSON_VALUE to jsonb ->> operator",
        )

    def _add_document_access_patterns(self):
        """Add document field access patterns"""

        # IRIS document.field syntax - only match if not preceded by table alias context
        # Disabled for now as it incorrectly matches table.column references
        # Need more sophisticated context analysis to distinguish document vs table access
        # self.add_filter(
        #     name="DOCUMENT_FIELD_ACCESS",
        #     pattern=r'(\w+)\.(\w+)(?:\.(\w+))*',
        #     replacement=None,
        #     post_process=self._convert_document_field_access,
        #     confidence=0.7,
        #     construct_type=ConstructType.DOCUMENT_FILTER,
        #     notes="Convert document field access to jsonb operators"
        # )

        # IRIS document['field'] syntax
        self.add_filter(
            name="DOCUMENT_BRACKET_ACCESS",
            pattern=r'(\w+)\[[\'""]([^\'\"]+)[\'\"]\]',
            replacement=r"\1->'\2'",
            confidence=0.9,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert bracket notation to jsonb -> operator",
        )

        # IRIS document[index] for arrays
        self.add_filter(
            name="DOCUMENT_ARRAY_INDEX",
            pattern=r"(\w+)\[(\d+)\]",
            replacement=r"\1->\2",
            confidence=1.0,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert array index access to jsonb -> operator",
        )

    def _add_array_operations(self):
        """Add JSON array operation mappings"""

        # JSON_ARRAY_LENGTH
        self.add_filter(
            name="JSON_ARRAY_LENGTH",
            pattern=r"\bJSON_ARRAY_LENGTH\s*\(\s*([^)]+)\s*\)",
            replacement=r"jsonb_array_length(\1)",
            confidence=1.0,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Direct mapping to jsonb_array_length",
        )

        # JSON_ARRAY_ELEMENTS
        self.add_filter(
            name="JSON_ARRAY_ELEMENTS",
            pattern=r"\bJSON_ARRAY_ELEMENTS\s*\(\s*([^)]+)\s*\)",
            replacement=r"jsonb_array_elements(\1)",
            confidence=1.0,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Direct mapping to jsonb_array_elements",
        )

        # JSON_ARRAY_ELEMENTS_TEXT
        self.add_filter(
            name="JSON_ARRAY_ELEMENTS_TEXT",
            pattern=r"\bJSON_ARRAY_ELEMENTS_TEXT\s*\(\s*([^)]+)\s*\)",
            replacement=r"jsonb_array_elements_text(\1)",
            confidence=1.0,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Direct mapping to jsonb_array_elements_text",
        )

        # Array contains operations
        self.add_filter(
            name="JSON_CONTAINS_ARRAY",
            pattern=r"\bJSON_CONTAINS\s*\(\s*([^,]+),\s*([^)]+)\s*\)",
            replacement=r"\1 @> \2",
            confidence=0.9,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert JSON_CONTAINS to jsonb @> operator",
        )

    def _add_nested_operations(self):
        """Add nested document operation mappings"""

        # Nested object access with multiple levels
        self.add_filter(
            name="NESTED_OBJECT_ACCESS",
            pattern=r'(\w+)->[\'""]([^\'\"]+)[\'""]->[\'""]([^\'\"]+)[\'""]',
            replacement=r"\1#>'{{\2,\3}}'",
            confidence=0.9,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert multi-level access to #> path operator",
        )

        # JSON path with wildcards
        self.add_filter(
            name="JSON_PATH_WILDCARD",
            pattern=r'[\'"]\$\.([^\'\"]*)\*([^\'\"]*)[\'"]',
            replacement=None,
            post_process=self._convert_wildcard_path,
            confidence=0.6,
            construct_type=ConstructType.DOCUMENT_FILTER,
            notes="Convert wildcard paths to jsonb operations",
        )

    def add_filter(
        self,
        name: str,
        pattern: str,
        replacement: str | None,
        confidence: float = 1.0,
        construct_type: ConstructType = ConstructType.DOCUMENT_FILTER,
        notes: str = "",
        post_process=None,
    ):
        """Add a document filter mapping"""
        self._filter_patterns[name] = {
            "pattern": re.compile(pattern, re.IGNORECASE),
            "replacement": replacement,
            "confidence": confidence,
            "construct_type": construct_type,
            "notes": notes,
            "post_process": post_process,
        }

    def translate_document_filters(self, sql: str) -> tuple[str, list[ConstructMapping]]:
        """
        Translate IRIS document filter operations to PostgreSQL jsonb
        Returns (translated_sql, list_of_mappings)
        """
        translated_sql = sql
        mappings = []

        for name, filter_info in self._filter_patterns.items():
            pattern = filter_info["pattern"]
            replacement = filter_info["replacement"]
            post_process = filter_info.get("post_process")

            # Find all matches
            matches = list(pattern.finditer(translated_sql))

            for match in reversed(matches):  # Process from end to preserve positions
                start, end = match.span()
                original_text = match.group(0)

                # Apply replacement
                if replacement is not None:
                    new_text = pattern.sub(replacement, original_text, count=1)
                elif post_process:
                    new_text = post_process(match, translated_sql)
                else:
                    continue  # Skip if no replacement method

                # Update SQL
                translated_sql = translated_sql[:start] + new_text + translated_sql[end:]

                # Create mapping record
                source_location = SourceLocation(
                    line=translated_sql[:start].count("\n") + 1,
                    column=len(translated_sql[:start].split("\n")[-1]) + 1,
                    length=len(original_text),
                    original_text=original_text,
                )

                mapping = ConstructMapping(
                    construct_type=filter_info["construct_type"],
                    original_syntax=original_text,
                    translated_syntax=new_text,
                    confidence=filter_info["confidence"],
                    source_location=source_location,
                    metadata={"filter_name": name, "notes": filter_info["notes"]},
                )
                mappings.append(mapping)

        return translated_sql, mappings

    def _convert_json_table(self, match, full_sql: str) -> str:
        """Convert JSON_TABLE to PostgreSQL equivalent"""
        json_data = match.group(1).strip()
        match.group(2).strip().strip("'\"")
        columns_spec = match.group(3).strip()

        # Parse columns specification
        columns = self._parse_json_table_columns(columns_spec)

        # Build PostgreSQL equivalent using jsonb_to_recordset or lateral join
        if len(columns) == 1:
            # Single column extraction
            col_name, col_type, col_path = columns[0]
            if col_path:
                return f"(SELECT ({json_data}::jsonb->>'{col_path}')::{col_type} AS {col_name})"
            else:
                return f"(SELECT ({json_data}::jsonb->>'{col_name}')::{col_type} AS {col_name})"
        else:
            # Multiple columns - use jsonb_to_recordset
            type_def = ", ".join([f"{name} {dtype}" for name, dtype, _ in columns])
            return f"jsonb_to_recordset({json_data}::jsonb) AS t({type_def})"

    def _convert_json_table_nested(self, match, full_sql: str) -> str:
        """Convert nested JSON_TABLE to complex jsonb operations"""
        # This is a complex transformation - simplified for now
        return self._convert_json_table(match, full_sql)

    def _convert_json_extract(self, match, full_sql: str) -> str:
        """Convert JSON_EXTRACT to PostgreSQL jsonb operation"""
        json_data = match.group(1).strip()
        path = match.group(2).strip()

        # Convert JSONPath to PostgreSQL path
        pg_path = self._convert_jsonpath_to_postgres(path)

        if pg_path.startswith("{") and pg_path.endswith("}"):
            # Array path
            return f"({json_data}::jsonb#>'{pg_path}')"
        else:
            # Simple key
            return f"({json_data}::jsonb->'{pg_path}')"

    def _convert_json_extract_scalar(self, match, full_sql: str) -> str:
        """Convert JSON_EXTRACT_SCALAR to ->> operator"""
        json_data = match.group(1).strip()
        path = match.group(2).strip()

        # Convert JSONPath to PostgreSQL path
        pg_path = self._convert_jsonpath_to_postgres(path)

        if pg_path.startswith("{") and pg_path.endswith("}"):
            # Array path
            return f"({json_data}::jsonb#>>'{pg_path}')"
        else:
            # Simple key
            return f"({json_data}::jsonb->>'{pg_path}')"

    def _convert_json_exists(self, match, full_sql: str) -> str:
        """Convert JSON_EXISTS to PostgreSQL existence check"""
        json_data = match.group(1).strip()
        path = match.group(2).strip()

        # Convert JSONPath to PostgreSQL path
        pg_path = self._convert_jsonpath_to_postgres(path)

        if pg_path.startswith("{") and pg_path.endswith("}"):
            # Array path
            return f"({json_data}::jsonb#>'{pg_path}' IS NOT NULL)"
        else:
            # Simple key
            return f"({json_data}::jsonb ? '{pg_path}')"

    def _convert_json_exists_returning(self, match, full_sql: str) -> str:
        """Convert JSON_EXISTS with RETURNING clause"""
        match.group(1).strip()
        match.group(2).strip()
        return_type = match.group(3).strip().upper()

        base_check = self._convert_json_exists(match, full_sql)

        if return_type == "BOOLEAN":
            return base_check
        else:
            return f"CASE WHEN {base_check} THEN 1 ELSE 0 END"

    def _convert_json_query(self, match, full_sql: str) -> str:
        """Convert JSON_QUERY to #> operator"""
        json_data = match.group(1).strip()
        path = match.group(2).strip()

        pg_path = self._convert_jsonpath_to_postgres(path)
        return f"({json_data}::jsonb#>'{pg_path}')"

    def _convert_json_value(self, match, full_sql: str) -> str:
        """Convert JSON_VALUE to ->> operator"""
        json_data = match.group(1).strip()
        path = match.group(2).strip()

        pg_path = self._convert_jsonpath_to_postgres(path)
        return f"({json_data}::jsonb->>'{pg_path}')"

    def _convert_document_field_access(self, match, full_sql: str) -> str:
        """Convert document field access to jsonb operators"""
        # This would need context to determine if it's document access
        # For now, return original
        return match.group(0)

    def _convert_wildcard_path(self, match, full_sql: str) -> str:
        """Convert wildcard JSONPath to PostgreSQL operations"""
        # Complex transformation - simplified for now
        return match.group(0)

    def _parse_json_table_columns(self, columns_spec: str) -> list[tuple[str, str, str | None]]:
        """Parse JSON_TABLE COLUMNS specification"""
        columns = []

        # Simple parsing - real implementation would need proper SQL parser
        parts = [part.strip() for part in columns_spec.split(",")]

        for part in parts:
            # Pattern: column_name data_type [PATH 'path']
            match = re.match(
                r'(\w+)\s+(\w+(?:\(\d+\))?)\s*(?:PATH\s+[\'"]([^\'\"]+)[\'"])?', part, re.IGNORECASE
            )
            if match:
                col_name = match.group(1)
                col_type = match.group(2)
                col_path = match.group(3) if match.group(3) else None
                columns.append((col_name, col_type, col_path))

        return columns

    def _convert_jsonpath_to_postgres(self, jsonpath: str) -> str:
        """Convert JSONPath expression to PostgreSQL path format"""
        # Remove leading $. if present
        if jsonpath.startswith("$."):
            jsonpath = jsonpath[2:]
        elif jsonpath.startswith("$"):
            jsonpath = jsonpath[1:]

        # Convert array access [n] to PostgreSQL format
        jsonpath = re.sub(r"\[(\d+)\]", r",\1", jsonpath)

        # Split by dots and handle array indices
        parts = []
        for part in jsonpath.split("."):
            if "," in part:
                # Has array index
                key, index = part.split(",", 1)
                if key:
                    parts.append(key)
                parts.append(index)
            else:
                parts.append(part)

        # Return as array format for #> operator
        if len(parts) > 1:
            formatted_parts = ",".join([f'"{p}"' if not p.isdigit() else p for p in parts])
            return f"{{{formatted_parts}}}"
        else:
            return parts[0] if parts else ""

    def has_filter(self, filter_name: str) -> bool:
        """Check if document filter mapping exists"""
        return filter_name in self._filter_patterns

    def get_filter_info(self, filter_name: str) -> dict | None:
        """Get information about a filter mapping"""
        return self._filter_patterns.get(filter_name)

    def search_filters(self, pattern: str) -> list[str]:
        """Search for filter mappings by name or notes"""
        pattern_lower = pattern.lower()
        matches = []

        for name, info in self._filter_patterns.items():
            if pattern_lower in name.lower() or pattern_lower in info["notes"].lower():
                matches.append(name)

        return matches

    def get_filter_categories(self) -> dict[str, list[str]]:
        """Get filters organized by category"""
        categories = {
            "json_table": [],
            "json_extract": [],
            "json_exists": [],
            "json_query": [],
            "document_access": [],
            "array_operations": [],
            "nested_operations": [],
            "other": [],
        }

        for name in self._filter_patterns.keys():
            name_lower = name.lower()

            if "json_table" in name_lower:
                categories["json_table"].append(name)
            elif "json_extract" in name_lower:
                categories["json_extract"].append(name)
            elif "json_exists" in name_lower:
                categories["json_exists"].append(name)
            elif any(x in name_lower for x in ["json_query", "json_value"]):
                categories["json_query"].append(name)
            elif any(x in name_lower for x in ["document", "field", "bracket"]):
                categories["document_access"].append(name)
            elif any(x in name_lower for x in ["array", "elements", "length"]):
                categories["array_operations"].append(name)
            elif any(x in name_lower for x in ["nested", "wildcard"]):
                categories["nested_operations"].append(name)
            else:
                categories["other"].append(name)

        return categories

    def get_all_filter_names(self) -> set[str]:
        """Get all registered filter names"""
        return set(self._filter_patterns.keys())

    def get_mapping_stats(self) -> dict[str, Any]:
        """Get statistics about document filter mappings"""
        total_filters = len(self._filter_patterns)

        # Count by confidence levels
        high_confidence = len([f for f in self._filter_patterns.values() if f["confidence"] >= 0.9])
        medium_confidence = len(
            [f for f in self._filter_patterns.values() if 0.7 <= f["confidence"] < 0.9]
        )
        low_confidence = len([f for f in self._filter_patterns.values() if f["confidence"] < 0.7])

        # Count by category
        categories = self.get_filter_categories()
        category_counts = {cat: len(filters) for cat, filters in categories.items()}

        return {
            "total_filters": total_filters,
            "confidence_distribution": {
                "high": high_confidence,
                "medium": medium_confidence,
                "low": low_confidence,
            },
            "category_counts": category_counts,
            "average_confidence": sum(f["confidence"] for f in self._filter_patterns.values())
            / total_filters,
        }


# Global registry instance
_document_filter_registry = IRISDocumentFilterRegistry()


def get_document_filter_registry() -> IRISDocumentFilterRegistry:
    """Get the global document filter registry instance"""
    return _document_filter_registry


def translate_document_filters(sql: str) -> tuple[str, list[ConstructMapping]]:
    """Translate IRIS document filters to PostgreSQL jsonb (convenience function)"""
    return _document_filter_registry.translate_document_filters(sql)


def has_document_filter(filter_name: str) -> bool:
    """Check if document filter mapping exists (convenience function)"""
    return _document_filter_registry.has_filter(filter_name)


# Export main components
__all__ = [
    "IRISDocumentFilterRegistry",
    "get_document_filter_registry",
    "translate_document_filters",
    "has_document_filter",
]
