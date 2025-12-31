# Translation Confidence Analysis API

## Overview

The Translation Confidence Analysis system provides comprehensive confidence assessment for IRIS SQL translations. It analyzes translation quality, reliability, and provides actionable insights to ensure high-quality PostgreSQL compatibility.

## Core Components

### 1. Confidence Analyzer

The `TranslationConfidenceAnalyzer` provides multi-dimensional confidence analysis:

```python
from iris_pgwire.sql_translator.confidence_analyzer import (
    get_confidence_analyzer,
    analyze_translation_confidence
)

# Get analyzer instance
analyzer = get_confidence_analyzer()

# Analyze translation result
report = analyzer.analyze_translation_confidence(translation_result)
```

### 2. Confidence Levels

Confidence is classified into five levels:

| Level | Range | Description | Action Required |
|-------|-------|-------------|-----------------|
| EXCELLENT | 0.9 - 1.0 | Fully reliable, production ready | None |
| HIGH | 0.8 - 0.9 | Very reliable, minimal risk | Standard testing |
| MEDIUM | 0.6 - 0.8 | Generally reliable | Thorough testing |
| LOW | 0.4 - 0.6 | Requires review | Manual review recommended |
| CRITICAL | 0.0 - 0.4 | High risk of errors | Manual review required |

### 3. Risk Categories

Confidence analysis identifies risks across multiple categories:

- **SYNTAX_COMPATIBILITY**: PostgreSQL syntax compatibility issues
- **SEMANTIC_ACCURACY**: Logical equivalence and data integrity
- **PERFORMANCE_IMPACT**: Query performance implications
- **DATA_INTEGRITY**: Data consistency and accuracy risks
- **FUNCTIONAL_CORRECTNESS**: Overall functional behavior

## API Integration

### REST Endpoint for Confidence Analysis

**POST** `/translate/confidence`

Enhanced translation endpoint with confidence analysis included in response.

#### Request
```json
{
  "sql": "SELECT %SQLUPPER(name), JSON_EXTRACT(data, '$.email') FROM users",
  "include_confidence_analysis": true,
  "confidence_options": {
    "include_trends": true,
    "include_recommendations": true
  }
}
```

#### Response
```json
{
  "success": true,
  "translated_sql": "SELECT UPPER(name), data->>'email' FROM users;",
  "confidence_analysis": {
    "overall_confidence": 0.92,
    "confidence_level": "EXCELLENT",
    "construct_confidence_avg": 0.95,
    "validation_confidence_avg": 0.88,
    "risk_factors": [],
    "recommendations": [
      "Translation appears reliable for production use."
    ],
    "construct_breakdown": {
      "FUNCTION": 0.95,
      "DOCUMENT_FILTER": 0.88
    },
    "insights": [
      {
        "category": "FUNCTIONAL_CORRECTNESS",
        "severity": "info",
        "message": "High confidence translation with excellent PostgreSQL compatibility",
        "confidence_impact": 0.0
      }
    ],
    "summary": "Translation confidence is excellent (0.92). Translation appears reliable for production use."
  },
  "performance_stats": {
    "translation_time_ms": 2.1,
    "sla_compliant": true
  }
}
```

### Confidence Trends Endpoint

**GET** `/confidence/trends`

Analyze confidence trends over time periods.

#### Parameters
- `time_period`: Time period for analysis (1h, 24h, 7d, 30d)
- `include_details`: Include detailed trend analysis

#### Response
```json
{
  "time_period": "24h",
  "average_confidence": 0.89,
  "confidence_trend": "improving",
  "trend_confidence": 0.85,
  "sample_count": 450,
  "confidence_distribution": {
    "EXCELLENT": 290,
    "HIGH": 120,
    "MEDIUM": 35,
    "LOW": 5,
    "CRITICAL": 0
  },
  "risk_pattern_changes": [
    "Improved DOCUMENT_FILTER confidence by 12%",
    "Reduced PERFORMANCE_IMPACT risks by 8%"
  ]
}
```

### Confidence Statistics Endpoint

**GET** `/confidence/statistics`

Get comprehensive confidence statistics and constitutional compliance.

