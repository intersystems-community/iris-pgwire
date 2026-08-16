"""Catalog tables projected as IRIS views."""

from .definitions import (
    CATALOG_SCHEMA,
    CATALOG_VIEWS,
    VIEW_BACKED_TABLES,
    CatalogView,
)
from .installer import CatalogViewInstaller, CatalogViewInstallError

__all__ = [
    "CATALOG_SCHEMA",
    "CATALOG_VIEWS",
    "VIEW_BACKED_TABLES",
    "CatalogView",
    "CatalogViewInstaller",
    "CatalogViewInstallError",
]
