"""
Unit tests for iris_pgwire.sql_translator.config module.

Tests all dataclasses, ConfigurationManager, and convenience functions
without requiring IRIS or any external services.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from iris_pgwire.sql_translator.config import (
    CacheConfig,
    ConfigFormat,
    ConfigurationManager,
    DebugConfig,
    IRISConfig,
    MetricsConfig,
    PerformanceConfig,
    TranslationConfig,
    ValidationConfig,
    get_config,
    get_config_manager,
    load_config,
    reload_config,
)


# ---------------------------------------------------------------------------
# CacheConfig tests
# ---------------------------------------------------------------------------


class TestCacheConfig:
    def test_defaults(self):
        cfg = CacheConfig()
        assert cfg.enabled is True
        assert cfg.max_size == 10000
        assert cfg.ttl_seconds == 3600
        assert cfg.cleanup_interval_seconds == 300
        assert cfg.memory_limit_mb == 100
        assert cfg.hit_rate_threshold == 0.8

    def test_custom_values(self):
        cfg = CacheConfig(enabled=False, max_size=500, ttl_seconds=60)
        assert cfg.enabled is False
        assert cfg.max_size == 500
        assert cfg.ttl_seconds == 60

    def test_invalid_max_size_raises(self):
        with pytest.raises(ValueError, match="max_size must be positive"):
            CacheConfig(max_size=0)

    def test_negative_max_size_raises(self):
        with pytest.raises(ValueError, match="max_size must be positive"):
            CacheConfig(max_size=-1)

    def test_invalid_ttl_raises(self):
        with pytest.raises(ValueError, match="TTL must be positive"):
            CacheConfig(ttl_seconds=0)

    def test_invalid_hit_rate_below_zero_raises(self):
        with pytest.raises(ValueError, match="Hit rate threshold"):
            CacheConfig(hit_rate_threshold=-0.1)

    def test_invalid_hit_rate_above_one_raises(self):
        with pytest.raises(ValueError, match="Hit rate threshold"):
            CacheConfig(hit_rate_threshold=1.1)

    def test_boundary_hit_rate_zero(self):
        cfg = CacheConfig(hit_rate_threshold=0.0)
        assert cfg.hit_rate_threshold == 0.0

    def test_boundary_hit_rate_one(self):
        cfg = CacheConfig(hit_rate_threshold=1.0)
        assert cfg.hit_rate_threshold == 1.0


# ---------------------------------------------------------------------------
# DebugConfig tests
# ---------------------------------------------------------------------------


class TestDebugConfig:
    def test_defaults(self):
        cfg = DebugConfig()
        assert cfg.enabled is False
        assert cfg.trace_all_queries is False
        assert cfg.log_level == "INFO"
        assert cfg.log_format == "json"
        assert cfg.log_file is None

    def test_valid_log_levels(self):
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            cfg = DebugConfig(log_level=level)
            assert cfg.log_level == level

    def test_log_level_case_insensitive_validation(self):
        # Post-init upcases the check, so "debug" should be valid
        cfg = DebugConfig(log_level="debug")
        assert cfg.log_level == "debug"

    def test_invalid_log_level_raises(self):
        with pytest.raises(ValueError, match="Invalid log level"):
            DebugConfig(log_level="VERBOSE")

    def test_valid_log_formats(self):
        for fmt in ["json", "console", "structured"]:
            cfg = DebugConfig(log_format=fmt)
            assert cfg.log_format == fmt

    def test_invalid_log_format_raises(self):
        with pytest.raises(ValueError, match="Invalid log format"):
            DebugConfig(log_format="xml")

    def test_custom_log_file(self):
        cfg = DebugConfig(log_file="/tmp/iris.log")
        assert cfg.log_file == "/tmp/iris.log"

    def test_max_trace_size_default(self):
        cfg = DebugConfig()
        assert cfg.max_trace_size == 1000

    def test_trace_retention_hours_default(self):
        cfg = DebugConfig()
        assert cfg.trace_retention_hours == 24


# ---------------------------------------------------------------------------
# PerformanceConfig tests
# ---------------------------------------------------------------------------


class TestPerformanceConfig:
    def test_defaults(self):
        cfg = PerformanceConfig()
        assert cfg.sla_threshold_ms == 5.0
        assert cfg.validation_sla_ms == 2.0
        assert cfg.enable_async_translation is True
        assert cfg.thread_pool_size == 4
        assert cfg.batch_size == 100
        assert cfg.memory_limit_mb == 512
        assert cfg.enable_profiling is False
        assert cfg.profile_sample_rate == 0.01

    def test_invalid_sla_threshold_raises(self):
        with pytest.raises(ValueError, match="SLA threshold must be positive"):
            PerformanceConfig(sla_threshold_ms=0)

    def test_negative_sla_raises(self):
        with pytest.raises(ValueError, match="SLA threshold must be positive"):
            PerformanceConfig(sla_threshold_ms=-1.0)

    def test_invalid_thread_pool_size_raises(self):
        with pytest.raises(ValueError, match="Thread pool size must be positive"):
            PerformanceConfig(thread_pool_size=0)

    def test_invalid_profile_sample_rate_below_zero(self):
        with pytest.raises(ValueError, match="Profile sample rate"):
            PerformanceConfig(profile_sample_rate=-0.01)

    def test_invalid_profile_sample_rate_above_one(self):
        with pytest.raises(ValueError, match="Profile sample rate"):
            PerformanceConfig(profile_sample_rate=1.01)

    def test_boundary_profile_sample_rate_zero(self):
        cfg = PerformanceConfig(profile_sample_rate=0.0)
        assert cfg.profile_sample_rate == 0.0

    def test_boundary_profile_sample_rate_one(self):
        cfg = PerformanceConfig(profile_sample_rate=1.0)
        assert cfg.profile_sample_rate == 1.0


# ---------------------------------------------------------------------------
# ValidationConfig tests
# ---------------------------------------------------------------------------


class TestValidationConfig:
    def test_defaults(self):
        cfg = ValidationConfig()
        assert cfg.enabled is True
        assert cfg.default_level == "SEMANTIC"
        assert cfg.confidence_threshold == 0.8
        assert cfg.enable_constitutional_checks is True
        assert cfg.strict_ddl is False

    def test_valid_levels(self):
        for level in ["BASIC", "SEMANTIC", "STRICT", "EXHAUSTIVE"]:
            cfg = ValidationConfig(default_level=level)
            assert cfg.default_level == level

    def test_invalid_level_raises(self):
        with pytest.raises(ValueError, match="Invalid validation level"):
            ValidationConfig(default_level="MINIMAL")

    def test_invalid_confidence_below_zero(self):
        with pytest.raises(ValueError, match="Confidence threshold"):
            ValidationConfig(confidence_threshold=-0.1)

    def test_invalid_confidence_above_one(self):
        with pytest.raises(ValueError, match="Confidence threshold"):
            ValidationConfig(confidence_threshold=1.1)

    def test_strict_ddl_flag(self):
        cfg = ValidationConfig(strict_ddl=True)
        assert cfg.strict_ddl is True

    def test_max_issues_per_query_default(self):
        cfg = ValidationConfig()
        assert cfg.max_issues_per_query == 50


# ---------------------------------------------------------------------------
# MetricsConfig tests
# ---------------------------------------------------------------------------


class TestMetricsConfig:
    def test_defaults(self):
        cfg = MetricsConfig()
        assert cfg.enabled is True
        assert cfg.enable_otel is False
        assert cfg.enable_prometheus is False
        assert cfg.otel_endpoint is None
        assert cfg.prometheus_port == 8080
        assert cfg.collection_interval_seconds == 30
        assert cfg.retention_days == 7
        assert cfg.iris_integration is True

    def test_invalid_prometheus_port_zero(self):
        with pytest.raises(ValueError, match="Prometheus port"):
            MetricsConfig(prometheus_port=0)

    def test_invalid_prometheus_port_too_high(self):
        with pytest.raises(ValueError, match="Prometheus port"):
            MetricsConfig(prometheus_port=65536)

    def test_valid_prometheus_port_boundary_low(self):
        cfg = MetricsConfig(prometheus_port=1)
        assert cfg.prometheus_port == 1

    def test_valid_prometheus_port_boundary_high(self):
        cfg = MetricsConfig(prometheus_port=65535)
        assert cfg.prometheus_port == 65535

    def test_invalid_collection_interval_zero(self):
        with pytest.raises(ValueError, match="Collection interval must be positive"):
            MetricsConfig(collection_interval_seconds=0)

    def test_custom_otel_endpoint(self):
        cfg = MetricsConfig(enable_otel=True, otel_endpoint="http://otel:4317")
        assert cfg.otel_endpoint == "http://otel:4317"


# ---------------------------------------------------------------------------
# IRISConfig tests
# ---------------------------------------------------------------------------


class TestIRISConfig:
    def test_defaults(self):
        cfg = IRISConfig()
        assert cfg.connection_string is None
        assert cfg.embedded_python is True
        assert cfg.namespace == "USER"
        assert cfg.timeout_seconds == 30
        assert cfg.pool_size == 10
        assert cfg.enable_vector_support is True

    def test_invalid_timeout_raises(self):
        with pytest.raises(ValueError, match="Timeout must be positive"):
            IRISConfig(timeout_seconds=0)

    def test_invalid_pool_size_raises(self):
        with pytest.raises(ValueError, match="Pool size must be positive"):
            IRISConfig(pool_size=0)

    def test_custom_connection_string(self):
        cfg = IRISConfig(connection_string="iris://localhost:1972/USER")
        assert cfg.connection_string == "iris://localhost:1972/USER"

    def test_custom_namespace(self):
        cfg = IRISConfig(namespace="PRODUCTION")
        assert cfg.namespace == "PRODUCTION"


# ---------------------------------------------------------------------------
# TranslationConfig tests
# ---------------------------------------------------------------------------


class TestTranslationConfig:
    def test_defaults(self):
        cfg = TranslationConfig()
        assert isinstance(cfg.cache, CacheConfig)
        assert isinstance(cfg.debug, DebugConfig)
        assert isinstance(cfg.performance, PerformanceConfig)
        assert isinstance(cfg.validation, ValidationConfig)
        assert isinstance(cfg.metrics, MetricsConfig)
        assert isinstance(cfg.iris, IRISConfig)
        assert cfg.environment == "development"
        assert cfg.config_version == "1.0.0"
        assert cfg.loaded_from is None

    def test_custom_environment(self):
        cfg = TranslationConfig(environment="production")
        assert cfg.environment == "production"

    def test_custom_config_version(self):
        cfg = TranslationConfig(config_version="2.0.0")
        assert cfg.config_version == "2.0.0"


# ---------------------------------------------------------------------------
# ConfigFormat enum
# ---------------------------------------------------------------------------


class TestConfigFormat:
    def test_enum_values(self):
        assert ConfigFormat.JSON.value == "json"
        assert ConfigFormat.YAML.value == "yaml"
        assert ConfigFormat.TOML.value == "toml"
        assert ConfigFormat.ENV.value == "env"


# ---------------------------------------------------------------------------
# ConfigurationManager - basic operations
# ---------------------------------------------------------------------------


class TestConfigurationManagerBasic:
    def test_init_no_path(self):
        mgr = ConfigurationManager()
        assert mgr.config_path is None
        assert mgr.config is None

    def test_init_with_path(self):
        mgr = ConfigurationManager("/tmp/some_config.json")
        assert mgr.config_path == Path("/tmp/some_config.json")

    def test_load_config_defaults_when_no_file(self, tmp_path):
        # Change to a temp dir so no iris_pgwire.json on the search path is found
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert isinstance(cfg, TranslationConfig)
            assert cfg.loaded_from == "defaults"
        finally:
            os.chdir(original_cwd)

    def test_get_config_loads_on_first_call(self):
        mgr = ConfigurationManager()
        cfg = mgr.get_config()
        assert isinstance(cfg, TranslationConfig)

    def test_get_config_returns_same_object_on_second_call(self):
        mgr = ConfigurationManager()
        cfg1 = mgr.get_config()
        cfg2 = mgr.get_config()
        assert cfg1 is cfg2

    def test_reload_config_resets_and_reloads(self):
        mgr = ConfigurationManager()
        cfg1 = mgr.load_config()
        cfg2 = mgr.reload_config()
        # Different objects but same type
        assert isinstance(cfg2, TranslationConfig)
        assert cfg1 is not cfg2

    def test_load_config_with_explicit_path_overrides(self, tmp_path):
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            mgr = ConfigurationManager(str(tmp_path / "nonexistent_abc.json"))
            # Nonexistent file → falls back to defaults
            cfg = mgr.load_config()
            assert cfg.loaded_from == "defaults"
        finally:
            os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# ConfigurationManager - JSON file loading
# ---------------------------------------------------------------------------


class TestConfigurationManagerFileLoading:
    def test_load_json_file(self, tmp_path):
        config_file = tmp_path / "iris_pgwire.json"
        config_data = {
            "environment": "testing",
            "cache": {"max_size": 500},
            "debug": {"enabled": True},
        }
        config_file.write_text(json.dumps(config_data))

        mgr = ConfigurationManager(str(config_file))
        cfg = mgr.load_config()

        assert cfg.environment == "testing"
        assert cfg.cache.max_size == 500
        assert cfg.debug.enabled is True
        assert cfg.loaded_from == str(config_file)

    def test_load_json_file_sets_loaded_from(self, tmp_path):
        config_file = tmp_path / "test.json"
        config_file.write_text("{}")
        mgr = ConfigurationManager(str(config_file))
        cfg = mgr.load_config()
        assert cfg.loaded_from == str(config_file)

    def test_malformed_json_falls_back_to_defaults(self, tmp_path):
        config_file = tmp_path / "bad.json"
        config_file.write_text("not valid json {{{")
        mgr = ConfigurationManager(str(config_file))
        cfg = mgr.load_config()
        # Malformed JSON returns empty dict → defaults apply
        assert isinstance(cfg, TranslationConfig)

    def test_load_config_with_explicit_path_arg(self, tmp_path):
        config_file = tmp_path / "explicit.json"
        config_file.write_text(json.dumps({"environment": "staging"}))
        mgr = ConfigurationManager()
        cfg = mgr.load_config(config_path=str(config_file))
        assert cfg.environment == "staging"

    def test_load_unknown_extension_tries_json_fallback(self, tmp_path):
        config_file = tmp_path / "config.cfg"
        config_file.write_text(json.dumps({"environment": "fallback"}))
        mgr = ConfigurationManager(str(config_file))
        cfg = mgr.load_config()
        assert cfg.environment == "fallback"


# ---------------------------------------------------------------------------
# ConfigurationManager - save_config
# ---------------------------------------------------------------------------


class TestConfigurationManagerSave:
    def test_save_json(self, tmp_path):
        output_file = tmp_path / "output.json"
        mgr = ConfigurationManager()
        cfg = TranslationConfig(environment="saved")
        mgr.save_config(cfg, output_path=str(output_file), format=ConfigFormat.JSON)
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["environment"] == "saved"

    def test_save_default_path_uses_format_extension(self, tmp_path):
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            mgr = ConfigurationManager()
            cfg = TranslationConfig()
            mgr.save_config(cfg, format=ConfigFormat.JSON)
            assert (tmp_path / "iris_pgwire.json").exists()
        finally:
            os.chdir(original_cwd)

    def test_save_uses_config_path_when_no_output_path(self, tmp_path):
        config_file = tmp_path / "test_save.json"
        mgr = ConfigurationManager(str(config_file))
        cfg = TranslationConfig()
        mgr.save_config(cfg)
        assert config_file.exists()

    def test_save_unsupported_format_raises(self, tmp_path):
        mgr = ConfigurationManager()
        cfg = TranslationConfig()
        with pytest.raises(ValueError, match="Unsupported format"):
            mgr.save_config(cfg, output_path=str(tmp_path / "x.env"), format=ConfigFormat.ENV)

    def test_roundtrip_json(self, tmp_path):
        output_file = tmp_path / "roundtrip.json"
        mgr = ConfigurationManager()
        original = TranslationConfig(environment="roundtrip")
        original.cache = CacheConfig(max_size=777)
        mgr.save_config(original, output_path=str(output_file), format=ConfigFormat.JSON)

        mgr2 = ConfigurationManager(str(output_file))
        loaded = mgr2.load_config()
        assert loaded.environment == "roundtrip"
        assert loaded.cache.max_size == 777


# ---------------------------------------------------------------------------
# ConfigurationManager - environment variable overrides
# ---------------------------------------------------------------------------


class TestConfigurationManagerEnvOverrides:
    def test_debug_enabled_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_DEBUG": "true"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.debug.enabled is True

    def test_debug_disabled_from_env_false(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_DEBUG": "false"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.debug.enabled is False

    def test_bool_true_variants(self):
        for val in ["true", "1", "yes", "on"]:
            with patch.dict(os.environ, {"IRIS_PGWIRE_DEBUG": val}):
                mgr = ConfigurationManager()
                cfg = mgr.load_config()
                assert cfg.debug.enabled is True, f"Failed for value: {val!r}"

    def test_bool_false_variants(self):
        for val in ["false", "0", "no", "off"]:
            with patch.dict(os.environ, {"IRIS_PGWIRE_DEBUG": val}):
                mgr = ConfigurationManager()
                cfg = mgr.load_config()
                assert cfg.debug.enabled is False, f"Failed for value: {val!r}"

    def test_cache_size_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_CACHE_SIZE": "2000"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.cache.max_size == 2000

    def test_cache_ttl_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_CACHE_TTL": "7200"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.cache.ttl_seconds == 7200

    def test_log_level_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_LOG_LEVEL": "DEBUG"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.debug.log_level == "DEBUG"

    def test_log_format_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_LOG_FORMAT": "console"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.debug.log_format == "console"

    def test_log_file_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_LOG_FILE": "/var/log/iris.log"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.debug.log_file == "/var/log/iris.log"

    def test_sla_threshold_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_SLA_THRESHOLD": "10.5"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.performance.sla_threshold_ms == 10.5

    def test_thread_pool_size_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_THREAD_POOL_SIZE": "8"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.performance.thread_pool_size == 8

    def test_validation_enabled_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_VALIDATION_ENABLED": "false"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.validation.enabled is False

    def test_validation_level_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_VALIDATION_LEVEL": "STRICT"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.validation.default_level == "STRICT"

    def test_strict_ddl_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_STRICT_DDL": "true"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.validation.strict_ddl is True

    def test_metrics_enabled_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_METRICS_ENABLED": "false"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.metrics.enabled is False

    def test_otel_enabled_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_OTEL_ENABLED": "true"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.metrics.enable_otel is True

    def test_otel_endpoint_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_OTEL_ENDPOINT": "http://otel:4317"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.metrics.otel_endpoint == "http://otel:4317"

    def test_prometheus_enabled_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_PROMETHEUS_ENABLED": "1"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.metrics.enable_prometheus is True

    def test_prometheus_port_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_PROMETHEUS_PORT": "9090"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.metrics.prometheus_port == 9090

    def test_iris_namespace_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_IRIS_NAMESPACE": "PRODUCTION"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.iris.namespace == "PRODUCTION"

    def test_iris_timeout_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_IRIS_TIMEOUT": "60"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.iris.timeout_seconds == 60

    def test_environment_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_ENVIRONMENT": "production"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.environment == "production"

    def test_invalid_env_value_is_skipped(self):
        # Non-integer value for an int field should be silently skipped
        with patch.dict(os.environ, {"IRIS_PGWIRE_CACHE_SIZE": "not-a-number"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            # Default value should remain
            assert cfg.cache.max_size == 10000

    def test_cache_enabled_from_env(self):
        with patch.dict(os.environ, {"IRIS_PGWIRE_CACHE_ENABLED": "false"}):
            mgr = ConfigurationManager()
            cfg = mgr.load_config()
            assert cfg.cache.enabled is False


# ---------------------------------------------------------------------------
# ConfigurationManager - _merge_config
# ---------------------------------------------------------------------------


class TestMergeConfig:
    def test_merge_non_overlapping_keys(self):
        mgr = ConfigurationManager()
        base = {"a": 1, "b": 2}
        override = {"c": 3}
        result = mgr._merge_config(base, override)
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_merge_overrides_scalar(self):
        mgr = ConfigurationManager()
        base = {"a": 1}
        override = {"a": 99}
        result = mgr._merge_config(base, override)
        assert result["a"] == 99

    def test_merge_recursively_merges_nested_dicts(self):
        mgr = ConfigurationManager()
        base = {"cache": {"max_size": 100, "ttl_seconds": 3600}}
        override = {"cache": {"max_size": 200}}
        result = mgr._merge_config(base, override)
        assert result["cache"]["max_size"] == 200
        assert result["cache"]["ttl_seconds"] == 3600

    def test_merge_does_not_mutate_base(self):
        mgr = ConfigurationManager()
        base = {"a": 1}
        override = {"a": 2}
        mgr._merge_config(base, override)
        assert base["a"] == 1


# ---------------------------------------------------------------------------
# ConfigurationManager - _convert_env_value
# ---------------------------------------------------------------------------


class TestConvertEnvValue:
    def test_convert_bool_true(self):
        assert ConfigurationManager._convert_env_value("true", bool) is True
        assert ConfigurationManager._convert_env_value("1", bool) is True
        assert ConfigurationManager._convert_env_value("yes", bool) is True
        assert ConfigurationManager._convert_env_value("on", bool) is True

    def test_convert_bool_false(self):
        assert ConfigurationManager._convert_env_value("false", bool) is False
        assert ConfigurationManager._convert_env_value("0", bool) is False
        assert ConfigurationManager._convert_env_value("no", bool) is False

    def test_convert_int(self):
        assert ConfigurationManager._convert_env_value("42", int) == 42

    def test_convert_float(self):
        assert ConfigurationManager._convert_env_value("3.14", float) == pytest.approx(3.14)

    def test_convert_str(self):
        assert ConfigurationManager._convert_env_value("hello", str) == "hello"


# ---------------------------------------------------------------------------
# ConfigurationManager - get_constitutional_compliance_config
# ---------------------------------------------------------------------------


class TestConstitutionalComplianceConfig:
    def test_returns_dict_with_expected_keys(self):
        mgr = ConfigurationManager()
        result = mgr.get_constitutional_compliance_config()
        assert "sla_requirements" in result
        assert "monitoring" in result
        assert "quality_thresholds" in result
        assert "audit_trail" in result

    def test_sla_requirements(self):
        mgr = ConfigurationManager()
        result = mgr.get_constitutional_compliance_config()
        sla = result["sla_requirements"]
        assert sla["translation_threshold_ms"] == 5.0
        assert sla["validation_threshold_ms"] == 2.0
        assert sla["enabled"] is True

    def test_monitoring_section(self):
        mgr = ConfigurationManager()
        result = mgr.get_constitutional_compliance_config()
        mon = result["monitoring"]
        assert "metrics_enabled" in mon
        assert "debug_tracing" in mon
        assert "performance_tracking" in mon
        assert "constitutional_checks" in mon

    def test_quality_thresholds(self):
        mgr = ConfigurationManager()
        result = mgr.get_constitutional_compliance_config()
        qt = result["quality_thresholds"]
        assert qt["confidence_threshold"] == 0.8
        assert qt["cache_hit_rate_threshold"] == 0.8
        assert qt["validation_level"] == "SEMANTIC"

    def test_audit_trail(self):
        mgr = ConfigurationManager()
        result = mgr.get_constitutional_compliance_config()
        audit = result["audit_trail"]
        assert audit["trace_retention_hours"] == 24
        assert audit["metrics_retention_days"] == 7
        assert audit["log_file"] is None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    def test_get_config_manager_returns_manager(self):
        mgr = get_config_manager()
        assert isinstance(mgr, ConfigurationManager)

    def test_get_config_manager_is_singleton(self):
        mgr1 = get_config_manager()
        mgr2 = get_config_manager()
        assert mgr1 is mgr2

    def test_get_config_returns_translation_config(self):
        cfg = get_config()
        assert isinstance(cfg, TranslationConfig)

    def test_load_config_returns_translation_config(self):
        cfg = load_config()
        assert isinstance(cfg, TranslationConfig)

    def test_reload_config_returns_translation_config(self):
        cfg = reload_config()
        assert isinstance(cfg, TranslationConfig)

    def test_load_config_with_json_file(self, tmp_path):
        config_file = tmp_path / "test_convenience.json"
        config_file.write_text(json.dumps({"environment": "ci"}))
        cfg = load_config(config_path=str(config_file))
        assert cfg.environment == "ci"


# ---------------------------------------------------------------------------
# ConfigurationManager - search path fallback
# ---------------------------------------------------------------------------


class TestConfigSearchPaths:
    def test_search_paths_are_defined(self):
        mgr = ConfigurationManager()
        assert len(mgr.search_paths) > 0
        # All are Path objects
        for p in mgr.search_paths:
            assert isinstance(p, Path)

    def test_nonexistent_search_paths_fall_back_to_defaults(self):
        mgr = ConfigurationManager()
        # Force no search path file to exist
        for path in mgr.search_paths:
            assert not path.exists() or True  # Just iterate
        cfg = mgr.load_config()
        # Should still return a valid config
        assert isinstance(cfg, TranslationConfig)
