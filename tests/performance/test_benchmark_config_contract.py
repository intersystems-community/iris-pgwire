"""
Contract tests for BenchmarkConfiguration validation (T004).

CRITICAL TDD REQUIREMENT: These tests MUST FAIL before implementation.
Tests validate BenchmarkConfiguration.validate() method per specs/015-add-3-way/contracts/benchmark_api.py
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from benchmarks.config import BenchmarkConfiguration, ConnectionConfig


class TestBenchmarkConfigurationValidation:
    """Contract tests for BenchmarkConfiguration.validate()"""

    def test_valid_configuration_passes(self):
        """Valid configuration should pass validation with no errors"""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            iterations=1000,
            concurrent_connections=1,
            warmup_queries=100,
            random_seed=42,
            connection_configs={
                "iris_pgwire": ConnectionConfig(
                    method_name="iris_pgwire", host="localhost", port=5432, database="USER"
                ),
                "postgresql_psycopg3": ConnectionConfig(
                    method_name="postgresql_psycopg3",
                    host="localhost",
                    port=5433,
                    database="benchmark",
                    username="postgres",
                    password="postgres",
                ),
                "iris_dbapi": ConnectionConfig(
                    method_name="iris_dbapi",
                    host="localhost",
                    port=1972,
                    database="USER",
                    username="_SYSTEM",
                    password="SYS",
                ),
            },
        )

        errors = config.validate()
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_invalid_vector_dimensions_raises_error(self):
        """Vector dimensions <= 0 should raise validation error"""
        config = BenchmarkConfiguration(
            vector_dimensions=0,  # Invalid
            dataset_size=100000,
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig(
                    "postgresql_psycopg3", "localhost", 5433, "benchmark"
                ),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            },
        )

        errors = config.validate()
        assert any(
            "vector_dimensions must be > 0" in err for err in errors
        ), f"Expected vector_dimensions error, got: {errors}"

    def test_dataset_size_below_100k_raises_error(self):
        """Dataset size < 100K should raise validation error"""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=50000,  # Below 100K threshold
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig(
                    "postgresql_psycopg3", "localhost", 5433, "benchmark"
                ),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            },
        )

        errors = config.validate()
        assert any(
            "dataset_size must be 100K-1M" in err for err in errors
        ), f"Expected dataset_size error, got: {errors}"

    def test_dataset_size_above_1m_raises_error(self):
        """Dataset size > 1M should raise validation error"""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=2000000,  # Above 1M threshold
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig(
                    "postgresql_psycopg3", "localhost", 5433, "benchmark"
                ),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            },
        )

        errors = config.validate()
        assert any(
            "dataset_size must be 100K-1M" in err for err in errors
        ), f"Expected dataset_size error, got: {errors}"

    def test_missing_connection_configs_raises_error(self):
        """Missing connection_configs should raise validation error"""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            connection_configs=None,  # Missing required configs
        )

        errors = config.validate()
        assert any(
            "connection_configs cannot be None" in err for err in errors
        ), f"Expected connection_configs error, got: {errors}"

    def test_missing_required_method_raises_error(self):
        """Missing one of the three required methods should raise error"""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig(
                    "postgresql_psycopg3", "localhost", 5433, "benchmark"
                ),
                # Missing iris_dbapi
            },
        )

        errors = config.validate()
        assert any(
            "Must configure all three methods" in err for err in errors
        ), f"Expected missing method error, got: {errors}"

    def test_invalid_iterations_raises_error(self):
        """Iterations <= 0 should raise validation error"""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            iterations=0,  # Invalid
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig(
                    "postgresql_psycopg3", "localhost", 5433, "benchmark"
                ),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            },
        )

        errors = config.validate()
        assert any(
            "iterations must be > 0" in err for err in errors
        ), f"Expected iterations error, got: {errors}"


class TestConnectionConfigValidation:
    """Contract tests for ConnectionConfig.validate()"""

    def test_valid_connection_config_passes(self):
        """Valid connection config should pass validation"""
        config = ConnectionConfig(
            method_name="iris_pgwire", host="localhost", port=5432, database="USER"
        )

        errors = config.validate()
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_invalid_method_name_raises_error(self):
        """Invalid method_name should raise validation error"""
        config = ConnectionConfig(
            method_name="invalid_method",  # Not in allowed methods
            host="localhost",
            port=5432,
            database="USER",
        )

        errors = config.validate()
        assert any(
            "Invalid method_name" in err for err in errors
        ), f"Expected method_name error, got: {errors}"

    def test_invalid_port_raises_error(self):
        """Port outside 1-65535 range should raise validation error"""
        config = ConnectionConfig(
            method_name="iris_pgwire",
            host="localhost",
            port=99999,  # Out of valid range
            database="USER",
        )

        errors = config.validate()
        assert any(
            "Port must be 1-65535" in err for err in errors
        ), f"Expected port error, got: {errors}"

    def test_negative_timeout_raises_error(self):
        """Negative connection_timeout should raise validation error"""
        config = ConnectionConfig(
            method_name="iris_pgwire",
            host="localhost",
            port=5432,
            database="USER",
            connection_timeout=-1.0,  # Invalid negative timeout
        )

        errors = config.validate()
        assert any(
            "connection_timeout must be > 0" in err for err in errors
        ), f"Expected timeout error, got: {errors}"
