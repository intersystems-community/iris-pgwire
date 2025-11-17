"""
IRIS SQL Translation Mappings

This module provides comprehensive mappings between IRIS SQL constructs and
PostgreSQL equivalents, organized by category for efficient lookup and translation.

Constitutional Compliance: High-confidence mappings ensuring accurate translation.
"""

from .constructs import (
    IRISSQLConstructRegistry,
    get_construct_registry,
    has_sql_construct,
    translate_sql_constructs,
)
from .datatypes import (
    IRISDataTypeRegistry,
    get_datatype_registry,
    get_type_mapping,
    has_type_mapping,
    translate_type_specification,
)
from .document_filters import (
    IRISDocumentFilterRegistry,
    get_document_filter_registry,
    has_document_filter,
    translate_document_filters,
)
from .functions import (
    IRISFunctionRegistry,
    get_function_mapping,
    get_function_registry,
    has_function_mapping,
)


# Convenience functions for unified access
def get_all_registries():
    """Get all mapping registries"""
    return {
        "functions": get_function_registry(),
        "datatypes": get_datatype_registry(),
        "constructs": get_construct_registry(),
        "document_filters": get_document_filter_registry(),
    }


def get_comprehensive_stats():
    """Get comprehensive statistics across all mappings"""
    registries = get_all_registries()

    total_mappings = 0
    stats = {}

    for category, registry in registries.items():
        registry_stats = registry.get_mapping_stats()
        stats[category] = registry_stats

        if "total_mappings" in registry_stats:
            total_mappings += registry_stats["total_mappings"]
        elif "total_constructs" in registry_stats:
            total_mappings += registry_stats["total_constructs"]
        elif "total_filters" in registry_stats:
            total_mappings += registry_stats["total_filters"]

    stats["summary"] = {
        "total_mappings_across_all_categories": total_mappings,
        "categories": list(registries.keys()),
    }

    return stats


# Export all registry classes and convenience functions
__all__ = [
    # Function mappings
    "IRISFunctionRegistry",
    "get_function_registry",
    "get_function_mapping",
    "has_function_mapping",
    # Data type mappings
    "IRISDataTypeRegistry",
    "get_datatype_registry",
    "get_type_mapping",
    "has_type_mapping",
    "translate_type_specification",
    # SQL construct mappings
    "IRISSQLConstructRegistry",
    "get_construct_registry",
    "translate_sql_constructs",
    "has_sql_construct",
    # Document filter mappings
    "IRISDocumentFilterRegistry",
    "get_document_filter_registry",
    "translate_document_filters",
    "has_document_filter",
    # Unified access
    "get_all_registries",
    "get_comprehensive_stats",
]
