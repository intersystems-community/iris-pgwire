"""
IRIS SQL Constructs Translation Module

Provides translation capabilities for IRIS-specific SQL syntax, functions,
and data types to PostgreSQL equivalents for wire protocol compatibility.

Constitutional Requirements:
- 5ms translation SLA
- E2E testing with real PostgreSQL clients
- Production-ready monitoring and debug tracing
- IRIS Integration via embedded Python
- Protocol fidelity with PostgreSQL wire protocol v3
"""

from .translator import IRISSQLTranslator, get_translator, translate_sql, TranslationContext
from .models import (
    TranslationRequest,
    TranslationResult,
    ConstructMapping,
    PerformanceStats,
    TranslationError
)
from .validator import ValidationLevel, ValidationContext

__version__ = "1.0.0"
__all__ = [
    "IRISSQLTranslator",
    "get_translator",
    "translate_sql",
    "TranslationContext",
    "TranslationRequest",
    "TranslationResult",
    "ConstructMapping",
    "PerformanceStats",
    "TranslationError",
    "ValidationLevel",
    "ValidationContext"
]