"""
Performance Benchmarks and Constitutional Validation Tests

Comprehensive performance testing for IRIS SQL translation with constitutional
compliance monitoring, SLA validation, and performance regression detection.

Constitutional Requirements:
- 5ms translation SLA for all query types
- 95% SLA compliance rate
- Real-time performance monitoring
- Memory efficiency under load
- Graceful degradation under stress
"""

import concurrent.futures
import statistics
import time
from dataclasses import dataclass

from iris_pgwire.constitutional import get_governor
from iris_pgwire.sql_translator.performance_monitor import (
    get_constitutional_compliance,
    get_monitor,
)
from iris_pgwire.sql_translator.translator import IRISSQLTranslator, TranslationContext


@dataclass
class BenchmarkResult:
    """Results from a performance benchmark"""

    test_name: str
    query_count: int
    total_time_ms: float
    avg_time_ms: float
    min_time_ms: float
    max_time_ms: float
    p95_time_ms: float
    p99_time_ms: float
    sla_violations: int
    sla_compliance_rate: float
    cache_hit_rate: float
    success_rate: float
    memory_growth_factor: float
    constitutional_compliance: bool


class TestConstitutionalPerformance:
    """Constitutional compliance and SLA validation tests"""

    def setup_method(self):
        """Setup translator and performance monitoring"""
        self.translator = IRISSQLTranslator(enable_debug=True)
        self.monitor = get_monitor()
        self.governor = get_governor()

        # Clear metrics before each test
        self.monitor.clear_metrics()

    def test_constitutional_sla_compliance_simple_queries(self):
        """Test 5ms SLA compliance for simple queries"""
        simple_queries = [
            "SELECT * FROM users",
            "SELECT id, name FROM customers",
            "SELECT COUNT(*) FROM orders",
            "SELECT DISTINCT status FROM products",
            "SELECT name FROM users WHERE id = 123",
        ]

        violations = 0
        times = []

        for sql in simple_queries:
            context = TranslationContext(original_sql=sql)

            start_time = time.perf_counter()
            result = self.translator.translate(context)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            times.append(elapsed_ms)

            # Constitutional requirement: 5ms SLA
            if elapsed_ms > 5.0:
                violations += 1

            assert result.translated_sql is not None
            assert result.performance_stats.is_sla_compliant or elapsed_ms <= 5.0

        # Require 100% compliance for simple queries
        compliance_rate = (len(simple_queries) - violations) / len(simple_queries)
        assert (
            compliance_rate >= 1.0
        ), f"Simple queries must have 100% SLA compliance, got {compliance_rate:.1%}"

        avg_time = statistics.mean(times)
        assert (
            avg_time < 2.0
        ), f"Average time for simple queries should be <2ms, got {avg_time:.2f}ms"

    def test_constitutional_sla_compliance_complex_queries(self):
        """Test 5ms SLA compliance for complex IRIS queries"""
        complex_queries = [
            """
            SELECT TOP 10
                %SQLUPPER(u.name) as name,
                JSON_EXTRACT(u.profile, '$.email') as email,
                COUNT(p.id) as post_count
            FROM users u
            LEFT JOIN posts p ON u.id = p.user_id
            WHERE JSON_EXISTS(u.profile, '$.active')
            GROUP BY u.id, u.name, u.profile
            ORDER BY post_count DESC
            """,
            """
            SELECT
                %SQLLOWER(category) as category,
                JSON_ARRAY_LENGTH(tags) as tag_count,
                AVG(price) as avg_price
            FROM products
            WHERE JSON_EXISTS(metadata, '$.featured')
            GROUP BY category
            HAVING COUNT(*) > 5
            """,
            """
            CREATE TABLE test_vectors (
                id INTEGER,
                name LONGVARCHAR,
                data VARBINARY,
                embedding VECTOR(128),
                created_date DATE
            )
            """,
            """
            SELECT
                %SQLSTRING(description, 100) as short_desc,
                JSON_EXTRACT(config, '$.settings.timeout') as timeout_val
            FROM applications
            WHERE status IN ('active', 'pending')
              AND JSON_EXISTS(config, '$.version')
            """,
        ]

        violations = 0
        times = []

        for sql in complex_queries:
            context = TranslationContext(original_sql=sql)

            start_time = time.perf_counter()
            result = self.translator.translate(context)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            times.append(elapsed_ms)

            if elapsed_ms > 5.0:
                violations += 1

            assert result.translated_sql is not None

        # Require 95% compliance for complex queries (constitutional requirement)
        compliance_rate = (len(complex_queries) - violations) / len(complex_queries)
        assert (
            compliance_rate >= 0.95
        ), f"Complex queries must have ≥95% SLA compliance, got {compliance_rate:.1%}"

    def test_bulk_translation_performance_benchmark(self):
        """Comprehensive bulk translation performance benchmark"""

        # Generate test queries across different complexity levels
        queries = self._generate_benchmark_queries(
            simple=50,  # 50 simple queries
            medium=75,  # 75 medium complexity
            complex=25,  # 25 complex queries
        )

        results = []
        times = []
        violations = 0
        cache_hits = 0
        errors = 0

        start_time = time.perf_counter()

        for i, sql in enumerate(queries):
            context = TranslationContext(original_sql=sql, session_id=f"bench_{i}")

            query_start = time.perf_counter()
            try:
                result = self.translator.translate(context)
                query_time = (time.perf_counter() - query_start) * 1000

                times.append(query_time)
                results.append(result)

                if query_time > 5.0:
                    violations += 1

                if result.performance_stats.cache_hit:
                    cache_hits += 1

            except Exception as e:
                errors += 1
                print(f"Translation error for query {i}: {e}")

        total_time = (time.perf_counter() - start_time) * 1000

        # Calculate performance metrics
        benchmark = BenchmarkResult(
            test_name="bulk_translation_benchmark",
            query_count=len(queries),
            total_time_ms=total_time,
            avg_time_ms=statistics.mean(times) if times else 0,
            min_time_ms=min(times) if times else 0,
            max_time_ms=max(times) if times else 0,
            p95_time_ms=statistics.quantiles(times, n=20)[18] if len(times) >= 20 else 0,
            p99_time_ms=statistics.quantiles(times, n=100)[98] if len(times) >= 100 else 0,
            sla_violations=violations,
            sla_compliance_rate=(len(times) - violations) / len(times) if times else 0,
            cache_hit_rate=cache_hits / len(times) if times else 0,
            success_rate=(len(queries) - errors) / len(queries),
            memory_growth_factor=1.0,  # Would measure actual memory growth
            constitutional_compliance=violations / len(times) <= 0.05 if times else False,
        )

        # Constitutional compliance assertions
        assert (
            benchmark.sla_compliance_rate >= 0.95
        ), f"SLA compliance rate {benchmark.sla_compliance_rate:.1%} below 95% requirement"
        assert (
            benchmark.success_rate >= 0.99
        ), f"Success rate {benchmark.success_rate:.1%} below 99% requirement"
        assert (
            benchmark.avg_time_ms < 3.0
        ), f"Average translation time {benchmark.avg_time_ms:.2f}ms exceeds 3ms target"
        assert (
            benchmark.p95_time_ms <= 5.0
        ), f"P95 translation time {benchmark.p95_time_ms:.2f}ms exceeds 5ms SLA"

        # Print benchmark results for analysis
        print("\n📊 Bulk Translation Benchmark Results:")
        print(f"  Queries processed: {benchmark.query_count}")
        print(f"  Total time: {benchmark.total_time_ms:.2f}ms")
        print(f"  Average time: {benchmark.avg_time_ms:.2f}ms")
        print(f"  P95 time: {benchmark.p95_time_ms:.2f}ms")
        print(f"  P99 time: {benchmark.p99_time_ms:.2f}ms")
        print(f"  SLA violations: {benchmark.sla_violations}")
        print(f"  SLA compliance: {benchmark.sla_compliance_rate:.1%}")
        print(f"  Cache hit rate: {benchmark.cache_hit_rate:.1%}")
        print(f"  Success rate: {benchmark.success_rate:.1%}")
        print(
            f"  Constitutional compliance: {'✅ PASS' if benchmark.constitutional_compliance else '❌ FAIL'}"
        )

    def test_concurrent_translation_performance(self):
        """Test performance under concurrent load"""

        def translate_queries(query_batch: list[str], thread_id: int) -> list[float]:
            """Translate a batch of queries and return timing results"""
            times = []
            for i, sql in enumerate(query_batch):
                context = TranslationContext(
                    original_sql=sql, session_id=f"thread_{thread_id}_query_{i}"
                )

                start = time.perf_counter()
                result = self.translator.translate(context)
                elapsed = (time.perf_counter() - start) * 1000

                times.append(elapsed)
                assert result.translated_sql is not None

            return times

        # Generate queries for concurrent execution
        queries_per_thread = 10
        num_threads = 5
        total_queries = queries_per_thread * num_threads

        all_queries = self._generate_benchmark_queries(
            simple=int(total_queries * 0.6),
            medium=int(total_queries * 0.3),
            complex=int(total_queries * 0.1),
        )

        # Split queries among threads
        query_batches = [all_queries[i::num_threads] for i in range(num_threads)]

        start_time = time.perf_counter()

        # Execute concurrent translations
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(translate_queries, batch, thread_id)
                for thread_id, batch in enumerate(query_batches)
            ]

            all_times = []
            for future in concurrent.futures.as_completed(futures):
                thread_times = future.result()
                all_times.extend(thread_times)

        total_time = (time.perf_counter() - start_time) * 1000

        # Analyze concurrent performance
        violations = sum(1 for t in all_times if t > 5.0)
        compliance_rate = (len(all_times) - violations) / len(all_times)
        avg_time = statistics.mean(all_times)

        # Concurrent performance should maintain reasonable compliance (thread contention expected)
        assert (
            compliance_rate >= 0.80
        ), f"Concurrent SLA compliance {compliance_rate:.1%} below 80% minimum"
        assert (
            avg_time < 6.0
        ), f"Concurrent average time {avg_time:.2f}ms exceeds 6ms (allowing for thread contention)"

        print("\n🔄 Concurrent Translation Performance:")
        print(f"  Threads: {num_threads}")
        print(f"  Queries per thread: {queries_per_thread}")
        print(f"  Total queries: {len(all_times)}")
        print(f"  Total time: {total_time:.2f}ms")
        print(f"  Average time: {avg_time:.2f}ms")
        print(f"  SLA violations: {violations}")
        print(f"  Compliance rate: {compliance_rate:.1%}")

    def test_memory_efficiency_benchmark(self):
        """Test memory efficiency under sustained load"""
        try:
            import os

            import psutil

            has_psutil = True
        except ImportError:
            has_psutil = False

        if has_psutil:
            process = psutil.Process(os.getpid())
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        else:
            initial_memory = 0.0  # Fallback for systems without psutil

        # Run sustained load for memory testing
        num_iterations = 200
        queries = self._generate_benchmark_queries(simple=50, medium=30, complex=20)

        memory_samples = [initial_memory]

        for iteration in range(num_iterations):
            # Process a batch of queries
            for sql in queries:
                context = TranslationContext(
                    original_sql=sql, session_id=f"memory_test_{iteration}"
                )
                result = self.translator.translate(context)
                assert result.translated_sql is not None

            # Sample memory usage every 10 iterations
            if iteration % 10 == 0 and has_psutil:
                current_memory = process.memory_info().rss / 1024 / 1024
                memory_samples.append(current_memory)

        if has_psutil:
            final_memory = process.memory_info().rss / 1024 / 1024
        else:
            final_memory = 0.0
        memory_growth = final_memory - initial_memory
        if has_psutil and initial_memory > 0:
            growth_percentage = (memory_growth / initial_memory) * 100
        else:
            growth_percentage = 0.0

        print("\n💾 Memory Efficiency Benchmark:")
        if has_psutil:
            print(f"  Initial memory: {initial_memory:.2f} MB")
            print(f"  Final memory: {final_memory:.2f} MB")
            print(f"  Memory growth: {memory_growth:.2f} MB ({growth_percentage:.1f}%)")
        else:
            print("  Memory monitoring: N/A (psutil not available)")
        print(f"  Queries processed: {num_iterations * len(queries)}")

        # Memory growth should be reasonable (< 50% increase) - only if psutil available
        if has_psutil and initial_memory > 0:
            assert (
                growth_percentage < 50.0
            ), f"Memory growth {growth_percentage:.1f}% exceeds 50% limit"

    def test_translation_cache_performance(self):
        """Test cache performance and hit rates"""

        # Test queries that should benefit from caching
        cache_test_queries = [
            "SELECT * FROM users WHERE id = 1",
            "SELECT %SQLUPPER(name) FROM customers",
            "SELECT JSON_EXTRACT(data, '$.email') FROM profiles",
            "SELECT TOP 10 * FROM products ORDER BY price",
        ]

        cache_hits = 0
        total_translations = 0
        times_with_cache = []
        times_without_cache = []

        # First pass - populate cache
        for sql in cache_test_queries * 3:  # Run each query 3 times
            context = TranslationContext(original_sql=sql)

            start = time.perf_counter()
            result = self.translator.translate(context)
            elapsed = (time.perf_counter() - start) * 1000

            if result.performance_stats.cache_hit:
                cache_hits += 1
                times_with_cache.append(elapsed)
            else:
                times_without_cache.append(elapsed)

            total_translations += 1
            assert result.translated_sql is not None

        cache_hit_rate = cache_hits / total_translations
        avg_cache_time = statistics.mean(times_with_cache) if times_with_cache else 0
        avg_nocache_time = statistics.mean(times_without_cache) if times_without_cache else 0

        print("\n🗄️ Cache Performance Analysis:")
        print(f"  Cache hit rate: {cache_hit_rate:.1%}")
        print(f"  Average cache hit time: {avg_cache_time:.2f}ms")
        print(f"  Average cache miss time: {avg_nocache_time:.2f}ms")
        if times_with_cache and times_without_cache:
            speedup = avg_nocache_time / avg_cache_time
            print(f"  Cache speedup: {speedup:.1f}x")

        # Cache should provide significant performance benefit
        assert cache_hit_rate >= 0.60, f"Cache hit rate {cache_hit_rate:.1%} below 60% target"
        if times_with_cache and times_without_cache:
            assert avg_cache_time < avg_nocache_time, "Cache hits should be faster than misses"

    def test_constitutional_compliance_report(self):
        """Generate and validate constitutional compliance report"""

        # Run a variety of translations to populate metrics
        test_queries = self._generate_benchmark_queries(simple=20, medium=15, complex=10)

        for sql in test_queries:
            context = TranslationContext(original_sql=sql)
            result = self.translator.translate(context)
            assert result.translated_sql is not None

        # Get constitutional compliance report
        compliance_report = get_constitutional_compliance()
        translator_stats = self.translator.get_translation_stats()

        print("\n📋 Constitutional Compliance Report:")
        print(
            f"  Overall compliance: {'✅ COMPLIANT' if compliance_report.overall_compliance_rate >= 0.95 else '❌ NON-COMPLIANT'}"
        )
        print(f"  Overall compliance rate: {compliance_report.overall_compliance_rate:.1%}")
        print(f"  SLA compliance rate: {translator_stats['sla_compliance_rate']:.1%}")
        print(
            f"  Average translation time: {translator_stats['average_translation_time_ms']:.2f}ms"
        )
        print(f"  Total translations: {translator_stats['total_translations']}")
        print(f"  SLA violations: {translator_stats['sla_violations']}")
        print(f"  Cache hit rate: {translator_stats['cache_hit_rate']:.1%}")

        # Constitutional requirements
        assert translator_stats["sla_compliance_rate"] >= 0.95, "SLA compliance must be ≥95%"
        assert translator_stats["average_translation_time_ms"] <= 5.0, "Average time must be ≤5ms"
        assert (
            compliance_report.overall_compliance_rate >= 0.95
        ), "Overall constitutional compliance must be ≥95%"

    def _generate_benchmark_queries(
        self, simple: int = 10, medium: int = 10, complex: int = 10
    ) -> list[str]:
        """Generate a mix of queries for benchmarking"""
        queries = []

        # Simple queries
        for i in range(simple):
            simple_templates = [
                f"SELECT * FROM table_{i % 5}",
                f"SELECT id, name FROM users WHERE id = {i}",
                f"SELECT COUNT(*) FROM orders_{i % 3}",
                f"SELECT DISTINCT status FROM products_{i % 4}",
                f"INSERT INTO logs (message) VALUES ('test_{i}')",
            ]
            queries.append(simple_templates[i % len(simple_templates)])

        # Medium complexity queries
        for i in range(medium):
            medium_templates = [
                f"SELECT %SQLUPPER(name) FROM users_{i % 3} WHERE active = 1",
                f"SELECT TOP {(i % 10) + 1} * FROM products ORDER BY price DESC",
                f"SELECT JSON_EXTRACT(data, '$.field_{i}') FROM documents WHERE id > {i}",
                f"CREATE TABLE temp_{i} (id INTEGER, name LONGVARCHAR, data VARBINARY)",
                f"SELECT %SQLLOWER(category) FROM items_{i % 2} GROUP BY category",
            ]
            queries.append(medium_templates[i % len(medium_templates)])

        # Complex queries
        for i in range(complex):
            complex_templates = [
                f"""
                SELECT TOP {(i % 5) + 1}
                    %SQLUPPER(u.name) as name,
                    JSON_EXTRACT(u.profile, '$.email_{i}') as email,
                    COUNT(p.id) as count
                FROM users_{i % 2} u
                LEFT JOIN posts p ON u.id = p.user_id
                WHERE JSON_EXISTS(u.profile, '$.active')
                GROUP BY u.id, u.name, u.profile
                ORDER BY count DESC
                """,
                f"""
                SELECT
                    %SQLSTRING(description, {(i % 50) + 50}) as desc,
                    JSON_ARRAY_LENGTH(tags) as tag_count,
                    AVG(price) as avg_price
                FROM products_{i % 3}
                WHERE JSON_EXISTS(metadata, '$.category_{i}')
                GROUP BY description
                HAVING COUNT(*) > {i % 3 + 1}
                """,
                f"""
                CREATE TABLE vectors_{i} (
                    id INTEGER,
                    name LONGVARCHAR,
                    embedding VECTOR({(i % 5 + 1) * 32}),
                    metadata JSON,
                    created_date DATE
                )
                """,
            ]
            queries.append(complex_templates[i % len(complex_templates)])

        return queries


