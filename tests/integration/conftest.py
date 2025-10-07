"""
Integration test configuration for Feature 018 (DBAPI backend).

This conftest provides fixtures for DBAPI integration tests that run in Docker.
Environment variables are set by docker-compose.yml (pytest-integration service).

Constitutional Principle II: All integration tests MUST run against real IRIS instances.
"""

import os

import pytest

from iris_pgwire.models.backend_config import BackendConfig, BackendType


@pytest.fixture
def iris_connection_params():
    """
    IRIS connection parameters from environment variables.

    Docker compose sets:
    - IRIS_HOSTNAME=iris
    - IRIS_PORT=1972
    - IRIS_NAMESPACE=USER
    - IRIS_USERNAME=_SYSTEM
    - IRIS_PASSWORD=SYS
    """
    return {
        "hostname": os.getenv("IRIS_HOSTNAME", "localhost"),
        "port": int(os.getenv("IRIS_PORT", "1972")),
        "namespace": os.getenv("IRIS_NAMESPACE", "USER"),
        "username": os.getenv("IRIS_USERNAME", "_SYSTEM"),
        "password": os.getenv("IRIS_PASSWORD", "SYS"),
    }


@pytest.fixture
def dbapi_config(iris_connection_params):
    """
    BackendConfig for DBAPI testing with connection pooling.

    Uses environment variables for IRIS connection details.
    Default pool settings: 50 base + 20 overflow = 70 total.
    """
    return BackendConfig(
        backend_type=BackendType.DBAPI,
        iris_hostname=iris_connection_params["hostname"],
        iris_port=iris_connection_params["port"],
        iris_namespace=iris_connection_params["namespace"],
        iris_username=iris_connection_params["username"],
        iris_password=iris_connection_params["password"],
        pool_size=50,
        pool_max_overflow=20,
        pool_timeout=30,
        pool_recycle=3600,
    )


@pytest.fixture
def pool_config(dbapi_config):
    """
    Alias for dbapi_config for connection pooling tests.

    Provides backward compatibility with existing test names.
    """
    return dbapi_config
