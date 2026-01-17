"""
Translation Confidence Analyzer

Analyzes and reports on the confidence levels of IRIS SQL translations,
providing insights into translation quality, reliability, and potential issues.

Constitutional Compliance: High-confidence translations ensure reliable PostgreSQL compatibility.
"""

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from .models import (
    ConstructMapping,
    ConstructType,
    PerformanceStats,
    TranslationResult,
    ValidationResult,
)


class ConfidenceLevel(Enum):
    """Confidence level classifications"""

    CRITICAL = "CRITICAL"  # 0.0 - 0.4: Very low confidence, potential issues
    LOW = "LOW"  # 0.4 - 0.6: Low confidence, requires review
    MEDIUM = "MEDIUM"  # 0.6 - 0.8: Medium confidence, generally reliable
    HIGH = "HIGH"  # 0.8 - 0.9: High confidence, very reliable
    EXCELLENT = "EXCELLENT"  # 0.9 - 1.0: Excellent confidence, fully reliable


class RiskCategory(Enum):
    """Risk categories for translations"""

    SYNTAX_COMPATIBILITY = "SYNTAX_COMPATIBILITY"
    SEMANTIC_ACCURACY = "SEMANTIC_ACCURACY"
    PERFORMANCE_IMPACT = "PERFORMANCE_IMPACT"
    DATA_INTEGRITY = "DATA_INTEGRITY"
    FUNCTIONAL_CORRECTNESS = "FUNCTIONAL_CORRECTNESS"


@dataclass
class ConfidenceMetrics:
    """Metrics for translation confidence analysis"""

    overall_confidence: float
    confidence_level: ConfidenceLevel
    construct_confidence_avg: float
    validation_confidence_avg: float
    low_confidence_count: int
    critical_confidence_count: int
    construct_type_breakdown: dict[ConstructType, float] = field(default_factory=dict)
    risk_factors: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    confidence_distribution: dict[ConfidenceLevel, int] = field(default_factory=dict)

    def __post_init__(self):
        """Validate confidence metrics"""
        if not 0.0 <= self.overall_confidence <= 1.0:
            raise ValueError("Overall confidence must be between 0.0 and 1.0")


@dataclass
class ConfidenceInsight:
    """Individual insight about translation confidence"""

    category: RiskCategory
    severity: str  # "info", "warning", "error", "critical"
    message: str
    affected_constructs: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    confidence_impact: float = 0.0


@dataclass
class ConfidenceReport:
    """Comprehensive confidence analysis report"""

    analysis_timestamp: datetime
    query_sql: str
    metrics: ConfidenceMetrics
    insights: list[ConfidenceInsight] = field(default_factory=list)
    construct_analysis: dict[str, dict] = field(default_factory=dict)
    performance_analysis: dict[str, Any] = field(default_factory=dict)
    validation_analysis: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


@dataclass
class ConfidenceTrend:
    """Confidence trends over time"""

    time_period: str
    average_confidence: float
    confidence_trend: str  # "improving", "declining", "stable"
    trend_confidence: float  # Confidence in the trend analysis
    sample_count: int
    risk_pattern_changes: list[str] = field(default_factory=list)