class TestRegressionDetection:
    """Performance regression detection tests"""

    def setup_method(self):
        """Setup for regression testing"""
        self.translator = IRISSQLTranslator()

    def test_baseline_performance_regression(self):
        """Detect performance regressions against baseline metrics"""

        # Known baseline performance targets (in milliseconds)
        baselines = {
            "simple_query": 1.0,  # Simple SELECT should be <1ms
            "function_translation": 2.0,  # Function translation should be <2ms
            "json_operation": 3.0,  # JSON operations should be <3ms
            "complex_mixed": 4.0,  # Complex mixed queries should be <4ms
            "ddl_statement": 2.5,  # DDL statements should be <2.5ms
        }

        test_cases = {
            "simple_query": "SELECT * FROM users WHERE id = 123",
            "function_translation": "SELECT %SQLUPPER(name), %SQLLOWER(email) FROM customers",
            "json_operation": "SELECT JSON_EXTRACT(data, '$.user.profile'), JSON_ARRAY_LENGTH(tags) FROM docs",
            "complex_mixed": """
                SELECT TOP 5
                    %SQLUPPER(u.name) as name,
                    JSON_EXTRACT(u.profile, '$.bio') as bio,
                    COUNT(*) as post_count
                FROM users u
                INNER JOIN posts p ON u.id = p.user_id
                WHERE u.status = 'active'
                  AND JSON_EXISTS(u.profile, '$.verified')
                GROUP BY u.id, u.name, u.created_date, u.profile
                ORDER BY post_count DESC
            """,
            "ddl_statement": "CREATE TABLE test (id INTEGER, name LONGVARCHAR, data VARBINARY, embedding VECTOR(128))",
        }

        regressions = []

        for test_name, sql in test_cases.items():
            baseline = baselines[test_name]

            # Run test multiple times for accurate measurement
            times = []
            for _ in range(5):
                context = TranslationContext(original_sql=sql)

                start = time.perf_counter()
                result = self.translator.translate(context)
                elapsed = (time.perf_counter() - start) * 1000

                times.append(elapsed)
                assert result.translated_sql is not None

            avg_time = statistics.mean(times)

            if avg_time > baseline:
                regressions.append(
                    {
                        "test": test_name,
                        "baseline": baseline,
                        "actual": avg_time,
                        "regression": avg_time - baseline,
                    }
                )

        # Report any regressions found
        if regressions:
            print("\n⚠️ Performance Regressions Detected:")
            for reg in regressions:
                print(
                    f"  {reg['test']}: {reg['actual']:.2f}ms (baseline: {reg['baseline']:.2f}ms, +{reg['regression']:.2f}ms)"
                )
        else:
            print("\n✅ No Performance Regressions Detected")

        # Fail test if significant regressions found
        significant_regressions = [
            r for r in regressions if r["regression"] > 1.0
        ]  # >1ms regression
        assert (
            len(significant_regressions) == 0
        ), f"Significant performance regressions detected: {significant_regressions}"

    def test_stress_load_performance(self):
        """Test performance under stress load conditions"""

        # Generate high-volume stress test
        stress_queries = []

        # Generate 500 varied queries for stress testing
        for i in range(500):
            query_types = [
                f"SELECT * FROM stress_test_{i % 10}",
                f"SELECT %SQLUPPER(col_{i % 20}) FROM table_{i % 5}",
                f"SELECT JSON_EXTRACT(data, '$.field_{i}') FROM docs_{i % 8}",
                f"SELECT TOP {(i % 10) + 1} * FROM products_{i % 3} ORDER BY id",
                f"CREATE TABLE temp_{i} (id INTEGER, data LONGVARCHAR)",
            ]
            stress_queries.append(query_types[i % len(query_types)])

        start_time = time.perf_counter()
        violations = 0
        errors = 0

        for i, sql in enumerate(stress_queries):
            try:
                context = TranslationContext(original_sql=sql, session_id=f"stress_{i}")

                query_start = time.perf_counter()
                result = self.translator.translate(context)
                query_time = (time.perf_counter() - query_start) * 1000

                if query_time > 5.0:
                    violations += 1

                assert result.translated_sql is not None

            except Exception:
                errors += 1
                if errors > 5:  # Stop if too many errors
                    break

        total_time = (time.perf_counter() - start_time) * 1000
        processed = len(stress_queries) - errors
        compliance_rate = (processed - violations) / processed if processed > 0 else 0

        print("\n🔥 Stress Load Performance:")
        print(f"  Queries processed: {processed}/{len(stress_queries)}")
        print(f"  Total time: {total_time:.2f}ms")
        print(f"  Average time: {total_time/processed:.2f}ms")
        print(f"  SLA violations: {violations}")
        print(f"  Error rate: {errors/len(stress_queries):.1%}")
        print(f"  Compliance rate: {compliance_rate:.1%}")

        # Stress test requirements
        assert (
            errors / len(stress_queries) < 0.01
        ), f"Error rate {errors/len(stress_queries):.1%} exceeds 1% limit"
        assert (
            compliance_rate >= 0.85
        ), f"Stress SLA compliance {compliance_rate:.1%} below 85% minimum"
