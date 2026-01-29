# Data Model: Fix Connection Pool AttributeError

## Entity Updates

### DBAPIConnection (src/iris_pgwire/models/dbapi_connection.py)

Add the following fields and properties to the existing Pydantic model:

| Field | Type | Description |
|-------|------|-------------|
| is_overflow | boolean | Whether this is an overflow connection (above base pool size) |
| idle_seconds | property (float) | Computed duration since last usage or creation |

## Validation Rules

- `is_overflow` must default to `False`.
- `idle_seconds` must return `0.0` if the connection has never been used and its creation time is in the future (safety check for clock skew).
- `idle_seconds` calculation must use `UTC` consistently to avoid timezone crashes.
