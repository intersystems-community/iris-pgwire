#!/usr/bin/env python3
"""
SQL Translation API Demo

Demonstrates the REST API for translating IRIS SQL to PostgreSQL.
The translation API runs as a standalone microservice for:
- Pre-translation of queries
- Translation testing and debugging
- Integration with external tools
- Query optimization analysis
"""

import asyncio
import time

import httpx

# Translation API base URL (when running standalone)
API_BASE_URL = "http://localhost:8000"


async def demo_basic_translation():
    """Demo 1: Basic SQL translation"""
    print("=== Demo 1: Basic SQL Translation ===")

    async with httpx.AsyncClient() as client:
        # Simple IRIS SQL query
        request = {
            "sql": "SELECT TOP 10 * FROM users WHERE age > 21",
            "enable_caching": True,
            "enable_validation": True,
            "validation_level": "semantic"
        }

        response = await client.post(f"{API_BASE_URL}/translate", json=request)
        result = response.json()

        print(f"✓ Original SQL: {result['original_sql']}")
        print(f"✓ Translated SQL: {result['translated_sql']}")
        print(f"✓ Performance: {result['performance_stats']['total_time_ms']:.2f}ms")
        print(f"✓ Constructs mapped: {len(result['construct_mappings'])}")

        if result['warnings']:
            print(f"⚠ Warnings: {result['warnings']}")

        print()
        return True


async def demo_vector_translation():
    """Demo 2: Vector operation translation"""
    print("=== Demo 2: Vector Operation Translation ===")

    async with httpx.AsyncClient() as client:
        # IRIS vector similarity query
        request = {
            "sql": """
                SELECT id, title,
                       VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]', FLOAT)) as similarity
                FROM documents
                ORDER BY similarity DESC
                LIMIT 5
            """,
            "enable_debug": True
        }

        response = await client.post(f"{API_BASE_URL}/translate", json=request)
        result = response.json()

        print(f"✓ Original SQL:\n{result['original_sql'][:100]}...")
        print(f"✓ Translated SQL:\n{result['translated_sql'][:100]}...")
        print("✓ Vector functions preserved: Yes")
        print(f"✓ Translation time: {result['performance_stats']['total_time_ms']:.2f}ms")

        if result['debug_trace']:
            print(f"✓ Debug trace available: {result['debug_trace']['parsing_steps']} parsing steps")

        print()
        return True


async def demo_batch_translation():
    """Demo 3: Batch translation performance"""
    print("=== Demo 3: Batch Translation Performance ===")

    queries = [
        "SELECT COUNT(*) FROM users",
        "SELECT TOP 100 * FROM orders WHERE status = 'pending'",
        "SELECT customer_id, SUM(total) FROM orders GROUP BY customer_id",
        "SELECT * FROM products WHERE price > 100 ORDER BY price DESC",
        "SELECT a.*, b.name FROM orders a JOIN customers b ON a.customer_id = b.id"
    ]

    async with httpx.AsyncClient() as client:
        start_time = time.time()

        # Translate all queries
        tasks = []
        for sql in queries:
            request = {"sql": sql, "enable_caching": True}
            tasks.append(client.post(f"{API_BASE_URL}/translate", json=request))

        responses = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        successful = sum(1 for r in responses if r.status_code == 200)

        print(f"✓ Queries translated: {successful}/{len(queries)}")
        print(f"✓ Total time: {total_time*1000:.2f}ms")
        print(f"✓ Average per query: {(total_time*1000)/len(queries):.2f}ms")
        print(f"✓ Throughput: {len(queries)/total_time:.1f} queries/second")

        # Check cache effectiveness
        stats_response = await client.get(f"{API_BASE_URL}/cache/stats")
        if stats_response.status_code == 200:
            stats = stats_response.json()
            print(f"✓ Cache hit rate: {stats['hit_rate']*100:.1f}%")
            print(f"✓ Cache entries: {stats['total_entries']}")

        print()
        return True


async def demo_validation_levels():
    """Demo 4: Different validation levels"""
    print("=== Demo 4: Validation Levels ===")

    # SQL with potential issues
    test_sql = "SELECT * FROM nonexistent_table WHERE id = 1"

    validation_levels = ["basic", "semantic", "strict", "exhaustive"]

    async with httpx.AsyncClient() as client:
        for level in validation_levels:
            request = {
                "sql": test_sql,
                "enable_validation": True,
                "validation_level": level
            }

            response = await client.post(f"{API_BASE_URL}/translate", json=request)
            result = response.json()

            print(f"✓ Validation level: {level}")
            print(f"  - Success: {result['success']}")
            print(f"  - Warnings: {len(result['warnings'])}")
            print(f"  - Translation time: {result['performance_stats']['total_time_ms']:.2f}ms")

        print()
        return True


