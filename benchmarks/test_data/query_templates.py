"""
Query templates for 3-way benchmark (T008).

Defines SQL query templates for three complexity categories per FR-002:
- Simple SELECT queries
- Vector similarity queries
- Complex join queries

Per FR-008: All methods execute identical query patterns.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, Callable
import numpy as np


class QueryCategory(Enum):
    """Query complexity categories per FR-002"""
    SIMPLE = "simple"
    VECTOR_SIMILARITY = "vector_similarity"
    COMPLEX_JOIN = "complex_join"


@dataclass
class QueryTemplate:
    """
    Query template with parameter generator.

    Attributes:
        query_id: Unique identifier for this query
        category: Query complexity category
        template: SQL template (may differ by database method)
        description: Human-readable description
    """
    query_id: str
    category: QueryCategory
    description: str

    # Method-specific templates
    pgwire_template: str  # PostgreSQL-compatible SQL for PGWire
    postgres_template: str  # PostgreSQL SQL with pgvector operators
    iris_template: str  # IRIS SQL with VECTOR functions


# Simple SELECT query templates (FR-002: Simple queries)
SIMPLE_QUERIES = [
    QueryTemplate(
        query_id="simple_select_all",
        category=QueryCategory.SIMPLE,
        description="Simple SELECT * with LIMIT",
        pgwire_template="SELECT * FROM benchmark_vectors LIMIT {limit}",
        postgres_template="SELECT * FROM benchmark_vectors LIMIT {limit}",
        iris_template="SELECT TOP {limit} * FROM benchmark_vectors"
    ),
    QueryTemplate(
        query_id="simple_select_id",
        category=QueryCategory.SIMPLE,
        description="Simple SELECT by ID",
        pgwire_template="SELECT * FROM benchmark_vectors WHERE id = {id}",
        postgres_template="SELECT * FROM benchmark_vectors WHERE id = {id}",
        iris_template="SELECT * FROM benchmark_vectors WHERE id = {id}"
    ),
    QueryTemplate(
        query_id="simple_count",
        category=QueryCategory.SIMPLE,
        description="Simple COUNT(*)",
        pgwire_template="SELECT COUNT(*) FROM benchmark_vectors",
        postgres_template="SELECT COUNT(*) FROM benchmark_vectors",
        iris_template="SELECT COUNT(*) FROM benchmark_vectors"
    ),
]


# Vector similarity query templates (FR-002: Vector operations)
VECTOR_QUERIES = [
    QueryTemplate(
        query_id="vector_cosine_similarity",
        category=QueryCategory.VECTOR_SIMILARITY,
        description="Vector similarity with cosine distance",
        pgwire_template="SELECT id, embedding <=> '{vector}' AS distance FROM benchmark_vectors ORDER BY distance LIMIT {k}",
        postgres_template="SELECT id, embedding <=> '{vector}' AS distance FROM benchmark_vectors ORDER BY distance LIMIT {k}",
        iris_template="SELECT TOP {k} id, VECTOR_COSINE(embedding, TO_VECTOR('{vector}', FLOAT)) AS distance FROM benchmark_vectors ORDER BY distance"
    ),
    QueryTemplate(
        query_id="vector_l2_distance",
        category=QueryCategory.VECTOR_SIMILARITY,
        description="Vector similarity with L2 distance",
        pgwire_template="SELECT id, embedding <-> '{vector}' AS distance FROM benchmark_vectors ORDER BY distance LIMIT {k}",
        postgres_template="SELECT id, embedding <-> '{vector}' AS distance FROM benchmark_vectors ORDER BY distance LIMIT {k}",
        iris_template="SELECT TOP {k} id, VECTOR_DOT_PRODUCT(embedding, TO_VECTOR('{vector}', FLOAT)) AS distance FROM benchmark_vectors ORDER BY distance"
    ),
    QueryTemplate(
        query_id="vector_inner_product",
        category=QueryCategory.VECTOR_SIMILARITY,
        description="Vector similarity with inner product",
        pgwire_template="SELECT id, (embedding <#> '{vector}') * -1 AS similarity FROM benchmark_vectors ORDER BY similarity DESC LIMIT {k}",
        postgres_template="SELECT id, (embedding <#> '{vector}') * -1 AS similarity FROM benchmark_vectors ORDER BY similarity DESC LIMIT {k}",
        iris_template="SELECT TOP {k} id, VECTOR_DOT_PRODUCT(embedding, TO_VECTOR('{vector}', FLOAT)) AS similarity FROM benchmark_vectors ORDER BY similarity DESC"
    ),
]


# Complex join query templates (FR-002: Complex queries)
COMPLEX_QUERIES = [
    QueryTemplate(
        query_id="join_with_metadata",
        category=QueryCategory.COMPLEX_JOIN,
        description="Join vectors with metadata table",
        pgwire_template="""
            SELECT v.id, v.embedding, m.label, m.created_at
            FROM benchmark_vectors v
            JOIN benchmark_metadata m ON v.id = m.vector_id
            WHERE m.label = '{label}'
            LIMIT {limit}
        """,
        postgres_template="""
            SELECT v.id, v.embedding, m.label, m.created_at
            FROM benchmark_vectors v
            JOIN benchmark_metadata m ON v.id = m.vector_id
            WHERE m.label = '{label}'
            LIMIT {limit}
        """,
        iris_template="""
            SELECT TOP {limit} v.id, v.embedding, m.label, m.created_at
            FROM benchmark_vectors v
            JOIN benchmark_metadata m ON v.id = m.vector_id
            WHERE m.label = '{label}'
        """
    ),
    QueryTemplate(
        query_id="vector_similarity_with_filter",
        category=QueryCategory.COMPLEX_JOIN,
        description="Vector similarity with metadata filter",
        pgwire_template="""
            SELECT v.id, v.embedding <=> '{vector}' AS distance, m.label
            FROM benchmark_vectors v
            JOIN benchmark_metadata m ON v.id = m.vector_id
            WHERE m.category = '{category}'
            ORDER BY distance
            LIMIT {k}
        """,
        postgres_template="""
            SELECT v.id, v.embedding <=> '{vector}' AS distance, m.label
            FROM benchmark_vectors v
            JOIN benchmark_metadata m ON v.id = m.vector_id
            WHERE m.category = '{category}'
            ORDER BY distance
            LIMIT {k}
        """,
        iris_template="""
            SELECT TOP {k} v.id, VECTOR_COSINE(v.embedding, TO_VECTOR('{vector}', FLOAT)) AS distance, m.label
            FROM benchmark_vectors v
            JOIN benchmark_metadata m ON v.id = m.vector_id
            WHERE m.category = '{category}'
            ORDER BY distance
        """
    ),
]


def get_all_query_templates() -> Dict[QueryCategory, list[QueryTemplate]]:
    """
    Get all query templates organized by category.

    Returns:
        Dictionary mapping QueryCategory to list of QueryTemplate instances
    """
    return {
        QueryCategory.SIMPLE: SIMPLE_QUERIES,
        QueryCategory.VECTOR_SIMILARITY: VECTOR_QUERIES,
        QueryCategory.COMPLEX_JOIN: COMPLEX_QUERIES,
    }


def format_query_for_method(template: QueryTemplate, method: str, params: Dict[str, Any]) -> str:
    """
    Format query template for specific database method.

    Args:
        template: QueryTemplate to format
        method: Database method ("iris_pgwire", "postgresql_psycopg3", "iris_dbapi")
        params: Parameter values (e.g., {"limit": 10, "vector": "[0.1,0.2,0.3]"})

    Returns:
        Formatted SQL query string

    Raises:
        ValueError: If method is invalid
    """
    if method == "iris_pgwire":
        sql_template = template.pgwire_template
    elif method == "postgresql_psycopg3":
        sql_template = template.postgres_template
    elif method == "iris_dbapi":
        sql_template = template.iris_template
    else:
        raise ValueError(f"Unknown method: {method}")

    return sql_template.format(**params)
