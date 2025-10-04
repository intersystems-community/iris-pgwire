"""
Contract tests for BenchmarkReport JSON/table export (T006).

CRITICAL TDD REQUIREMENT: These tests MUST FAIL before implementation.
Tests validate BenchmarkReport.to_json() and to_table_rows() methods per specs/015-add-3-way/contracts/benchmark_api.py
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from benchmarks.config import BenchmarkConfiguration, BenchmarkReport, MethodResults, ConnectionConfig, CategoryMetrics


class TestBenchmarkReportJSONExport:
    """Contract tests for BenchmarkReport.to_json()"""

    def test_json_structure_matches_specification(self):
        """JSON output should match specification format"""
        # Create minimal benchmark report
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            iterations=1000,
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig("postgresql_psycopg3", "localhost", 5433, "benchmark"),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            }
        )

        method_results = {
            "iris_pgwire": MethodResults(
                method_name="iris_pgwire",
                queries_executed=3000,
                queries_failed=0,
                qps=1234.5,
                latency_p50_ms=8.3,
                latency_p95_ms=12.7,
                latency_p99_ms=15.9,
                by_category={}
            ),
            "postgresql_psycopg3": MethodResults(
                method_name="postgresql_psycopg3",
                queries_executed=3000,
                queries_failed=0,
                qps=2345.6,
                latency_p50_ms=4.2,
                latency_p95_ms=6.8,
                latency_p99_ms=9.1,
                by_category={}
            ),
            "iris_dbapi": MethodResults(
                method_name="iris_dbapi",
                queries_executed=3000,
                queries_failed=0,
                qps=987.3,
                latency_p50_ms=10.1,
                latency_p95_ms=14.5,
                latency_p99_ms=18.3,
                by_category={}
            ),
        }

        report = BenchmarkReport(
            report_id="test_report_001",
            config=config,
            start_time=datetime(2025, 1, 3, 12, 0, 0),
            end_time=datetime(2025, 1, 3, 12, 2, 3),
            total_duration_seconds=123.4,
            method_results=method_results,
            raw_results=[],
            validation_errors=[]
        )

        json_output = report.to_json()

        # Validate JSON structure per spec
        assert "report_id" in json_output, "Missing report_id"
        assert "timestamp" in json_output, "Missing timestamp"
        assert "config" in json_output, "Missing config"
        assert "duration_seconds" in json_output, "Missing duration_seconds"
        assert "results" in json_output, "Missing results"

        # Validate config structure
        assert json_output["config"]["vector_dimensions"] == 1024
        assert json_output["config"]["dataset_size"] == 100000
        assert json_output["config"]["iterations"] == 1000

        # Validate results structure
        assert "iris_pgwire" in json_output["results"]
        assert "postgresql_psycopg3" in json_output["results"]
        assert "iris_dbapi" in json_output["results"]

        # Validate method result fields
        iris_result = json_output["results"]["iris_pgwire"]
        assert "qps" in iris_result
        assert "latency_p50_ms" in iris_result
        assert "latency_p95_ms" in iris_result
        assert "latency_p99_ms" in iris_result
        assert "queries_executed" in iris_result
        assert "queries_failed" in iris_result

    def test_json_contains_all_three_methods(self):
        """JSON output should contain all three database methods"""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig("postgresql_psycopg3", "localhost", 5433, "benchmark"),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            }
        )

        method_results = {
            "iris_pgwire": MethodResults("iris_pgwire", 100, 0, 1234.5, 8.3, 12.7, 15.9, {}),
            "postgresql_psycopg3": MethodResults("postgresql_psycopg3", 100, 0, 2345.6, 4.2, 6.8, 9.1, {}),
            "iris_dbapi": MethodResults("iris_dbapi", 100, 0, 987.3, 10.1, 14.5, 18.3, {}),
        }

        report = BenchmarkReport(
            report_id="test_report_002",
            config=config,
            start_time=datetime.now(),
            end_time=datetime.now(),
            total_duration_seconds=100.0,
            method_results=method_results,
            raw_results=[],
            validation_errors=[]
        )

        json_output = report.to_json()
        assert len(json_output["results"]) == 3, "Should have exactly 3 methods"
        assert "iris_pgwire" in json_output["results"]
        assert "postgresql_psycopg3" in json_output["results"]
        assert "iris_dbapi" in json_output["results"]


class TestBenchmarkReportTableExport:
    """Contract tests for BenchmarkReport.to_table_rows()"""

    def test_table_rows_format_five_columns(self):
        """Table rows should have 5 columns: method, qps, p50, p95, p99"""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig("postgresql_psycopg3", "localhost", 5433, "benchmark"),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            }
        )

        method_results = {
            "iris_pgwire": MethodResults("iris_pgwire", 100, 0, 1234.5, 8.3, 12.7, 15.9, {}),
            "postgresql_psycopg3": MethodResults("postgresql_psycopg3", 100, 0, 2345.6, 4.2, 6.8, 9.1, {}),
            "iris_dbapi": MethodResults("iris_dbapi", 100, 0, 987.3, 10.1, 14.5, 18.3, {}),
        }

        report = BenchmarkReport(
            report_id="test_report_003",
            config=config,
            start_time=datetime.now(),
            end_time=datetime.now(),
            total_duration_seconds=100.0,
            method_results=method_results,
            raw_results=[],
            validation_errors=[]
        )

        table_rows = report.to_table_rows()

        # Validate row structure
        assert len(table_rows) == 3, "Should have 3 rows (one per method)"
        for row in table_rows:
            assert len(row) == 5, f"Each row should have 5 columns, got {len(row)}: {row}"

    def test_table_rows_contain_all_methods(self):
        """Table output should include all three methods"""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig("postgresql_psycopg3", "localhost", 5433, "benchmark"),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            }
        )

        method_results = {
            "iris_pgwire": MethodResults("iris_pgwire", 100, 0, 1234.5, 8.3, 12.7, 15.9, {}),
            "postgresql_psycopg3": MethodResults("postgresql_psycopg3", 100, 0, 2345.6, 4.2, 6.8, 9.1, {}),
            "iris_dbapi": MethodResults("iris_dbapi", 100, 0, 987.3, 10.1, 14.5, 18.3, {}),
        }

        report = BenchmarkReport(
            report_id="test_report_004",
            config=config,
            start_time=datetime.now(),
            end_time=datetime.now(),
            total_duration_seconds=100.0,
            method_results=method_results,
            raw_results=[],
            validation_errors=[]
        )

        table_rows = report.to_table_rows()
        method_names = [row[0] for row in table_rows]

        assert "iris_pgwire" in method_names
        assert "postgresql_psycopg3" in method_names
        assert "iris_dbapi" in method_names

    def test_table_values_formatted_correctly(self):
        """Table values should be formatted as strings with proper precision"""
        config = BenchmarkConfiguration(
            vector_dimensions=1024,
            dataset_size=100000,
            connection_configs={
                "iris_pgwire": ConnectionConfig("iris_pgwire", "localhost", 5432, "USER"),
                "postgresql_psycopg3": ConnectionConfig("postgresql_psycopg3", "localhost", 5433, "benchmark"),
                "iris_dbapi": ConnectionConfig("iris_dbapi", "localhost", 1972, "USER"),
            }
        )

        method_results = {
            "iris_pgwire": MethodResults("iris_pgwire", 100, 0, 1234.567, 8.345, 12.789, 15.912, {}),
        }

        report = BenchmarkReport(
            report_id="test_report_005",
            config=config,
            start_time=datetime.now(),
            end_time=datetime.now(),
            total_duration_seconds=100.0,
            method_results=method_results,
            raw_results=[],
            validation_errors=[]
        )

        table_rows = report.to_table_rows()
        row = table_rows[0]

        # QPS should be formatted with 1 decimal place
        assert "." in row[1], "QPS should be formatted as decimal"

        # Latencies should be formatted with 2 decimal places
        assert "." in row[2], "P50 should be formatted as decimal"
        assert "." in row[3], "P95 should be formatted as decimal"
        assert "." in row[4], "P99 should be formatted as decimal"