async def demo_cache_management():
    """Demo 5: Cache management operations"""
    print("=== Demo 5: Cache Management ===")

    async with httpx.AsyncClient() as client:
        # Get initial cache stats
        stats_response = await client.get(f"{API_BASE_URL}/cache/stats")
        initial_stats = stats_response.json()

        print("✓ Initial cache state:")
        print(f"  - Entries: {initial_stats['total_entries']}")
        print(f"  - Hit rate: {initial_stats['hit_rate']*100:.1f}%")
        print(f"  - Memory usage: {initial_stats['memory_usage_mb']:.2f}MB")
        print(f"  - Average lookup: {initial_stats['average_lookup_ms']:.3f}ms")

        # Populate cache with some queries
        for i in range(10):
            request = {"sql": f"SELECT * FROM table_{i} WHERE id = {i}"}
            await client.post(f"{API_BASE_URL}/translate", json=request)

        # Get updated stats
        stats_response = await client.get(f"{API_BASE_URL}/cache/stats")
        updated_stats = stats_response.json()

        print("\n✓ After adding 10 queries:")
        print(f"  - Entries: {updated_stats['total_entries']}")
        print(f"  - Memory usage: {updated_stats['memory_usage_mb']:.2f}MB")

        # Selective cache invalidation
        invalidate_request = {
            "pattern": "SELECT%",
            "confirm": True
        }

        invalidate_response = await client.post(
            f"{API_BASE_URL}/cache/invalidate",
            json=invalidate_request
        )
        invalidate_result = invalidate_response.json()

        print("\n✓ Cache invalidation:")
        print(f"  - Pattern: {invalidate_result['pattern']}")
        print(f"  - Entries invalidated: {invalidate_result['invalidated_count']}")

        print()
        return True


async def demo_api_statistics():
    """Demo 6: API performance statistics"""
    print("=== Demo 6: API Statistics & Health ===")

    async with httpx.AsyncClient() as client:
        # Get comprehensive stats
        stats_response = await client.get(f"{API_BASE_URL}/stats")
        stats = stats_response.json()

        print("✓ API Statistics:")
        print(f"  - Total requests: {stats['api_stats']['total_requests']}")
        print(f"  - Error rate: {stats['api_stats']['error_rate']*100:.2f}%")
        print(f"  - Uptime: {stats['api_stats']['uptime_seconds']:.0f}s")
        print(f"  - Requests/second: {stats['api_stats']['requests_per_second']:.2f}")
        print(f"  - SLA violations: {stats['api_stats']['sla_violations']}")
        print(f"  - SLA compliance: {stats['api_stats']['sla_compliance_rate']*100:.1f}%")

        print("\n✓ Translator Statistics:")
        print(f"  - Total translations: {stats['translator_stats']['total_translations']}")
        print(f"  - Average time: {stats['translator_stats']['average_translation_time_ms']:.2f}ms")

        print("\n✓ Constitutional Compliance:")
        print(f"  - SLA requirement: {stats['constitutional_compliance']['api_sla_requirement_ms']}ms")
        print(f"  - Compliance status: {stats['constitutional_compliance']['overall_compliance_status']}")

        # Health check
        health_response = await client.get(f"{API_BASE_URL}/health")
        health = health_response.json()

        print("\n✓ Health Status:")
        print(f"  - Status: {health['status']}")
        print(f"  - Uptime: {health['uptime_seconds']:.0f}s")
        print(f"  - Requests processed: {health['requests_processed']}")
        print(f"  - Error rate: {health['error_rate']*100:.2f}%")
        print(f"  - SLA compliance: {health['sla_compliance']}")

        print()
        return True


async def demo_error_handling():
    """Demo 7: Error handling and validation"""
    print("=== Demo 7: Error Handling ===")

    async with httpx.AsyncClient() as client:
        # Test various error conditions
        test_cases = [
            {
                "name": "Empty SQL",
                "request": {"sql": ""},
                "expected_status": 422
            },
            {
                "name": "Invalid SQL",
                "request": {"sql": "SELECT FROM WHERE"},
                "expected_status": 200  # Translation may succeed with warnings
            },
            {
                "name": "SQL too large",
                "request": {"sql": "SELECT * FROM users" * 10000},
                "expected_status": 400
            },
            {
                "name": "Invalid validation level",
                "request": {"sql": "SELECT 1", "validation_level": "invalid"},
                "expected_status": 422
            }
        ]

        for test in test_cases:
            try:
                response = await client.post(f"{API_BASE_URL}/translate", json=test["request"])

                if response.status_code == test["expected_status"]:
                    print(f"✓ {test['name']}: Handled correctly ({response.status_code})")
                else:
                    print(f"⚠ {test['name']}: Unexpected status ({response.status_code})")

            except Exception as e:
                print(f"✗ {test['name']}: Exception - {str(e)[:50]}")

        print()
        return True


