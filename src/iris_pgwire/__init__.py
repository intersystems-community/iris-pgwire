"""
IRIS PostgreSQL Wire Protocol Server

A PostgreSQL wire protocol implementation for InterSystems IRIS using embedded Python.
Based on the specification from docs/iris_pgwire_plan.md and proven patterns from
caretdev/sqlalchemy-iris.
"""

__version__ = "0.1.0"
__author__ = "IRIS PGWire Team"

from .server import PGWireServer
from .protocol import PGWireProtocol

__all__ = ["PGWireServer", "PGWireProtocol"]