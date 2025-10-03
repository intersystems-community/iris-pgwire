#!/usr/bin/env python3
"""
3-Way Database Performance Benchmark (T023).

Main CLI entry point for comparing:
- IRIS + PostgreSQL wire protocol (PGWire)
- PostgreSQL + psycopg3
- IRIS + DBAPI

Per FR-010: Outputs results in JSON and console table formats.
Per FR-006: Aborts on connection failure.
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, List

# Add benchmarks to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.config import BenchmarkConfiguration, ConnectionConfig
from benchmarks.runner import BenchmarkRunner
from benchmarks.executors.pgwire_executor import PGWireExecutor
from benchmarks.executors.postgres_executor import PostgresExecutor
from benchmarks.executors.dbapi_executor import DbapiExecutor
from benchmarks.test_data.query_templates import (
    SIMPLE_QUERIES,
    VECTOR_QUERIES,
    COMPLEX_QUERIES,
    format_query_for_method
)
from benchmarks.test_data.vector_generator import generate_query_vector, vector_to_text
from benchmarks.output.json_exporter import export_json
from benchmarks.output.table_exporter import export_table
from benchmarks.validate_connections import validate_all_connections


def create_test_queries(method: str, dimensions: int = 1024) -> Dict[str, List[str]]:
    """
    Create test queries for a specific database method.

    Args:
        method: Database method ("iris_pgwire", "postgresql_psycopg3", "iris_dbapi")
        dimensions: Vector dimensions for query generation

    Returns:
        Dict mapping category to list of SQL queries
    """
    # Generate a test query vector
    query_vec = generate_query_vector(dimensions=dimensions, seed=42)
    query_vec_text = vector_to_text(query_vec)

    queries = {
        'simple': [],
        'vector_similarity': [],
        'complex_join': []
    }

    # Simple queries
    for template in SIMPLE_QUERIES:
        sql = format_query_for_method(
            template,
            method,
            {'limit': 10, 'id': 1}
        )
        queries['simple'].append(sql)

    # Vector similarity queries
    for template in VECTOR_QUERIES:
        sql = format_query_for_method(
            template,
            method,
            {'vector': query_vec_text, 'k': 5}
        )
        queries['vector_similarity'].append(sql)

    # Complex join queries
    for template in COMPLEX_QUERIES:
        sql = format_query_for_method(
            template,
            method,
            {
                'vector': query_vec_text,
                'k': 5,
                'limit': 10,
                'label': 'vector_0',
                'category': 'category_0'
            }
        )
        queries['complex_join'].append(sql)

    return queries


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="3-Way Database Performance Benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default configuration (1024D, 100K rows, 1000 iterations)
  python benchmarks/3way_comparison.py

  # Run with custom parameters
  python benchmarks/3way_comparison.py --vector-dims 512 --dataset-size 500000 --iterations 2000

  # Run with configuration file
  python benchmarks/3way_comparison.py --config benchmarks/config.yaml

  # Skip specific methods
  python benchmarks/3way_comparison.py --skip-postgres --skip-dbapi
        """
    )

    parser.add_argument(
        '--vector-dims',
        type=int,
        default=1024,
        help='Vector dimensions (default: 1024)'
    )
    parser.add_argument(
        '--dataset-size',
        type=int,
        default=100000,
        help='Dataset size (default: 100000)'
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=1000,
        help='Iterations per query (default: 1000)'
    )
    parser.add_argument(
        '--warmup-queries',
        type=int,
        default=100,
        help='Warmup query count (default: 100)'
    )
    parser.add_argument(
        '--skip-postgres',
        action='store_true',
        help='Skip PostgreSQL benchmark'
    )
    parser.add_argument(
        '--skip-pgwire',
        action='store_true',
        help='Skip IRIS PGWire benchmark'
    )
    parser.add_argument(
        '--skip-dbapi',
        action='store_true',
        help='Skip IRIS DBAPI benchmark'
    )
    parser.add_argument(
        '--config',
        type=str,
        help='Path to YAML configuration file'
    )
    parser.add_argument(
        '--output-json',
        type=str,
        default='benchmarks/results/json',
        help='JSON output directory (default: benchmarks/results/json)'
    )
    parser.add_argument(
        '--output-table',
        type=str,
        default='benchmarks/results/tables',
        help='Table output directory (default: benchmarks/results/tables)'
    )

    args = parser.parse_args()

    print("=" * 70)
    print("3-Way Database Performance Benchmark")
    print("=" * 70)
    print()

    # Validate connections first (FR-006)
    print("🔍 Validating database connections...")
    connection_results = validate_all_connections()
    connection_failures = {
        method: error
        for method, error in connection_results.items()
        if error is not None
    }

    if connection_failures:
        print("\n❌ Connection validation failed:")
        for method, error in connection_failures.items():
            print(f"  {method}: {error}")
        print("\n⚠️  Fix connection issues before running benchmark.")
        print("    Run: python benchmarks/validate_connections.py")
        return 1

    print("✅ All connections validated\n")

    # Get connection parameters from environment (for Docker/CI compatibility)
    import os
    pgwire_port = int(os.environ.get("PGWIRE_PORT", "5432"))
    postgres_port = int(os.environ.get("POSTGRES_PORT", "5433"))
    iris_port = int(os.environ.get("IRIS_PORT", "1972"))

    # Create configuration
    config = BenchmarkConfiguration(
        vector_dimensions=args.vector_dims,
        dataset_size=args.dataset_size,
        iterations=args.iterations,
        warmup_queries=args.warmup_queries,
        connection_configs={
            "iris_pgwire": ConnectionConfig(
                method_name="iris_pgwire",
                host=os.environ.get("PGWIRE_HOST", "localhost"),
                port=pgwire_port,
                database="USER"
            ),
            "postgresql_psycopg3": ConnectionConfig(
                method_name="postgresql_psycopg3",
                host=os.environ.get("POSTGRES_HOST", "localhost"),
                port=postgres_port,
                database="benchmark",
                username="postgres",
                password="postgres"
            ),
            "iris_dbapi": ConnectionConfig(
                method_name="iris_dbapi",
                host=os.environ.get("IRIS_HOST", "localhost"),
                port=iris_port,
                database="USER",
                username="_SYSTEM",
                password="SYS"
            ),
        }
    )

    # Create executors and queries
    executors = {}
    all_queries = {}

    if not args.skip_pgwire:
        executors['iris_pgwire'] = PGWireExecutor()
        all_queries['iris_pgwire'] = create_test_queries('iris_pgwire', args.vector_dims)

    if not args.skip_postgres:
        executors['postgresql_psycopg3'] = PostgresExecutor()
        all_queries['postgresql_psycopg3'] = create_test_queries('postgresql_psycopg3', args.vector_dims)

    if not args.skip_dbapi:
        executors['iris_dbapi'] = DbapiExecutor()
        all_queries['iris_dbapi'] = create_test_queries('iris_dbapi', args.vector_dims)

    if not executors:
        print("❌ No methods selected for benchmarking")
        return 1

    # Create runner and execute benchmark
    runner = BenchmarkRunner(config)

    # Create executor callables
    executor_funcs = {
        method: (lambda exec=executor: lambda q: exec.execute(q))()
        for method, executor in executors.items()
    }

    # Combine all queries (same for all methods)
    benchmark_queries = all_queries[list(all_queries.keys())[0]]

    # Run benchmark
    try:
        report = runner.run(executor_funcs, benchmark_queries)

        # Export results
        print("\n📤 Exporting results...")

        # JSON export
        json_path = export_json(report, args.output_json)
        print(f"✅ JSON:  {json_path}")

        # Table export (also prints to console)
        table_output = export_table(report, args.output_table)
        print(f"✅ Table: {args.output_table}/benchmark_*.txt")
        print()
        print(table_output)

        return 0

    except Exception as e:
        print(f"\n❌ Benchmark failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Clean up executors
        for executor in executors.values():
            try:
                executor.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
