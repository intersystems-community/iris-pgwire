"""
Configuration Management for SQL Translation System

Provides centralized configuration loading and management for debug mode,
cache settings, performance tuning, and constitutional compliance parameters.

Constitutional Compliance: Configurable SLA thresholds and monitoring settings.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

try:
    import toml

    TOML_AVAILABLE = True
except ImportError:
    TOML_AVAILABLE = False


class ConfigFormat(Enum):
    """Supported configuration file formats"""

    JSON = "json"
    YAML = "yaml"
    TOML = "toml"
    ENV = "env"


@dataclass
class CacheConfig:
    """Cache configuration settings"""

    enabled: bool = True
    max_size: int = 10000
    ttl_seconds: int = 3600
    cleanup_interval_seconds: int = 300
    memory_limit_mb: int = 100
    hit_rate_threshold: float = 0.8  # Constitutional requirement

    def __post_init__(self):
        """Validate cache configuration"""
        if self.max_size <= 0:
            raise ValueError("Cache max_size must be positive")
        if self.ttl_seconds <= 0:
            raise ValueError("Cache TTL must be positive")
        if not 0.0 <= self.hit_rate_threshold <= 1.0:
            raise ValueError("Hit rate threshold must be between 0.0 and 1.0")


@dataclass
class DebugConfig:
    """Debug and tracing configuration"""

    enabled: bool = False
    trace_all_queries: bool = False
    trace_constructs: bool = True
    trace_mappings: bool = True
    trace_performance: bool = True
    trace_validation: bool = False
    log_level: str = "INFO"
    log_format: str = "json"
    log_file: str | None = None
    max_trace_size: int = 1000
    trace_retention_hours: int = 24

    def __post_init__(self):
        """Validate debug configuration"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {self.log_level}")

        valid_formats = ["json", "console", "structured"]
        if self.log_format.lower() not in valid_formats:
            raise ValueError(f"Invalid log format: {self.log_format}")


@dataclass
class PerformanceConfig:
    """Performance and optimization settings"""

    sla_threshold_ms: float = 5.0  # Constitutional requirement
    validation_sla_ms: float = 2.0
    enable_async_translation: bool = True
    thread_pool_size: int = 4
    batch_size: int = 100
    memory_limit_mb: int = 512
    enable_profiling: bool = False
    profile_sample_rate: float = 0.01

    def __post_init__(self):
        """Validate performance configuration"""
        if self.sla_threshold_ms <= 0:
            raise ValueError("SLA threshold must be positive")
        if self.thread_pool_size <= 0:
            raise ValueError("Thread pool size must be positive")
        if not 0.0 <= self.profile_sample_rate <= 1.0:
            raise ValueError("Profile sample rate must be between 0.0 and 1.0")


@dataclass
class ValidationConfig:
    """Validation system configuration"""

    enabled: bool = True
    default_level: str = "SEMANTIC"
    confidence_threshold: float = 0.8
    enable_constitutional_checks: bool = True
    enable_performance_checks: bool = True
    enable_semantic_checks: bool = True
    max_issues_per_query: int = 50
    validation_timeout_ms: float = 2000.0
    strict_ddl: bool = False  # Feature 036: Strict mode for unsupported PostgreSQL DDL

    def __post_init__(self):
        """Validate validation configuration"""
        valid_levels = ["BASIC", "SEMANTIC", "STRICT", "EXHAUSTIVE"]
        if self.default_level.upper() not in valid_levels:
            raise ValueError(f"Invalid validation level: {self.default_level}")

        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("Confidence threshold must be between 0.0 and 1.0")


@dataclass
class MetricsConfig:
    """Metrics collection configuration"""

    enabled: bool = True
    enable_otel: bool = False
    enable_prometheus: bool = False
    otel_endpoint: str | None = None
    prometheus_port: int = 8080
    collection_interval_seconds: int = 30
    retention_days: int = 7
    export_timeout_ms: int = 5000
    iris_integration: bool = True  # Use IRIS native OTEL if available

    def __post_init__(self):
        """Validate metrics configuration"""
        if self.prometheus_port <= 0 or self.prometheus_port > 65535:
            raise ValueError("Prometheus port must be between 1 and 65535")
        if self.collection_interval_seconds <= 0:
            raise ValueError("Collection interval must be positive")


@dataclass
class IRISConfig:
    """IRIS-specific configuration"""

    connection_string: str | None = None
    embedded_python: bool = True
    namespace: str = "USER"
    timeout_seconds: int = 30
    pool_size: int = 10
    enable_vector_support: bool = True
    vector_license_check: bool = True
    version_detection: bool = True

    def __post_init__(self):
        """Validate IRIS configuration"""
        if self.timeout_seconds <= 0:
            raise ValueError("Timeout must be positive")
        if self.pool_size <= 0:
            raise ValueError("Pool size must be positive")


