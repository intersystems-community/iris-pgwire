"""
Utilities for translating PostgreSQL vector syntax (pgvector) to IRIS vector syntax.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass
class HnswIndexSpec:
    """Parsed HNSW index specification."""

    index_name: str
    table_name: str
    column_name: str
    distance_metric: Literal["COSINE", "DOT_PRODUCT"]
    if_not_exists: bool = False

    # Ignored PostgreSQL options (logged as warnings)
    ignored_options: dict[str, Any] = field(default_factory=dict)

    def to_iris_sql(self) -> str:
        """
        Convert to IRIS SQL index creation syntax.

        Returns:
            IRIS SQL string (e.g., "CREATE INDEX idx ON table (col) AS HNSW")
        """
        # Note: IRIS doesn't specify distance metric in the CREATE INDEX statement
        # It's inferred from usage, but we validate support here.
        # Actually, IRIS HNSW index syntax is simply:
        # CREATE INDEX idxname ON table (col) AS HNSW
        return f"CREATE INDEX {self.index_name} ON {self.table_name} ({self.column_name}) AS HNSW"

    @classmethod
    def from_postgres_sql(cls, sql: str) -> Optional["HnswIndexSpec"]:
        """
        Parse a PostgreSQL HNSW index creation statement.

        Example: CREATE INDEX IF NOT EXISTS idx ON documents USING hnsw (embedding vector_cosine_ops)

        Args:
            sql: PostgreSQL CREATE INDEX statement

        Returns:
            HnswIndexSpec if matched, else None
        """
        # Regex to capture parts
        pattern = (
            r"CREATE\s+INDEX\s+(?P<if_not_exists>IF\s+NOT\s+EXISTS\s+)?(?P<index_name>\w+)\s+ON\s+"
            r"(?P<table_name>\w+)\s+USING\s+hnsw\s*\((?P<column_name>\w+)\s+(?P<operator>\w+)\)"
        )

        match = re.search(pattern, sql, re.IGNORECASE)
        if not match:
            return None

        operator = match.group("operator").lower()

        if operator == "vector_l2_ops":
            raise ValueError(
                "IRIS does not support L2/Euclidean distance for HNSW indexes. "
                "Use vector_cosine_ops or vector_ip_ops."
            )

        distance_metric: Literal["COSINE", "DOT_PRODUCT"]
        if operator == "vector_cosine_ops":
            distance_metric = "COSINE"
        elif operator == "vector_ip_ops":
            distance_metric = "DOT_PRODUCT"
        else:
            raise ValueError(f"Unsupported vector operator for HNSW: {operator}")

        return cls(
            index_name=match.group("index_name"),
            table_name=match.group("table_name"),
            column_name=match.group("column_name"),
            distance_metric=distance_metric,
            if_not_exists=bool(match.group("if_not_exists")),
        )


def normalize_vector(vector: list[float]) -> list[float]:
    """
    Ensure vector is in a format IRIS can handle (list of floats).

    Args:
        vector: List of floats

    Returns:
        Normalized vector
    """
    return [float(x) for x in vector]
