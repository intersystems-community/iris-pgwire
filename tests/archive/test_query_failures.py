#!/usr/bin/env python3
"""
Diagnostic script to identify failing queries in PGWire benchmark.
"""

import sys

import psycopg

# Connect to PGWire
try:
    conn = psycopg.connect(host="localhost", port=5434, dbname="USER", connect_timeout=10)
    cursor = conn.cursor()
    print("✅ Connected to PGWire")
except Exception as e:
    print(f"❌ Connection failed: {e}")
    sys.exit(1)

# Test vector from query templates
test_vector = "[" + ",".join(["0.1"] * 1024) + "]"

# All query templates from benchmarks/test_data/query_templates.py
test_queries = {
    # Simple queries
    "simple_select_all": "SELECT * FROM benchmark_vectors LIMIT 10",
    "simple_select_id": "SELECT * FROM benchmark_vectors WHERE id = 1",
    "simple_count": "SELECT COUNT(*) FROM benchmark_vectors",
    # Vector similarity queries (pgvector operators)
    "vector_cosine": f"SELECT id, embedding <=> '{test_vector}' AS distance FROM benchmark_vectors ORDER BY distance LIMIT 5",
    "vector_l2": f"SELECT id, embedding <-> '{test_vector}' AS distance FROM benchmark_vectors ORDER BY distance LIMIT 5",
    "vector_inner_product": f"SELECT id, (embedding <#> '{test_vector}') * -1 AS similarity FROM benchmark_vectors ORDER BY similarity DESC LIMIT 5",
    # Complex join queries
    "join_with_metadata": """
        SELECT v.id, v.embedding, m.label, m.created_at
        FROM benchmark_vectors v
        JOIN benchmark_metadata m ON v.id = m.vector_id
        WHERE m.label = 'vector_0'
        LIMIT 10
    """,
    "vector_similarity_with_filter": f"""
        SELECT v.id, v.embedding <=> '{test_vector}' AS distance, m.label
        FROM benchmark_vectors v
        JOIN benchmark_metadata m ON v.id = m.vector_id
        WHERE m.category = 'category_0'
        ORDER BY distance
        LIMIT 5
    """,
}

print(f"\n{'='*70}")
print("Testing all query templates against PGWire")
print(f"{'='*70}\n")

failures = []
successes = []

for query_id, sql in test_queries.items():
    try:
        cursor.execute(sql)
        result = cursor.fetchall()
        successes.append(query_id)
        print(f"✅ {query_id:30s} - {len(result)} rows")
    except Exception as e:
        failures.append((query_id, str(e)))
        print(f"❌ {query_id:30s} - ERROR: {e}")

cursor.close()
conn.close()

print(f"\n{'='*70}")
print(f"Summary: {len(successes)} passed, {len(failures)} failed")
print(f"{'='*70}\n")

if failures:
    print("Failed queries:")
    for query_id, error in failures:
        print(f"  {query_id}: {error}")
    sys.exit(1)
else:
    print("✅ All queries passed!")
    sys.exit(0)
