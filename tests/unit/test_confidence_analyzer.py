"""
Unit Tests for Translation Confidence Analyzer

Tests the confidence analysis system that evaluates translation quality,
reliability, and provides actionable insights for IRIS SQL translations.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock

from iris_pgwire.sql_translator.confidence_analyzer import (
    TranslationConfidenceAnalyzer,
    ConfidenceLevel,
    RiskCategory,
    ConfidenceMetrics,
    ConfidenceInsight,
    ConfidenceReport,
    ConfidenceTrend,
    get_confidence_analyzer,
    analyze_translation_confidence
)
from iris_pgwire.sql_translator.models import (
    TranslationResult,
    ConstructMapping,
    ConstructType,
    PerformanceStats,
    ValidationResult,
    ValidationIssue,
    SourceLocation,
    DebugTrace
)


class TestTranslationConfidenceAnalyzer:
    """Test the confidence analyzer functionality"""

    def setup_method(self):
        """Setup analyzer for each test"""
        self.analyzer = TranslationConfidenceAnalyzer()

    def test_confidence_level_classification(self):
        """Test confidence level classification"""
        assert self.analyzer._classify_confidence_level(0.95) == ConfidenceLevel.EXCELLENT
        assert self.analyzer._classify_confidence_level(0.85) == ConfidenceLevel.HIGH
        assert self.analyzer._classify_confidence_level(0.75) == ConfidenceLevel.MEDIUM
        assert self.analyzer._classify_confidence_level(0.55) == ConfidenceLevel.LOW
        assert self.analyzer._classify_confidence_level(0.25) == ConfidenceLevel.CRITICAL

    def test_excellent_confidence_translation(self):
        """Test analysis of high-confidence translation"""
        # Create high-confidence translation result
        mappings = [
            ConstructMapping(
                construct_type=ConstructType.FUNCTION,
                original_syntax="%SQLUPPER(name)",
                translated_syntax="UPPER(name)",
                confidence=0.95,
                source_location=SourceLocation(line=1, column=8, length=15)
            )
        ]

        performance_stats = PerformanceStats(
            translation_time_ms=2.5,
            cache_hit=False,
            constructs_detected=1,
            constructs_translated=1
        )

        validation_result = ValidationResult(
            success=True,
            confidence=0.9
        )

        result = TranslationResult(
            translated_sql="SELECT UPPER(name) FROM users;",
            construct_mappings=mappings,
            performance_stats=performance_stats,
            validation_result=validation_result
        )

        # Analyze confidence
        report = self.analyzer.analyze_translation_confidence(result)

        assert report.metrics.confidence_level == ConfidenceLevel.EXCELLENT
        assert report.metrics.overall_confidence > 0.9
        assert report.metrics.critical_confidence_count == 0
        assert report.metrics.low_confidence_count == 0
        assert len(report.insights) == 0  # No issues for excellent translation
        assert "excellent" in report.summary.lower()

    def test_critical_confidence_translation(self):
        """Test analysis of low-confidence translation"""
        # Create low-confidence translation result
        mappings = [
            ConstructMapping(
                construct_type=ConstructType.DOCUMENT_FILTER,
                original_syntax="JSON_COMPLEX_FUNCTION(data, path)",
                translated_syntax="jsonb_path_query(data, path)",  # Hypothetical low-confidence mapping
                confidence=0.3,
                source_location=SourceLocation(line=1, column=8, length=25)
            ),
            ConstructMapping(
                construct_type=ConstructType.SYNTAX,
                original_syntax="TOP 10 PERCENT",
                translated_syntax="LIMIT (0.1 * COUNT(*))",  # Complex, low-confidence conversion
                confidence=0.2,
                source_location=SourceLocation(line=1, column=40, length=12)
            )
        ]

        performance_stats = PerformanceStats(
            translation_time_ms=8.5,  # SLA violation
            cache_hit=False,
            constructs_detected=2,
            constructs_translated=1  # One construct failed
        )

        validation_result = ValidationResult(
            success=False,
            confidence=0.4,
            issues=[
                ValidationIssue(severity="error", message="Semantic mismatch detected")
            ]
        )

        result = TranslationResult(
            translated_sql="SELECT * FROM users LIMIT (0.1 * COUNT(*));",
            construct_mappings=mappings,
            performance_stats=performance_stats,
            validation_result=validation_result,
            warnings=["Complex construct translation may be inaccurate"]
        )

        # Analyze confidence
        report = self.analyzer.analyze_translation_confidence(result)

        assert report.metrics.confidence_level == ConfidenceLevel.CRITICAL
        assert report.metrics.overall_confidence < 0.4
        assert report.metrics.critical_confidence_count == 2
        assert len(report.insights) > 0
        assert any(insight.severity == "critical" for insight in report.insights)
        assert "CRITICAL" in report.summary

    def test_mixed_confidence_translation(self):
        """Test analysis of mixed confidence translation"""
        mappings = [
            ConstructMapping(
                construct_type=ConstructType.FUNCTION,
                original_syntax="%SQLUPPER(name)",
                translated_syntax="UPPER(name)",
                confidence=0.95,
                source_location=SourceLocation(line=1, column=8, length=15)
            ),
            ConstructMapping(
                construct_type=ConstructType.DATA_TYPE,
                original_syntax="LONGVARCHAR",
                translated_syntax="TEXT",
                confidence=0.85,
                source_location=SourceLocation(line=2, column=15, length=11)
            ),
            ConstructMapping(
                construct_type=ConstructType.JSON_FUNCTION,
                original_syntax="JSON_EXTRACT(data, '$.field')",
                translated_syntax="data->>'field'",
                confidence=0.6,  # Medium confidence
                source_location=SourceLocation(line=3, column=8, length=28)
            )
        ]

        performance_stats = PerformanceStats(
            translation_time_ms=3.2,
            cache_hit=True,
            constructs_detected=3,
            constructs_translated=3
        )

        result = TranslationResult(
            translated_sql="SELECT UPPER(name) FROM users WHERE data->>'field' = 'value';",
            construct_mappings=mappings,
            performance_stats=performance_stats
        )

        # Analyze confidence
        report = self.analyzer.analyze_translation_confidence(result)

        assert report.metrics.confidence_level in [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM]
        assert 0.7 <= report.metrics.overall_confidence <= 0.9
        assert ConstructType.FUNCTION in report.metrics.construct_type_breakdown
        assert ConstructType.DATA_TYPE in report.metrics.construct_type_breakdown
        assert ConstructType.JSON_FUNCTION in report.metrics.construct_type_breakdown

    def test_performance_confidence_calculation(self):
        """Test performance confidence calculation"""
        # High performance stats
        high_perf_stats = PerformanceStats(
            translation_time_ms=1.5,
            cache_hit=True,
            constructs_detected=5,
            constructs_translated=5
        )

        high_confidence = self.analyzer._calculate_performance_confidence(high_perf_stats)
        assert high_confidence > 0.9

        # Low performance stats
        low_perf_stats = PerformanceStats(
            translation_time_ms=7.5,  # SLA violation
            cache_hit=False,
            constructs_detected=5,
            constructs_translated=3  # Some failures
        )

        low_confidence = self.analyzer._calculate_performance_confidence(low_perf_stats)
        assert low_confidence < 0.7

    def test_risk_factor_identification(self):
        """Test identification of various risk factors"""
        # Create result with multiple risk factors
        mappings = [
            ConstructMapping(
                construct_type=ConstructType.DOCUMENT_FILTER,
                original_syntax="COMPLEX_OPERATION",
                translated_syntax="complex_translation",
                confidence=0.3,  # Critical confidence
                source_location=SourceLocation(line=1, column=1, length=10)
            )
        ]

        performance_stats = PerformanceStats(
            translation_time_ms=12.0,  # SLA violation
            cache_hit=False,
            constructs_detected=2,
            constructs_translated=1  # Incomplete translation
        )

        validation_result = ValidationResult(
            success=False,  # Validation failure
            confidence=0.5
        )

        result = TranslationResult(
            translated_sql="SELECT complex_translation FROM table;",
            construct_mappings=mappings,
            performance_stats=performance_stats,
            validation_result=validation_result,
            warnings=["Translation warning"]  # Has warnings
        )

        metrics = self.analyzer._calculate_confidence_metrics(result)
        risk_factors = metrics.risk_factors

        # Check for expected risk factors
        assert any("constitutional threshold" in risk.lower() for risk in risk_factors)
        assert any("critical confidence" in risk.lower() for risk in risk_factors)
        assert any("sla violation" in risk.lower() for risk in risk_factors)
        assert any("warnings" in risk.lower() for risk in risk_factors)
        assert any("validation failure" in risk.lower() for risk in risk_factors)
        assert any("untranslated" in risk.lower() for risk in risk_factors)

    def test_recommendations_generation(self):
        """Test generation of actionable recommendations"""
        # Critical confidence scenario
        result_critical = self._create_test_result(overall_confidence=0.3)
        metrics_critical = self.analyzer._calculate_confidence_metrics(result_critical)
        recommendations_critical = self.analyzer._generate_recommendations(
            0.3, metrics_critical.risk_factors, result_critical
        )

        assert any("manual review" in rec.lower() for rec in recommendations_critical)
        assert any("critical" in rec.lower() for rec in recommendations_critical)

        # Medium confidence scenario
        result_medium = self._create_test_result(overall_confidence=0.75)
        metrics_medium = self.analyzer._calculate_confidence_metrics(result_medium)
        recommendations_medium = self.analyzer._generate_recommendations(
            0.75, metrics_medium.risk_factors, result_medium
        )

        assert any("testing" in rec.lower() for rec in recommendations_medium)

    def test_construct_analysis(self):
        """Test individual construct confidence analysis"""
        mappings = [
            ConstructMapping(
                construct_type=ConstructType.FUNCTION,
                original_syntax="%SQLUPPER(name)",
                translated_syntax="UPPER(name)",
                confidence=0.95,
                source_location=SourceLocation(line=1, column=8, length=15),
                metadata={"function_name": "%SQLUPPER"}
            ),
            ConstructMapping(
                construct_type=ConstructType.DATA_TYPE,
                original_syntax="LONGVARCHAR",
                translated_syntax="TEXT",
                confidence=0.4,  # Low confidence
                source_location=SourceLocation(line=2, column=15, length=11)
            )
        ]

        analysis = self.analyzer._analyze_construct_confidence(mappings)

        assert len(analysis) == 2

        function_key = "FUNCTION:%SQLUPPER(name)"
        assert function_key in analysis
        assert analysis[function_key]['confidence'] == 0.95
        assert analysis[function_key]['confidence_level'] == ConfidenceLevel.EXCELLENT.value
        assert analysis[function_key]['risk_assessment'] == "minimal"

        datatype_key = "DATA_TYPE:LONGVARCHAR"
        assert datatype_key in analysis
        assert analysis[datatype_key]['confidence'] == 0.4
        assert analysis[datatype_key]['confidence_level'] == ConfidenceLevel.LOW.value
        assert analysis[datatype_key]['risk_assessment'] == "high"

    def test_insight_generation(self):
        """Test generation of confidence insights"""
        # Create result with various insight triggers
        result = self._create_test_result(
            sla_violation=True,
            validation_failure=True,
            low_confidence_constructs=True
        )

        metrics = self.analyzer._calculate_confidence_metrics(result)
        insights = self.analyzer._generate_confidence_insights(result, metrics)

        # Should have multiple insights
        assert len(insights) > 0

        # Check for different insight categories
        categories = {insight.category for insight in insights}
        severities = {insight.severity for insight in insights}

        assert RiskCategory.PERFORMANCE_IMPACT in categories or RiskCategory.SEMANTIC_ACCURACY in categories
        assert "warning" in severities or "error" in severities

    def test_confidence_trends_analysis(self):
        """Test confidence trends over time"""
        # Record some confidence data
        base_time = datetime.utcnow()

        # Simulate improving trend - ensure all timestamps are within the last 24 hours
        confidence_values = [0.6, 0.65, 0.7, 0.75, 0.8, 0.85]
        for i, confidence in enumerate(confidence_values):
            timestamp = base_time - timedelta(hours=i*3)  # Each entry 3 hours apart, all within 24h
            self.analyzer._record_confidence_data(timestamp, confidence, f"query_{i}")

        # Analyze trend
        trend = self.analyzer.analyze_confidence_trends("24h")

        assert trend.sample_count == len(confidence_values)
        assert trend.confidence_trend in ["improving", "stable"]  # Might be stable due to small diff
        assert trend.trend_confidence > 0.5
        assert trend.average_confidence > 0.7

    def test_confidence_statistics(self):
        """Test overall confidence statistics"""
        # Record various confidence levels
        confidence_values = [0.9, 0.8, 0.7, 0.6, 0.3, 0.95, 0.85]
        for i, confidence in enumerate(confidence_values):
            self.analyzer._record_confidence_data(
                datetime.utcnow() - timedelta(minutes=i),
                confidence,
                f"query_{i}"
            )

        stats = self.analyzer.get_confidence_statistics()

        assert stats["total_translations"] == len(confidence_values)
        assert stats["average_confidence"] == sum(confidence_values) / len(confidence_values)
        assert stats["min_confidence"] == min(confidence_values)
        assert stats["max_confidence"] == max(confidence_values)
        assert "confidence_distribution" in stats
        assert "constitutional_compliance" in stats

    def test_global_analyzer_functions(self):
        """Test global analyzer convenience functions"""
        # Test get_confidence_analyzer
        analyzer1 = get_confidence_analyzer()
        analyzer2 = get_confidence_analyzer()
        assert analyzer1 is analyzer2  # Should be singleton

        # Test analyze_translation_confidence convenience function
        result = self._create_test_result()
        report = analyze_translation_confidence(result)
        assert isinstance(report, ConfidenceReport)
        assert report.metrics is not None

    def test_confidence_metrics_validation(self):
        """Test confidence metrics validation"""
        # Test invalid overall confidence
        with pytest.raises(ValueError, match="Overall confidence must be between 0.0 and 1.0"):
            ConfidenceMetrics(
                overall_confidence=1.5,  # Invalid
                confidence_level=ConfidenceLevel.HIGH,
                construct_confidence_avg=0.8,
                validation_confidence_avg=0.8,
                low_confidence_count=0,
                critical_confidence_count=0
            )

    def test_weighted_confidence_calculation(self):
        """Test weighted confidence calculation with different scenarios"""
        # Simple translation (few constructs)
        simple_result = self._create_test_result(constructs_count=1)
        simple_metrics = self.analyzer._calculate_confidence_metrics(simple_result)

        # Complex translation (many constructs)
        complex_result = self._create_test_result(constructs_count=10)
        complex_metrics = self.analyzer._calculate_confidence_metrics(complex_result)

        # Both should have reasonable confidence values
        assert 0.0 <= simple_metrics.overall_confidence <= 1.0
        assert 0.0 <= complex_metrics.overall_confidence <= 1.0

    def test_constitutional_compliance_integration(self):
        """Test integration with constitutional compliance requirements"""
        # Test translation that meets constitutional requirements
        compliant_result = self._create_test_result(
            translation_time=2.0,  # Under 5ms SLA
            high_confidence=True
        )

        report = self.analyzer.analyze_translation_confidence(compliant_result)

        assert report.performance_analysis['constitutional_compliance']['sla_violation'] is False

        # Test translation that violates constitutional requirements
        non_compliant_result = self._create_test_result(
            translation_time=8.0,  # Over 5ms SLA
            high_confidence=False
        )

        report_nc = self.analyzer.analyze_translation_confidence(non_compliant_result)

        assert report_nc.performance_analysis['constitutional_compliance']['sla_violation'] is True
        assert any("constitutional" in risk.lower() for risk in report_nc.metrics.risk_factors)

    def _create_test_result(self, overall_confidence=0.8, sla_violation=False,
                           validation_failure=False, low_confidence_constructs=False,
                           constructs_count=3, translation_time=3.0,
                           high_confidence=True) -> TranslationResult:
        """Helper to create test translation results"""

        # Create mappings based on parameters
        mappings = []
        for i in range(constructs_count):
            confidence = 0.9 if high_confidence else (0.3 if low_confidence_constructs else 0.8)
            if i == 0 and low_confidence_constructs:
                confidence = 0.3  # Ensure at least one low confidence

            mappings.append(ConstructMapping(
                construct_type=ConstructType.FUNCTION,
                original_syntax=f"FUNCTION_{i}()",
                translated_syntax=f"function_{i}()",
                confidence=confidence,
                source_location=SourceLocation(line=i+1, column=1, length=10)
            ))

        # Create performance stats
        performance_stats = PerformanceStats(
            translation_time_ms=translation_time if not sla_violation else 8.0,
            cache_hit=False,
            constructs_detected=constructs_count,
            constructs_translated=constructs_count
        )

        # Create validation result
        validation_result = None
        if validation_failure:
            validation_result = ValidationResult(
                success=False,
                confidence=0.4,
                issues=[ValidationIssue(severity="error", message="Test validation error")]
            )
        else:
            validation_result = ValidationResult(success=True, confidence=0.9)

        return TranslationResult(
            translated_sql="SELECT function_0() FROM test;",
            construct_mappings=mappings,
            performance_stats=performance_stats,
            validation_result=validation_result
        )


class TestConfidenceAnalyzerIntegration:
    """Integration tests for confidence analyzer"""

    def test_end_to_end_confidence_analysis(self):
        """Test complete confidence analysis workflow"""
        analyzer = TranslationConfidenceAnalyzer()

        # Create a realistic translation result
        mappings = [
            ConstructMapping(
                construct_type=ConstructType.FUNCTION,
                original_syntax="%SQLUPPER(name)",
                translated_syntax="UPPER(name)",
                confidence=0.95,
                source_location=SourceLocation(line=1, column=8, length=15)
            ),
            ConstructMapping(
                construct_type=ConstructType.DATA_TYPE,
                original_syntax="LONGVARCHAR",
                translated_syntax="TEXT",
                confidence=0.85,
                source_location=SourceLocation(line=2, column=20, length=11)
            ),
            ConstructMapping(
                construct_type=ConstructType.DOCUMENT_FILTER,
                original_syntax="JSON_EXTRACT(data, '$.field')",
                translated_syntax="data->>'field'",
                confidence=0.75,
                source_location=SourceLocation(line=3, column=15, length=28)
            )
        ]

        performance_stats = PerformanceStats(
            translation_time_ms=3.2,
            cache_hit=True,
            constructs_detected=3,
            constructs_translated=3,
            parsing_time_ms=1.0,
            mapping_time_ms=1.5,
            validation_time_ms=0.7
        )

        validation_result = ValidationResult(
            success=True,
            confidence=0.85,
            performance_impact="minimal"
        )

        result = TranslationResult(
            translated_sql="SELECT UPPER(name) FROM users WHERE data->>'field' = 'test';",
            construct_mappings=mappings,
            performance_stats=performance_stats,
            validation_result=validation_result
        )

        # Perform analysis
        report = analyzer.analyze_translation_confidence(result)

        # Verify comprehensive analysis
        assert isinstance(report, ConfidenceReport)
        assert report.metrics.confidence_level in [ConfidenceLevel.HIGH, ConfidenceLevel.EXCELLENT]
        assert len(report.construct_analysis) == 3
        assert report.performance_analysis['sla_compliant'] is True
        assert report.validation_analysis['success'] is True
        assert "reliable" in report.summary.lower() or "high" in report.summary.lower()

        # Test trend analysis after multiple translations
        for i in range(5):
            analyzer.analyze_translation_confidence(result)

        trend = analyzer.analyze_confidence_trends("1h")
        assert trend.sample_count > 1
        assert trend.average_confidence > 0.8

        # Test statistics
        stats = analyzer.get_confidence_statistics()
        assert stats["total_translations"] > 5
        assert stats["constitutional_compliance"]["compliance_rate"] == 1.0  # All compliant