#### Response
```json
{
  "total_translations": 12500,
  "average_confidence": 0.875,
  "median_confidence": 0.91,
  "confidence_distribution": {
    "EXCELLENT": 8750,
    "HIGH": 2500,
    "MEDIUM": 1000,
    "LOW": 200,
    "CRITICAL": 50
  },
  "constitutional_compliance": {
    "above_threshold": 12250,
    "below_threshold": 250,
    "compliance_rate": 0.98,
    "threshold": 0.7
  },
  "performance_correlation": {
    "high_confidence_avg_time_ms": 1.8,
    "low_confidence_avg_time_ms": 3.2,
    "confidence_performance_correlation": 0.65
  }
}
```

## Python SDK Integration

### Enhanced Translation Client

```python
from iris_pgwire.sql_translator.translator import IRISSQLTranslator, TranslationContext
from iris_pgwire.sql_translator.confidence_analyzer import get_confidence_analyzer

class ConfidenceAwareTranslator:
    def __init__(self):
        self.translator = IRISSQLTranslator()
        self.analyzer = get_confidence_analyzer()

    def translate_with_confidence(self, sql, min_confidence=0.8):
        """Translate with confidence validation"""
        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)

        # Analyze confidence
        confidence_report = self.analyzer.analyze_translation_confidence(result)

        if confidence_report.metrics.overall_confidence < min_confidence:
            raise ValueError(
                f"Translation confidence {confidence_report.metrics.overall_confidence:.2f} "
                f"below minimum threshold {min_confidence}"
            )

        return {
            'translated_sql': result.translated_sql,
            'confidence_report': confidence_report,
            'safe_for_production': confidence_report.metrics.confidence_level.value in ['EXCELLENT', 'HIGH']
        }

    def get_confidence_recommendations(self, sql):
        """Get confidence-based recommendations for query"""
        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)
        confidence_report = self.analyzer.analyze_translation_confidence(result)

        return {
            'recommendations': confidence_report.metrics.recommendations,
            'risk_factors': confidence_report.metrics.risk_factors,
            'insights': confidence_report.insights,
            'suggested_testing': self._get_testing_suggestions(confidence_report)
        }

    def _get_testing_suggestions(self, report):
        """Generate testing suggestions based on confidence"""
        suggestions = []

        if report.metrics.confidence_level.value == 'CRITICAL':
            suggestions.extend([
                "Extensive manual testing required",
                "Compare results with original IRIS execution",
                "Test with representative data sets",
                "Validate data integrity"
            ])
        elif report.metrics.confidence_level.value == 'LOW':
            suggestions.extend([
                "Thorough functional testing recommended",
                "Validate query results",
                "Test edge cases"
            ])
        elif report.metrics.confidence_level.value == 'MEDIUM':
            suggestions.extend([
                "Standard testing procedures",
                "Performance validation"
            ])

        return suggestions
```

### Usage Examples

```python
# Basic confidence-aware translation
translator = ConfidenceAwareTranslator()

try:
    result = translator.translate_with_confidence(
        "SELECT %SQLUPPER(name), JSON_EXTRACT(data, '$.field') FROM table",
        min_confidence=0.8
    )

    print(f"Translation: {result['translated_sql']}")
    print(f"Confidence: {result['confidence_report'].metrics.overall_confidence:.2f}")
    print(f"Production Ready: {result['safe_for_production']}")

except ValueError as e:
    print(f"Translation rejected: {e}")

    # Get recommendations for improvement
    recommendations = translator.get_confidence_recommendations(sql)
    print("Recommendations:", recommendations['recommendations'])
    print("Testing suggestions:", recommendations['suggested_testing'])
```

## Constitutional Compliance Integration

### Confidence-Based SLA Monitoring

The confidence analyzer integrates with constitutional compliance monitoring:

