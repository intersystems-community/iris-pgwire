"""
SQL Translation Data Models

Core data structures for IRIS SQL construct translation, matching the OpenAPI
contract specifications and supporting constitutional performance requirements.

Constitutional Compliance: All models enforce 5ms SLA and provide debug tracing.
"""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ConstructType(Enum):
    """Types of IRIS constructs that can be translated"""

    FUNCTION = "FUNCTION"
    SYSTEM_FUNCTION = "SYSTEM_FUNCTION"
    DATA_TYPE = "DATA_TYPE"
    SYNTAX = "SYNTAX"
    JSON_FUNCTION = "JSON_FUNCTION"
    DOCUMENT_FILTER = "DOCUMENT_FILTER"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    UNKNOWN = "UNKNOWN"


class ErrorCode(Enum):
    """Error codes for translation failures"""

    PARSE_ERROR = "PARSE_ERROR"
    UNSUPPORTED_CONSTRUCT = "UNSUPPORTED_CONSTRUCT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    MAPPING_ERROR = "MAPPING_ERROR"
    IRIS_ERROR = "IRIS_ERROR"


class FallbackStrategy(Enum):
    """Strategies for handling unsupported constructs"""

    ERROR = "ERROR"  # Fail immediately
    WARNING = "WARNING"  # Log warning, attempt execution
    IGNORE = "IGNORE"  # Silently skip unsupported parts
    PRESERVE = "PRESERVE"  # Keep original syntax
    HYBRID = "HYBRID"  # Intelligent fallback based on context


@dataclass
class SourceLocation:
    """Location information for SQL construct in original query"""

    line: int
    column: int
    length: int
    original_text: str = ""

    def __post_init__(self):
        """Validate source location"""
        if self.line < 1:
            raise ValueError("Line number must be >= 1")
        if self.column < 1:
            raise ValueError("Column number must be >= 1")
        if self.length < 0:
            raise ValueError("Length must be >= 0")


@dataclass
class ConstructMapping:
    """Mapping information for a translated IRIS construct"""

    construct_type: ConstructType
    original_syntax: str
    translated_syntax: str
    confidence: float
    source_location: SourceLocation
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate construct mapping"""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        if not self.original_syntax.strip():
            raise ValueError("Original syntax cannot be empty")
        if not self.translated_syntax.strip():
            raise ValueError("Translated syntax cannot be empty")


@dataclass
class PerformanceStats:
    """Performance statistics for translation operations"""

    translation_time_ms: float
    cache_hit: bool
    constructs_detected: int
    constructs_translated: int
    parsing_time_ms: float = 0.0
    mapping_time_ms: float = 0.0
    validation_time_ms: float = 0.0

    def __post_init__(self):
        """Validate performance stats and check constitutional SLA compliance"""
        if self.translation_time_ms < 0:
            raise ValueError("Translation time cannot be negative")
        if self.constructs_detected < 0:
            raise ValueError("Constructs detected cannot be negative")
        if self.constructs_translated < 0:
            raise ValueError("Constructs translated cannot be negative")
        if self.constructs_translated > self.constructs_detected:
            raise ValueError("Cannot translate more constructs than detected")

        # Constitutional requirement: 5ms SLA compliance check
        if self.translation_time_ms > 5.0:
            # Log SLA violation for constitutional monitoring
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                f"Constitutional SLA violation: Translation took {self.translation_time_ms}ms, "
                f"exceeds 5ms requirement"
            )

    @property
    def is_sla_compliant(self) -> bool:
        """Check if translation meets constitutional 5ms SLA requirement"""
        return self.translation_time_ms <= 5.0

    @property
    def translation_success_rate(self) -> float:
        """Calculate translation success rate"""
        if self.constructs_detected == 0:
            return 1.0
        return self.constructs_translated / self.constructs_detected


@dataclass
class CacheEntry:
    """Cache entry for translated SQL queries"""

    original_sql: str
    translated_sql: str
    construct_mappings: list[ConstructMapping]
    performance_stats: PerformanceStats
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(UTC))
    access_count: int = 1
    ttl_seconds: int = 3600  # 1 hour default TTL

    def __post_init__(self):
        """Validate cache entry"""
        if not self.original_sql.strip():
            raise ValueError("Original SQL cannot be empty")
        if not self.translated_sql.strip():
            raise ValueError("Translated SQL cannot be empty")
        if self.ttl_seconds <= 0:
            raise ValueError("TTL must be positive")

    @property
    def is_expired(self) -> bool:
        """Check if cache entry has expired"""
        age_seconds = (datetime.now(UTC) - self.created_at).total_seconds()
        return age_seconds > self.ttl_seconds

    def update_access(self):
        """Update access tracking"""
        self.last_accessed = datetime.now(UTC)
        self.access_count += 1

    @property
    def age_minutes(self) -> float:
        """Get age of entry in minutes"""
        return (datetime.now(UTC) - self.created_at).total_seconds() / 60


@dataclass
class ParsingStep:
    """Individual step in SQL parsing process"""

    step_name: str
    input_sql: str
    output_sql: str
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate parsing step"""
        if self.duration_ms < 0:
            raise ValueError("Duration cannot be negative")


