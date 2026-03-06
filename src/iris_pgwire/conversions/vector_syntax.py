"""
Utilities for translating PostgreSQL vector syntax (pgvector) to IRIS vector syntax.

IRIS HNSW index syntax (confirmed against live IRIS instance):
    CREATE INDEX name ON [TABLE] schema.table (col)
        AS HNSW(Distance='Cosine'[, M=16, efConstruction=64])

Distance values: 'Cosine' | 'DotProduct'
M and efConstruction are optional (IRIS defaults: M=16, efConstruction=64).
Distance is required for correct query-time behaviour.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass
class HnswIndexSpec:
    """Parsed HNSW index specification."""

    index_name: str
    table_name: str  # may include schema, e.g. "SQLUser.MyTable"
    column_name: str
    distance_metric: Literal["Cosine", "DotProduct"]
    m: Optional[int] = None
    ef_construction: Optional[int] = None
    if_not_exists: bool = False

    # Ignored PostgreSQL options (logged as warnings)
    ignored_options: dict[str, Any] = field(default_factory=dict)

    def to_iris_sql(self) -> str:
        """Convert to IRIS SQL.

        IRIS syntax:
            CREATE INDEX name ON table (col) AS HNSW(Distance='Cosine'[, M=N, efConstruction=N])

        Distance is always emitted so IRIS uses the right index structure at
        query time (VECTOR_COSINE → Cosine, VECTOR_DOT_PRODUCT → DotProduct).
        """
        params = [f"Distance='{self.distance_metric}'"]
        if self.m is not None:
            params.append(f"M={self.m}")
        if self.ef_construction is not None:
            params.append(f"efConstruction={self.ef_construction}")
        return (
            f"CREATE INDEX {self.index_name} ON {self.table_name} "
            f"({self.column_name}) AS HNSW({', '.join(params)})"
        )

    @classmethod
    def from_postgres_sql(cls, sql: str) -> Optional["HnswIndexSpec"]:
        """Parse an HNSW index statement in either pgvector or hybrid form.

        Form 1 — pgvector standard (USING hnsw before column list):
            CREATE [UNIQUE] INDEX [IF NOT EXISTS] name ON [schema.]table
                USING hnsw (col vector_cosine_ops) [WITH (m=16, ef_construction=64)]

        Form 2 — hybrid / user-written (column list before USING):
            CREATE INDEX name ON [schema.]table (col)
                USING HNSW [WITH (M=16, efConstruction=64, Distance='COSINE')]

        Returns HnswIndexSpec if matched, None if not an HNSW statement.
        Raises ValueError for unsupported operators (e.g. vector_l2_ops).
        """
        # Form 1: USING hnsw (col ops) [WITH (...)]
        form1 = re.search(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?P<ine>IF\s+NOT\s+EXISTS\s+)?"
            r"(?P<name>\w+)\s+ON\s+(?P<table>[\w.]+)\s+"
            r"USING\s+hnsw\s*\(\s*(?P<col>\w+)\s+(?P<op>\w+)\s*\)"
            r"(?:\s+WITH\s*\((?P<with>[^)]*)\))?",
            sql,
            re.IGNORECASE,
        )
        if form1:
            op = form1.group("op").lower()
            if op == "vector_l2_ops":
                raise ValueError(
                    "IRIS does not support L2/Euclidean distance for HNSW indexes. "
                    "Use vector_cosine_ops or vector_ip_ops."
                )
            if op == "vector_cosine_ops":
                distance: Literal["Cosine", "DotProduct"] = "Cosine"
            elif op == "vector_ip_ops":
                distance = "DotProduct"
            else:
                raise ValueError(f"Unsupported vector operator for HNSW: {op}")
            m, ef = _parse_with_options(form1.group("with") or "")
            return cls(
                index_name=form1.group("name"),
                table_name=form1.group("table"),
                column_name=form1.group("col"),
                distance_metric=distance,
                m=m,
                ef_construction=ef,
                if_not_exists=bool(form1.group("ine")),
            )

        # Form 2: (col) USING HNSW [WITH (...)]
        form2 = re.search(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?P<ine>IF\s+NOT\s+EXISTS\s+)?"
            r"(?P<name>\w+)\s+ON\s+(?P<table>[\w.]+)\s*"
            r"\(\s*(?P<col>\w+)\s*\)\s+"
            r"USING\s+HNSW"
            r"(?:\s+WITH\s*\((?P<with>[^)]*)\))?",
            sql,
            re.IGNORECASE,
        )
        if form2:
            with_str = form2.group("with") or ""
            m, ef = _parse_with_options(with_str)
            distance = _parse_distance_from_with(with_str)
            return cls(
                index_name=form2.group("name"),
                table_name=form2.group("table"),
                column_name=form2.group("col"),
                distance_metric=distance,
                m=m,
                ef_construction=ef,
                if_not_exists=bool(form2.group("ine")),
            )

        return None


def _parse_with_options(with_str: str) -> tuple[Optional[int], Optional[int]]:
    """Extract M and efConstruction / ef_construction from a WITH clause body."""
    m: Optional[int] = None
    ef: Optional[int] = None
    for part in with_str.split(","):
        kv = re.match(r"\s*(\w+)\s*=\s*(\d+)", part.strip())
        if not kv:
            continue
        key, val = kv.group(1).lower(), int(kv.group(2))
        if key == "m":
            m = val
        elif key in ("efconstruction", "ef_construction"):
            ef = val
    return m, ef


def _parse_distance_from_with(with_str: str) -> Literal["Cosine", "DotProduct"]:
    """Extract Distance= value from a WITH clause body, defaulting to Cosine."""
    dist = re.search(r"Distance\s*=\s*['\"]?(\w+)['\"]?", with_str, re.IGNORECASE)
    if not dist:
        return "Cosine"
    val = dist.group(1).lower()
    if val in ("dotproduct", "dot_product", "innerproduct", "inner_product"):
        return "DotProduct"
    return "Cosine"


def normalize_vector(vector: list[float]) -> list[float]:
    """Ensure vector is in a format IRIS can handle (list of floats)."""
    return [float(x) for x in vector]
