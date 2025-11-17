"""
Vector query request model.

Represents a vector similarity query after PostgreSQL pgvector syntax translation
to IRIS vector functions. Includes performance telemetry for constitutional SLA validation.

Constitutional Requirements:
- Principle VI (Vector Performance): <5ms translation overhead
- Principle I (Protocol Fidelity): Support pgvector syntax compatibility

Feature: 018-add-dbapi-option
Data Model: Entity #3 - VectorQueryRequest
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class VectorQueryRequest(BaseModel):
    """
    Vector similarity query after translation from pgvector to IRIS syntax.

    Lifecycle:
    1. Client sends pgvector query: SELECT * FROM docs ORDER BY embedding <-> '[0.1,0.2]' LIMIT 5
    2. PGWire translates to IRIS: SELECT TOP 5 * FROM docs ORDER BY VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2]', 'DECIMAL'))
    3. VectorQueryRequest captures both original and translated SQL + telemetry
    4. DBAPI executor uses translated_sql for execution
    5. Response includes translation_time_ms for SLA validation
    """

    # Request Identification
    request_id: str = Field(description="Unique request ID for tracing")

    # Query Content
    original_sql: str = Field(description="Original PostgreSQL query with pgvector syntax")
    translated_sql: str = Field(description="Translated IRIS SQL with vector functions")

    # Vector Operation Details
    vector_operator: str = Field(
        description="pgvector operator used: '<->' (L2), '<=>' (cosine), '<#>' (inner product)"
    )
    vector_column: str = Field(description="Column name containing vector data")
    query_vector: list[float] = Field(description="Query vector values")
    vector_dimensions: int = Field(ge=1, le=2048, description="Vector dimensionality")

    # Query Constraints
    limit_clause: int | None = Field(
        default=None, ge=1, description="LIMIT value if present in query"
    )
    filter_conditions: str | None = Field(
        default=None, description="WHERE clause conditions if present"
    )

    # Performance Telemetry
    translation_time_ms: float = Field(ge=0, description="Query translation time in milliseconds")
    backend_type: str = Field(description="Backend that will execute: 'dbapi' or 'embedded'")

    # Timestamps
    received_at: datetime = Field(
        default_factory=datetime.utcnow, description="When request was received"
    )
    translated_at: datetime | None = Field(default=None, description="When translation completed")

    @field_validator("vector_operator")
    @classmethod
    def validate_vector_operator(cls, v: str) -> str:
        """Validate operator is a known pgvector operator."""
        valid_operators = ["<->", "<=>", "<#>"]
        if v not in valid_operators:
            raise ValueError(
                f"Invalid vector operator '{v}'. Must be one of: {', '.join(valid_operators)}"
            )
        return v

    @field_validator("query_vector")
    @classmethod
    def validate_vector_dimensions(cls, v: list[float], info) -> list[float]:
        """Validate query vector matches declared dimensions."""
        vector_dims = info.data.get("vector_dimensions")
        if vector_dims and len(v) != vector_dims:
            raise ValueError(
                f"Query vector length ({len(v)}) does not match declared dimensions ({vector_dims})"
            )
        return v

    @field_validator("translation_time_ms")
    @classmethod
    def validate_translation_sla(cls, v: float) -> float:
        """Log warning if translation exceeds constitutional 5ms SLA."""
        if v > 5.0:
            import logging

            logging.warning(
                f"Vector query translation time ({v:.2f}ms) exceeds constitutional 5ms SLA"
            )
        return v

    def operator_to_iris_function(self) -> str:
        """
        Map pgvector operator to IRIS vector function.

        Returns:
            IRIS function name (VECTOR_L2, VECTOR_COSINE, VECTOR_DOT_PRODUCT)
        """
        operator_map = {
            "<->": "VECTOR_L2",  # L2 distance (Euclidean)
            "<=>": "VECTOR_COSINE",  # Cosine distance
            "<#>": "VECTOR_DOT_PRODUCT",  # Inner product (max)
        }
        return operator_map[self.vector_operator]

    def exceeds_sla(self) -> bool:
        """
        Check if translation exceeded constitutional 5ms SLA.

        Returns:
            True if translation_time_ms > 5.0
        """
        return self.translation_time_ms > 5.0

    def to_telemetry_event(self) -> dict:
        """
        Format as OpenTelemetry span attributes.

        Returns:
            Dict suitable for OTEL span attributes
        """
        return {
            "vector.request_id": self.request_id,
            "vector.operator": self.vector_operator,
            "vector.dimensions": self.vector_dimensions,
            "vector.column": self.vector_column,
            "vector.limit": self.limit_clause,
            "vector.translation_ms": round(self.translation_time_ms, 3),
            "vector.sla_exceeded": self.exceeds_sla(),
            "backend.type": self.backend_type,
            "query.original": self.original_sql[:200],  # Truncate for telemetry
            "query.translated": self.translated_sql[:200],
        }

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "request_id": "req-f47ac10b-58cc-4372-a567-0e02b2c3d479",
                "original_sql": "SELECT * FROM documents ORDER BY embedding <-> '[0.1,0.2,0.3]' LIMIT 5",
                "translated_sql": "SELECT TOP 5 * FROM documents ORDER BY VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]', 'DECIMAL'))",
                "vector_operator": "<->",
                "vector_column": "embedding",
                "query_vector": [0.1, 0.2, 0.3],
                "vector_dimensions": 3,
                "limit_clause": 5,
                "filter_conditions": None,
                "translation_time_ms": 2.5,
                "backend_type": "dbapi",
                "received_at": "2025-10-05T14:30:00Z",
                "translated_at": "2025-10-05T14:30:00.0025Z",
            }
        }
