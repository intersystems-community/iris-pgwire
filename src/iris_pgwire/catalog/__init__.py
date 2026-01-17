"""
PostgreSQL System Catalog Emulation for IRIS PGWire

This module provides emulation of PostgreSQL system catalogs (pg_class, pg_attribute,
pg_constraint, pg_index, etc.) to enable ORM introspection tools like Prisma to
discover IRIS database schema through the PostgreSQL wire protocol.

Key Components:
- OIDGenerator: Deterministic OID generation for IRIS objects
- PgNamespaceEmulator: Schema/namespace catalog
- PgClassEmulator: Table/view catalog
- PgAttributeEmulator: Column catalog
- PgConstraintEmulator: Constraint catalog
- PgIndexEmulator: Index catalog
- PgAttrdefEmulator: Default value catalog
- CatalogRouter: Query routing to appropriate emulators
"""

# Lazy imports - only import when accessed to allow incremental development
from .oid_generator import ObjectIdentity, OIDGenerator

__all__ = [
    # OID Generation
    "OIDGenerator",
    "ObjectIdentity",
    # Catalogs (available after implementation)
    "PgNamespace",
    "PgNamespaceEmulator",
    "PgClass",
    "PgClassEmulator",
    "PgAttribute",
    "PgAttributeEmulator",
    "PgConstraint",
    "PgConstraintEmulator",
    "PgIndex",
    "PgIndexEmulator",
    "PgAttrdef",
    "PgAttrdefEmulator",
    # Router
    "CatalogRouter",
    "CatalogQueryResult",
]


def __getattr__(name: str):
    """Lazy import for catalog modules."""
    if name in ("PgNamespace", "PgNamespaceEmulator"):
        from .pg_namespace import PgNamespace, PgNamespaceEmulator
        return PgNamespace if name == "PgNamespace" else PgNamespaceEmulator
    elif name in ("PgClass", "PgClassEmulator"):
        from .pg_class import PgClass, PgClassEmulator
        return PgClass if name == "PgClass" else PgClassEmulator
    elif name in ("PgAttribute", "PgAttributeEmulator"):
        from .pg_attribute import PgAttribute, PgAttributeEmulator
        return PgAttribute if name == "PgAttribute" else PgAttributeEmulator
    elif name in ("PgConstraint", "PgConstraintEmulator"):
        from .pg_constraint import PgConstraint, PgConstraintEmulator
        return PgConstraint if name == "PgConstraint" else PgConstraintEmulator
    elif name in ("PgIndex", "PgIndexEmulator"):
        from .pg_index import PgIndex, PgIndexEmulator
        return PgIndex if name == "PgIndex" else PgIndexEmulator
    elif name in ("PgAttrdef", "PgAttrdefEmulator"):
        from .pg_attrdef import PgAttrdef, PgAttrdefEmulator
        return PgAttrdef if name == "PgAttrdef" else PgAttrdefEmulator
    elif name in ("CatalogRouter", "CatalogQueryResult"):
        from .catalog_router import CatalogQueryResult, CatalogRouter
        return CatalogRouter if name == "CatalogRouter" else CatalogQueryResult
    raise AttributeError(f"module 'iris_pgwire.catalog' has no attribute {name!r}")
