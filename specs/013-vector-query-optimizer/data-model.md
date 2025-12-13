# Data Model: Vector Query Optimizer

**Feature**: 013-vector-query-optimizer
**Last Updated**: 2025-10-01

## Overview

This document defines the data entities and their relationships for the Vector Query Optimizer feature. The optimizer operates on immutable query transformation data, producing metrics for performance monitoring.

## Entity Definitions

### Vector Query

**Purpose**: Represents a SQL query containing vector similarity operations that may benefit from optimization.

**Attributes**:
- `sql: str` - Original SQL statement with parameter placeholders (`%s` or `?`)
- `params: Optional[List[Any]]` - Query parameters including vector embeddings
- `query_pattern: str` - Protocol pattern ("simple" for Simple Query, "extended" for Parse/Bind/Execute)
- `vector_function: Optional[str]` - Detected vector function ("COSINE", "DOT_PRODUCT", "L2", or None)

**Validation Rules**:
- SQL must be non-empty string
- If params provided, length must match placeholder count in SQL
- query_pattern must be "simple" or "extended"
- vector_function extracted from ORDER BY clause if present

**Invariants**:
- Immutable (query object created once, not modified)
- SQL and params represent user input (untrusted, requires validation)
- vector_function None means no transformation needed

**Relationships**:
- Contains 0+ Vector Parameters (detected from params list)
- Produces 1 Transformation Context (metrics from optimization attempt)

---

### Vector Parameter

**Purpose**: Represents a vector embedding parameter that can be transformed from encoded format to IRIS-optimized literal.

**Attributes**:
- `value: str` - Raw parameter value (base64, JSON array, or comma-delimited)
- `format: str` - Detected format ("base64", "json_array", "comma_delimited", or "unknown")
- `dimensions: Optional[int]` - Number of vector components (if successfully parsed)
- `data_type: str` - IRIS data type ("FLOAT", "INT", "DECIMAL") - default "FLOAT"
- `position: int` - Zero-based parameter index in query

**Validation Rules**:
- value must be string (not bytes, list, or other types)
- format detected via pattern matching (prefix "base64:", brackets for JSON array, commas for delimited)
- dimensions must be > 0 and < 100000 if parsed (sanity check for malformed vectors)
- position must be valid index in params list

**Invariants**:
- Immutable (created during parsing, not modified)
- Unknown format triggers graceful degradation (pass-through original value)
- dimensions may be None if parsing fails (error logged)

**Relationships**:
- Part of Vector Query (1:N relationship)
- Transforms into Vector Literal (1:1 transformation on success)
- May fail transformation → no literal produced (graceful degradation)

**Format Detection Patterns**:
```python
base64: value.startswith("base64:")
json_array: value.startswith("[") and value.endswith("]")
comma_delimited: "," in value and not value.startswith("[")
unknown: none of the above patterns match
```

---

### Vector Literal

**Purpose**: Represents the transformed vector in IRIS-optimized JSON array literal format.

**Attributes**:
- `json_array: str` - JSON array format `[value1,value2,...,valueN]` (no spaces)
- `component_count: int` - Number of components (matches original vector dimensions)
- `data_type: str` - Type specifier for TO_VECTOR() call ("FLOAT", "INT", "DECIMAL")

**Validation Rules**:
- json_array must start with `[` and end with `]`
- json_array must contain comma-separated numeric values
- component_count must match original Vector Parameter dimensions
- data_type must be IRIS-compatible

**Invariants**:
- Immutable (created from Vector Parameter, terminal state)
- Preserves numeric precision from original parameter
- May contain invalid floats (let IRIS handle SQL validation errors)

**Relationships**:
- Created from Vector Parameter (1:1 transformation)
- Embedded in transformed SQL (string substitution)
- No state transitions (terminal object)

**Example Instances**:
```python
# From base64 parameter
VectorLiteral(
    json_array="[0.1,0.2,0.3,0.4,0.5]",
    component_count=5,
    data_type="FLOAT"
)

# From JSON array parameter (pass-through)
VectorLiteral(
    json_array="[1.0,2.0,3.0]",
    component_count=3,
    data_type="FLOAT"
)

# From comma-delimited parameter
VectorLiteral(
    json_array="[4.5,5.6,6.7]",
    component_count=3,
    data_type="FLOAT"
)
```

---

### Transformation Context

**Purpose**: Captures metrics and metadata about the query transformation process for performance monitoring and constitutional compliance tracking.

**Attributes**:
- `timestamp: float` - Transformation start time (time.perf_counter())
- `duration_ms: float` - Transformation duration in milliseconds
- `formats_detected: List[str]` - Vector formats found in parameters
- `params_original: int` - Original parameter count
- `params_remaining: int` - Parameter count after transformation
- `params_substituted: int` - Number of parameters transformed to literals
- `success: bool` - Transformation success flag (False on errors)
- `sla_compliant: bool` - Constitutional 5ms SLA compliance
- `budget_compliant: bool` - 10ms overhead budget compliance
- `error_message: Optional[str]` - Error details if success=False

