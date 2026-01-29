# Research: Fix Connection Pool AttributeError

## Decision: Pydantic Model Enhancements

### Decision
Add `is_overflow` as a boolean field and `idle_seconds` as a `@property` to the `DBAPIConnection` model.

### Rationale
- **Consistency**: Adding `is_overflow` to the model ensures that connection state is fully captured in the Pydantic schema, making it available for logging, metrics, and API responses.
- **Computed Property**: `idle_seconds` is transient and depends on the current time. Implementing it as a `@property` on the model allows the logging code to use the expected `.idle_seconds` syntax without storing redundant or stale data.
- **Defensive Programming**: Using `getattr(obj, "attr", default)` in the connection pool's logging logic provides a safety net against future model changes, preventing a single log line from crashing the entire server.

### Alternatives Considered
- **Local Calculation**: Calculating `idle_seconds` locally in `dbapi_connection_pool.py` was rejected because it leads to code duplication across different logging/monitoring points.
- **Manual Dictionary Logging**: Passing a dictionary to the logger was rejected as it bypasses the benefits of using the structured connection model.

## Research Findings: Pydantic v2 Properties

- Pydantic v2 `BaseModel` supports standard Python `@property` decorators.
- These properties are not included in `.model_dump()` by default unless specified, which is appropriate for `idle_seconds` as it is a derived metric.
- `extra="allow"` is already enabled on the model, but explicit field definitions are preferred for better type checking and validation.