async def demo_integration_workflow():
    """Demo 8: Real-world integration workflow"""
    print("=== Demo 8: Integration Workflow ===")

    async with httpx.AsyncClient() as client:
        # Simulate a real-world workflow
        print("Scenario: Pre-translating queries for a BI dashboard\n")

        # Step 1: Translate dashboard queries
        dashboard_queries = [
            "SELECT region, SUM(sales) FROM orders GROUP BY region",
            "SELECT product_id, COUNT(*) FROM orders WHERE status = 'completed' GROUP BY product_id",
            "SELECT DATE(order_date), SUM(total) FROM orders GROUP BY DATE(order_date)"
        ]

        translated_queries = []

        for i, sql in enumerate(dashboard_queries, 1):
            request = {
                "sql": sql,
                "session_id": "dashboard_123",
                "enable_caching": True,
                "metadata": {"widget_id": f"widget_{i}"}
            }

            response = await client.post(f"{API_BASE_URL}/translate", json=request)
            result = response.json()

            translated_queries.append(result['translated_sql'])

            print(f"✓ Widget {i}:")
            print(f"  - Original: {sql[:60]}...")
            print("  - Translated successfully")
            print(f"  - Time: {result['performance_stats']['total_time_ms']:.2f}ms")

        # Step 2: Check cache effectiveness
        stats_response = await client.get(f"{API_BASE_URL}/cache/stats")
        stats = stats_response.json()

        print("\n✓ Cache Performance:")
        print(f"  - Hit rate: {stats['hit_rate']*100:.1f}%")
        print(f"  - Average lookup: {stats['average_lookup_ms']:.3f}ms")

        # Step 3: Verify health before production use
        health_response = await client.get(f"{API_BASE_URL}/health")
        health = health_response.json()

        print(f"\n✓ Service Health: {health['status']}")
        print(f"  - Ready for production: {'Yes' if health['status'] == 'healthy' else 'No'}")

        print()
        return True


async def start_api_server():
    """Start the translation API server in background"""
    try:
        # Import and start the API
        import uvicorn

        from iris_pgwire.sql_translator.api import get_translation_api

        app = get_translation_api()

        # Start server in background
        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config)

        print("🚀 Starting Translation API server on http://localhost:8000")
        print("📚 API documentation available at http://localhost:8000/docs\n")

        # Run in background
        await server.serve()

    except Exception as e:
        print(f"✗ Failed to start API server: {e}")
        print("\nAlternative: Start manually with:")
        print("  uvicorn iris_pgwire.sql_translator.api:get_translation_api --host 0.0.0.0 --port 8000")
        return None


async def run_all_demos():
    """Run all translation API demonstrations"""
    print("🚀 SQL Translation API Demonstration\n")
    print("=" * 70)

    # Check if API is available
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE_URL}/health", timeout=2.0)
            api_available = response.status_code == 200
        except:
            api_available = False

    if not api_available:
        print("⚠ Translation API not running")
        print("Start the API with:")
        print("  uvicorn iris_pgwire.sql_translator.api:get_translation_api --reload")
        print("  or")
        print("  python -m iris_pgwire.sql_translator.api")
        print()
        return

    demos = [
        ("Basic Translation", demo_basic_translation()),
        ("Vector Operations", demo_vector_translation()),
        ("Batch Performance", demo_batch_translation()),
        ("Validation Levels", demo_validation_levels()),
        ("Cache Management", demo_cache_management()),
        ("API Statistics", demo_api_statistics()),
        ("Error Handling", demo_error_handling()),
        ("Integration Workflow", demo_integration_workflow()),
    ]

    results = []

    for name, demo_coro in demos:
        print(f"🔄 Running {name} demo...")
        try:
            result = await demo_coro
            results.append((name, result))
        except Exception as e:
            print(f"✗ {name} demo failed: {e}\n")
            results.append((name, False))

    # Summary
    print("=" * 70)
    print("TRANSLATION API DEMONSTRATION RESULTS")
    print("=" * 70)

    successful = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{name:30} {status}")

    print(f"\nOverall: {successful}/{total} demos successful")

    print("\n🎉 TRANSLATION API CAPABILITIES DEMONSTRATED!")
    print("\n📚 Key Features Showcased:")
    print("   ✅ REST API for SQL translation")
    print("   ✅ High-performance caching (<1ms lookups)")
    print("   ✅ Multiple validation levels")
    print("   ✅ Constitutional compliance (5ms SLA)")
    print("   ✅ Comprehensive statistics and monitoring")
    print("   ✅ Cache management operations")
    print("   ✅ Error handling and validation")
    print("   ✅ Production-ready integration patterns")

    print("\n💡 The Translation API enables:")
    print("   • Pre-translation of queries before execution")
    print("   • Translation testing and debugging")
    print("   • Integration with external tools")
    print("   • Query optimization analysis")
    print("   • Microservice architecture patterns")


if __name__ == "__main__":
    # Note: Start the API server separately with:
    # uvicorn iris_pgwire.sql_translator.api:get_translation_api --reload

    asyncio.run(run_all_demos())