@dataclass
class TranslationConfig:
    """Complete translation system configuration"""

    cache: CacheConfig = field(default_factory=CacheConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    iris: IRISConfig = field(default_factory=IRISConfig)

    # Global settings
    environment: str = "development"
    config_version: str = "1.0.0"
    loaded_from: str | None = None


class ConfigurationManager:
    """
    Configuration manager for SQL translation system

    Features:
    - Multiple config file format support (JSON, YAML, TOML)
    - Environment variable override
    - Configuration validation
    - Hot reloading capability
    - Constitutional compliance defaults
    """

    def __init__(self, config_path: str | Path | None = None):
        """
        Initialize configuration manager

        Args:
            config_path: Optional path to configuration file
        """
        self.config_path = Path(config_path) if config_path else None
        self.config: TranslationConfig | None = None
        self.logger = logging.getLogger("iris_pgwire.sql_translator.config")

        # Default config search paths
        self.search_paths = [
            Path("iris_pgwire.json"),
            Path("iris_pgwire.yaml"),
            Path("iris_pgwire.yml"),
            Path("iris_pgwire.toml"),
            Path("config/iris_pgwire.json"),
            Path("config/iris_pgwire.yaml"),
            Path("config/iris_pgwire.yml"),
            Path("config/iris_pgwire.toml"),
            Path(".iris_pgwire.json"),
            Path(".iris_pgwire.yaml"),
            Path(".iris_pgwire.yml"),
            Path(".iris_pgwire.toml"),
        ]

    def load_config(self, config_path: str | Path | None = None) -> TranslationConfig:
        """
        Load configuration from file or environment

        Args:
            config_path: Optional path to configuration file

        Returns:
            Loaded and validated configuration
        """
        if config_path:
            self.config_path = Path(config_path)

        # Try to find and load config file
        config_data = {}
        loaded_from = "defaults"

        if self.config_path and self.config_path.exists():
            config_data = self._load_config_file(self.config_path)
            loaded_from = str(self.config_path)
        else:
            # Search for config files in standard locations
            for search_path in self.search_paths:
                if search_path.exists():
                    config_data = self._load_config_file(search_path)
                    loaded_from = str(search_path)
                    self.config_path = search_path
                    break

        # Apply environment variable overrides
        env_overrides = self._load_environment_config()
        config_data = self._merge_config(config_data, env_overrides)

        # Create configuration object
        self.config = self._create_config_object(config_data)
        self.config.loaded_from = loaded_from

        self.logger.info(f"Configuration loaded from: {loaded_from}")
        return self.config

    def get_config(self) -> TranslationConfig:
        """
        Get current configuration, loading defaults if not loaded

        Returns:
            Current configuration
        """
        if self.config is None:
            return self.load_config()
        return self.config

    def reload_config(self) -> TranslationConfig:
        """
        Reload configuration from file

        Returns:
            Reloaded configuration
        """
        self.config = None
        return self.load_config()

    def save_config(
        self,
        config: TranslationConfig,
        output_path: str | Path | None = None,
        format: ConfigFormat = ConfigFormat.JSON,
    ) -> None:
        """
        Save configuration to file

        Args:
            config: Configuration to save
            output_path: Output file path
            format: Configuration file format
        """
        if output_path is None:
            if self.config_path:
                output_path = self.config_path
            else:
                output_path = Path(f"iris_pgwire.{format.value}")
        else:
            output_path = Path(output_path)

        config_data = self._config_to_dict(config)

        if format == ConfigFormat.JSON:
            with open(output_path, "w") as f:
                json.dump(config_data, f, indent=2, default=str)
        elif format == ConfigFormat.YAML and YAML_AVAILABLE:
            with open(output_path, "w") as f:
                yaml.dump(config_data, f, default_flow_style=False)
        elif format == ConfigFormat.TOML and TOML_AVAILABLE:
            with open(output_path, "w") as f:
                toml.dump(config_data, f)
        else:
            raise ValueError(f"Unsupported format: {format}")

        self.logger.info(f"Configuration saved to: {output_path}")

    def _load_config_file(self, config_path: Path) -> dict[str, Any]:
        """Load configuration from file"""
        try:
            with open(config_path) as f:
                if config_path.suffix.lower() == ".json":
                    return json.load(f)
                elif config_path.suffix.lower() in [".yaml", ".yml"]:
                    if not YAML_AVAILABLE:
                        raise ImportError("PyYAML not available for YAML config files")
                    return yaml.safe_load(f) or {}
                elif config_path.suffix.lower() == ".toml":
                    if not TOML_AVAILABLE:
                        raise ImportError("toml not available for TOML config files")
                    return toml.load(f)
                else:
                    # Try JSON as fallback
                    f.seek(0)
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config from {config_path}: {e}")
            return {}

    def _load_environment_config(self) -> dict[str, Any]:
        """Load configuration overrides from environment variables"""
        env_config = {}

        # Define environment variable mappings
        env_mappings = {
            "IRIS_PGWIRE_DEBUG": ("debug", "enabled", bool),
            "IRIS_PGWIRE_CACHE_ENABLED": ("cache", "enabled", bool),
            "IRIS_PGWIRE_CACHE_SIZE": ("cache", "max_size", int),
            "IRIS_PGWIRE_CACHE_TTL": ("cache", "ttl_seconds", int),
            "IRIS_PGWIRE_LOG_LEVEL": ("debug", "log_level", str),
            "IRIS_PGWIRE_LOG_FORMAT": ("debug", "log_format", str),
            "IRIS_PGWIRE_LOG_FILE": ("debug", "log_file", str),
            "IRIS_PGWIRE_SLA_THRESHOLD": ("performance", "sla_threshold_ms", float),
            "IRIS_PGWIRE_THREAD_POOL_SIZE": ("performance", "thread_pool_size", int),
            "IRIS_PGWIRE_VALIDATION_ENABLED": ("validation", "enabled", bool),
            "IRIS_PGWIRE_VALIDATION_LEVEL": ("validation", "default_level", str),
            "IRIS_PGWIRE_STRICT_DDL": ("validation", "strict_ddl", bool),
            "IRIS_PGWIRE_METRICS_ENABLED": ("metrics", "enabled", bool),
            "IRIS_PGWIRE_OTEL_ENABLED": ("metrics", "enable_otel", bool),
            "IRIS_PGWIRE_OTEL_ENDPOINT": ("metrics", "otel_endpoint", str),
            "IRIS_PGWIRE_PROMETHEUS_ENABLED": ("metrics", "enable_prometheus", bool),
            "IRIS_PGWIRE_PROMETHEUS_PORT": ("metrics", "prometheus_port", int),
            "IRIS_PGWIRE_IRIS_NAMESPACE": ("iris", "namespace", str),
            "IRIS_PGWIRE_IRIS_TIMEOUT": ("iris", "timeout_seconds", int),
            "IRIS_PGWIRE_ENVIRONMENT": ("environment", None, str),
        }

        for env_var, (section, key, value_type) in env_mappings.items():
            env_value = os.getenv(env_var)
            if env_value is not None:
                try:
                    # Convert value to appropriate type
                    if value_type == bool:
                        converted_value = env_value.lower() in ("true", "1", "yes", "on")
                    elif value_type == int:
                        converted_value = int(env_value)
                    elif value_type == float:
                        converted_value = float(env_value)
                    else:
                        converted_value = env_value

                    # Set in config structure
                    if key is None:
                        env_config[section] = converted_value
                    else:
                        if section not in env_config:
                            env_config[section] = {}
                        env_config[section][key] = converted_value

                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Invalid value for {env_var}: {env_value} ({e})")

        return env_config

    def _merge_config(
        self, base_config: dict[str, Any], override_config: dict[str, Any]
    ) -> dict[str, Any]:
        """Recursively merge configuration dictionaries"""
        merged = base_config.copy()

        for key, value in override_config.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._merge_config(merged[key], value)
            else:
                merged[key] = value

        return merged

    def _create_config_object(self, config_data: dict[str, Any]) -> TranslationConfig:
        """Create configuration object from dictionary"""
        # Extract section data with defaults
        cache_data = config_data.get("cache", {})
        debug_data = config_data.get("debug", {})
        performance_data = config_data.get("performance", {})
        validation_data = config_data.get("validation", {})
        metrics_data = config_data.get("metrics", {})
        iris_data = config_data.get("iris", {})

        # Create configuration object
        config = TranslationConfig(
            cache=CacheConfig(**cache_data),
            debug=DebugConfig(**debug_data),
            performance=PerformanceConfig(**performance_data),
            validation=ValidationConfig(**validation_data),
            metrics=MetricsConfig(**metrics_data),
            iris=IRISConfig(**iris_data),
            environment=config_data.get("environment", "development"),
            config_version=config_data.get("config_version", "1.0.0"),
        )

        return config

    def _config_to_dict(self, config: TranslationConfig) -> dict[str, Any]:
        """Convert configuration object to dictionary"""
        return {
            "cache": {
                "enabled": config.cache.enabled,
                "max_size": config.cache.max_size,
                "ttl_seconds": config.cache.ttl_seconds,
                "cleanup_interval_seconds": config.cache.cleanup_interval_seconds,
                "memory_limit_mb": config.cache.memory_limit_mb,
                "hit_rate_threshold": config.cache.hit_rate_threshold,
            },
            "debug": {
                "enabled": config.debug.enabled,
                "trace_all_queries": config.debug.trace_all_queries,
                "trace_constructs": config.debug.trace_constructs,
                "trace_mappings": config.debug.trace_mappings,
                "trace_performance": config.debug.trace_performance,
                "trace_validation": config.debug.trace_validation,
                "log_level": config.debug.log_level,
                "log_format": config.debug.log_format,
                "log_file": config.debug.log_file,
                "max_trace_size": config.debug.max_trace_size,
                "trace_retention_hours": config.debug.trace_retention_hours,
            },
            "performance": {
                "sla_threshold_ms": config.performance.sla_threshold_ms,
                "validation_sla_ms": config.performance.validation_sla_ms,
                "enable_async_translation": config.performance.enable_async_translation,
                "thread_pool_size": config.performance.thread_pool_size,
                "batch_size": config.performance.batch_size,
                "memory_limit_mb": config.performance.memory_limit_mb,
                "enable_profiling": config.performance.enable_profiling,
                "profile_sample_rate": config.performance.profile_sample_rate,
            },
            "validation": {
                "enabled": config.validation.enabled,
                "default_level": config.validation.default_level,
                "confidence_threshold": config.validation.confidence_threshold,
                "enable_constitutional_checks": config.validation.enable_constitutional_checks,
                "enable_performance_checks": config.validation.enable_performance_checks,
                "enable_semantic_checks": config.validation.enable_semantic_checks,
                "max_issues_per_query": config.validation.max_issues_per_query,
                "validation_timeout_ms": config.validation.validation_timeout_ms,
            },
            "metrics": {
                "enabled": config.metrics.enabled,
                "enable_otel": config.metrics.enable_otel,
                "enable_prometheus": config.metrics.enable_prometheus,
                "otel_endpoint": config.metrics.otel_endpoint,
                "prometheus_port": config.metrics.prometheus_port,
                "collection_interval_seconds": config.metrics.collection_interval_seconds,
                "retention_days": config.metrics.retention_days,
                "export_timeout_ms": config.metrics.export_timeout_ms,
                "iris_integration": config.metrics.iris_integration,
            },
            "iris": {
                "connection_string": config.iris.connection_string,
                "embedded_python": config.iris.embedded_python,
                "namespace": config.iris.namespace,
                "timeout_seconds": config.iris.timeout_seconds,
                "pool_size": config.iris.pool_size,
                "enable_vector_support": config.iris.enable_vector_support,
                "vector_license_check": config.iris.vector_license_check,
                "version_detection": config.iris.version_detection,
            },
            "environment": config.environment,
            "config_version": config.config_version,
        }

    def get_constitutional_compliance_config(self) -> dict[str, Any]:
        """
        Get constitutional compliance configuration summary

        Returns:
            Constitutional compliance settings
        """
        config = self.get_config()

        return {
            "sla_requirements": {
                "translation_threshold_ms": config.performance.sla_threshold_ms,
                "validation_threshold_ms": config.performance.validation_sla_ms,
                "enabled": True,
            },
            "monitoring": {
                "metrics_enabled": config.metrics.enabled,
                "debug_tracing": config.debug.enabled,
                "performance_tracking": config.debug.trace_performance,
                "constitutional_checks": config.validation.enable_constitutional_checks,
            },
            "quality_thresholds": {
                "confidence_threshold": config.validation.confidence_threshold,
                "cache_hit_rate_threshold": config.cache.hit_rate_threshold,
                "validation_level": config.validation.default_level,
            },
            "audit_trail": {
                "trace_retention_hours": config.debug.trace_retention_hours,
                "metrics_retention_days": config.metrics.retention_days,
                "log_file": config.debug.log_file,
            },
        }


# Global configuration manager instance
_config_manager = ConfigurationManager()


def get_config_manager() -> ConfigurationManager:
    """Get the global configuration manager instance"""
    return _config_manager


def get_config() -> TranslationConfig:
    """Get current configuration (convenience function)"""
    return _config_manager.get_config()


def load_config(config_path: str | Path | None = None) -> TranslationConfig:
    """Load configuration from file (convenience function)"""
    return _config_manager.load_config(config_path)


def reload_config() -> TranslationConfig:
    """Reload configuration (convenience function)"""
    return _config_manager.reload_config()


# Export main components
__all__ = [
    "TranslationConfig",
    "CacheConfig",
    "DebugConfig",
    "PerformanceConfig",
    "ValidationConfig",
    "MetricsConfig",
    "IRISConfig",
    "ConfigurationManager",
    "ConfigFormat",
    "get_config_manager",
    "get_config",
    "load_config",
    "reload_config",
]
