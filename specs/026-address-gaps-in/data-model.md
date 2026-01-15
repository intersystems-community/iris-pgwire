# Data Model: Address IRIS Bridge Gaps

## Overview

This feature introduces utility classes and extends existing registries rather than creating new database entities. The "entities" below are **code structures** that enable the four gap-filling capabilities.

---

## Core Classes

### 1. `JsonPathBuilder`

**Purpose**: Accumulate PostgreSQL JSON operators into IRIS-compatible JSONPath strings.

**Location**: `src/iris_pgwire/conversions/json_path.py`

```python
@dataclass
class JsonPathBuilder:
    """Build IRIS JSONPath from PostgreSQL JSON operators."""
    
    # Fields
    base_column: str                    # The column being accessed
    path_segments: list[str]            # Accumulated path parts
    return_type: Literal["json", "text"]  # -> returns json, ->> returns text
    
    # Methods
    def add_key(self, key: str) -> None
    def add_index(self, index: int) -> None
    def build(self) -> str  # Returns "JSON_VALUE(col, '$.a.b.c')"
    
    # Class method
    @classmethod
    def parse(cls, sql: str) -> tuple[str, "JsonPathBuilder"]
```

**Validation Rules**:
- `base_column` must be a valid identifier
- `path_segments` cannot be empty after parsing
- Array indices must be non-negative integers

---

### 2. `HnswIndexSpec`

**Purpose**: Represent a parsed HNSW index creation statement.

**Location**: `src/iris_pgwire/conversions/vector_syntax.py`

```python
@dataclass
class HnswIndexSpec:
    """Parsed HNSW index specification."""
    
    # Fields
    index_name: str
    table_name: str
    column_name: str
    distance_metric: Literal["COSINE", "DOT_PRODUCT"]
    if_not_exists: bool = False
    
    # Ignored PostgreSQL options (logged as warnings)
    ignored_options: dict[str, Any] = field(default_factory=dict)
    
    # Methods
    def to_iris_sql(self) -> str
    # Returns: "CREATE INDEX idx ON table (col) AS HNSW"
    
    @classmethod
    def from_postgres_sql(cls, sql: str) -> Optional["HnswIndexSpec"]
```

**Distance Metric Mapping**:
| PostgreSQL Operator | IRIS Equivalent | Supported |
|---------------------|-----------------|-----------|
| `vector_cosine_ops` | `COSINE` | ✅ Yes |
| `vector_ip_ops` | `DOT_PRODUCT` | ✅ Yes |
| `vector_l2_ops` | N/A | ❌ **Not supported** – raise error |

---

### 3. `DdlResult`

**Purpose**: Structured result from DDL execution with idempotency handling.

**Location**: `src/iris_pgwire/conversions/ddl_idempotency.py`

```python
@dataclass
class DdlResult:
    """Result of DDL statement execution."""
    
    # Fields
    success: bool
    skipped: bool = False           # True if object already existed
    object_name: str | None = None  # Name of created/skipped object
    object_type: str | None = None  # TABLE, INDEX, etc.
    warning: str | None = None      # Message if skipped
    error: Exception | None = None  # Original error if failed
```

---

### 4. `DdlErrorHandler`

**Purpose**: Classify DDL errors and handle `IF NOT EXISTS` semantics.

**Location**: `src/iris_pgwire/conversions/ddl_idempotency.py`

```python
class DdlErrorHandler:
    """Handle DDL errors with idempotency support."""
    
    # Class constants
    DUPLICATE_TABLE_CODES = {"42P07", "42S01"}
    DUPLICATE_INDEX_CODES = {"42P07", "42710"}
    
    # Methods
    def handle(self, sql: str, error: Exception) -> DdlResult
    def has_if_not_exists(self, sql: str) -> bool
    def extract_object_name(self, sql: str) -> str | None
    def classify_error(self, error: Exception) -> str  # "duplicate", "permission", "syntax", "unknown"
```

---

### 5. `BulkInsertJob` (State Tracking)

**Purpose**: Track bulk insert operation for monitoring and error recovery.

**Location**: `src/iris_pgwire/conversions/bulk_insert.py`

```python
@dataclass
class BulkInsertJob:
    """Track bulk insert operation state."""
    
    # Fields
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    table_name: str
    total_rows: int
    inserted_rows: int = 0
    failed_rows: int = 0
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    
    # Methods
    def mark_started(self) -> None
    def mark_completed(self) -> None
    def mark_failed(self, error: str) -> None
    def rows_per_second(self) -> float
```

---

## Registry Extensions

These are **additions to existing registries**, not new entities.

### `constructs.py` Additions

```python
# Add to ConstructRegistry
HNSW_INDEX_PATTERN = ConstructPattern(
    name="hnsw_index",
    pattern=r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s+USING\s+hnsw",
    handler=translate_hnsw_index,
    confidence=0.95
)
```

### `document_filters.py` Additions

```python
# Add recursive JSON operator handling
NESTED_JSON_PATTERN = DocumentFilterPattern(
    name="nested_json_access",
    pattern=r"(\w+)((?:->>'?\w+'?)+)",  # Matches chains of -> and ->>
    handler=translate_nested_json,
    confidence=0.90
)
```

### `functions.py` Additions

```python
# Add vector distance functions (L2 NOT SUPPORTED by IRIS)
VECTOR_FUNCTIONS = [
    FunctionMapping("vector_cosine_distance", "VECTOR_COSINE", confidence=0.95),
    FunctionMapping("vector_ip_distance", "VECTOR_DOT_PRODUCT", confidence=0.95),
    # vector_l2_distance intentionally omitted - IRIS does not support L2
]
```

---

## Relationships

```
┌─────────────────────┐
│   IRISExecutor      │
│   (existing)        │
└─────────┬───────────┘
          │ uses
          ▼
┌─────────────────────┐     ┌─────────────────────┐
│  DdlErrorHandler    │────▶│     DdlResult       │
└─────────────────────┘     └─────────────────────┘
          │
          │ for bulk ops
          ▼
┌─────────────────────┐
│   BulkInsertJob     │
└─────────────────────┘

┌─────────────────────┐
│   SQLTranslator     │
│   (existing)        │
└─────────┬───────────┘
          │ extended by
          ▼
┌─────────────────────┐     ┌─────────────────────┐
│  ConstructRegistry  │────▶│   HnswIndexSpec     │
│  (extended)         │     └─────────────────────┘
└─────────────────────┘
          │
          ▼
┌─────────────────────┐     ┌─────────────────────┐
│ DocumentFilterReg   │────▶│   JsonPathBuilder   │
│  (extended)         │     └─────────────────────┘
└─────────────────────┘
```

---

## Validation Summary

| Entity | Key Validations |
|--------|-----------------|
| `JsonPathBuilder` | Valid column name, non-empty path, valid array indices |
| `HnswIndexSpec` | Valid identifiers, known distance metric |
| `DdlResult` | Consistent state (success XOR error) |
| `BulkInsertJob` | Non-negative counts, valid state transitions |

---

*Data model focuses on utility classes that enable the four gap-filling capabilities.*