class TranslationConfidenceAnalyzer:
    """
    Analyzes translation confidence and provides insights

    Features:
    - Multi-dimensional confidence analysis
    - Risk assessment and categorization
    - Trend analysis over time
    - Constitutional compliance integration
    - Actionable recommendations
    """

    def __init__(self):
        self._confidence_history: list[tuple[datetime, float, str]] = []
        self._risk_patterns: dict[str, int] = defaultdict(int)
        self._construct_performance: dict[ConstructType, list[float]] = defaultdict(list)

        # Confidence thresholds for constitutional compliance
        self.constitutional_thresholds = {
            "minimum_acceptable_confidence": 0.7,
            "high_confidence_target": 0.9,
            "critical_confidence_threshold": 0.4,
        }

    def analyze_translation_confidence(
        self, result: TranslationResult, query_context: dict | None = None
    ) -> ConfidenceReport:
        """
        Perform comprehensive confidence analysis on a translation result

        Args:
            result: Translation result to analyze
            query_context: Optional context about the query (complexity, usage patterns, etc.)

        Returns:
            Detailed confidence report with insights and recommendations
        """
        timestamp = datetime.now(UTC)

        # Calculate base confidence metrics
        metrics = self._calculate_confidence_metrics(result)

        # Generate insights based on analysis
        insights = self._generate_confidence_insights(result, metrics, query_context)

        # Analyze individual constructs
        construct_analysis = self._analyze_construct_confidence(result.construct_mappings)

        # Analyze performance confidence
        performance_analysis = self._analyze_performance_confidence(result.performance_stats)

        # Analyze validation confidence
        validation_analysis = self._analyze_validation_confidence(result.validation_result)

        # Generate summary
        summary = self._generate_confidence_summary(metrics, insights)

        # Record for trend analysis
        self._record_confidence_data(timestamp, metrics.overall_confidence, result.translated_sql)

        return ConfidenceReport(
            analysis_timestamp=timestamp,
            query_sql=result.translated_sql,
            metrics=metrics,
            insights=insights,
            construct_analysis=construct_analysis,
            performance_analysis=performance_analysis,
            validation_analysis=validation_analysis,
            summary=summary,
        )

    def _calculate_confidence_metrics(self, result: TranslationResult) -> ConfidenceMetrics:
        """Calculate comprehensive confidence metrics"""

        # Construct confidence analysis
        construct_confidences = [m.confidence for m in result.construct_mappings]
        construct_confidence_avg = (
            statistics.mean(construct_confidences) if construct_confidences else 1.0
        )

        # Validation confidence
        validation_confidence_avg = (
            result.validation_result.confidence if result.validation_result else 1.0
        )

        # Performance confidence (based on SLA compliance and success rate)
        performance_confidence = self._calculate_performance_confidence(result.performance_stats)

        # Overall confidence (weighted combination)
        overall_confidence = self._calculate_weighted_confidence(
            construct_confidence_avg, validation_confidence_avg, performance_confidence, result
        )

        # Confidence level classification
        confidence_level = self._classify_confidence_level(overall_confidence)

        # Count low and critical confidence constructs
        low_confidence_count = len([c for c in construct_confidences if 0.4 <= c < 0.7])
        critical_confidence_count = len([c for c in construct_confidences if c < 0.4])

        # Construct type breakdown
        construct_type_breakdown = {}
        for construct_type in ConstructType:
            type_confidences = [
                m.confidence
                for m in result.construct_mappings
                if m.construct_type == construct_type
            ]
            if type_confidences:
                construct_type_breakdown[construct_type] = statistics.mean(type_confidences)

        # Confidence distribution
        confidence_distribution = {}
        for confidence in construct_confidences:
            level = self._classify_confidence_level(confidence)
            confidence_distribution[level] = confidence_distribution.get(level, 0) + 1

        # Risk factors
        risk_factors = self._identify_risk_factors(result, overall_confidence)

        # Recommendations
        recommendations = self._generate_recommendations(overall_confidence, risk_factors, result)

        return ConfidenceMetrics(
            overall_confidence=overall_confidence,
            confidence_level=confidence_level,
            construct_confidence_avg=construct_confidence_avg,
            validation_confidence_avg=validation_confidence_avg,
            low_confidence_count=low_confidence_count,
            critical_confidence_count=critical_confidence_count,
            construct_type_breakdown=construct_type_breakdown,
            risk_factors=risk_factors,
            recommendations=recommendations,
            confidence_distribution=confidence_distribution,
        )

    def _calculate_performance_confidence(self, stats: PerformanceStats) -> float:
        """Calculate confidence based on performance metrics"""
        # Base confidence from success rate
        success_confidence = stats.translation_success_rate

        # SLA compliance confidence
        sla_confidence = 1.0 if stats.is_sla_compliant else 0.8

        # Cache hit can indicate stability (if enabled)
        cache_confidence = 1.0 if stats.cache_hit else 0.95

        # Combined performance confidence
        return success_confidence * 0.6 + sla_confidence * 0.3 + cache_confidence * 0.1

    def _calculate_weighted_confidence(
        self,
        construct_conf: float,
        validation_conf: float,
        performance_conf: float,
        result: TranslationResult,
    ) -> float:
        """Calculate weighted overall confidence"""
        weights = {
            "construct": 0.5,  # Construct mapping confidence is most important
            "validation": 0.3,  # Validation confidence for semantic accuracy
            "performance": 0.2,  # Performance confidence for reliability
        }

        # Adjust weights based on translation complexity
        complexity_factor = len(result.construct_mappings) / max(
            1, result.performance_stats.constructs_detected
        )

        if complexity_factor < 0.5:  # Simple translation, emphasize performance
            weights = {"construct": 0.4, "validation": 0.3, "performance": 0.3}
        elif complexity_factor > 0.9:  # Complex translation, emphasize construct accuracy
            weights = {"construct": 0.6, "validation": 0.3, "performance": 0.1}

        # Warning penalty
        warning_penalty = min(0.1 * len(result.warnings), 0.3)

        base_confidence = (
            construct_conf * weights["construct"]
            + validation_conf * weights["validation"]
            + performance_conf * weights["performance"]
        )

        return max(0.0, base_confidence - warning_penalty)

    def _classify_confidence_level(self, confidence: float) -> ConfidenceLevel:
        """Classify confidence score into level"""
        if confidence >= 0.9:
            return ConfidenceLevel.EXCELLENT
        elif confidence >= 0.8:
            return ConfidenceLevel.HIGH
        elif confidence >= 0.6:
            return ConfidenceLevel.MEDIUM
        elif confidence >= 0.4:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.CRITICAL

    def _identify_risk_factors(
        self, result: TranslationResult, overall_confidence: float
    ) -> list[str]:
        """Identify potential risk factors in the translation"""
        risk_factors = []

        # Low overall confidence
        if overall_confidence < self.constitutional_thresholds["minimum_acceptable_confidence"]:
            risk_factors.append("Overall confidence below constitutional threshold")

        # Critical confidence constructs
        critical_constructs = [m for m in result.construct_mappings if m.confidence < 0.4]
        if critical_constructs:
            risk_factors.append(f"{len(critical_constructs)} constructs with critical confidence")

        # SLA violations
        if not result.performance_stats.is_sla_compliant:
            risk_factors.append("Constitutional SLA violation (>5ms translation time)")

        # Translation warnings
        if result.warnings:
            risk_factors.append(f"{len(result.warnings)} translation warnings present")

        # Validation failures
        if result.validation_result and not result.validation_result.success:
            risk_factors.append("Validation failure detected")

        # Incomplete translations
        if (
            result.performance_stats.constructs_translated
            < result.performance_stats.constructs_detected
        ):
            untranslated = (
                result.performance_stats.constructs_detected
                - result.performance_stats.constructs_translated
            )
            risk_factors.append(f"{untranslated} constructs left untranslated")

        # Complex construct types with low confidence
        for construct_type, avg_confidence in self._get_construct_type_confidence(
            result.construct_mappings
        ).items():
            if avg_confidence < 0.6 and construct_type in [
                ConstructType.DOCUMENT_FILTER,
                ConstructType.JSON_FUNCTION,
            ]:
                risk_factors.append(f"Low confidence in {construct_type.value} translations")

        return risk_factors

    def _generate_recommendations(
        self, overall_confidence: float, risk_factors: list[str], result: TranslationResult
    ) -> list[str]:
        """Generate actionable recommendations based on confidence analysis"""
        recommendations = []

        # Overall confidence recommendations
        if overall_confidence < 0.4:
            recommendations.append("CRITICAL: Manual review required before production use")
            recommendations.append("Consider alternative SQL formulation for better compatibility")
        elif overall_confidence < 0.7:
            recommendations.append("Thorough testing recommended before production deployment")
            recommendations.append("Monitor query behavior in staging environment")
        elif overall_confidence < 0.9:
            recommendations.append("Standard testing and validation procedures apply")

        # Specific risk-based recommendations
        if "SLA violation" in str(risk_factors):
            recommendations.append("Optimize query complexity or enable caching for performance")

        if any("untranslated" in risk for risk in risk_factors):
            recommendations.append("Review untranslated constructs for manual conversion")

        if result.warnings:
            recommendations.append("Address translation warnings to improve reliability")

        # Construct-specific recommendations
        low_confidence_constructs = [m for m in result.construct_mappings if m.confidence < 0.7]
        if low_confidence_constructs:
            construct_types = {m.construct_type for m in low_confidence_constructs}
            for construct_type in construct_types:
                recommendations.append(f"Review {construct_type.value} mappings for accuracy")

        return recommendations

    def _generate_confidence_insights(
        self,
        result: TranslationResult,
        metrics: ConfidenceMetrics,
        query_context: dict | None = None,
    ) -> list[ConfidenceInsight]:
        """Generate detailed insights about confidence factors"""
        insights = []

        # Overall confidence insight
        if metrics.confidence_level == ConfidenceLevel.CRITICAL:
            insights.append(
                ConfidenceInsight(
                    category=RiskCategory.FUNCTIONAL_CORRECTNESS,
                    severity="critical",
                    message=f"Critical confidence level ({metrics.overall_confidence:.2f}) indicates high risk of translation errors",
                    suggested_actions=[
                        "Manual review required",
                        "Consider query rewriting",
                        "Extensive testing needed",
                    ],
                )
            )

        # Performance insights
        if not result.performance_stats.is_sla_compliant:
            insights.append(
                ConfidenceInsight(
                    category=RiskCategory.PERFORMANCE_IMPACT,
                    severity="warning",
                    message=f"Translation time ({result.performance_stats.translation_time_ms:.2f}ms) exceeds constitutional SLA",
                    suggested_actions=[
                        "Enable caching",
                        "Optimize query complexity",
                        "Profile translation bottlenecks",
                    ],
                )
            )

        # Validation insights
        if result.validation_result and not result.validation_result.success:
            insights.append(
                ConfidenceInsight(
                    category=RiskCategory.SEMANTIC_ACCURACY,
                    severity="error",
                    message="Validation failed, semantic accuracy cannot be guaranteed",
                    suggested_actions=[
                        "Review validation issues",
                        "Manual testing recommended",
                        "Check SQL compatibility",
                    ],
                )
            )

        # Construct-specific insights
        for construct_type, avg_confidence in metrics.construct_type_breakdown.items():
            if avg_confidence < 0.6:
                insights.append(
                    ConfidenceInsight(
                        category=RiskCategory.SYNTAX_COMPATIBILITY,
                        severity="warning" if avg_confidence >= 0.4 else "error",
                        message=f"{construct_type.value} constructs have low confidence ({avg_confidence:.2f})",
                        affected_constructs=[
                            m.original_syntax
                            for m in result.construct_mappings
                            if m.construct_type == construct_type
                        ],
                        suggested_actions=[
                            "Review construct mappings",
                            "Test affected functionality",
                        ],
                    )
                )

        return insights

    def _analyze_construct_confidence(self, mappings: list[ConstructMapping]) -> dict[str, dict]:
        """Analyze confidence at the construct level"""
        analysis = {}

        for mapping in mappings:
            construct_key = f"{mapping.construct_type.value}:{mapping.original_syntax}"

            analysis[construct_key] = {
                "confidence": mapping.confidence,
                "confidence_level": self._classify_confidence_level(mapping.confidence).value,
                "construct_type": mapping.construct_type.value,
                "original_syntax": mapping.original_syntax,
                "translated_syntax": mapping.translated_syntax,
                "source_location": {
                    "line": mapping.source_location.line,
                    "column": mapping.source_location.column,
                },
                "metadata": mapping.metadata,
                "risk_assessment": self._assess_construct_risk(mapping),
            }

        return analysis

    def _analyze_performance_confidence(self, stats: PerformanceStats) -> dict[str, Any]:
        """Analyze performance-related confidence factors"""
        return {
            "sla_compliant": stats.is_sla_compliant,
            "translation_time_ms": stats.translation_time_ms,
            "success_rate": stats.translation_success_rate,
            "cache_utilized": stats.cache_hit,
            "performance_confidence": self._calculate_performance_confidence(stats),
            "constitutional_compliance": {
                "sla_violation": not stats.is_sla_compliant,
                "constructs_processed": stats.constructs_detected,
                "constructs_successful": stats.constructs_translated,
            },
        }

    def _analyze_validation_confidence(
        self, validation_result: ValidationResult | None
    ) -> dict[str, Any]:
        """Analyze validation-related confidence factors"""
        if not validation_result:
            return {
                "validation_performed": False,
                "confidence": 1.0,  # Assume success if no validation performed
                "issues": [],
            }

        return {
            "validation_performed": True,
            "success": validation_result.success,
            "confidence": validation_result.confidence,
            "issues_count": len(validation_result.issues),
            "issues": [
                {
                    "severity": issue.severity,
                    "message": issue.message,
                    "recommendation": issue.recommendation,
                }
                for issue in validation_result.issues
            ],
            "performance_impact": validation_result.performance_impact,
            "recommendations": validation_result.recommendations,
        }

    def _assess_construct_risk(self, mapping: ConstructMapping) -> str:
        """Assess risk level for individual construct"""
        if mapping.confidence >= 0.9:
            return "minimal"
        elif mapping.confidence >= 0.7:
            return "low"
        elif mapping.confidence >= 0.5:
            return "medium"
        elif mapping.confidence >= 0.3:
            return "high"
        else:
            return "critical"

    def _generate_confidence_summary(
        self, metrics: ConfidenceMetrics, insights: list[ConfidenceInsight]
    ) -> str:
        """Generate human-readable confidence summary"""
        confidence_desc = {
            ConfidenceLevel.EXCELLENT: "excellent",
            ConfidenceLevel.HIGH: "high",
            ConfidenceLevel.MEDIUM: "medium",
            ConfidenceLevel.LOW: "low",
            ConfidenceLevel.CRITICAL: "critical",
        }

        critical_insights = [i for i in insights if i.severity == "critical"]
        error_insights = [i for i in insights if i.severity == "error"]
        warning_insights = [i for i in insights if i.severity == "warning"]

        summary_parts = [
            f"Translation confidence is {confidence_desc[metrics.confidence_level]} ({metrics.overall_confidence:.2f})."
        ]

        if critical_insights:
            summary_parts.append(
                f"CRITICAL: {len(critical_insights)} critical issues require immediate attention."
            )

        if error_insights:
            summary_parts.append(f"{len(error_insights)} errors detected.")

        if warning_insights:
            summary_parts.append(f"{len(warning_insights)} warnings present.")

        if metrics.critical_confidence_count > 0:
            summary_parts.append(
                f"{metrics.critical_confidence_count} constructs have critical confidence levels."
            )

        if (
            not critical_insights
            and not error_insights
            and metrics.confidence_level in [ConfidenceLevel.HIGH, ConfidenceLevel.EXCELLENT]
        ):
            summary_parts.append("Translation appears reliable for production use.")

        return " ".join(summary_parts)

    def _get_construct_type_confidence(
        self, mappings: list[ConstructMapping]
    ) -> dict[ConstructType, float]:
        """Get average confidence by construct type"""
        type_confidences = defaultdict(list)

        for mapping in mappings:
            type_confidences[mapping.construct_type].append(mapping.confidence)

        return {
            construct_type: statistics.mean(confidences)
            for construct_type, confidences in type_confidences.items()
        }

    def _record_confidence_data(self, timestamp: datetime, confidence: float, sql: str):
        """Record confidence data for trend analysis"""
        self._confidence_history.append((timestamp, confidence, sql))

        # Keep only recent history (last 1000 entries)
        if len(self._confidence_history) > 1000:
            self._confidence_history = self._confidence_history[-1000:]

    def analyze_confidence_trends(self, time_period: str = "24h") -> ConfidenceTrend:
        """Analyze confidence trends over specified time period"""
        if not self._confidence_history:
            return ConfidenceTrend(
                time_period=time_period,
                average_confidence=0.0,
                confidence_trend="insufficient_data",
                trend_confidence=0.0,
                sample_count=0,
            )

        # Filter by time period
        cutoff_time = datetime.now(UTC) - self._parse_time_period(time_period)
        recent_data = [
            (ts, conf, sql) for ts, conf, sql in self._confidence_history if ts >= cutoff_time
        ]

        if len(recent_data) < 2:
            return ConfidenceTrend(
                time_period=time_period,
                average_confidence=recent_data[0][1] if recent_data else 0.0,
                confidence_trend="insufficient_data",
                trend_confidence=0.0,
                sample_count=len(recent_data),
            )

        # Calculate trend
        confidences = [conf for _, conf, _ in recent_data]
        average_confidence = statistics.mean(confidences)

        # Simple trend analysis (first half vs second half)
        mid_point = len(confidences) // 2
        first_half_avg = statistics.mean(confidences[:mid_point])
        second_half_avg = statistics.mean(confidences[mid_point:])

        diff = second_half_avg - first_half_avg
        if abs(diff) < 0.05:
            trend = "stable"
            trend_confidence = 0.8
        elif diff > 0:
            trend = "improving"
            trend_confidence = min(0.9, 0.5 + abs(diff))
        else:
            trend = "declining"
            trend_confidence = min(0.9, 0.5 + abs(diff))

        return ConfidenceTrend(
            time_period=time_period,
            average_confidence=average_confidence,
            confidence_trend=trend,
            trend_confidence=trend_confidence,
            sample_count=len(recent_data),
        )

    def _parse_time_period(self, period: str) -> timedelta:
        """Parse time period string to timedelta"""
        if period.endswith("h"):
            return timedelta(hours=int(period[:-1]))
        elif period.endswith("d"):
            return timedelta(days=int(period[:-1]))
        elif period.endswith("m"):
            return timedelta(minutes=int(period[:-1]))
        else:
            return timedelta(hours=24)  # Default to 24 hours

    def get_confidence_statistics(self) -> dict[str, Any]:
        """Get overall confidence statistics"""
        if not self._confidence_history:
            return {"message": "No confidence data available"}

        confidences = [conf for _, conf, _ in self._confidence_history]

        return {
            "total_translations": len(confidences),
            "average_confidence": statistics.mean(confidences),
            "median_confidence": statistics.median(confidences),
            "min_confidence": min(confidences),
            "max_confidence": max(confidences),
            "std_deviation": statistics.stdev(confidences) if len(confidences) > 1 else 0.0,
            "confidence_distribution": {
                level.value: len(
                    [c for c in confidences if self._classify_confidence_level(c) == level]
                )
                for level in ConfidenceLevel
            },
            "constitutional_compliance": {
                "above_threshold": len(
                    [
                        c
                        for c in confidences
                        if c >= self.constitutional_thresholds["minimum_acceptable_confidence"]
                    ]
                ),
                "below_threshold": len(
                    [
                        c
                        for c in confidences
                        if c < self.constitutional_thresholds["minimum_acceptable_confidence"]
                    ]
                ),
                "compliance_rate": len(
                    [
                        c
                        for c in confidences
                        if c >= self.constitutional_thresholds["minimum_acceptable_confidence"]
                    ]
                )
                / len(confidences),
            },
        }


# Global analyzer instance
_confidence_analyzer = TranslationConfidenceAnalyzer()


def get_confidence_analyzer() -> TranslationConfidenceAnalyzer:
    """Get the global confidence analyzer instance"""
    return _confidence_analyzer


def analyze_translation_confidence(
    result: TranslationResult, query_context: dict | None = None
) -> ConfidenceReport:
    """Analyze translation confidence (convenience function)"""
    return _confidence_analyzer.analyze_translation_confidence(result, query_context)


def get_confidence_trends(time_period: str = "24h") -> ConfidenceTrend:
    """Get confidence trends (convenience function)"""
    return _confidence_analyzer.analyze_confidence_trends(time_period)


def get_confidence_statistics() -> dict[str, Any]:
    """Get confidence statistics (convenience function)"""
    return _confidence_analyzer.get_confidence_statistics()


# Export main components
__all__ = [
    "TranslationConfidenceAnalyzer",
    "ConfidenceReport",
    "ConfidenceMetrics",
    "ConfidenceInsight",
    "ConfidenceTrend",
    "ConfidenceLevel",
    "RiskCategory",
    "get_confidence_analyzer",
    "analyze_translation_confidence",
    "get_confidence_trends",
    "get_confidence_statistics",
]
