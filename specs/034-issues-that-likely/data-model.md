# Data Model: IRIS pgwire compatibility fixes

## Entities

### SQL Statement
- **Description**: Client-submitted SQL text that may contain comments, parameters, and multiple statements.
- **Key Fields**:
  - `raw_text`: Original SQL text from client.
  - `normalized_text`: SQL after normalization/translation steps.
  - `statement_list`: Parsed list of individual statements (order-preserving).
- **Relationships**:
  - Contains zero or more `Parameter Binding` entries.

### Parameter Binding
- **Description**: Positional parameter placeholders and runtime values supplied by the client.
- **Key Fields**:
  - `placeholder_style`: `$n` (PostgreSQL) or `?` (IRIS).
  - `values`: Ordered list of bound parameter values.
  - `types`: Optional inferred types for parameter descriptions.
- **Relationships**:
  - Belongs to a `SQL Statement`.

### Timestamp Value
- **Description**: Temporal values passed as literals or bound parameters that must be compatible with IRIS.
- **Key Fields**:
  - `input_format`: ISO 8601 variants (with/without timezone suffix).
  - `normalized_format`: IRIS-accepted ODBC-like timestamp string.
- **Validation Rules**:
  - Timezone suffixes are stripped for standard timestamp columns.

## State Transitions
- **Statement Lifecycle**: `raw_text` → `normalized_text` → `statement_list` → executed.
- **Parameter Lifecycle**: `$n` placeholders + values → translated placeholders + normalized values.
