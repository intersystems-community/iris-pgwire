"""
IRIS SQL Translator Engine

Main orchestrator for translating IRIS SQL constructs to PostgreSQL equivalents.
Coordinates all translation components with constitutional compliance monitoring.

Constitutional Compliance: Sub-5ms translation with high-confidence mappings.
"""

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from .cache import generate_cache_key, get_cache
from .debug import get_tracer
from .mappings import (
    get_comprehensive_stats,
    get_construct_registry,
    get_datatype_registry,
    get_document_filter_registry,
    get_function_registry,
)
from .models import (
    ConstructMapping,
    ConstructType,
    DebugTrace,
    PerformanceStats,
    PerformanceTimer,
    TranslationResult,
)
from .parser import ParsedConstruct, get_parser
from .validator import (
    ValidationContext,
    ValidationLevel,
    ValidationResult,
    get_validator,
)

logger = structlog.get_logger()


@dataclass
class TranslationContext:
    """Context for translation operations"""

    original_sql: str
    session_id: str | None = None
    parameters: dict | None = None
    enable_caching: bool = True
    enable_validation: bool = True
    enable_debug: bool = False
    validation_level: ValidationLevel = ValidationLevel.SEMANTIC
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TranslationSession:
    """Translation session tracking"""

    session_id: str
    created_at: datetime
    queries_translated: int = 0
    total_time_ms: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    validation_passes: int = 0
    validation_failures: int = 0
    constitutional_violations: int = 0


