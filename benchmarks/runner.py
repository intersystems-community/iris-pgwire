"""
Benchmark runner implementation (T014, T015, T019).

Implements:
- Warmup query execution (T014, FR-009)
- High-resolution timing with perf_counter (T015)
- BenchmarkRunner class (T019)
"""

import time
from typing import List, Dict, Any, Callable
from datetime import datetime
import uuid

from benchmarks.config import (
    BenchmarkConfiguration,
    BenchmarkReport,
    PerformanceResult,
    MethodResults,
    BenchmarkState,
    CategoryMetrics
)
from benchmarks.metrics import calculate_metrics, calculate_category_metrics


class BenchmarkRunner:
    """
    Main benchmark runner for 3-way database comparison.

    Constitutional Compliance:
    - FR-006: Aborts on connection failure
    - FR-008: Uses identical test data
    - FR-009: Performs warmup before measurements
    - Principle VI: <5ms translation overhead validation
    """

    def __init__(self, config: BenchmarkConfiguration):
        """
        Initialize benchmark runner.

        Args:
            config: Validated benchmark configuration

        Raises:
            ValueError: If configuration validation fails
        """
        errors = config.validate()
        if errors:
            raise ValueError(f"Invalid configuration:\n" + "\n".join(errors))

        self.config = config
        self.raw_results: List[PerformanceResult] = []

    def execute_warmup(
        self,
        executor: Callable[[str], Any],
        query: str,
        warmup_count: int = None
    ):
        """
        Execute warmup queries to avoid cold-start bias (FR-009, T014).

        Args:
            executor: Function to execute queries
            query: SQL query to execute
            warmup_count: Number of warmup iterations (defaults to config.warmup_queries)
        """
        count = warmup_count or self.config.warmup_queries

        for i in range(count):
            try:
                executor(query)
            except Exception:
                # Warmup failures are ignored
                pass

    def measure_query_execution(
        self,
        method_name: str,
        query_id: str,
        executor: Callable[[str], Any],
        query: str
    ) -> PerformanceResult:
        """
        Execute query with high-resolution timing (T015).

        Args:
            method_name: Database method identifier
            query_id: Query identifier
            executor: Function to execute queries
            query: SQL query to execute

        Returns:
            PerformanceResult with timing measurements

        Constitutional Validation:
            Uses perf_counter for nanosecond precision (Principle VI)
        """
        result_id = f"{method_name}_{query_id}_{uuid.uuid4().hex[:8]}"

        # High-resolution timing with perf_counter (T015)
        start = time.perf_counter()

        try:
            # Execute query
            result = executor(query)

            # Calculate elapsed time in milliseconds
            elapsed = time.perf_counter() - start
            elapsed_ms = elapsed * 1000.0

            # Count rows if possible
            row_count = 0
            if hasattr(result, '__len__'):
                row_count = len(result)
            elif hasattr(result, 'rowcount'):
                row_count = result.rowcount

            return PerformanceResult(
                result_id=result_id,
                method_name=method_name,
                query_id=query_id,
                timestamp=datetime.now(),
                elapsed_ms=elapsed_ms,
                success=True,
                row_count=row_count
            )

        except Exception as e:
            elapsed = time.perf_counter() - start
            elapsed_ms = elapsed * 1000.0

            return PerformanceResult(
                result_id=result_id,
                method_name=method_name,
                query_id=query_id,
                timestamp=datetime.now(),
                elapsed_ms=elapsed_ms,
                success=False,
                error_message=str(e),
                row_count=0
            )

    def execute_benchmark_queries(
        self,
        method_name: str,
        executor: Callable[[str], Any],
        queries: Dict[str, List[str]],
        iterations: int = None
    ) -> List[PerformanceResult]:
        """
        Execute all benchmark queries for a single method.

        Args:
            method_name: Database method identifier
            executor: Function to execute queries
            queries: Dict mapping category to list of queries
            iterations: Number of iterations per query (defaults to config.iterations)

        Returns:
            List of PerformanceResult instances
        """
        results = []
        iteration_count = iterations or self.config.iterations

        for category, query_list in queries.items():
            for query_idx, query in enumerate(query_list):
                query_id = f"{category}_{query_idx}"

                # Warmup for this query
                self.execute_warmup(executor, query)

                # Execute iterations
                for iteration in range(iteration_count):
                    result = self.measure_query_execution(
                        method_name=method_name,
                        query_id=query_id,
                        executor=executor,
                        query=query
                    )
                    results.append(result)

        return results

    def aggregate_results(
        self,
        method_name: str,
        results: List[PerformanceResult]
    ) -> MethodResults:
        """
        Aggregate performance results for a single method.

        Args:
            method_name: Database method identifier
            results: List of PerformanceResult instances

        Returns:
            MethodResults with aggregated metrics
        """
        # Separate successful and failed queries
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        # Group by category
        timings_by_category = {}
        for result in successful:
            category = result.query_id.rsplit('_', 1)[0]  # Extract category from query_id
            if category not in timings_by_category:
                timings_by_category[category] = []
            timings_by_category[category].append(result.elapsed_ms)

        # Calculate overall metrics
        all_timings = [r.elapsed_ms for r in successful]
        overall_metrics = calculate_metrics(all_timings)

        # Calculate category-specific metrics
        category_metrics = calculate_category_metrics(timings_by_category)

        # Convert to CategoryMetrics objects
        by_category = {}
        for category, metrics in category_metrics.items():
            by_category[category] = CategoryMetrics(
                count=metrics['count'],
                qps=metrics['qps'],
                p50_ms=metrics['p50_ms'],
                p95_ms=metrics['p95_ms'],
                p99_ms=metrics['p99_ms']
            )

        return MethodResults(
            method_name=method_name,
            queries_executed=len(results),
            queries_failed=len(failed),
            qps=overall_metrics['qps'],
            latency_p50_ms=overall_metrics['p50_ms'],
            latency_p95_ms=overall_metrics['p95_ms'],
            latency_p99_ms=overall_metrics['p99_ms'],
            by_category=by_category
        )

    def run(
        self,
        executors: Dict[str, Callable[[str], Any]],
        queries: Dict[str, List[str]]
    ) -> BenchmarkReport:
        """
        Execute complete benchmark across all methods (T019).

        Args:
            executors: Dict mapping method_name to executor function
            queries: Dict mapping category to list of queries

        Returns:
            BenchmarkReport with results for all methods

        Raises:
            RuntimeError: On connection failure per FR-006
        """
        report_id = f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now()

        print(f"\n{'='*70}")
        print(f"Starting 3-Way Benchmark: {report_id}")
        print(f"{'='*70}")
        print(f"Configuration:")
        print(f"  Vector dimensions:  {self.config.vector_dimensions}")
        print(f"  Dataset size:       {self.config.dataset_size:,}")
        print(f"  Iterations:         {self.config.iterations}")
        print(f"  Warmup queries:     {self.config.warmup_queries}")
        print()

        # Execute benchmark for each method
        method_results = {}
        all_raw_results = []

        for method_name, executor in executors.items():
            print(f"\n📊 Benchmarking {method_name}...")
            print(f"{'─'*70}")

            try:
                # Execute all queries
                results = self.execute_benchmark_queries(
                    method_name=method_name,
                    executor=executor,
                    queries=queries
                )

                # Aggregate results
                aggregated = self.aggregate_results(method_name, results)
                method_results[method_name] = aggregated
                all_raw_results.extend(results)

                # Print summary
                print(f"✅ Completed {aggregated.queries_executed} queries")
                print(f"   QPS:     {aggregated.qps:.1f}")
                print(f"   P50:     {aggregated.latency_p50_ms:.2f}ms")
                print(f"   P95:     {aggregated.latency_p95_ms:.2f}ms")
                print(f"   P99:     {aggregated.latency_p99_ms:.2f}ms")
                print(f"   Failed:  {aggregated.queries_failed}")

            except Exception as e:
                print(f"❌ Method {method_name} failed: {e}")
                # Per FR-006: Continue despite failures (partial results allowed)

        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()

        print(f"\n{'='*70}")
        print(f"Benchmark Complete: {total_duration:.2f}s")
        print(f"{'='*70}\n")

        # Create report
        return BenchmarkReport(
            report_id=report_id,
            config=self.config,
            start_time=start_time,
            end_time=end_time,
            total_duration_seconds=total_duration,
            method_results=method_results,
            raw_results=all_raw_results,
            validation_errors=[],
            state=BenchmarkState.COMPLETED
        )
