"""
IRIS PostgreSQL Wire Protocol Server

A PostgreSQL wire protocol implementation for InterSystems IRIS using embedded Python.
Based on the specification from docs/iris_pgwire_plan.md and proven patterns from
caretdev/sqlalchemy-iris.
"""

__version__ = "0.1.0"
__author__ = "IRIS PGWire Team"

# Don't import server/protocol in __init__ to avoid sys.modules conflicts
# when running with python -m iris_pgwire.server
# Users can import directly: from iris_pgwire.server import PGWireServer

__all__ = ["__version__", "__author__"]