class IRISSQLTranslator:
    """
    Main IRIS SQL translator engine

    Features:
    - Orchestrates all translation components
    - High-performance caching with LRU/TTL
    - Constitutional compliance monitoring
    - Comprehensive debug tracing
    - Semantic validation
    - Performance optimization
    """

    def __init__(
        self,
        enable_caching: bool = True,
        enable_validation: bool = True,
        enable_debug: bool = False,
        max_cache_size: int = 10000,
    ):
        """
        Initialize IRIS SQL translator

        Args:
            enable_caching: Enable translation caching
            enable_validation: Enable semantic validation
            enable_debug: Enable debug tracing
            max_cache_size: Maximum cache entries
        """
        self.enable_caching = enable_caching
        self.enable_validation = enable_validation
        self.enable_debug = enable_debug

        # Initialize components
        self.parser = get_parser()
        self.cache = get_cache() if enable_caching else None
        self.validator = get_validator() if enable_validation else None
        self.tracer = get_tracer() if enable_debug else None

        # Get registries
        self.function_registry = get_function_registry()
        self.datatype_registry = get_datatype_registry()
        self.construct_registry = get_construct_registry()
        self.document_filter_registry = get_document_filter_registry()

        # Session management
        self._sessions: dict[str, TranslationSession] = {}
        self._global_stats = {
            "total_translations": 0,
            "total_time_ms": 0.0,
            "cache_hits": 0,
            "cache_misses": 0,
        }
        self._lock = threading.Lock()

        # Constitutional monitoring
        self._sla_violations = 0
        self._total_translations = 0
        self._start_time = datetime.now(UTC)

        # Setup logging
        self.logger = logging.getLogger("iris_pgwire.sql_translator")

        # Performance optimization
        self._thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="iris_translator")

    def translate(self, context: TranslationContext) -> TranslationResult:
        """
        Translate IRIS SQL to PostgreSQL equivalent

        Args:
            context: Translation context with SQL and options

        Returns:
            Translation result with SQL and metadata
        """
        with PerformanceTimer() as timer:
            # Generate trace ID if debug enabled
            trace_id = context.trace_id or (str(uuid.uuid4()) if self.enable_debug else None)

            try:
                # Start debug trace
                debug_trace = None
                if self.enable_debug and trace_id and self.tracer:
                    debug_trace = self.tracer.start_trace(trace_id, context.original_sql)

                # Check cache first
                cache_entry = None
                cache_key = None
                if self.enable_caching and context.enable_caching and self.cache:
                    cache_key = generate_cache_key(
                        context.original_sql, context.parameters, {"session_id": context.session_id}
                    )
                    cache_entry = self.cache.get(cache_key)

                    if cache_entry:
                        # Cache hit - return cached result
                        self._update_session_stats(
                            context.session_id, timer.elapsed_ms, cache_hit=True
                        )

                        if debug_trace and trace_id and self.tracer:
                            self.tracer.add_parsing_step(
                                trace_id,
                                "cache_hit",
                                context.original_sql,
                                cache_entry.translated_sql,
                                0.1,
                                cache_key=cache_key,
                            )
                            self.tracer.complete_trace(
                                trace_id, cache_entry.translated_sql, True, timer.elapsed_ms
                            )

                        return TranslationResult(
                            translated_sql=cache_entry.translated_sql,
                            construct_mappings=cache_entry.construct_mappings,
                            performance_stats=PerformanceStats(
                                translation_time_ms=timer.elapsed_ms,
                                cache_hit=True,
                                constructs_detected=len(cache_entry.construct_mappings),
                                constructs_translated=len(cache_entry.construct_mappings),
                            ),
                            debug_trace=debug_trace,
                        )

                # Perform translation
                translation_result = self._perform_translation(context, trace_id, debug_trace)

                # Cache result if successful (no errors in warnings)
                is_successful = not any("failed" in w.lower() for w in translation_result.warnings)
                if (
                    is_successful
                    and self.enable_caching
                    and context.enable_caching
                    and self.cache
                    and cache_key
                ):
                    self.cache.put(
                        cache_key,
                        translation_result.translated_sql,
                        translation_result.construct_mappings,
                        translation_result.performance_stats,
                        original_sql=context.original_sql,
                    )

                # Update session stats
                self._update_session_stats(
                    context.session_id,
                    timer.elapsed_ms,
                    cache_hit=False,
                    validation_success=(
                        translation_result.validation_result.success
                        if translation_result.validation_result
                        else True
                    ),
                )

                # Constitutional compliance check
                if timer.elapsed_ms > 5.0:  # 5ms SLA
                    self._sla_violations += 1
                    if debug_trace and trace_id and self.tracer:
                        self.tracer.add_warning(
                            trace_id,
                            f"Translation exceeded 5ms SLA: {timer.elapsed_ms}ms",
                            "constitutional",
                        )

                return translation_result

            except Exception as e:
                logger.error(f"Translation failed: {e}")

                if debug_trace and trace_id and self.tracer:
                    if hasattr(self.tracer, "add_error"):
                        self.tracer.add_error(trace_id, str(e), "TranslationError")
                    self.tracer.complete_trace(trace_id, "", False, timer.elapsed_ms)

                return TranslationResult(
                    translated_sql=context.original_sql,  # Fallback to original
                    construct_mappings=[],
                    performance_stats=PerformanceStats(
                        translation_time_ms=timer.elapsed_ms,
                        cache_hit=False,
                        constructs_detected=0,
                        constructs_translated=0,
                    ),
                    warnings=[f"Translation failed: {str(e)}"],
                    debug_trace=debug_trace,
                )

    def _perform_translation(
        self,
        context: TranslationContext,
        trace_id: str | None,
        debug_trace: DebugTrace | None,
    ) -> TranslationResult:
        """Perform the actual translation process"""
        with PerformanceTimer() as total_timer:
            construct_mappings = []
            warnings = []

            # Strip trailing semicolons from incoming SQL before translation
            # PostgreSQL clients send queries with semicolons, but IRIS expects them without
            # We'll add them back in _finalize_translation() if needed
            original_sql = context.original_sql.rstrip(";").strip()
            translated_sql = original_sql

            # Step 1: Parse SQL to identify IRIS constructs
            with PerformanceTimer() as parse_timer:
                parsed_constructs, parse_debug = self.parser.parse(
                    original_sql,  # Use cleaned SQL without trailing semicolon
                    debug_mode=self.enable_debug,
                )

            if debug_trace and trace_id and self.tracer:
                self.tracer.add_parsing_step(
                    trace_id,
                    "parse_constructs",
                    context.original_sql,
                    context.original_sql,
                    parse_timer.elapsed_ms,
                    constructs_found=len(parsed_constructs),
                )

            # Step 2: Translate each construct type
            translated_sql = self._translate_constructs(
                translated_sql, parsed_constructs, construct_mappings, trace_id, debug_trace
            )

            # Step 3: Validate translation if enabled
            validation_result = None
            if self.enable_validation and context.enable_validation:
                validation_result = self._validate_translation(
                    context, translated_sql, construct_mappings, trace_id
                )

                if not validation_result.success:
                    warnings.extend([issue.message for issue in validation_result.issues])

            # Step 4: Final cleanup and optimization
            translated_sql = self._finalize_translation(translated_sql, trace_id, debug_trace)

            # Audit logging: Record all transformations applied
            if construct_mappings:
                logger.info(
                    "Audit: SQL transformations applied",
                    original_sql=context.original_sql[:200],
                    translated_sql=translated_sql[:200],
                    mapping_count=len(construct_mappings),
                    mappings=[
                        {
                            "type": m.construct_type.value,
                            "original": m.original_syntax,
                            "translated": m.translated_syntax,
                        }
                        for m in construct_mappings
                    ],
                    session_id=context.session_id,
                    trace_id=trace_id,
                )

            # Complete debug trace
            if debug_trace and trace_id and self.tracer:
                self.tracer.complete_trace(trace_id, translated_sql, True, total_timer.elapsed_ms)

            return TranslationResult(
                translated_sql=translated_sql,
                construct_mappings=construct_mappings,
                performance_stats=PerformanceStats(
                    translation_time_ms=total_timer.elapsed_ms,
                    cache_hit=False,
                    constructs_detected=len(parsed_constructs),
                    constructs_translated=len(construct_mappings),
                ),
                warnings=warnings,
                validation_result=validation_result,
                debug_trace=debug_trace,
            )

    def _translate_constructs(
        self,
        sql: str,
        parsed_constructs: list[ParsedConstruct],
        construct_mappings: list[ConstructMapping],
        trace_id: str | None,
        debug_trace: DebugTrace | None,
    ) -> str:
        """Translate all identified IRIS constructs"""

        # Organize constructs by type for efficient processing
        constructs_by_type = {
            ConstructType.FUNCTION: [],
            ConstructType.SYSTEM_FUNCTION: [],
            ConstructType.DATA_TYPE: [],
            ConstructType.SYNTAX: [],
            ConstructType.JSON_FUNCTION: [],
            ConstructType.DOCUMENT_FILTER: [],
        }

        for construct in parsed_constructs:
            if construct.construct_type in constructs_by_type:
                constructs_by_type[construct.construct_type].append(construct)

        # Translate functions (including system functions)
        function_constructs = (
            constructs_by_type[ConstructType.FUNCTION]
            + constructs_by_type[ConstructType.SYSTEM_FUNCTION]
            + constructs_by_type[ConstructType.JSON_FUNCTION]
        )
        if function_constructs:
            sql = self._translate_functions(sql, function_constructs, construct_mappings, trace_id)

        # Translate data types
        if constructs_by_type[ConstructType.DATA_TYPE]:
            sql = self._translate_datatypes(
                sql, constructs_by_type[ConstructType.DATA_TYPE], construct_mappings, trace_id
            )

        # Translate SQL constructs
        if constructs_by_type[ConstructType.SYNTAX]:
            sql = self._translate_sql_constructs(
                sql, constructs_by_type[ConstructType.SYNTAX], construct_mappings, trace_id
            )

        # Translate document filters
        if constructs_by_type[ConstructType.DOCUMENT_FILTER]:
            sql = self._translate_document_filters(
                sql, constructs_by_type[ConstructType.DOCUMENT_FILTER], construct_mappings, trace_id
            )

        return sql

    def _translate_functions(
        self,
        sql: str,
        function_constructs: list[ParsedConstruct],
        construct_mappings: list[ConstructMapping],
        trace_id: str | None,
    ) -> str:
        """Translate IRIS functions to PostgreSQL equivalents"""
        with PerformanceTimer() as timer:
            for construct in function_constructs:
                # Get function name from metadata (parser stores it there)
                function_name = construct.metadata.get("function_name", construct.original_text)
                mapping = self.function_registry.get_mapping(function_name)

                if mapping:
                    # Perform the function translation
                    old_pattern = construct.original_text
                    new_text = mapping.postgresql_function

                    # Handle parameterized functions
                    if construct.parameters:
                        # Check if function template has placeholders ($1, $2, etc.)
                        if "$" in new_text:
                            new_text = self._apply_function_parameters(
                                new_text, construct.parameters
                            )
                        else:
                            # For simple functions without placeholders, append parameters directly
                            params_str = ", ".join(construct.parameters)
                            new_text = f"{new_text}({params_str})"
                    else:
                        # For functions without parameters, extract from original_text
                        import re

                        param_match = re.search(r"\(([^)]*)\)", construct.original_text)
                        if param_match:
                            params = param_match.group(1)
                            new_text = f"{new_text}({params})"

                    sql = sql.replace(old_pattern, new_text)

                    # Record mapping
                    construct_mapping = ConstructMapping(
                        construct_type=ConstructType.FUNCTION,
                        original_syntax=construct.original_text,
                        translated_syntax=new_text,
                        confidence=mapping.confidence,
                        source_location=construct.location,
                        metadata={"function_name": function_name},
                    )
                    construct_mappings.append(construct_mapping)

                    # Debug trace
                    if trace_id and self.tracer:
                        self.tracer.add_mapping_decision(
                            trace_id,
                            construct.original_text,
                            [new_text],
                            new_text,
                            mapping.confidence,
                            f"Function mapping: {mapping.notes}",
                        )

            if trace_id and self.tracer:
                self.tracer.add_parsing_step(
                    trace_id,
                    "translate_functions",
                    sql,
                    sql,
                    timer.elapsed_ms,
                    functions_translated=len(function_constructs),
                )

        return sql

    def _translate_datatypes(
        self,
        sql: str,
        datatype_constructs: list[ParsedConstruct],
        construct_mappings: list[ConstructMapping],
        trace_id: str | None,
    ) -> str:
        """Translate IRIS data types to PostgreSQL equivalents"""
        with PerformanceTimer() as timer:
            for construct in datatype_constructs:
                mapping = self.datatype_registry.get_mapping(construct.original_text)

                if mapping:
                    old_pattern = construct.original_text
                    new_text = mapping.postgresql_type

                    sql = sql.replace(old_pattern, new_text)

                    # Record mapping
                    construct_mapping = ConstructMapping(
                        construct_type=ConstructType.DATA_TYPE,
                        original_syntax=construct.original_text,
                        translated_syntax=new_text,
                        confidence=mapping.confidence,
                        source_location=construct.location,
                        metadata={"type_name": construct.original_text},
                    )
                    construct_mappings.append(construct_mapping)

            if trace_id and self.tracer:
                self.tracer.add_parsing_step(
                    trace_id,
                    "translate_datatypes",
                    sql,
                    sql,
                    timer.elapsed_ms,
                    datatypes_translated=len(datatype_constructs),
                )

        return sql

    def _translate_sql_constructs(
        self,
        sql: str,
        sql_constructs: list[ParsedConstruct],
        construct_mappings: list[ConstructMapping],
        trace_id: str | None,
    ) -> str:
        """Translate IRIS SQL constructs to PostgreSQL equivalents"""
        with PerformanceTimer() as timer:
            translated_sql, mappings = self.construct_registry.translate_constructs(sql)
            construct_mappings.extend(mappings)

            if trace_id and self.tracer:
                self.tracer.add_parsing_step(
                    trace_id,
                    "translate_sql_constructs",
                    sql,
                    translated_sql,
                    timer.elapsed_ms,
                    constructs_translated=len(mappings),
                )

        return translated_sql

    def _translate_document_filters(
        self,
        sql: str,
        document_constructs: list[ParsedConstruct],
        construct_mappings: list[ConstructMapping],
        trace_id: str | None,
    ) -> str:
        """Translate IRIS document filter operations to PostgreSQL jsonb"""
        with PerformanceTimer() as timer:
            translated_sql, mappings = self.document_filter_registry.translate_document_filters(sql)
            construct_mappings.extend(mappings)

            if trace_id and self.tracer:
                self.tracer.add_parsing_step(
                    trace_id,
                    "translate_document_filters",
                    sql,
                    translated_sql,
                    timer.elapsed_ms,
                    document_filters_translated=len(mappings),
                )

        return translated_sql

    def _apply_function_parameters(self, function_template: str, parameters: list[str]) -> str:
        """Apply parameters to function template"""
        # Simple parameter substitution - could be enhanced
        result = function_template
        for i, param in enumerate(parameters):
            placeholder = f"${i + 1}"
            if placeholder in result:
                result = result.replace(placeholder, param)
        return result

    def _validate_translation(
        self,
        context: TranslationContext,
        translated_sql: str,
        construct_mappings: list[ConstructMapping],
        trace_id: str | None,
    ) -> ValidationResult:
        """Validate translation accuracy"""
        validation_context = ValidationContext(
            original_sql=context.original_sql,
            translated_sql=translated_sql,
            construct_mappings=construct_mappings,
            validation_level=context.validation_level,
            trace_id=trace_id,
        )

        if self.validator:
            return self.validator.validate_query_equivalence(validation_context)
        else:
            return ValidationResult(success=True, confidence=1.0)

    def _finalize_translation(
        self, sql: str, trace_id: str | None, debug_trace: DebugTrace | None
    ) -> str:
        """Final cleanup and optimization of translated SQL"""
        with PerformanceTimer() as timer:
            # Remove extra whitespace
            sql = " ".join(sql.split())

            # Ensure proper semicolon termination for non-empty SQL
            if sql.strip() and not sql.endswith(";"):
                sql += ";"

            if trace_id and self.tracer:
                self.tracer.add_parsing_step(
                    trace_id,
                    "finalize_translation",
                    sql,
                    sql,
                    timer.elapsed_ms,
                    optimization="whitespace_cleanup",
                )

        return sql

    def _update_session_stats(
        self,
        session_id: str | None,
        elapsed_ms: float,
        cache_hit: bool = False,
        validation_success: bool = True,
    ):
        """Update translation session statistics"""
        with self._lock:
            self._total_translations += 1
            self._global_stats["total_translations"] += 1
            self._global_stats["total_time_ms"] += elapsed_ms

            if session_id:
                if session_id not in self._sessions:
                    self._sessions[session_id] = TranslationSession(
                        session_id=session_id, created_at=datetime.now(UTC)
                    )

                session = self._sessions[session_id]
                session.queries_translated += 1
                session.total_time_ms += elapsed_ms

                if cache_hit:
                    session.cache_hits += 1
                    self._global_stats["cache_hits"] += 1
                else:
                    session.cache_misses += 1
                    self._global_stats["cache_misses"] += 1

                if validation_success:
                    session.validation_passes += 1
                else:
                    session.validation_failures += 1

    def get_translation_stats(self) -> dict[str, Any]:
        """Get comprehensive translation statistics"""
        with self._lock:
            uptime_seconds = (datetime.now(UTC) - self._start_time).total_seconds()

            # Calculate rates
            translations_per_second = (
                self._total_translations / uptime_seconds if uptime_seconds > 0 else 0.0
            )

            avg_translation_time = (
                self._global_stats["total_time_ms"] / self._total_translations
                if self._total_translations > 0
                else 0.0
            )

            cache_hit_rate = self._global_stats["cache_hits"] / max(
                self._global_stats["cache_hits"] + self._global_stats["cache_misses"], 1
            )

            return {
                "total_translations": self._total_translations,
                "uptime_seconds": uptime_seconds,
                "translations_per_second": translations_per_second,
                "average_translation_time_ms": avg_translation_time,
                "cache_hit_rate": cache_hit_rate,
                "sla_violations": self._sla_violations,
                "sla_compliance_rate": max(
                    0.0, 1.0 - (self._sla_violations / max(self._total_translations, 1))
                ),
                "active_sessions": len(self._sessions),
                "constitutional_compliance": {
                    "sla_requirement_ms": 5.0,
                    "violations": self._sla_violations,
                    "compliance_rate": max(
                        0.0, 1.0 - (self._sla_violations / max(self._total_translations, 1))
                    ),
                },
                "component_stats": {
                    "cache": self.cache.get_cache_info() if self.cache else None,
                    "validator": self.validator.get_validation_stats() if self.validator else None,
                    "tracer": self.tracer.get_session_stats() if self.tracer else None,
                    "mappings": get_comprehensive_stats(),
                },
            }

    def get_session_stats(self, session_id: str) -> dict[str, Any] | None:
        """Get statistics for a specific session"""
        with self._lock:
            if session_id not in self._sessions:
                return None

            session = self._sessions[session_id]
            avg_time = (
                session.total_time_ms / session.queries_translated
                if session.queries_translated > 0
                else 0.0
            )

            return {
                "session_id": session_id,
                "created_at": session.created_at.isoformat(),
                "queries_translated": session.queries_translated,
                "total_time_ms": session.total_time_ms,
                "average_time_ms": avg_time,
                "cache_hits": session.cache_hits,
                "cache_misses": session.cache_misses,
                "cache_hit_rate": session.cache_hits
                / max(session.cache_hits + session.cache_misses, 1),
                "validation_passes": session.validation_passes,
                "validation_failures": session.validation_failures,
                "constitutional_violations": session.constitutional_violations,
            }

    def clear_session(self, session_id: str) -> bool:
        """Clear a translation session"""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def invalidate_cache(self, pattern: str | None = None) -> int:
        """Invalidate translation cache"""
        if self.cache:
            result = self.cache.invalidate(pattern)
            return result.invalidated_count
        return 0

    def shutdown(self):
        """Shutdown translator and cleanup resources"""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)

    @contextmanager
    def translation_session(self, session_id: str | None = None):
        """Context manager for translation sessions"""
        if session_id is None:
            session_id = str(uuid.uuid4())

        try:
            yield session_id
        finally:
            # Optional: cleanup session after use
            pass


# Global translator instance
_translator = IRISSQLTranslator()


def get_translator() -> IRISSQLTranslator:
    """Get the global translator instance"""
    return _translator


def translate_sql(
    sql: str,
    session_id: str | None = None,
    enable_caching: bool = True,
    enable_validation: bool = True,
    enable_debug: bool = False,
) -> TranslationResult:
    """Translate IRIS SQL to PostgreSQL (convenience function)"""
    context = TranslationContext(
        original_sql=sql,
        session_id=session_id,
        enable_caching=enable_caching,
        enable_validation=enable_validation,
        enable_debug=enable_debug,
    )
    return _translator.translate(context)


# Export main components
__all__ = [
    "IRISSQLTranslator",
    "TranslationContext",
    "TranslationSession",
    "get_translator",
    "translate_sql",
]
