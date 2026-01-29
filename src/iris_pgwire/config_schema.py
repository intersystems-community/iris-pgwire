"""
Proxy for BackendConfig to maintain backward compatibility.
All configuration schema logic has moved to iris_pgwire.models.backend_config.
"""

from iris_pgwire.models.backend_config import BackendConfig, BackendType

__all__ = ["BackendConfig", "BackendType"]
