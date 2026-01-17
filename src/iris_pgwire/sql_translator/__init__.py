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

from .date_translator import DATETranslator
from .identifier_normalizer import IdentifierNormalizer
from .models import (
    ConstructMapping,
    PerformanceStats,
    TranslationError,
    TranslationRequest,
    TranslationResult,
)

# Feature 021: PostgreSQL-Compatible SQL Normalization
from .normalizer import SQLTranslator, TranslationResult as NormalizationResult

# Feature 022: PostgreSQL Transaction Verb Compatibility
from .transaction_translator import TransactionTranslator

# Feature 035: PostgreSQL DDL Compatibility (ENUM, RLS, Boolean Defaults)
from .enum_registry import EnumTypeRegistry
from .statement_filter import StatementFilter, SkipReason, FilterResult
from .enum_translator import EnumTranslator
from .boolean_translator import BooleanTranslator
from .translator import IRISSQLTranslator, TranslationContext, get_translator, translate_sql
from .validator import ValidationContext, ValidationLevel

__version__ = "1.0.0"
__all__ = [
    # IRIS → PostgreSQL translation (existing)
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
    "ValidationContext",
    # PostgreSQL → IRIS normalization (Feature 021)
    "SQLTranslator",
    "IdentifierNormalizer",
    "DATETranslator",
    # PostgreSQL → IRIS transaction verb translation (Feature 022)
    "TransactionTranslator",
    # PostgreSQL DDL Compatibility (Feature 035)
    "NormalizationResult",
    "EnumTypeRegistry",
    "StatementFilter",
    "SkipReason",
    "FilterResult",
    "EnumTranslator",
    "BooleanTranslator",
]
