"""
Unit tests for iris_pgwire/models/backend_config.py.

Covers BackendConfig validation rules, from_yaml, from_env,
requires_pool, total_connections, and BackendType enum.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest
import yaml

from iris_pgwire.models.backend_config import BackendConfig, BackendType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _embedded(**kwargs) -> BackendConfig:
    defaults = dict(backend_type=BackendType.EMBEDDED, enable_otel=False)
    defaults.update(kwargs)
    return BackendConfig(**defaults)


def _dbapi(**kwargs) -> BackendConfig:
    defaults = dict(
        backend_type=BackendType.DBAPI,
        iris_password="secret",
        pool_size=5,
        pool_max_overflow=5,
        enable_otel=False,
    )
    defaults.update(kwargs)
    return BackendConfig(**defaults)


# ---------------------------------------------------------------------------
# BackendType enum
# ---------------------------------------------------------------------------


class TestBackendType:
    def test_dbapi_value(self):
        assert BackendType.DBAPI == "dbapi"

    def test_embedded_value(self):
        assert BackendType.EMBEDDED == "embedded"

    def test_is_str_subclass(self):
        assert isinstance(BackendType.DBAPI, str)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestBackendConfigDefaults:
    def test_default_backend_type_is_embedded(self):
        c = _embedded()
        assert c.backend_type == BackendType.EMBEDDED

    def test_default_hostname_localhost(self):
        c = _embedded()
        assert c.iris_hostname == "localhost"

    def test_default_port(self):
        c = _embedded()
        assert c.iris_port == 1972

    def test_default_namespace(self):
        c = _embedded()
        assert c.iris_namespace == "USER"

    def test_default_username(self):
        c = _embedded()
        assert c.iris_username == "_SYSTEM"

    def test_default_pool_size(self):
        c = _embedded()
        assert c.pool_size == 50

    def test_default_pool_max_overflow(self):
        c = _embedded()
        assert c.pool_max_overflow == 20

    def test_default_pool_timeout(self):
        c = _embedded()
        assert c.pool_timeout == 30

    def test_default_pool_recycle(self):
        c = _embedded()
        assert c.pool_recycle == 3600

    def test_default_query_timeout(self):
        c = _embedded()
        assert c.query_timeout == 30.0

    def test_otel_endpoint_default(self):
        c = _embedded(enable_otel=True)
        assert c.otel_endpoint == "http://localhost:4318"


# ---------------------------------------------------------------------------
# OTEL endpoint validation
# ---------------------------------------------------------------------------


class TestOtelEndpointValidation:
    def test_http_endpoint_valid(self):
        c = _embedded(enable_otel=True, otel_endpoint="http://otel:4318")
        assert c.otel_endpoint == "http://otel:4318"

    def test_https_endpoint_valid(self):
        c = _embedded(enable_otel=True, otel_endpoint="https://otel.example.com:4318")
        assert c.otel_endpoint.startswith("https://")

    def test_invalid_endpoint_raises(self):
        with pytest.raises(Exception, match="HTTP/HTTPS"):
            _embedded(enable_otel=True, otel_endpoint="ftp://bad.example.com")

    def test_otel_disabled_invalid_endpoint_allowed(self):
        # When otel is disabled, endpoint validation may still pass (depends on
        # validator checking enable_otel). Per source: checks info.data.get("enable_otel", True)
        # So when enable_otel=False and the endpoint is invalid, it should NOT raise.
        # But note: field order matters — otel_endpoint is declared AFTER enable_otel,
        # so info.data should contain enable_otel when validating otel_endpoint.
        c = _embedded(enable_otel=False, otel_endpoint="ftp://whatever")
        assert c.otel_endpoint == "ftp://whatever"


# ---------------------------------------------------------------------------
# Backend constraint validation
# ---------------------------------------------------------------------------


class TestBackendConstraintValidation:
    def test_dbapi_without_password_raises(self):
        with pytest.raises(Exception, match="iris_password"):
            BackendConfig(
                backend_type=BackendType.DBAPI,
                pool_size=5,
                pool_max_overflow=5,
                enable_otel=False,
            )

    def test_embedded_without_password_ok(self):
        c = _embedded()
        assert c.iris_password is None

    def test_pool_over_200_raises(self):
        with pytest.raises(Exception, match="200"):
            _embedded(pool_size=150, pool_max_overflow=100)

    def test_pool_exactly_200_ok(self):
        c = _embedded(pool_size=100, pool_max_overflow=100)
        assert c.pool_size + c.pool_max_overflow == 200


# ---------------------------------------------------------------------------
# requires_pool / total_connections
# ---------------------------------------------------------------------------


class TestRequiresPool:
    def test_dbapi_requires_pool(self):
        c = _dbapi()
        assert c.requires_pool() is True

    def test_embedded_does_not_require_pool(self):
        c = _embedded()
        assert c.requires_pool() is False


class TestTotalConnections:
    def test_total_connections_sum(self):
        c = _dbapi(pool_size=30, pool_max_overflow=10)
        assert c.total_connections() == 40

    def test_total_connections_default(self):
        c = _dbapi(pool_size=50, pool_max_overflow=20)
        assert c.total_connections() == 70


# ---------------------------------------------------------------------------
# from_yaml
# ---------------------------------------------------------------------------


class TestFromYaml:
    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            BackendConfig.from_yaml(tmp_path / "nonexistent.yaml")

    def test_embedded_yaml_loads(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump({"backend": {"type": "embedded"}, "observability": {"enable_otel": False}})
        )
        c = BackendConfig.from_yaml(config_path)
        assert c.backend_type == BackendType.EMBEDDED

    def test_dbapi_yaml_loads(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        data = {
            "backend": {"type": "dbapi"},
            "iris": {"password": "s3cr3t"},
            "observability": {"enable_otel": False},
        }
        config_path.write_text(yaml.dump(data))
        c = BackendConfig.from_yaml(config_path)
        assert c.backend_type == BackendType.DBAPI
        assert c.iris_password == "s3cr3t"

    def test_iris_section_mapped(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        data = {
            "iris": {"hostname": "iris.example.com", "port": 2000, "namespace": "MYNS"},
            "observability": {"enable_otel": False},
        }
        config_path.write_text(yaml.dump(data))
        c = BackendConfig.from_yaml(config_path)
        assert c.iris_hostname == "iris.example.com"
        assert c.iris_port == 2000
        assert c.iris_namespace == "MYNS"

    def test_connection_pool_section_mapped(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        data = {
            "connection_pool": {"size": 10, "max_overflow": 5, "timeout": 60, "recycle": 7200},
            "observability": {"enable_otel": False},
        }
        config_path.write_text(yaml.dump(data))
        c = BackendConfig.from_yaml(config_path)
        assert c.pool_size == 10
        assert c.pool_max_overflow == 5
        assert c.pool_timeout == 60
        assert c.pool_recycle == 7200

    def test_observability_section_mapped(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        data = {
            "observability": {
                "enable_otel": True,
                "otel_endpoint": "http://custom:4318",
            }
        }
        config_path.write_text(yaml.dump(data))
        c = BackendConfig.from_yaml(config_path)
        assert c.enable_otel is True
        assert c.otel_endpoint == "http://custom:4318"


# ---------------------------------------------------------------------------
# from_env
# ---------------------------------------------------------------------------


class TestFromEnv:
    def _run(self, env_vars: dict) -> BackendConfig:
        """Run from_env with specific environment variables set."""
        clean = {k: v for k, v in env_vars.items() if v is not None}
        with patch.dict(os.environ, clean, clear=False):
            # Remove keys we didn't set so they don't bleed in
            to_remove = [
                "PGWIRE_BACKEND_TYPE", "IRIS_HOSTNAME", "IRIS_PORT", "IRIS_NAMESPACE",
                "IRIS_USERNAME", "IRIS_PASSWORD", "PGWIRE_POOL_SIZE", "PGWIRE_POOL_MAX_OVERFLOW",
                "PGWIRE_POOL_TIMEOUT", "PGWIRE_POOL_RECYCLE", "PGWIRE_QUERY_TIMEOUT",
                "PGWIRE_ENABLE_OTEL", "PGWIRE_OTEL_ENDPOINT",
            ]
            env_patch = {k: clean.get(k, "") for k in to_remove}
            # Build env with only our vars set (others cleared)
            with patch.dict(os.environ, clean):
                for k in to_remove:
                    if k not in clean:
                        os.environ.pop(k, None)
                return BackendConfig.from_env()

    def test_default_embedded_when_no_env(self):
        env_clean = {
            "PGWIRE_BACKEND_TYPE": None, "IRIS_HOSTNAME": None, "IRIS_PORT": None,
            "IRIS_NAMESPACE": None, "IRIS_USERNAME": None, "IRIS_PASSWORD": None,
            "PGWIRE_POOL_SIZE": None, "PGWIRE_POOL_MAX_OVERFLOW": None,
            "PGWIRE_POOL_TIMEOUT": None, "PGWIRE_POOL_RECYCLE": None,
            "PGWIRE_QUERY_TIMEOUT": None, "PGWIRE_ENABLE_OTEL": None,
            "PGWIRE_OTEL_ENDPOINT": None,
        }
        remove = {k for k, v in env_clean.items()}
        original = {k: os.environ.pop(k, None) for k in remove}
        try:
            c = BackendConfig.from_env()
            assert c.backend_type == BackendType.EMBEDDED
        finally:
            for k, v in original.items():
                if v is not None:
                    os.environ[k] = v

    def test_backend_type_from_env(self):
        remove_keys = [
            "PGWIRE_BACKEND_TYPE", "IRIS_HOSTNAME", "IRIS_PORT", "IRIS_NAMESPACE",
            "IRIS_USERNAME", "IRIS_PASSWORD", "PGWIRE_POOL_SIZE", "PGWIRE_POOL_MAX_OVERFLOW",
            "PGWIRE_POOL_TIMEOUT", "PGWIRE_POOL_RECYCLE", "PGWIRE_QUERY_TIMEOUT",
            "PGWIRE_ENABLE_OTEL", "PGWIRE_OTEL_ENDPOINT",
        ]
        saved = {k: os.environ.pop(k, None) for k in remove_keys}
        os.environ["PGWIRE_BACKEND_TYPE"] = "dbapi"
        os.environ["IRIS_PASSWORD"] = "envpass"
        os.environ["PGWIRE_ENABLE_OTEL"] = "false"
        try:
            c = BackendConfig.from_env()
            assert c.backend_type == BackendType.DBAPI
            assert c.iris_password == "envpass"
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
            os.environ.pop("PGWIRE_BACKEND_TYPE", None)
            os.environ.pop("IRIS_PASSWORD", None)
            os.environ.pop("PGWIRE_ENABLE_OTEL", None)

    def test_integer_env_vars_converted(self):
        remove_keys = [
            "PGWIRE_BACKEND_TYPE", "IRIS_HOSTNAME", "IRIS_PORT", "IRIS_NAMESPACE",
            "IRIS_USERNAME", "IRIS_PASSWORD", "PGWIRE_POOL_SIZE", "PGWIRE_POOL_MAX_OVERFLOW",
            "PGWIRE_POOL_TIMEOUT", "PGWIRE_POOL_RECYCLE", "PGWIRE_QUERY_TIMEOUT",
            "PGWIRE_ENABLE_OTEL", "PGWIRE_OTEL_ENDPOINT",
        ]
        saved = {k: os.environ.pop(k, None) for k in remove_keys}
        os.environ["IRIS_PORT"] = "2000"
        os.environ["PGWIRE_POOL_SIZE"] = "10"
        os.environ["PGWIRE_ENABLE_OTEL"] = "false"
        try:
            c = BackendConfig.from_env()
            assert c.iris_port == 2000
            assert c.pool_size == 10
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
            os.environ.pop("IRIS_PORT", None)
            os.environ.pop("PGWIRE_POOL_SIZE", None)
            os.environ.pop("PGWIRE_ENABLE_OTEL", None)

    def test_bool_env_var_true_variants(self):
        remove_keys = [
            "PGWIRE_BACKEND_TYPE", "IRIS_HOSTNAME", "IRIS_PORT", "IRIS_NAMESPACE",
            "IRIS_USERNAME", "IRIS_PASSWORD", "PGWIRE_POOL_SIZE", "PGWIRE_POOL_MAX_OVERFLOW",
            "PGWIRE_POOL_TIMEOUT", "PGWIRE_POOL_RECYCLE", "PGWIRE_QUERY_TIMEOUT",
            "PGWIRE_ENABLE_OTEL", "PGWIRE_OTEL_ENDPOINT",
        ]
        for true_val in ("true", "1", "yes"):
            saved = {k: os.environ.pop(k, None) for k in remove_keys}
            os.environ["PGWIRE_ENABLE_OTEL"] = true_val
            os.environ["PGWIRE_OTEL_ENDPOINT"] = "http://localhost:4318"
            try:
                c = BackendConfig.from_env()
                assert c.enable_otel is True, f"Expected True for PGWIRE_ENABLE_OTEL={true_val!r}"
            finally:
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v
                os.environ.pop("PGWIRE_ENABLE_OTEL", None)
                os.environ.pop("PGWIRE_OTEL_ENDPOINT", None)

    def test_bool_env_var_false_variants(self):
        remove_keys = [
            "PGWIRE_BACKEND_TYPE", "IRIS_HOSTNAME", "IRIS_PORT", "IRIS_NAMESPACE",
            "IRIS_USERNAME", "IRIS_PASSWORD", "PGWIRE_POOL_SIZE", "PGWIRE_POOL_MAX_OVERFLOW",
            "PGWIRE_POOL_TIMEOUT", "PGWIRE_POOL_RECYCLE", "PGWIRE_QUERY_TIMEOUT",
            "PGWIRE_ENABLE_OTEL", "PGWIRE_OTEL_ENDPOINT",
        ]
        for false_val in ("false", "0", "no"):
            saved = {k: os.environ.pop(k, None) for k in remove_keys}
            os.environ["PGWIRE_ENABLE_OTEL"] = false_val
            try:
                c = BackendConfig.from_env()
                assert c.enable_otel is False, f"Expected False for PGWIRE_ENABLE_OTEL={false_val!r}"
            finally:
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v
                os.environ.pop("PGWIRE_ENABLE_OTEL", None)

    def test_query_timeout_float_conversion(self):
        remove_keys = [
            "PGWIRE_BACKEND_TYPE", "IRIS_HOSTNAME", "IRIS_PORT", "IRIS_NAMESPACE",
            "IRIS_USERNAME", "IRIS_PASSWORD", "PGWIRE_POOL_SIZE", "PGWIRE_POOL_MAX_OVERFLOW",
            "PGWIRE_POOL_TIMEOUT", "PGWIRE_POOL_RECYCLE", "PGWIRE_QUERY_TIMEOUT",
            "PGWIRE_ENABLE_OTEL", "PGWIRE_OTEL_ENDPOINT",
        ]
        saved = {k: os.environ.pop(k, None) for k in remove_keys}
        os.environ["PGWIRE_QUERY_TIMEOUT"] = "45.5"
        os.environ["PGWIRE_ENABLE_OTEL"] = "false"
        try:
            c = BackendConfig.from_env()
            assert c.query_timeout == 45.5
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
            os.environ.pop("PGWIRE_QUERY_TIMEOUT", None)
            os.environ.pop("PGWIRE_ENABLE_OTEL", None)
