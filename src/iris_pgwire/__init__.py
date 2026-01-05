"""
IRIS PostgreSQL Wire Protocol Server

A PostgreSQL wire protocol implementation for InterSystems IRIS using embedded Python.
Based on the specification from docs/iris_pgwire_plan.md and proven patterns from
caretdev/sqlalchemy-iris.
"""

__version__ = "1.0.3"
__author__ = "IRIS PGWire Team"

# Don't import server/protocol in __init__ to avoid sys.modules conflicts
# when running with python -m iris_pgwire.server
# Users can import directly: from iris_pgwire.server import PGWireServer

# Export type mapping functions for programmatic configuration
from .type_mapping import (
    configure_type_mapping,
    configure_type_mappings,
    get_type_mapping,
    get_all_type_mappings,
    reset_type_mappings,
    load_type_mappings_from_file,
    dump_type_mappings_to_json,
)

__all__ = [
    "__version__",
    "__author__",
    # Type mapping API
    "configure_type_mapping",
    "configure_type_mappings",
    "get_type_mapping",
    "get_all_type_mappings",
    "reset_type_mappings",
    "load_type_mappings_from_file",
    "dump_type_mappings_to_json",
]