@dataclass
class MappingDecision:
    """Decision made during construct mapping"""

    construct: str
    available_mappings: list[str]
    chosen_mapping: str
    confidence: float
    reasoning: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate mapping decision"""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        if self.chosen_mapping not in self.available_mappings:
            raise ValueError("Chosen mapping must be in available mappings")


@dataclass
class DebugTrace:
    """Debug trace information for translation process"""

    parsing_steps: list[ParsingStep] = field(default_factory=list)
    mapping_decisions: list[MappingDecision] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_parsing_step(
        self, step_name: str, input_sql: str, output_sql: str, duration_ms: float, **metadata
    ):
        """Add a parsing step to the trace"""
        step = ParsingStep(
            step_name=step_name,
            input_sql=input_sql,
            output_sql=output_sql,
            duration_ms=duration_ms,
            metadata=metadata,
        )
        self.parsing_steps.append(step)

    def add_mapping_decision(
        self,
        construct: str,
        available_mappings: list[str],
        chosen_mapping: str,
        confidence: float,
        reasoning: str,
        **metadata,
    ):
        """Add a mapping decision to the trace"""
        decision = MappingDecision(
            construct=construct,
            available_mappings=available_mappings,
            chosen_mapping=chosen_mapping,
            confidence=confidence,
            reasoning=reasoning,
            metadata=metadata,
        )
        self.mapping_decisions.append(decision)

    def add_warning(self, message: str):
        """Add a warning to the trace"""
        self.warnings.append(message)

    @property
    def total_parsing_time_ms(self) -> float:
        """Calculate total parsing time"""
        return sum(step.duration_ms for step in self.parsing_steps)


@dataclass
class TranslationRequest:
    """Request for SQL translation"""

    original_sql: str
    parameters: dict[str, Any] | None = None
    session_context: dict[str, Any] | None = None
    debug_mode: bool = False
    cache_enabled: bool = True
    fallback_strategy: FallbackStrategy = FallbackStrategy.HYBRID
    timeout_ms: int = 5000  # 5 second timeout

    def __post_init__(self):
        """Validate translation request"""
        if not self.original_sql.strip():
            raise ValueError("original_sql must be non-empty")
        if self.timeout_ms <= 0:
            raise ValueError("Timeout must be positive")
        if self.timeout_ms > 30000:  # 30 second max
            raise ValueError("Timeout cannot exceed 30 seconds")

    def get_cache_key(self) -> str:
        """Generate cache key for this request"""
        import hashlib

        content = f"{self.original_sql}:{self.parameters}:{self.session_context}"
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class ValidationIssue:
    """Validation issue found during translation validation"""

    severity: str
    message: str
    location: SourceLocation | None = None
    recommendation: str | None = None


@dataclass
class IssueSeverity:
    """Severity levels for validation issues"""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationResult:
    """Result of SQL translation validation"""

    success: bool
    confidence: float
    issues: list[ValidationIssue] = field(default_factory=list)
    performance_impact: str | None = None
    recommendations: list[str] = field(default_factory=list)


@dataclass
class QueryEquivalenceReport:
    """Report on query equivalence between original and translated SQL"""

    equivalent: bool
    confidence: float
    differences: list[str] = field(default_factory=list)
    analysis: str | None = None


@dataclass
class TranslationResult:
    """Result of SQL translation"""

    translated_sql: str
    construct_mappings: list[ConstructMapping]
    performance_stats: PerformanceStats
    was_skipped: bool = False
    skip_reason: Any | None = None
    command_tag: str = ""
    warnings: list[str] = field(default_factory=list)
    debug_trace: DebugTrace | None = None
    validation_result: ValidationResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate translation result"""
        # Allow empty SQL for error cases or empty input
        pass

    def add_warning(self, message: str):
        """Add a warning to the result"""
        self.warnings.append(message)

    @property
    def has_warnings(self) -> bool:
        """Check if result has warnings"""
        return len(self.warnings) > 0

    @property
    def is_successful(self) -> bool:
        """Check if translation was successful"""
        return (
            self.performance_stats.constructs_translated
            == self.performance_stats.constructs_detected
        )

    @property
    def constitutional_compliance(self) -> dict[str, Any]:
        """Get constitutional compliance status"""
        return {
            "sla_compliant": self.performance_stats.is_sla_compliant,
            "translation_time_ms": self.performance_stats.translation_time_ms,
            "success_rate": self.performance_stats.translation_success_rate,
            "has_warnings": self.has_warnings,
            "constructs_processed": self.performance_stats.constructs_detected,
        }


@dataclass
class FunctionMapping:
    """Mapping definition for IRIS function translation"""

    iris_function: str
    postgresql_function: str
    parameter_mapping: dict[str, str] | None = None
    confidence: float = 1.0
    notes: str = ""
    examples: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self):
        """Validate function mapping"""
        if not self.iris_function.strip():
            raise ValueError("IRIS function name cannot be empty")
        if not self.postgresql_function.strip():
            raise ValueError("PostgreSQL function name cannot be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")

    def add_example(self, iris_example: str, postgresql_example: str, description: str = ""):
        """Add usage example"""
        self.examples.append(
            {"iris": iris_example, "postgresql": postgresql_example, "description": description}
        )


