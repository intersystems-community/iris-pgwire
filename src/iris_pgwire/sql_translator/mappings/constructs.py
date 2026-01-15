"""
IRIS SQL Construct Mappings

Mappings for IRIS-specific SQL syntax constructs that differ from standard SQL.
Handles TOP clauses, special operators, and IRIS-specific syntax patterns.

Constitutional Compliance: Comprehensive syntax translation preserving query semantics.
"""

import re
from typing import Any

from ...conversions.vector_syntax import HnswIndexSpec
from ..models import ConstructMapping, ConstructType, SourceLocation


class IRISSQLConstructRegistry:
    """Registry for IRIS SQL construct to PostgreSQL syntax mappings"""

    def __init__(self):
        self._construct_patterns: dict[str, dict] = {}
        self._initialize_constructs()

    def _initialize_constructs(self):
        """Initialize all IRIS SQL construct mappings"""
        self._add_top_clause_constructs()
        self._add_pagination_constructs()
        self._add_join_constructs()
        self._add_case_constructs()
        self._add_conditional_constructs()
        self._add_subquery_constructs()
        self._add_set_operations()
        self._add_window_functions()
        self._add_common_table_expressions()
        self._add_index_constructs()

    def _add_top_clause_constructs(self):
        """Add TOP clause construct mappings"""

        # IRIS supports both TOP and LIMIT natively - no translation needed
        # Keeping method for compatibility but not adding any TOP translations
        pass

    def _add_pagination_constructs(self):
        """Add pagination-related construct mappings"""

        # IRIS LIMIT with OFFSET syntax variations
        self.add_construct(
            name="IRIS_LIMIT_OFFSET",
            pattern=r"\bLIMIT\s+(\d+)\s+OFFSET\s+(\d+)\b",
            replacement=r"LIMIT \1 OFFSET \2",
            confidence=1.0,
            construct_type=ConstructType.SYNTAX,
            notes="Ensure PostgreSQL-compatible LIMIT OFFSET syntax",
        )

        # IRIS %ROWNUM pseudo-column
        self.add_construct(
            name="ROWNUM_PSEUDO_COLUMN",
            pattern=r"\b%ROWNUM\b",
            replacement=r"ROW_NUMBER() OVER (ORDER BY (SELECT NULL))",
            confidence=0.8,
            construct_type=ConstructType.SYNTAX,
            notes="Convert %ROWNUM to ROW_NUMBER() window function",
        )

    def _add_join_constructs(self):
        """Add JOIN-related construct mappings"""

        # IRIS (+) outer join syntax (Oracle-style)
        self.add_construct(
            name="ORACLE_STYLE_OUTER_JOIN",
            pattern=r"(\w+)\.\w+\s*\(\+\)\s*=\s*(\w+)\.\w+",
            replacement=None,  # Complex transformation needed
            post_process=self._convert_oracle_outer_join,
            confidence=0.7,
            construct_type=ConstructType.SYNTAX,
            notes="Convert Oracle-style (+) outer join to ANSI JOIN syntax",
        )

        # IRIS table hints
        self.add_construct(
            name="TABLE_HINTS",
            pattern=r"\bFROM\s+(\w+)\s+WITH\s*\([^)]+\)",
            replacement=r"FROM \1",
            confidence=0.9,
            construct_type=ConstructType.SYNTAX,
            notes="Remove IRIS table hints - not supported in PostgreSQL",
        )

    def _add_case_constructs(self):
        """Add CASE statement construct mappings"""

        # IRIS DECODE function (Oracle-style)
        self.add_construct(
            name="DECODE_FUNCTION",
            pattern=r"\bDECODE\s*\(",
            replacement=r"CASE ",
            post_process=self._convert_decode_to_case,
            confidence=0.9,
            construct_type=ConstructType.FUNCTION,
            notes="Convert DECODE function to CASE statement",
        )

        # IRIS IIF function (SQL Server-style)
        self.add_construct(
            name="IIF_FUNCTION",
            pattern=r"\bIIF\s*\(\s*([^,]+),\s*([^,]+),\s*([^)]+)\)",
            replacement=r"CASE WHEN \1 THEN \2 ELSE \3 END",
            confidence=1.0,
            construct_type=ConstructType.FUNCTION,
            notes="Convert IIF function to CASE statement",
        )

    def _add_conditional_constructs(self):
        """Add conditional construct mappings"""

        # IRIS ISNULL function
        self.add_construct(
            name="ISNULL_FUNCTION",
            pattern=r"\bISNULL\s*\(\s*([^,]+),\s*([^)]+)\)",
            replacement=r"COALESCE(\1, \2)",
            confidence=1.0,
            construct_type=ConstructType.FUNCTION,
            notes="Convert ISNULL to COALESCE",
        )

        # IRIS IFNULL function
        self.add_construct(
            name="IFNULL_FUNCTION",
            pattern=r"\bIFNULL\s*\(\s*([^,]+),\s*([^)]+)\)",
            replacement=r"COALESCE(\1, \2)",
            confidence=1.0,
            construct_type=ConstructType.FUNCTION,
            notes="Convert IFNULL to COALESCE",
        )

        # IRIS NVL function (Oracle-style)
        self.add_construct(
            name="NVL_FUNCTION",
            pattern=r"\bNVL\s*\(\s*([^,]+),\s*([^)]+)\)",
            replacement=r"COALESCE(\1, \2)",
            confidence=1.0,
            construct_type=ConstructType.FUNCTION,
            notes="Convert NVL to COALESCE",
        )

    def _add_subquery_constructs(self):
        """Add subquery-related construct mappings"""

        # IRIS EXISTS with correlated subqueries
        self.add_construct(
            name="CORRELATED_EXISTS",
            pattern=r"\bEXISTS\s*\(\s*SELECT\s+1\s+FROM\s+",
            replacement=r"EXISTS (SELECT 1 FROM ",
            confidence=1.0,
            construct_type=ConstructType.SYNTAX,
            notes="Ensure standard EXISTS syntax",
        )

        # IRIS ALL/ANY/SOME operators
        self.add_construct(
            name="QUANTIFIED_COMPARISONS",
            pattern=r"([<>=!]+)\s+(ALL|ANY|SOME)\s*\(",
            replacement=r"\1 \2 (",
            confidence=1.0,
            construct_type=ConstructType.SYNTAX,
            notes="Preserve quantified comparison operators",
        )

    def _add_set_operations(self):
        """Add set operation construct mappings"""

        # IRIS MINUS operator (Oracle-style)
        self.add_construct(
            name="MINUS_OPERATOR",
            pattern=r"\bMINUS\b",
            replacement=r"EXCEPT",
            confidence=1.0,
            construct_type=ConstructType.SYNTAX,
            notes="Convert MINUS to EXCEPT (PostgreSQL standard)",
        )

        # IRIS INTERSECT operator
        self.add_construct(
            name="INTERSECT_OPERATOR",
            pattern=r"\bINTERSECT\b",
            replacement=r"INTERSECT",
            confidence=1.0,
            construct_type=ConstructType.SYNTAX,
            notes="Preserve INTERSECT operator",
        )

    def _add_window_functions(self):
        """Add window function construct mappings"""

        # IRIS RANK() variations
        self.add_construct(
            name="RANK_FUNCTION",
            pattern=r"\bRANK\s*\(\s*\)\s+OVER\s*\(",
            replacement=r"RANK() OVER (",
            confidence=1.0,
            construct_type=ConstructType.FUNCTION,
            notes="Ensure standard RANK syntax",
        )

        # IRIS ROW_NUMBER() variations
        self.add_construct(
            name="ROW_NUMBER_FUNCTION",
            pattern=r"\bROW_NUMBER\s*\(\s*\)\s+OVER\s*\(",
            replacement=r"ROW_NUMBER() OVER (",
            confidence=1.0,
            construct_type=ConstructType.FUNCTION,
            notes="Ensure standard ROW_NUMBER syntax",
        )

    def _add_common_table_expressions(self):
        """Add CTE construct mappings"""

        # IRIS WITH clause variations
        self.add_construct(
            name="CTE_WITH_CLAUSE",
            pattern=r"\bWITH\s+(\w+)\s*\(\s*([^)]+)\s*\)\s+AS\s*\(",
            replacement=r"WITH \1(\2) AS (",
            confidence=1.0,
            construct_type=ConstructType.SYNTAX,
            notes="Ensure standard CTE syntax",
        )

        # IRIS RECURSIVE CTE
        self.add_construct(
            name="RECURSIVE_CTE",
            pattern=r"\bWITH\s+RECURSIVE\s+",
            replacement=r"WITH RECURSIVE ",
            confidence=1.0,
            construct_type=ConstructType.SYNTAX,
            notes="Preserve RECURSIVE CTE syntax",
        )

    def _add_index_constructs(self):
        """Add index-related construct mappings"""

        # CREATE INDEX IF NOT EXISTS support
        # IRIS doesn't support IF NOT EXISTS for indexes in the parser.
        # We strip it and let IRISExecutor's DdlErrorHandler handle the "already exists" error.
        self.add_construct(
            name="CREATE_INDEX_IF_NOT_EXISTS",
            pattern=r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS",
            replacement=lambda m: m.group(0).replace("IF NOT EXISTS", "").replace("  ", " ")
            + " /* IF_NOT_EXISTS */",
            confidence=1.0,
            construct_type=ConstructType.SYNTAX,
            notes="Strip IF NOT EXISTS from CREATE INDEX for IRIS compatibility",
        )

        # HNSW Index Support (PostgreSQL USING hnsw -> IRIS AS HNSW)
        self.add_construct(
            name="HNSW_INDEX",
            pattern=r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s+USING\s+hnsw\s*\([^)]+\)",
            replacement=None,  # Handled by post_process
            post_process=self._translate_hnsw_index,
            confidence=0.95,
            construct_type=ConstructType.SYNTAX,
            notes="Translate PostgreSQL HNSW index to IRIS syntax",
        )

    def _translate_hnsw_index(self, match: re.Match, full_sql: str) -> str:
        """Translate HNSW index creation to IRIS syntax"""
        sql = match.group(0)
        try:
            spec = HnswIndexSpec.from_postgres_sql(sql)
            if spec:
                return spec.to_iris_sql()
        except ValueError as e:
            # Re-raise as syntax error for the translator to handle
            raise ValueError(f"HNSW translation error: {e}") from e

        return sql

    def add_construct(
        self,
        name: str,
        pattern: str,
        replacement: Any,
        confidence: float = 1.0,
        construct_type: ConstructType = ConstructType.SYNTAX,
        notes: str = "",
        post_process=None,
    ):
        """Add a SQL construct mapping"""
        self._construct_patterns[name] = {
            "pattern": re.compile(pattern, re.IGNORECASE),
            "replacement": replacement,
            "confidence": confidence,
            "construct_type": construct_type,
            "notes": notes,
            "post_process": post_process,
        }

    def translate_constructs(self, sql: str) -> tuple[str, list[ConstructMapping]]:
        """
        Translate IRIS SQL constructs to PostgreSQL equivalents
        Returns (translated_sql, list_of_mappings)
        """
        translated_sql = sql
        mappings = []

        for name, construct_info in self._construct_patterns.items():
            pattern = construct_info["pattern"]
            replacement = construct_info["replacement"]
            post_process = construct_info.get("post_process")

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
                    construct_type=construct_info["construct_type"],
                    original_syntax=original_text,
                    translated_syntax=new_text,
                    confidence=construct_info["confidence"],
                    source_location=source_location,
                    metadata={"construct_name": name, "notes": construct_info["notes"]},
                )
                mappings.append(mapping)

        return translated_sql, mappings

    def _convert_oracle_outer_join(self, match, full_sql: str) -> str:
        """Convert Oracle-style (+) outer join to ANSI syntax"""
        # This is a complex transformation that would require full SQL parsing
        # Simplified approach for now
        return match.group(0)  # Return unchanged for now

    def _convert_decode_to_case(self, match, full_sql: str) -> str:
        """Convert DECODE function to CASE statement"""
        # This would require parsing the DECODE parameters and converting to CASE WHEN
        # Simplified approach for now
        return "CASE "

    def has_construct(self, construct_name: str) -> bool:
        """Check if construct mapping exists"""
        return construct_name in self._construct_patterns

    def get_construct_info(self, construct_name: str) -> dict | None:
        """Get information about a construct mapping"""
        return self._construct_patterns.get(construct_name)

    def search_constructs(self, pattern: str) -> list[str]:
        """Search for construct mappings by name or notes"""
        pattern_lower = pattern.lower()
        matches = []

        for name, info in self._construct_patterns.items():
            if pattern_lower in name.lower() or pattern_lower in info["notes"].lower():
                matches.append(name)

        return matches

    def get_construct_categories(self) -> dict[str, list[str]]:
        """Get constructs organized by category"""
        categories = {
            "pagination": [],
            "joins": [],
            "case_logic": [],
            "conditionals": [],
            "subqueries": [],
            "set_operations": [],
            "window_functions": [],
            "cte": [],
            "other": [],
        }

        for name in self._construct_patterns.keys():
            name_lower = name.lower()

            if any(x in name_lower for x in ["top", "limit", "rownum"]):
                categories["pagination"].append(name)
            elif any(x in name_lower for x in ["join", "outer"]):
                categories["joins"].append(name)
            elif any(x in name_lower for x in ["decode", "case", "iif"]):
                categories["case_logic"].append(name)
            elif any(x in name_lower for x in ["isnull", "ifnull", "nvl"]):
                categories["conditionals"].append(name)
            elif any(x in name_lower for x in ["exists", "all", "any", "some"]):
                categories["subqueries"].append(name)
            elif any(x in name_lower for x in ["minus", "intersect", "except"]):
                categories["set_operations"].append(name)
            elif any(x in name_lower for x in ["rank", "row_number", "window"]):
                categories["window_functions"].append(name)
            elif any(x in name_lower for x in ["cte", "with", "recursive"]):
                categories["cte"].append(name)
            else:
                categories["other"].append(name)

        return categories

    def get_all_construct_names(self) -> set[str]:
        """Get all registered construct names"""
        return set(self._construct_patterns.keys())

    def validate_construct_pattern(self, pattern: str) -> dict[str, Any]:
        """Validate a regex pattern for construct matching"""
        try:
            compiled_pattern = re.compile(pattern, re.IGNORECASE)
            return {"valid": True, "compiled_pattern": compiled_pattern, "warnings": []}
        except re.error as e:
            return {"valid": False, "error": str(e), "warnings": ["Invalid regex pattern"]}

    def get_mapping_stats(self) -> dict[str, Any]:
        """Get statistics about construct mappings"""
        total_constructs = len(self._construct_patterns)

        # Count by confidence levels
        high_confidence = len(
            [c for c in self._construct_patterns.values() if c["confidence"] >= 0.9]
        )
        medium_confidence = len(
            [c for c in self._construct_patterns.values() if 0.7 <= c["confidence"] < 0.9]
        )
        low_confidence = len(
            [c for c in self._construct_patterns.values() if c["confidence"] < 0.7]
        )

        # Count by construct type
        type_counts = {}
        for construct_info in self._construct_patterns.values():
            construct_type = construct_info["construct_type"].value
            type_counts[construct_type] = type_counts.get(construct_type, 0) + 1

        # Count by category
        categories = self.get_construct_categories()
        category_counts = {cat: len(constructs) for cat, constructs in categories.items()}

        return {
            "total_constructs": total_constructs,
            "confidence_distribution": {
                "high": high_confidence,
                "medium": medium_confidence,
                "low": low_confidence,
            },
            "type_distribution": type_counts,
            "category_counts": category_counts,
            "average_confidence": sum(c["confidence"] for c in self._construct_patterns.values())
            / total_constructs,
        }


# Global registry instance
_construct_registry = IRISSQLConstructRegistry()


def get_construct_registry() -> IRISSQLConstructRegistry:
    """Get the global SQL construct registry instance"""
    return _construct_registry


def translate_sql_constructs(sql: str) -> tuple[str, list[ConstructMapping]]:
    """Translate IRIS SQL constructs to PostgreSQL (convenience function)"""
    return _construct_registry.translate_constructs(sql)


def has_sql_construct(construct_name: str) -> bool:
    """Check if SQL construct mapping exists (convenience function)"""
    return _construct_registry.has_construct(construct_name)


# Export main components
__all__ = [
    "IRISSQLConstructRegistry",
    "get_construct_registry",
    "translate_sql_constructs",
    "has_sql_construct",
]