**Validation Rules**:
- timestamp captured using time.perf_counter() (monotonic clock)
- duration_ms calculated as (end_time - start_time) * 1000
- params_original >= params_remaining (transformation consumes parameters)
- params_substituted == params_original - params_remaining
- sla_compliant = (duration_ms <= 5.0)
- budget_compliant = (duration_ms <= 10.0)

**Invariants**:
- Immutable (created once after transformation completes)
- Always created (even on failure - captures error metrics)
- Used for constitutional performance monitoring
- Logged but not returned to caller (internal metrics only)

**Relationships**:
- Associated with Vector Query (1:1 relationship)
- Input to Performance Monitor (constitutional compliance tracking)
- No state transitions (immutable metrics object)

**Performance Categories**:
```python
# Excellent: Under constitutional SLA
duration_ms < 5.0 → sla_compliant=True, budget_compliant=True

# Good: Within overhead budget
5.0 <= duration_ms < 10.0 → sla_compliant=False, budget_compliant=True
# (Log warning, track violation rate)

# Poor: Exceeds budget
duration_ms >= 10.0 → sla_compliant=False, budget_compliant=False
# (Log error, investigate bottleneck)
```

---

### Vector Format (Enumeration)

**Purpose**: Defines supported encoding formats for vector parameters and their conversion characteristics.

**Enum Values**:
- `BASE64` - Base64-encoded binary float32 array (prefix "base64:")
- `JSON_ARRAY` - JSON array string format `[1.0,2.0,3.0,...]`
- `COMMA_DELIMITED` - Comma-separated values `1.0,2.0,3.0`
- `UNKNOWN` - Unrecognized format (triggers graceful degradation)

**Attributes** (per enum value):
- `format_id: str` - Format identifier ("base64", "json_array", "comma_delimited", "unknown")
- `detection_pattern: str` - Regex or string pattern for format detection
- `requires_conversion: bool` - Whether format needs transformation to JSON array
- `conversion_complexity: str` - Performance category ("O(1)", "O(n)", "O(n log n)")

**Format Characteristics**:

| Format | Detection | Conversion | Complexity | Typical Performance |
|--------|-----------|------------|------------|---------------------|
| BASE64 | `^base64:` | base64.b64decode → struct.unpack → JSON array | O(n) | 2-5ms (1024-dim) |
| JSON_ARRAY | `^\[.*\]$` | Pass-through (no conversion) | O(1) | <0.1ms |
| COMMA_DELIMITED | Has `,`, no `[` | Wrap in `[]` brackets | O(1) | <0.1ms |
| UNKNOWN | None match | Return None (graceful degradation) | O(1) | <0.1ms |

**Relationships**:
- Determines how Vector Parameter is converted to Vector Literal
- Influences Transformation Context performance metrics
- No runtime state (compile-time enumeration)

---

## Entity Relationships

```
┌─────────────────┐
│  Vector Query   │
│  - sql          │
│  - params       │
│  - pattern      │
└────────┬────────┘
         │
         │ contains (1:N)
         ▼
┌─────────────────────┐
│  Vector Parameter   │
│  - value            │
│  - format           │◄─────── Vector Format (enum)
│  - dimensions       │         determines conversion
│  - position         │
└────────┬────────────┘
         │
         │ transforms to (1:1)
         ▼
┌─────────────────────┐
│  Vector Literal     │
│  - json_array       │
│  - component_count  │
│  - data_type        │
└─────────────────────┘
         │
         │ embedded in
         ▼
┌─────────────────────┐
│  Transformed SQL    │ (string)
│  ORDER BY           │
│  VECTOR_COSINE(...  │
│  TO_VECTOR('[...]') │
└─────────────────────┘

┌─────────────────┐
│  Vector Query   │
└────────┬────────┘
         │
         │ produces (1:1)
         ▼
┌─────────────────────────┐
│ Transformation Context  │
│ - timestamp             │
│ - duration_ms           │
│ - sla_compliant         │
│ - success               │
└─────────┬───────────────┘
          │
          │ input to
          ▼
┌─────────────────────────┐
│  Performance Monitor    │ (constitutional compliance)
│  - SLA tracking         │
│  - violation reporting  │
└─────────────────────────┘
```

## Data Flow

### Transformation Pipeline

1. **Input**: Vector Query (SQL + params)
   ```python
   query = VectorQuery(
       sql="SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))",
       params=["base64:ABC123..."],
       pattern="simple"
   )
   ```

2. **Detection**: Extract Vector Parameters
   ```python
   param = VectorParameter(
       value="base64:ABC123...",
       format="base64",
       dimensions=1024,
       position=0
   )
   ```

3. **Transformation**: Convert to Vector Literal
   ```python
   literal = VectorLiteral(
       json_array="[0.1,0.2,0.3,...]",
       component_count=1024,
       data_type="FLOAT"
   )
   ```

