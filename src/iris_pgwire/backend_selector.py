"""
Backend selector for DBAPI vs Embedded execution.

Selects appropriate executor based on BackendConfig and validates
configuration requirements before instantiation.

Constitutional Requirements:
- Principle IV (IRIS Integration): Support both DBAPI and embedded backends
- Principle V (Production Readiness): Validate configuration before execution

Feature: 018-add-dbapi-option
Contract: contracts/backend-selector-contract.md
"""

import logging
from typing import Any, Protocol

from iris_pgwire.models.backend_config import BackendConfig, BackendType

logger = logging.getLogger(__name__)


class Executor(Protocol):
    """Executor protocol for type hints."""

    backend_type: str

    async def execute_query(self, sql: str, params: Any = None) -> Any:
        """Execute SQL query."""
        ...

    async def execute_many(self, sql: str, params_list: Any) -> Any:
        """Execute SQL with multiple parameter sets."""
        ...

    async def close(self) -> None:
        """Close executor resources."""
        ...


class BackendSelector:
    """
    Selects appropriate query executor based on configuration.

    Supports two backend types:
    - DBAPI: External connection via intersystems-irispython (for large-scale deployments)
    - Embedded: Direct iris.sql.exec() within IRIS process (for embedded deployments)

    Usage:
        config = BackendConfig.from_env()
        selector = BackendSelector()
        executor = selector.select_backend(config)
        results = await executor.execute_query("SELECT 1")
    """

    def __init__(self):
        """Initialize backend selector."""
        self._executors = {}
        logger.info("BackendSelector initialized")

    def select_backend(self, config: BackendConfig) -> Executor:
        """
        Select and instantiate appropriate executor based on configuration.

        Args:
            config: Validated backend configuration

        Returns:
            Executor instance (DBAPIExecutor or EmbeddedExecutor)

        Raises:
            ValueError: If configuration validation fails
            ImportError: If required executor module not available
        """
        # Validate configuration first
        if not self.validate_config(config):
            raise ValueError("Backend configuration validation failed")

        backend_type = config.backend_type

        logger.info(
            "Selecting backend executor",
            extra={
                "backend_type": backend_type.value,
                "requires_pool": config.requires_pool(),
                "pool_config": (
                    {
                        "size": config.pool_size,
                        "overflow": config.pool_max_overflow,
                        "total": config.total_connections(),
                    }
                    if config.requires_pool()
                    else None
                ),
            },
        )

        if backend_type == BackendType.DBAPI:
            return self._create_dbapi_executor(config)
        elif backend_type == BackendType.EMBEDDED:
            return self._create_embedded_executor(config)
        else:
            raise ValueError(f"Unsupported backend type: {backend_type}")

    def validate_config(self, config: BackendConfig) -> bool:
        """
        Validate backend configuration.

        Validation rules:
        - DBAPI backend requires iris_password
        - pool_size + pool_max_overflow <= 200 (IRIS connection limit)
        - Connection parameters must be valid

        Args:
            config: Backend configuration to validate

        Returns:
            True if configuration is valid

        Raises:
            ValueError: If validation fails with specific error message
        """
        # Pydantic already validates most constraints via model_validator
        # This method performs additional runtime validation

        backend_type = config.backend_type

        # DBAPI backend requires credentials
        if backend_type == BackendType.DBAPI:
            if not config.iris_password:
                raise ValueError(
                    "DBAPI backend requires iris_password to be set. "
                    "Provide via IRIS_PASSWORD environment variable or config file."
                )

            # Validate connection pool limits
            total_connections = config.pool_size + config.pool_max_overflow
            if total_connections > 200:
                raise ValueError(
                    f"Connection pool ({config.pool_size} + {config.pool_max_overflow} = {total_connections}) "
                    f"exceeds IRIS maximum (200). Reduce pool_size or pool_max_overflow."
                )

            logger.info(
                "DBAPI configuration validated",
                extra={
                    "hostname": config.iris_hostname,
                    "port": config.iris_port,
                    "namespace": config.iris_namespace,
                    "pool_size": config.pool_size,
                    "pool_overflow": config.pool_max_overflow,
                },
            )

        # Embedded backend validation
        else:
            logger.info("Embedded backend configuration validated (no pool required)")

        return True

    def _create_dbapi_executor(self, config: BackendConfig) -> Executor:
        """
        Create DBAPI executor with connection pooling.

        Args:
            config: Backend configuration

        Returns:
            DBAPIExecutor instance

        Raises:
            ImportError: If DBAPIExecutor module not available
        """
        try:
            from iris_pgwire.dbapi_executor import DBAPIExecutor
        except ImportError as e:
            logger.error(f"Failed to import DBAPIExecutor: {e}")
            raise ImportError(
                "DBAPIExecutor not available. Ensure intersystems-irispython is installed."
            ) from e

        executor = DBAPIExecutor(config)
        logger.info(
            "DBAPI executor created",
            extra={
                "executor_type": "DBAPIExecutor",
                "pool_size": config.pool_size,
                "otel_enabled": config.enable_otel,
            },
        )
        return executor

    def _create_embedded_executor(self, config: BackendConfig) -> Executor:
        """
        Create embedded executor for iris.sql.exec() usage.

        Args:
            config: Backend configuration

        Returns:
            EmbeddedExecutor instance

        Raises:
            ImportError: If IRISExecutor module not available
        """
        try:
            from iris_pgwire.iris_executor import IRISExecutor
        except ImportError as e:
            logger.error(f"Failed to import IRISExecutor: {e}")
            raise ImportError(
                "IRISExecutor not available. Ensure running inside IRIS process via irispython."
            ) from e

        # Map BackendConfig keys to IRISExecutor legacy iris_config format
        iris_config = {
            "host": config.iris_hostname,
            "port": config.iris_port,
            "username": config.iris_username,
            "password": config.iris_password,
            "namespace": config.iris_namespace,
        }
        
        executor = IRISExecutor(
            iris_config,
            connection_pool_size=config.pool_size,
            connection_pool_timeout=float(config.pool_timeout)
        )
        # backend_type is now set in IRISExecutor.__init__
        logger.info(
            "Embedded executor created",
            extra={
                "executor_type": "IRISExecutor",
                "backend_type": executor.backend_type,
            },
        )
        return executor

    async def close_all(self):
        """Close all cached executor instances."""
        for executor in self._executors.values():
            try:
                await executor.close()
            except Exception as e:
                logger.warning(f"Error closing executor: {e}")

        self._executors.clear()
        logger.info("All executors closed")