@dataclass
class TypeMapping:
    """Mapping definition for IRIS data type translation"""

    iris_type: str
    postgresql_type: str
    conversion_function: str | None = None
    size_mapping: dict[str, str] | None = None
    confidence: float = 1.0
    notes: str = ""

    def __post_init__(self):
        """Validate type mapping"""
        if not self.iris_type.strip():
            raise ValueError("IRIS type name cannot be empty")
        if not self.postgresql_type.strip():
            raise ValueError("PostgreSQL type name cannot be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")


class TranslationError(Exception):
    """Exception raised during SQL translation"""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        original_sql: str | None = None,
        construct_type: ConstructType | None = None,
        source_location: SourceLocation | None = None,
        fallback_strategy: FallbackStrategy | None = None,
    ):
        self.error_code = error_code
        self.message = message
        self.original_sql = original_sql
        self.construct_type = construct_type
        self.source_location = source_location
        self.fallback_strategy = fallback_strategy
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for API responses"""
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "original_sql": self.original_sql,
            "construct_type": self.construct_type.value if self.construct_type else None,
            "source_location": (
                {
                    "line": self.source_location.line,
                    "column": self.source_location.column,
                    "length": self.source_location.length,
                    "original_text": self.source_location.original_text,
                }
                if self.source_location
                else None
            ),
            "fallback_strategy": self.fallback_strategy.value if self.fallback_strategy else None,
        }


class UnsupportedConstructError(TranslationError):
    """Exception for unsupported IRIS constructs"""

    def __init__(
        self,
        construct: str,
        construct_type: ConstructType,
        fallback_strategy: FallbackStrategy = FallbackStrategy.ERROR,
        source_location: SourceLocation | None = None,
    ):
        message = f"Unsupported {construct_type.value} construct: {construct}"
        super().__init__(
            error_code=ErrorCode.UNSUPPORTED_CONSTRUCT,
            message=message,
            construct_type=construct_type,
            source_location=source_location,
            fallback_strategy=fallback_strategy,
        )
        self.construct = construct


@dataclass
class CacheStats:
    """Statistics for translation cache"""

    total_entries: int
    hit_rate: float
    average_lookup_ms: float
    memory_usage_mb: float
    oldest_entry_age_minutes: int

    def __post_init__(self):
        """Validate cache stats"""
        if self.total_entries < 0:
            raise ValueError("Total entries cannot be negative")
        if not 0.0 <= self.hit_rate <= 1.0:
            raise ValueError("Hit rate must be between 0.0 and 1.0")
        if self.average_lookup_ms < 0:
            raise ValueError("Average lookup time cannot be negative")
        if self.memory_usage_mb < 0:
            raise ValueError("Memory usage cannot be negative")
        if self.oldest_entry_age_minutes < 0:
            raise ValueError("Oldest entry age cannot be negative")


@dataclass
class InvalidationResult:
    """Result of cache invalidation operation"""

    invalidated_count: int

    def __post_init__(self):
        """Validate invalidation result"""
        if self.invalidated_count < 0:
            raise ValueError("Invalidated count cannot be negative")


# Performance monitoring utilities
class PerformanceTimer:
    """Context manager for measuring operation performance"""

    def __init__(self):
        self.start_time = 0.0
        self.end_time = 0.0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds"""
        end_time = self.end_time if self.end_time > 0 else time.perf_counter()
        return (end_time - self.start_time) * 1000


# Model validation utilities
def validate_sql_syntax(sql: str) -> bool:
    """Basic SQL syntax validation"""
    if not sql.strip():
        return False

    # Basic checks for SQL injection patterns
    dangerous_patterns = [";--", "/*", "*/", "xp_", "sp_", "exec", "execute"]

    lower_sql = sql.lower()
    for pattern in dangerous_patterns:
        if pattern in lower_sql:
            return False

    return True


def create_performance_stats(
    timer: PerformanceTimer, cache_hit: bool, detected: int, translated: int
) -> PerformanceStats:
    """Create performance stats from timer and counts"""
    return PerformanceStats(
        translation_time_ms=timer.elapsed_ms,
        cache_hit=cache_hit,
        constructs_detected=detected,
        constructs_translated=translated,
    )


# Export all models for easy importing
__all__ = [
    "ConstructType",
    "ErrorCode",
    "FallbackStrategy",
    "SourceLocation",
    "ConstructMapping",
    "PerformanceStats",
    "CacheEntry",
    "ParsingStep",
    "MappingDecision",
    "DebugTrace",
    "TranslationRequest",
    "TranslationResult",
    "FunctionMapping",
    "TypeMapping",
    "TranslationError",
    "UnsupportedConstructError",
    "CacheStats",
    "InvalidationResult",
    "PerformanceTimer",
    "validate_sql_syntax",
    "create_performance_stats",
]