```python
class ConstitutionalConfidenceMonitor:
    def __init__(self):
        self.analyzer = get_confidence_analyzer()
        self.compliance_thresholds = {
            'minimum_confidence': 0.7,
            'high_confidence_target': 0.9,
            'critical_threshold': 0.4
        }

    def validate_constitutional_compliance(self, translation_result):
        """Validate translation meets constitutional requirements"""
        confidence_report = self.analyzer.analyze_translation_confidence(translation_result)

        compliance_status = {
            'sla_compliant': translation_result.performance_stats.is_sla_compliant,
            'confidence_compliant': confidence_report.metrics.overall_confidence >= self.compliance_thresholds['minimum_confidence'],
            'overall_compliant': False
        }

        compliance_status['overall_compliant'] = (
            compliance_status['sla_compliant'] and
            compliance_status['confidence_compliant']
        )

        return compliance_status, confidence_report
```

### Automated Quality Gates

```python
def constitutional_quality_gate(sql):
    """Constitutional quality gate for translations"""
    translator = IRISSQLTranslator()
    analyzer = get_confidence_analyzer()

    # Perform translation
    context = TranslationContext(original_sql=sql)
    result = translator.translate(context)

    # Analyze confidence
    confidence_report = analyzer.analyze_translation_confidence(result)

    # Constitutional checks
    checks = {
        'sla_compliance': result.performance_stats.is_sla_compliant,
        'confidence_threshold': confidence_report.metrics.overall_confidence >= 0.7,
        'no_critical_risks': confidence_report.metrics.critical_confidence_count == 0,
        'validation_success': result.validation_result.success if result.validation_result else True
    }

    passed = all(checks.values())

    return {
        'passed': passed,
        'checks': checks,
        'confidence_report': confidence_report,
        'translation_result': result,
        'action_required': 'APPROVE' if passed else 'MANUAL_REVIEW'
    }
```

## Monitoring and Alerting

### Confidence Degradation Detection

```python
class ConfidenceDegradationAlert:
    def __init__(self, alert_threshold=0.1):
        self.analyzer = get_confidence_analyzer()
        self.alert_threshold = alert_threshold

    def check_confidence_degradation(self):
        """Check for confidence degradation patterns"""
        # Compare recent trends
        recent_trend = self.analyzer.analyze_confidence_trends("1h")
        daily_trend = self.analyzer.analyze_confidence_trends("24h")

        degradation_detected = False
        alerts = []

        if recent_trend.confidence_trend == "declining":
            if abs(recent_trend.average_confidence - daily_trend.average_confidence) > self.alert_threshold:
                degradation_detected = True
                alerts.append(f"Confidence degradation detected: {recent_trend.average_confidence:.2f} vs {daily_trend.average_confidence:.2f}")

        return {
            'degradation_detected': degradation_detected,
            'alerts': alerts,
            'recent_trend': recent_trend,
            'daily_trend': daily_trend
        }
```

### Dashboard Metrics

Key metrics for monitoring dashboards:

1. **Overall Confidence Trend**: Track confidence over time
2. **Construct Type Confidence**: Monitor specific construct reliability
3. **Risk Factor Frequency**: Track common risk patterns
4. **Constitutional Compliance Rate**: Combined SLA + confidence compliance
5. **Translation Success Rate**: Percentage of high-confidence translations

## Best Practices

### 1. Confidence Thresholds

Set appropriate confidence thresholds based on use case:

- **Production Queries**: 0.8+ confidence required
- **Development/Testing**: 0.6+ confidence acceptable
- **Experimental Features**: 0.4+ with manual review

### 2. Risk Mitigation

For low-confidence translations:

1. **Manual Review**: Expert validation of translation accuracy
2. **Extensive Testing**: Comprehensive functional and performance testing
3. **Gradual Rollout**: Phased deployment with monitoring
4. **Fallback Plans**: Alternative query formulations

### 3. Continuous Improvement

Use confidence analysis for:

1. **Translation Quality**: Identify patterns in low-confidence translations
2. **Registry Enhancement**: Improve mappings for problematic constructs
3. **Training Data**: Generate examples for machine learning improvements
4. **Documentation**: Create best practices based on confidence patterns

### 4. Constitutional Alignment

Ensure confidence analysis supports constitutional requirements:

1. **Performance**: Confidence analysis must complete within SLA
2. **Reliability**: High-confidence translations meet constitutional standards
3. **Monitoring**: Integrate with constitutional compliance reporting
4. **Quality Assurance**: Use confidence as quality gate for constitutional compliance