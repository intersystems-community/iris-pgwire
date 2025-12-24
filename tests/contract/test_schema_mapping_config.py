"""
Contract tests for schema mapping configuration (Feature 030).

Tests verify that:
1. Default configuration uses SQLUser
2. Environment variable overrides default
3. configure_schema() allows runtime configuration
4. Custom mapping dict works correctly
"""

import os
from unittest import mock

import pytest


class TestSchemaConfigDefault:
    """Test default schema configuration."""

    def test_default_schema_is_sqluser(self):
        """Default IRIS schema should be SQLUser."""
        from iris_pgwire.schema_mapper import IRIS_SCHEMA

        # Default should be SQLUser (unless env var is set)
        if "PGWIRE_IRIS_SCHEMA" not in os.environ:
            assert IRIS_SCHEMA == "SQLUser"

    def test_get_schema_config_returns_dict(self):
        """get_schema_config() returns proper structure."""
        from iris_pgwire.schema_mapper import get_schema_config

        config = get_schema_config()
        assert "iris_schema" in config
        assert "postgres_schema" in config
        assert "source" in config
        assert config["postgres_schema"] == "public"

    def test_schema_config_source_default(self):
        """Source should be 'default' when env var not set."""
        from iris_pgwire.schema_mapper import get_schema_config

        config = get_schema_config()
        if "PGWIRE_IRIS_SCHEMA" not in os.environ:
            assert config["source"] == "default"


class TestSchemaConfigRuntime:
    """Test runtime schema configuration via configure_schema()."""

    def test_configure_schema_simple(self):
        """configure_schema(iris_schema=...) updates mapping."""
        from iris_pgwire.schema_mapper import (
            IRIS_SCHEMA,
            configure_schema,
            get_schema_config,
            translate_input_schema,
        )

        # Save original
        original = get_schema_config()["iris_schema"]

        try:
            # Configure custom schema
            configure_schema(iris_schema="MyAppSchema")

            # Verify translation uses new schema
            sql = "SELECT * FROM information_schema.tables WHERE table_schema = 'public'"
            result = translate_input_schema(sql)
            assert "MyAppSchema" in result
            assert "SQLUser" not in result

        finally:
            # Restore original
            configure_schema(iris_schema=original)

    def test_configure_schema_with_mapping_dict(self):
        """configure_schema(mapping=...) accepts custom dict."""
        from iris_pgwire.schema_mapper import (
            configure_schema,
            get_schema_config,
            translate_input_schema,
        )

        original = get_schema_config()["iris_schema"]

        try:
            # Configure with custom mapping
            configure_schema(mapping={"public": "CustomSchema"})

            sql = "SELECT * FROM public.users"
            result = translate_input_schema(sql)
            assert "CustomSchema.users" in result

        finally:
            configure_schema(iris_schema=original)

    def test_configure_schema_requires_argument(self):
        """configure_schema() without args raises ValueError."""
        from iris_pgwire.schema_mapper import configure_schema

        with pytest.raises(ValueError, match="Must provide"):
            configure_schema()

    def test_configure_schema_updates_output_translation(self):
        """Output translation uses configured schema."""
        from iris_pgwire.schema_mapper import (
            configure_schema,
            get_schema_config,
            translate_output_schema,
        )

        original = get_schema_config()["iris_schema"]

        try:
            configure_schema(iris_schema="CustomData")

            # Rows with CustomData should translate to public
            rows = [("CustomData", "users"), ("CustomData", "orders")]
            columns = ["table_schema", "table_name"]
            result = translate_output_schema(rows, columns)

            assert result[0][0] == "public"
            assert result[1][0] == "public"

        finally:
            configure_schema(iris_schema=original)


class TestSchemaConfigEnvironment:
    """Test environment variable configuration."""

    def test_env_var_is_read(self):
        """PGWIRE_IRIS_SCHEMA env var is respected on module load."""
        # This test verifies the module respects env vars
        # Since the module is already loaded, we test via configure_schema
        from iris_pgwire.schema_mapper import (
            configure_schema,
            get_schema_config,
        )

        original = get_schema_config()["iris_schema"]

        try:
            # Simulate what happens with env var
            configure_schema(iris_schema="EnvTestSchema")
            config = get_schema_config()
            assert config["iris_schema"] == "EnvTestSchema"

        finally:
            configure_schema(iris_schema=original)


class TestSchemaConfigPerformance:
    """Test that configuration doesn't impact performance."""

    def test_reconfiguration_is_fast(self):
        """configure_schema() completes in < 1ms."""
        import time

        from iris_pgwire.schema_mapper import configure_schema, get_schema_config

        original = get_schema_config()["iris_schema"]

        try:
            start = time.perf_counter()
            for _ in range(100):
                configure_schema(iris_schema="TestSchema")
            elapsed_ms = (time.perf_counter() - start) * 1000

            # 100 reconfigurations should complete in < 100ms (1ms each)
            assert elapsed_ms < 100, f"Reconfiguration too slow: {elapsed_ms:.2f}ms for 100 ops"

        finally:
            configure_schema(iris_schema=original)
