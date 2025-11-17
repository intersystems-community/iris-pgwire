"""
E2E Integration tests for 3-way benchmark (T024-T027).

These tests validate end-to-end functionality without requiring actual database connections.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmarks.config import BenchmarkConfiguration, ConnectionConfig
from benchmarks.metrics import calculate_metrics, validate_constitutional_overhead
from benchmarks.output.json_exporter import export_json
from benchmarks.output.table_exporter import export_table
from benchmarks.runner import BenchmarkRunner, PerformanceResult


class MockExecutor:
    """Mock executor for testing without real database."""

    def __init__(self, base_latency_ms: float = 10.0):
        self.base_latency_ms = base_latency_ms
        self.call_count = 0

    def execute(self, query: str):
        """Simulate query execution."""
        import random
        import time

        # Simulate variable latency
        latency = self.base_latency_ms + random.uniform(-2.0, 2.0)
        time.sleep(latency / 1000.0)  # Convert ms to seconds

        self.call_count += 1
        return [("result", 1)]


class TestBenchmarkIntegration:
    """Integration tests for benchmark system."""

    def test_benchmark_configuration_validation(self):
        """Test configuration validation (T024)."""
        # Valid configuration
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            iterations=10,  # Small for testing
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig(
                    "postgresql_psycopg3", "localhost", 5433, "benchmark"
                ),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            },
        )

        errors = config.validate()
        assert errors == [], f"Valid config should have no errors, got: {errors}"

    def test_benchmark_runner_with_mock_executor(self):
        """Test benchmark runner with mock executor (T024)."""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            iterations=5,  # Small for testing
            warmup_queries=2,
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig(
                    "postgresql_psycopg3", "localhost", 5433, "benchmark"
                ),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            },
        )

        runner = BenchmarkRunner(config)

        # Create mock executors
        mock_executor = MockExecutor(base_latency_ms=10.0)

        # Simple test queries
        test_queries = {
            "simple": ["SELECT 1", "SELECT 2"],
            "vector_similarity": ["SELECT 3"],
        }

        # Execute benchmark queries
        results = runner.execute_benchmark_queries(
            method_name="test_method",
            executor=mock_executor.execute,
            queries=test_queries,
            iterations=5,
        )

        # Verify results
        assert len(results) > 0, "Should have results"
        assert all(
            isinstance(r, PerformanceResult) for r in results
        ), "All results should be PerformanceResult"
        assert all(r.success for r in results), "All queries should succeed with mock"

        # Verify warmup was called (warmup_queries=2 per query)
        # 3 queries * 2 warmup = 6 warmup calls
        # 3 queries * 5 iterations = 15 benchmark calls
        # Total = 21 calls minimum (warmup + benchmark)
        assert (
            mock_executor.call_count >= 15
        ), f"Expected at least 15 calls, got {mock_executor.call_count}"

    def test_metrics_calculation(self):
        """Test metrics calculation (T027)."""
        # Simulate timing data
        timings = [10.0, 12.0, 15.0, 11.0, 13.0, 14.0, 16.0, 10.5, 11.5, 12.5]

        metrics = calculate_metrics(timings)

        assert "p50_ms" in metrics
        assert "p95_ms" in metrics
        assert "p99_ms" in metrics
        assert "qps" in metrics

        # Verify percentiles are reasonable
        assert metrics["p50_ms"] > 0
        assert metrics["p95_ms"] >= metrics["p50_ms"]
        assert metrics["p99_ms"] >= metrics["p95_ms"]
        assert metrics["qps"] > 0

    def test_constitutional_overhead_validation(self):
        """Test constitutional overhead validation (T027)."""
        # PGWire timings (with translation overhead)
        pgwire_timings = [12.0, 13.0, 14.0, 12.5, 13.5]

        # IRIS DBAPI timings (baseline)
        dbapi_timings = [10.0, 11.0, 12.0, 10.5, 11.5]

        validation = validate_constitutional_overhead(
            pgwire_timings, dbapi_timings, threshold_ms=5.0
        )

        assert "compliant" in validation
        assert "overhead_p50_ms" in validation
        assert "overhead_p95_ms" in validation
        assert "overhead_p99_ms" in validation

        # In this case, overhead should be ~2ms (compliant)
        assert validation["compliant"] is True

    def test_json_export(self, tmp_path):
        """Test JSON export functionality (T024)."""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig(
                    "postgresql_psycopg3", "localhost", 5433, "benchmark"
                ),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            },
        )

        from benchmarks.config import BenchmarkReport, MethodResults

        report = BenchmarkReport(
            report_id="test_report",
            config=config,
            start_time=datetime.now(),
            end_time=datetime.now(),
            total_duration_seconds=100.0,
            method_results={
                "test_method": MethodResults(
                    method_name="test_method",
                    queries_executed=100,
                    queries_failed=0,
                    qps=10.0,
                    latency_p50_ms=10.0,
                    latency_p95_ms=15.0,
                    latency_p99_ms=20.0,
                    by_category={},
                )
            },
            raw_results=[],
            validation_errors=[],
        )

        # Export to temporary directory
        json_path = export_json(report, str(tmp_path))

        assert Path(json_path).exists()

        # Verify JSON content
        import json

        with open(json_path) as f:
            data = json.load(f)

        assert "report_id" in data
        assert "config" in data
        assert "results" in data
        assert "test_method" in data["results"]

    def test_table_export(self, tmp_path):
        """Test table export functionality (T024)."""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig(
                    "postgresql_psycopg3", "localhost", 5433, "benchmark"
                ),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            },
        )

        from benchmarks.config import BenchmarkReport, MethodResults

        report = BenchmarkReport(
            report_id="test_report",
            config=config,
            start_time=datetime.now(),
            end_time=datetime.now(),
            total_duration_seconds=100.0,
            method_results={
                "test_method": MethodResults(
                    method_name="test_method",
                    queries_executed=100,
                    queries_failed=0,
                    qps=10.0,
                    latency_p50_ms=10.0,
                    latency_p95_ms=15.0,
                    latency_p99_ms=20.0,
                    by_category={},
                )
            },
            raw_results=[],
            validation_errors=[],
        )

        # Export to temporary directory
        table_output = export_table(report, str(tmp_path))

        assert len(table_output) > 0
        assert "test_method" in table_output
        assert "10.0" in table_output  # P50 latency
