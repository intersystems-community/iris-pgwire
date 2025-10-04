"""
Configuration and data models for 3-way benchmark.

CRITICAL: This is a STUB implementation to make contract tests fail.
These classes will be properly implemented after contract tests are written (TDD).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum


class QueryCategory(Enum):
    """Query complexity categories per FR-002"""
    SIMPLE = "simple"
    VECTOR_SIMILARITY = "vector_similarity"
    COMPLEX_JOIN = "complex_join"


class BenchmarkState(Enum):
    """Benchmark execution states"""
    INITIALIZING = "initializing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPORTED = "exported"


@dataclass
class ConnectionConfig:
    """Connection parameters for a database access method"""
    method_name: str
    host: str
    port: int
    database: str
    username: Optional[str] = None
    password: Optional[str] = None
    connection_timeout: float = 10.0

    def validate(self) -> List[str]:
        """
        Validate configuration parameters.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        valid_methods = ["iris_pgwire", "postgresql_psycopg3", "iris_dbapi"]
        if self.method_name not in valid_methods:
            errors.append(f"Invalid method_name: {self.method_name}")

        if not (1 <= self.port <= 65535):
            errors.append(f"Port must be 1-65535, got {self.port}")

        if self.connection_timeout <= 0:
            errors.append(f"connection_timeout must be > 0, got {self.connection_timeout}")

        return errors


@dataclass
class BenchmarkConfiguration:
    """Configuration for a benchmark run (FR-005)"""
    vector_dimensions: int = 1024
    dataset_size: int = 100000
    iterations: int = 1000
    concurrent_connections: int = 1
    warmup_queries: int = 100
    random_seed: int = 42
    connection_configs: Optional[Dict[str, ConnectionConfig]] = None

    def validate(self) -> List[str]:
        """
        Validate configuration per functional requirements.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # FR-003: Vector dimensions must be positive
        if self.vector_dimensions <= 0:
            errors.append(f"vector_dimensions must be > 0, got {self.vector_dimensions}")

        # Allow smaller datasets for testing (minimum 10 for quick validation)
        if self.dataset_size < 10:
            errors.append(f"dataset_size must be >= 10, got {self.dataset_size}")

        if self.iterations <= 0:
            errors.append(f"iterations must be > 0, got {self.iterations}")

        if self.concurrent_connections <= 0:
            errors.append(f"concurrent_connections must be > 0, got {self.concurrent_connections}")

        # FR-001: Must have all three connection methods
        if self.connection_configs is None:
            errors.append("connection_configs cannot be None")
        else:
            required_methods = {"iris_pgwire", "postgresql_psycopg3", "iris_dbapi"}
            actual_methods = set(self.connection_configs.keys())
            if actual_methods != required_methods:
                errors.append(f"Must configure all three methods: {required_methods}, got {actual_methods}")

            # Validate each connection config
            for method, config in self.connection_configs.items():
                config_errors = config.validate()
                errors.extend([f"{method}: {e}" for e in config_errors])

        return errors


@dataclass
class PerformanceResult:
    """Single query execution result (FR-004)"""
    result_id: str
    method_name: str
    query_id: str
    timestamp: datetime
    elapsed_ms: float
    success: bool
    error_message: Optional[str] = None
    row_count: int = 0
    resource_usage: Optional[Dict] = None

    def validate(self) -> List[str]:
        """
        Validate result integrity.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if self.elapsed_ms < 0:
            errors.append(f"elapsed_ms cannot be negative, got {self.elapsed_ms}")

        if not self.success and self.error_message is None:
            errors.append("error_message required when success is False")

        if self.row_count < 0:
            errors.append(f"row_count cannot be negative, got {self.row_count}")

        return errors


@dataclass
class CategoryMetrics:
    """Performance metrics for a query category"""
    count: int
    qps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


@dataclass
class MethodResults:
    """Aggregated results for one database method (FR-004)"""
    method_name: str
    queries_executed: int
    queries_failed: int
    qps: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    by_category: Dict[str, CategoryMetrics]

    def validate(self) -> List[str]:
        """
        Validate aggregated results.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if self.qps < 0:
            errors.append(f"qps cannot be negative, got {self.qps}")

        for name, value in [("p50", self.latency_p50_ms),
                           ("p95", self.latency_p95_ms),
                           ("p99", self.latency_p99_ms)]:
            if value < 0:
                errors.append(f"{name} cannot be negative, got {value}")

        # FR-002: Must have results for all query categories
        from benchmarks.test_data.query_templates import QueryCategory
        required_categories = {QueryCategory.SIMPLE.value,
                              QueryCategory.VECTOR_SIMILARITY.value,
                              QueryCategory.COMPLEX_JOIN.value}
        actual_categories = set(self.by_category.keys())
        if actual_categories != required_categories:
            errors.append(f"Missing category results: {required_categories - actual_categories}")

        return errors


@dataclass
class BenchmarkReport:
    """Complete benchmark results (FR-007, FR-010)"""
    report_id: str
    config: BenchmarkConfiguration
    start_time: datetime
    end_time: datetime
    total_duration_seconds: float
    method_results: Dict[str, MethodResults]
    raw_results: List[PerformanceResult]
    validation_errors: List[str]
    state: BenchmarkState = BenchmarkState.INITIALIZING

    def to_json(self) -> Dict:
        """
        Export report as JSON (FR-010).

        Returns:
            Dict suitable for json.dumps() - raw metrics only per FR-007
        """
        return {
            "report_id": self.report_id,
            "timestamp": self.start_time.isoformat(),
            "config": {
                "vector_dimensions": self.config.vector_dimensions,
                "dataset_size": self.config.dataset_size,
                "iterations": self.config.iterations,
            },
            "duration_seconds": self.total_duration_seconds,
            "results": {
                method: {
                    "qps": results.qps,
                    "latency_p50_ms": results.latency_p50_ms,
                    "latency_p95_ms": results.latency_p95_ms,
                    "latency_p99_ms": results.latency_p99_ms,
                    "queries_executed": results.queries_executed,
                    "queries_failed": results.queries_failed,
                }
                for method, results in self.method_results.items()
            }
        }

    def to_table_rows(self) -> List[List]:
        """
        Export report as table rows for console display (FR-010).

        Returns:
            List of rows [method_name, qps, p50, p95, p99]
        """
        return [
            [
                results.method_name,
                f"{results.qps:.1f}",
                f"{results.latency_p50_ms:.2f}",
                f"{results.latency_p95_ms:.2f}",
                f"{results.latency_p99_ms:.2f}",
            ]
            for results in self.method_results.values()
        ]