4. **Substitution**: Embed literal in SQL
   ```python
   optimized_sql = "SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR('[0.1,0.2,...]', FLOAT))"
   remaining_params = []  # Vector param consumed
   ```

5. **Metrics**: Record Transformation Context
   ```python
   context = TransformationContext(
       timestamp=start_time,
       duration_ms=4.5,
       formats_detected=["base64"],
       params_original=1,
       params_remaining=0,
       params_substituted=1,
       success=True,
       sla_compliant=True,
       budget_compliant=True
   )
   ```

### Error Handling Flow

**Unknown Format** (graceful degradation):
```python
# Input
param = VectorParameter(value="unknown_xyz", format="unknown")

# Transformation
literal = None  # Conversion returns None

# Output
optimized_sql = original_sql  # Unchanged
remaining_params = original_params  # Unchanged

# Metrics
context = TransformationContext(
    success=False,
    error_message="Unknown vector format: unknown_xyz"
)
```

**Base64 Decode Failure**:
```python
# Input
param = VectorParameter(value="base64:INVALID!@#", format="base64")

# Transformation (exception caught)
try:
    decoded = base64.b64decode("INVALID!@#")
except Exception as e:
    literal = None
    error = f"Base64 decode failed: {e}"

# Output (graceful degradation)
optimized_sql = original_sql
remaining_params = original_params

# Metrics
context = TransformationContext(
    success=False,
    error_message="Base64 decode failed: Invalid base64-encoded string"
)
```

## Performance Characteristics

### Memory Usage

- **Vector Query**: O(len(sql) + sum(len(p) for p in params)) - query size
- **Vector Parameter**: O(len(value)) - parameter size
- **Vector Literal**: O(dimensions * 10) - JSON array string size (avg 10 chars/float)
- **Transformation Context**: O(1) - fixed-size metrics object

**Example** (1024-dim vector):
- Base64 parameter: ~5.5 KB (1024 floats × 4 bytes × 1.33 base64 overhead)
- JSON array literal: ~10 KB (1024 floats × ~10 chars/float)
- Total overhead: ~15 KB (temporary allocation during transformation)

### Time Complexity

- **Format Detection**: O(1) - prefix/bracket checking
- **Base64 Conversion**: O(n) - n = dimensions (base64.b64decode + struct.unpack)
- **JSON Array Construction**: O(n) - n = dimensions (string concatenation)
- **Regex Pattern Matching**: O(m) - m = len(sql) (single pass)
- **Overall Transformation**: O(n + m) where n = dimensions, m = SQL length

**Performance Targets**:
- 128-dim: <2ms
- 384-dim: <3ms
- 1024-dim: <5ms (constitutional SLA)
- 1536-dim: <8ms (within 10ms budget)
- 4096-dim: <20ms (edge case, document SLA exemption)

## Validation & Testing

### Entity Validation

**Vector Query Validation**:
```python
def validate_vector_query(query: VectorQuery) -> bool:
    assert query.sql, "SQL must be non-empty"
    assert query.query_pattern in ["simple", "extended"], "Invalid pattern"
    if query.params:
        placeholders = query.sql.count('%s') + query.sql.count('?')
        assert len(query.params) == placeholders, "Parameter count mismatch"
    return True
```

**Vector Parameter Validation**:
```python
def validate_vector_parameter(param: VectorParameter) -> bool:
    assert isinstance(param.value, str), "Value must be string"
    assert param.format in ["base64", "json_array", "comma_delimited", "unknown"]
    if param.dimensions:
        assert 0 < param.dimensions < 100000, "Invalid dimensions"
    assert param.position >= 0, "Position must be non-negative"
    return True
```

**Vector Literal Validation**:
```python
def validate_vector_literal(literal: VectorLiteral) -> bool:
    assert literal.json_array.startswith("["), "Must start with ["
    assert literal.json_array.endswith("]"), "Must end with ]"
    assert literal.component_count > 0, "Must have components"
    assert literal.data_type in ["FLOAT", "INT", "DECIMAL"], "Invalid type"
    return True
```

### Test Data Scenarios

**Scenario 1: Simple Base64 Transformation**
```python
query = VectorQuery(
    sql="SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5",
    params=["base64:ABC123..."],
    pattern="simple"
)
# Expected: params_substituted=1, sla_compliant=True
```

**Scenario 2: Multi-Parameter Preservation**
```python
query = VectorQuery(
    sql="SELECT TOP %s * FROM t ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) LIMIT %s",
    params=[10, "base64:XYZ789...", 5],
    pattern="extended"
)
# Expected: params_substituted=1, params_remaining=2 (TOP and LIMIT)
```

**Scenario 3: Graceful Degradation**
```python
query = VectorQuery(
    sql="SELECT * FROM t ORDER BY VECTOR_L2(vec, TO_VECTOR(%s))",
    params=["unknown_format_abc"],
    pattern="simple"
)
# Expected: success=False, sql unchanged, params unchanged
```

---

**Data Model Version**: 1.0.0
**Last Reviewed**: 2025-10-01
**Next Review**: After Phase 2 (Task Generation)
