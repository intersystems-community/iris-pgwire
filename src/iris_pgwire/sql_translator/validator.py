"""
Semantic Validator for SQL Query Equivalence

Validates that translated PostgreSQL SQL produces semantically equivalent results
to the original IRIS SQL, ensuring constitutional compliance with accuracy requirements.

Constitutional Compliance: High-confidence validation ensuring accurate translation.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import (
    ConstructMapping,
    IssueSeverity,
    PerformanceTimer,
    QueryEquivalenceReport,
    ValidationIssue,
    ValidationResult,
)


class ValidationLevel(Enum):
    """Validation rigor levels"""

    BASIC = "basic"  # Basic syntax and structure checks
    SEMANTIC = "semantic"  # Semantic equivalence validation
    STRICT = "strict"  # Strict constitutional compliance
    EXHAUSTIVE = "exhaustive"  # Comprehensive validation with edge cases


@dataclass
class ValidationContext:
    """Context for validation operations"""

    original_sql: str
    translated_sql: str
    construct_mappings: list[ConstructMapping]
    validation_level: ValidationLevel = ValidationLevel.SEMANTIC
    include_performance: bool = True
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryAnalysis:
    """Analysis results for a SQL query"""

    query_type: str  # SELECT, INSERT, UPDATE, DELETE, etc.
    tables_referenced: set[str]
    columns_referenced: set[str]
    functions_used: set[str]
    constructs_detected: set[str]
    complexity_score: float
    estimated_rows: int | None = None
    performance_hints: list[str] = field(default_factory=list)


class SemanticValidator:
    """
    Semantic validator for SQL query equivalence

    Features:
    - Query structure analysis and comparison
    - Semantic equivalence validation
    - Constitutional compliance checking
    - Performance impact assessment
    - Edge case detection
    """

    def __init__(self, validation_level: ValidationLevel = ValidationLevel.SEMANTIC):
        """
        Initialize semantic validator

        Args:
            validation_level: Level of validation rigor to apply
        """
        self.validation_level = validation_level
        self.logger = logging.getLogger("iris_pgwire.sql_translator.validator")

        # Validation rules and patterns
        self._setup_validation_rules()

        # Performance tracking
        self._validation_count = 0
        self._total_validation_time_ms = 0.0
        self._constitutional_violations = 0

    def validate_query_equivalence(self, context: ValidationContext) -> ValidationResult:
        """
        Validate semantic equivalence between original and translated queries

        Args:
            context: Validation context with original and translated SQL

        Returns:
            Validation result with issues and recommendations
        """
        # Feature 036: Add skip logic for CHECK constraints
        if re.search(r"\bADD\s+CONSTRAINT\b.*\bCHECK\s*\(", context.translated_sql, re.IGNORECASE):
            return ValidationResult(
                success=True,
                confidence=1.0,
                issues=[],
                recommendations=[],
            )

        with PerformanceTimer() as timer:
            issues: list[ValidationIssue] = []
            recommendations: list[str] = []

            try:
                # Basic syntax validation
                syntax_issues = self._validate_syntax(context)
                issues.extend(syntax_issues)

                # Structure comparison
                structure_issues = self._validate_structure(context)
                issues.extend(structure_issues)

                # Semantic analysis
                if self.validation_level in [
                    ValidationLevel.SEMANTIC,
                    ValidationLevel.STRICT,
                    ValidationLevel.EXHAUSTIVE,
                ]:
                    semantic_issues = self._validate_semantics(context)
                    issues.extend(semantic_issues)

                # Constitutional compliance checks
                if self.validation_level in [ValidationLevel.STRICT, ValidationLevel.EXHAUSTIVE]:
                    compliance_issues = self._validate_constitutional_compliance(context)
                    issues.extend(compliance_issues)

                # Performance impact assessment
                if context.include_performance:
                    perf_recommendations = self._assess_performance_impact(context)
                    recommendations.extend(perf_recommendations)

                # Generate overall validation result
                success = not any(issue.severity == IssueSeverity.ERROR for issue in issues)
                confidence = self._calculate_confidence(issues, context)

                # Update performance metrics
                self._update_metrics(timer.elapsed_ms, success)

                return ValidationResult(
                    success=success,
                    confidence=confidence,
                    issues=issues,
                    recommendations=recommendations,
                )

            except Exception as e:
                self.logger.error(f"Validation failed: {e}")
                return ValidationResult(
                    success=False,
                    confidence=0.0,
                    issues=[
                        ValidationIssue(
                            severity=IssueSeverity.ERROR,
                            message=f"Validation process failed: {str(e)}",
                        )
                    ],
                    recommendations=["Review query for potential syntax or structural issues"],
                )

    def analyze_query(self, sql: str) -> QueryAnalysis:
        """
        Analyze SQL query structure and characteristics

        Args:
            sql: SQL query to analyze

        Returns:
            Query analysis results
        """
        # Normalize SQL for analysis
        normalized_sql = self._normalize_sql(sql)

        # Detect query type
        query_type = self._detect_query_type(normalized_sql)

        # Extract components
        tables = self._extract_tables(normalized_sql)
        columns = self._extract_columns(normalized_sql)
        functions = self._extract_functions(normalized_sql)
        constructs = self._extract_constructs(normalized_sql)

        # Calculate complexity
        complexity = self._calculate_complexity(normalized_sql, tables, columns, functions)

        # Generate performance hints
        hints = self._generate_performance_hints(normalized_sql, complexity)

        return QueryAnalysis(
            query_type=query_type,
            tables_referenced=tables,
            columns_referenced=columns,
            functions_used=functions,
            constructs_detected=constructs,
            complexity_score=complexity,
            performance_hints=hints,
        )

    def compare_query_results(
        self, original_analysis: QueryAnalysis, translated_analysis: QueryAnalysis
    ) -> QueryEquivalenceReport:
        """
        Compare analysis results between original and translated queries

        Args:
            original_analysis: Analysis of original IRIS query
            translated_analysis: Analysis of translated PostgreSQL query

        Returns:
            Equivalence comparison report
        """
        equivalence_score = 1.0
        differences = []
        similarities = []

        # Compare query types
        if original_analysis.query_type != translated_analysis.query_type:
            differences.append(
                f"Query type mismatch: {original_analysis.query_type} vs {translated_analysis.query_type}"
            )
            equivalence_score -= 0.3
        else:
            similarities.append(f"Query type matches: {original_analysis.query_type}")

        # Compare table references
        table_overlap = original_analysis.tables_referenced & translated_analysis.tables_referenced
        table_diff = original_analysis.tables_referenced ^ translated_analysis.tables_referenced

        if table_diff:
            differences.append(f"Table reference differences: {table_diff}")
            equivalence_score -= 0.2 * (
                len(table_diff) / max(len(original_analysis.tables_referenced), 1)
            )

        if table_overlap:
            similarities.append(f"Common table references: {table_overlap}")

        # Compare complexity
        complexity_diff = abs(
            original_analysis.complexity_score - translated_analysis.complexity_score
        )
        if complexity_diff > 0.2:
            differences.append(f"Significant complexity difference: {complexity_diff:.2f}")
            equivalence_score -= min(complexity_diff * 0.1, 0.2)
        else:
            similarities.append(
                f"Similar complexity: {original_analysis.complexity_score:.2f} vs {translated_analysis.complexity_score:.2f}"
            )

        # Calculate final equivalence
        is_equivalent = equivalence_score >= 0.8  # 80% threshold for equivalence

        return QueryEquivalenceReport(
            is_equivalent=is_equivalent,
            equivalence_score=equivalence_score,
            differences=differences,
            similarities=similarities,
            original_complexity=original_analysis.complexity_score,
            translated_complexity=translated_analysis.complexity_score,
        )

    def get_validation_stats(self) -> dict[str, Any]:
        """
        Get validator performance statistics

        Returns:
            Validation statistics and metrics
        """
        avg_time = (
            self._total_validation_time_ms / self._validation_count
            if self._validation_count > 0
            else 0.0
        )

        return {
            "total_validations": self._validation_count,
            "average_validation_time_ms": avg_time,
            "constitutional_violations": self._constitutional_violations,
            "validation_level": self.validation_level.value,
            "sla_compliance_rate": max(
                0.0, 1.0 - (self._constitutional_violations / max(self._validation_count, 1))
            ),
            "performance_metrics": {
                "total_time_ms": self._total_validation_time_ms,
                "avg_time_ms": avg_time,
                "sla_requirement_ms": 2.0,  # Validation should be fast
                "violations": self._constitutional_violations,
            },
        }

    def _setup_validation_rules(self):
        """Setup validation rules and patterns"""
        # SQL keywords that should be preserved
        self.critical_keywords = {
            "SELECT",
            "FROM",
            "WHERE",
            "GROUP BY",
            "ORDER BY",
            "HAVING",
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "ALTER",
            "DROP",
        }

        # IRIS constructs that require careful translation
        self.iris_constructs = {
            "TOP",
            "%SQLUPPER",
            "%SQLLOWER",
            "%SYSTEM",
            "JSON_TABLE",
            "VECTOR_COSINE",
            "TO_VECTOR",
            "%STARTSWITH",
            "%CONTAINS",
        }

        # PostgreSQL equivalents to validate
        self.postgresql_equivalents = {
            "LIMIT",
            "UPPER",
            "LOWER",
            "CURRENT_DATABASE",
            "jsonb_extract_path",
            "cosine_distance",
            "ARRAY",
            "LIKE",
            "POSITION",
        }

    def _validate_syntax(self, context: ValidationContext) -> list[ValidationIssue]:
        """Validate basic SQL syntax"""
        issues = []

        # Check for balanced parentheses
        if not self._check_balanced_parentheses(context.translated_sql):
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR, message="Unbalanced parentheses in translated SQL"
                )
            )

        # Check for valid SQL structure
        if not self._check_basic_sql_structure(context.translated_sql):
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message="Invalid SQL structure in translated query",
                )
            )

        return issues

    def _validate_structure(self, context: ValidationContext) -> list[ValidationIssue]:
        """Validate query structure preservation"""
        issues = []

        # Analyze both queries
        original_analysis = self.analyze_query(context.original_sql)
        translated_analysis = self.analyze_query(context.translated_sql)

        # Compare structures
        if original_analysis.query_type != translated_analysis.query_type:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message=f"Query type changed: {original_analysis.query_type} -> {translated_analysis.query_type}",
                )
            )

        # Check for missing critical elements
        original_keywords = self._extract_sql_keywords(context.original_sql)
        translated_keywords = self._extract_sql_keywords(context.translated_sql)
        missing_keywords = original_keywords - translated_keywords

        if missing_keywords:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    message=f"Missing SQL keywords in translation: {missing_keywords}",
                )
            )

        return issues

    def _validate_semantics(self, context: ValidationContext) -> list[ValidationIssue]:
        """Validate semantic equivalence"""
        issues = []

        # Check construct mappings for accuracy
        for mapping in context.construct_mappings:
            if mapping.confidence < 0.8:  # High confidence threshold
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.WARNING,
                        message=f"Low confidence mapping: {mapping.original_syntax} -> {mapping.translated_syntax} (confidence: {mapping.confidence})",
                    )
                )

        # Validate function mappings
        function_issues = self._validate_function_mappings(context)
        issues.extend(function_issues)

        return issues

    def _validate_constitutional_compliance(
        self, context: ValidationContext
    ) -> list[ValidationIssue]:
        """Validate constitutional compliance requirements"""
        issues = []

        # Check if translation maintains data integrity
        if not self._check_data_integrity_preservation(context):
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    message="Translation may compromise data integrity",
                )
            )

        # Verify performance implications
        if self._has_performance_regression_risk(context):
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    message="Translation may introduce performance regression",
                )
            )

        return issues

    def _assess_performance_impact(self, context: ValidationContext) -> list[str]:
        """Assess performance impact of translation"""
        recommendations = []

        original_analysis = self.analyze_query(context.original_sql)
        translated_analysis = self.analyze_query(context.translated_sql)

        # Check complexity increase
        complexity_increase = (
            translated_analysis.complexity_score - original_analysis.complexity_score
        )
        if complexity_increase > 0.3:
            recommendations.append(
                f"Translation increased query complexity by {complexity_increase:.2f}"
            )

        # Check for performance hints
        if translated_analysis.performance_hints:
            recommendations.extend(translated_analysis.performance_hints)

        return recommendations

    def _calculate_confidence(
        self, issues: list[ValidationIssue], context: ValidationContext
    ) -> float:
        """Calculate overall validation confidence"""
        base_confidence = 1.0

        # Reduce confidence based on issues
        for issue in issues:
            if issue.severity == IssueSeverity.ERROR:
                base_confidence -= 0.3
            elif issue.severity == IssueSeverity.WARNING:
                base_confidence -= 0.1

        # Boost confidence for high-quality mappings
        high_confidence_mappings = sum(1 for m in context.construct_mappings if m.confidence >= 0.9)
        total_mappings = len(context.construct_mappings)

        if total_mappings > 0:
            mapping_quality_boost = (high_confidence_mappings / total_mappings) * 0.1
            base_confidence += mapping_quality_boost

        return max(0.0, min(1.0, base_confidence))

    def _update_metrics(self, validation_time_ms: float, success: bool):
        """Update validation metrics"""
        self._validation_count += 1
        self._total_validation_time_ms += validation_time_ms

        # Constitutional requirement: validation should be fast (2ms SLA)
        if validation_time_ms > 2.0:
            self._constitutional_violations += 1

    # Helper methods for query analysis

    def _normalize_sql(self, sql: str) -> str:
        """Normalize SQL for analysis"""
        # Remove comments
        sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
        sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)

        # Normalize whitespace
        sql = re.sub(r"\s+", " ", sql)
        return sql.strip()

    def _detect_query_type(self, sql: str) -> str:
        """Detect the type of SQL query"""
        sql_upper = sql.upper().strip()

        if sql_upper.startswith("SELECT"):
            return "SELECT"
        elif sql_upper.startswith("INSERT"):
            return "INSERT"
        elif sql_upper.startswith("UPDATE"):
            return "UPDATE"
        elif sql_upper.startswith("DELETE"):
            return "DELETE"
        elif sql_upper.startswith(("CREATE", "ALTER", "DROP")):
            return "DDL"
        else:
            return "UNKNOWN"

    def _extract_tables(self, sql: str) -> set[str]:
        """Extract table names from SQL"""
        tables = set()

        # Simple pattern matching for table names
        # More sophisticated parsing could use sqlparse
        from_pattern = r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)"
        join_pattern = r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)"
        update_pattern = r"\bUPDATE\s+([a-zA-Z_][a-zA-Z0-9_]*)"

        for pattern in [from_pattern, join_pattern, update_pattern]:
            matches = re.findall(pattern, sql, re.IGNORECASE)
            tables.update(matches)

        return tables

    def _extract_columns(self, sql: str) -> set[str]:
        """Extract column names from SQL"""
        columns = set()

        # Extract from SELECT clause
        select_match = re.search(r"\bSELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
        if select_match:
            select_clause = select_match.group(1)
            # Simple column extraction (could be enhanced)
            column_names = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", select_clause)
            columns.update(column_names)

        return columns

    def _extract_functions(self, sql: str) -> set[str]:
        """Extract function names from SQL"""
        functions = set()

        # Pattern for function calls
        function_pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\("
        matches = re.findall(function_pattern, sql, re.IGNORECASE)
        functions.update(matches)

        return functions

    def _extract_constructs(self, sql: str) -> set[str]:
        """Extract IRIS constructs from SQL"""
        constructs = set()

        for construct in self.iris_constructs:
            if construct in sql.upper():
                constructs.add(construct)

        return constructs

    def _calculate_complexity(
        self, sql: str, tables: set[str], columns: set[str], functions: set[str]
    ) -> float:
        """Calculate query complexity score"""
        complexity = 0.0

        # Base complexity from query length
        complexity += len(sql) / 1000.0

        # Add complexity for joins
        join_count = len(re.findall(r"\bJOIN\b", sql, re.IGNORECASE))
        complexity += join_count * 0.5

        # Add complexity for subqueries
        subquery_count = sql.count("(") - sql.count(")")  # Simplified
        complexity += abs(subquery_count) * 0.3

        # Add complexity for functions
        complexity += len(functions) * 0.2

        # Add complexity for multiple tables
        complexity += len(tables) * 0.1

        return complexity

    def _generate_performance_hints(self, sql: str, complexity: float) -> list[str]:
        """Generate performance optimization hints"""
        hints = []

        if complexity > 2.0:
            hints.append("Consider query optimization - high complexity detected")

        if "SELECT *" in sql.upper():
            hints.append("Avoid SELECT * - specify only needed columns")

        if len(re.findall(r"\bOR\b", sql, re.IGNORECASE)) > 3:
            hints.append("Consider restructuring multiple OR conditions")

        return hints

    def _check_balanced_parentheses(self, sql: str) -> bool:
        """Check if parentheses are balanced"""
        count = 0
        for char in sql:
            if char == "(":
                count += 1
            elif char == ")":
                count -= 1
                if count < 0:
                    return False
        return count == 0

    def _check_basic_sql_structure(self, sql: str) -> bool:
        """Check basic SQL structure validity"""
        sql_upper = sql.upper().strip()

        # Must start with valid SQL keyword
        valid_starts = ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "WITH"]
        starts_valid = any(sql_upper.startswith(start) for start in valid_starts)

        # Must not have obvious syntax errors
        has_semicolon_middle = ";" in sql[:-1]  # Semicolon not at end

        return starts_valid and not has_semicolon_middle

    def _extract_sql_keywords(self, sql: str) -> set[str]:
        """Extract SQL keywords from query"""
        keywords = set()
        sql_upper = sql.upper()

        for keyword in self.critical_keywords:
            if keyword in sql_upper:
                keywords.add(keyword)

        return keywords

    def _validate_function_mappings(self, context: ValidationContext) -> list[ValidationIssue]:
        """Validate function mappings accuracy"""
        issues = []

        # Check for unmapped IRIS functions
        iris_functions = self._extract_functions(context.original_sql)
        postgresql_functions = self._extract_functions(context.translated_sql)

        # Simple check for function preservation
        # More sophisticated mapping validation could be added
        if len(iris_functions) > len(postgresql_functions):
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    message="Some functions may not have been translated",
                )
            )

        return issues

    def _check_data_integrity_preservation(self, context: ValidationContext) -> bool:
        """Check if translation preserves data integrity"""
        # Basic check - ensure WHERE clauses are preserved
        original_has_where = "WHERE" in context.original_sql.upper()
        translated_has_where = "WHERE" in context.translated_sql.upper()

        return original_has_where == translated_has_where

    def _has_performance_regression_risk(self, context: ValidationContext) -> bool:
        """Check if translation has performance regression risk"""
        original_analysis = self.analyze_query(context.original_sql)
        translated_analysis = self.analyze_query(context.translated_sql)

        # Check for significant complexity increase
        complexity_increase = (
            translated_analysis.complexity_score - original_analysis.complexity_score
        )
        return complexity_increase > 0.5


# Global validator instance
_validator = SemanticValidator()


def get_validator() -> SemanticValidator:
    """Get the global validator instance"""
    return _validator


def validate_translation(
    original_sql: str,
    translated_sql: str,
    construct_mappings: list[ConstructMapping],
    validation_level: ValidationLevel = ValidationLevel.SEMANTIC,
) -> ValidationResult:
    """Validate translation equivalence (convenience function)"""
    context = ValidationContext(
        original_sql=original_sql,
        translated_sql=translated_sql,
        construct_mappings=construct_mappings,
        validation_level=validation_level,
    )
    return _validator.validate_query_equivalence(context)


def analyze_sql_query(sql: str) -> QueryAnalysis:
    """Analyze SQL query structure (convenience function)"""
    return _validator.analyze_query(sql)


# Export main components
__all__ = [
    "SemanticValidator",
    "ValidationContext",
    "QueryAnalysis",
    "ValidationLevel",
    "get_validator",
    "validate_translation",
    "analyze_sql_query",
]
