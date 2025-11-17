"""
Configuration schema for DBAPI backend option.

This module defines the configuration model for backend selection (DBAPI vs Embedded)
using Pydantic for validation. Supports loading from YAML files or environment variables.

Constitutional Requirements:
- Principle IV (IRIS Integration): Support both DBAPI and embedded Python backends
- Principle V (Production Readiness): Validate configuration before deployment

Feature: 018-add-dbapi-option
"""

import os
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class BackendType(str, Enum):
    """Backend execution type."""

    DBAPI = "dbapi"
    EMBEDDED = "embedded"


class BackendConfig(BaseModel):
    """
    Configuration for backend selection and connection parameters.

    This model represents the configuration defined in data-model.md entity #1.
    Supports both DBAPI backend (external connection via intersystems-irispython)
    and embedded backend (iris.sql.exec() within IRIS process).

    Validation Rules:
    - If backend_type == DBAPI: All IRIS connection fields are required
    - pool_size + pool_max_overflow <= 200 (IRIS connection limit)
    - pool_timeout >= 1 second (prevent instant failures)
    - OTEL endpoint must be valid HTTP/HTTPS URL if OTEL enabled
    """

    # Backend Selection
    backend_type: BackendType = Field(
        default=BackendType.EMBEDDED,
        description="Active backend selection: 'dbapi' or 'embedded'",
    )

    # IRIS Connection Parameters (required for DBAPI backend)
    iris_hostname: str = Field(
        default="localhost", description="IRIS instance hostname or IP address"
    )
    iris_port: int = Field(default=1972, ge=1, le=65535, description="IRIS SuperServer port")
    iris_namespace: str = Field(default="USER", description="Target IRIS namespace")
    iris_username: str = Field(default="_SYSTEM", description="IRIS authentication username")
    iris_password: str | None = Field(
        default=None, description="IRIS authentication password (required for DBAPI)"
    )

    # Connection Pool Configuration
    pool_size: int = Field(
        default=50, ge=1, le=200, description="Base connection pool size (always available)"
    )
    pool_max_overflow: int = Field(
        default=20, ge=0, le=100, description="Overflow connections under load"
    )
    pool_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Maximum seconds to wait for pool connection",
    )
    pool_recycle: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Connection lifetime in seconds (1 hour default)",
    )

    # Observability Configuration
    enable_otel: bool = Field(default=True, description="Enable OpenTelemetry instrumentation")
    otel_endpoint: str = Field(default="http://localhost:4318", description="OTLP endpoint URL")

    @field_validator("otel_endpoint")
    @classmethod
    def validate_otel_endpoint(cls, v: str, info) -> str:
        """Validate OTEL endpoint is a valid HTTP/HTTPS URL if OTEL enabled."""
        if info.data.get("enable_otel", True):
            # Basic URL validation
            if not (v.startswith("http://") or v.startswith("https://")):
                raise ValueError("OTEL endpoint must be a valid HTTP/HTTPS URL")
        return v

    @model_validator(mode="after")
    def validate_backend_constraints(self) -> "BackendConfig":
        """Validate backend-specific requirements."""
        # DBAPI backend requires password
        if self.backend_type == BackendType.DBAPI:
            if not self.iris_password:
                raise ValueError(
                    "DBAPI backend requires iris_password to be set. "
                    "Provide via environment variable or config file."
                )

        # Validate total connection pool limit
        total_connections = self.pool_size + self.pool_max_overflow
        if total_connections > 200:
            raise ValueError(
                f"Connection pool ({self.pool_size} + {self.pool_max_overflow}) "
                f"exceeds maximum (200). Reduce pool_size or pool_max_overflow."
            )

        return self

    @classmethod
    def from_yaml(cls, config_path: Path) -> "BackendConfig":
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to config.yaml file

        Returns:
            Validated BackendConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If YAML is invalid or validation fails
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path) as f:
            config_data = yaml.safe_load(f)

        # Flatten nested YAML structure (backend.type → backend_type)
        flat_config = {}
        if "backend" in config_data:
            flat_config["backend_type"] = config_data["backend"]["type"]

        if "iris" in config_data:
            for key, value in config_data["iris"].items():
                flat_config[f"iris_{key}"] = value

        if "connection_pool" in config_data:
            for key, value in config_data["connection_pool"].items():
                flat_config[f"pool_{key}"] = value

        if "observability" in config_data:
            flat_config["enable_otel"] = config_data["observability"].get("enable_otel", True)
            flat_config["otel_endpoint"] = config_data["observability"].get(
                "otel_endpoint", "http://localhost:4318"
            )

        return cls(**flat_config)

    @classmethod
    def from_env(cls) -> "BackendConfig":
        """
        Load configuration from environment variables.

        Environment variable mapping:
        - PGWIRE_BACKEND_TYPE → backend_type
        - IRIS_HOSTNAME → iris_hostname
        - IRIS_PORT → iris_port
        - IRIS_NAMESPACE → iris_namespace
        - IRIS_USERNAME → iris_username
        - IRIS_PASSWORD → iris_password
        - PGWIRE_POOL_SIZE → pool_size
        - PGWIRE_POOL_MAX_OVERFLOW → pool_max_overflow
        - PGWIRE_POOL_TIMEOUT → pool_timeout
        - PGWIRE_POOL_RECYCLE → pool_recycle
        - PGWIRE_ENABLE_OTEL → enable_otel
        - PGWIRE_OTEL_ENDPOINT → otel_endpoint

        Returns:
            Validated BackendConfig instance
        """
        env_config = {}

        # Backend selection
        if backend_type := os.getenv("PGWIRE_BACKEND_TYPE"):
            env_config["backend_type"] = backend_type

        # IRIS connection
        if hostname := os.getenv("IRIS_HOSTNAME"):
            env_config["iris_hostname"] = hostname
        if port := os.getenv("IRIS_PORT"):
            env_config["iris_port"] = int(port)
        if namespace := os.getenv("IRIS_NAMESPACE"):
            env_config["iris_namespace"] = namespace
        if username := os.getenv("IRIS_USERNAME"):
            env_config["iris_username"] = username
        if password := os.getenv("IRIS_PASSWORD"):
            env_config["iris_password"] = password

        # Connection pool
        if pool_size := os.getenv("PGWIRE_POOL_SIZE"):
            env_config["pool_size"] = int(pool_size)
        if pool_overflow := os.getenv("PGWIRE_POOL_MAX_OVERFLOW"):
            env_config["pool_max_overflow"] = int(pool_overflow)
        if pool_timeout := os.getenv("PGWIRE_POOL_TIMEOUT"):
            env_config["pool_timeout"] = int(pool_timeout)
        if pool_recycle := os.getenv("PGWIRE_POOL_RECYCLE"):
            env_config["pool_recycle"] = int(pool_recycle)

        # Observability
        if enable_otel := os.getenv("PGWIRE_ENABLE_OTEL"):
            env_config["enable_otel"] = enable_otel.lower() in ("true", "1", "yes")
        if otel_endpoint := os.getenv("PGWIRE_OTEL_ENDPOINT"):
            env_config["otel_endpoint"] = otel_endpoint

        return cls(**env_config)

    def requires_pool(self) -> bool:
        """Check if backend requires connection pooling."""
        return self.backend_type == BackendType.DBAPI

    def total_connections(self) -> int:
        """Calculate total maximum connections (base + overflow)."""
        return self.pool_size + self.pool_max_overflow
