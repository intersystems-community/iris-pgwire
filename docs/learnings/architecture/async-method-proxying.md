# Proxying Async Methods with Explicit Parameters

## Symptoms
When using a decorator or proxy pattern to enhance async methods (like `execute_query` or `execute_many`), we encountered a "multiple values for argument" `TypeError`. 

Example:
```python
async def execute_query_with_ml_support(
    sql: str,
    params: list | None = None,
    session_id: str | None = None,
    *args,
    **kwargs,
):
    # ... logic ...
    return await original_execute_query(sql, *args, **kwargs)
```

If the caller passed `session_id="abc"` as a keyword argument, it would be captured by the wrapper's `session_id` parameter *and* appear in `kwargs`. When calling `original_execute_query`, if we passed it both positionally (implicit in the capture) and as a keyword (via `**kwargs`), Python raises an error.

## Root Cause
The wrapper was trying to capture specific parameters (`params`, `session_id`) for its own logic but then forwarding everything via `*args` and `**kwargs`. If those captured parameters were part of the original method's signature and the caller used keyword arguments, they existed in two places.

## Solution
Always proxy with explicit named arguments when the original method signature is known and stable. This ensures each argument is passed exactly once and to the correct parameter.

```python
async def execute_query_with_ml_support(
    sql: str,
    params: list | None = None,
    session_id: str | None = None,
    **kwargs,
):
    # ... logic ...
    # Explicitly pass captured variables to the original method
    return await original_execute_query(
        sql, params=params, session_id=session_id, **kwargs
    )
```

For `execute_many`, which had a strict signature `(sql, params_list, session_id=None)` and didn't accept `**kwargs` in the underlying implementation, the wrapper must strictly follow that:

```python
async def execute_many_with_ml_support(
    sql: str, params_list: Any, session_id: str | None = None, **kwargs
):
    # ... logic ...
    # Drop kwargs if original doesn't support them, or filter appropriately
    return await original_execute_many(sql, params_list, session_id=session_id)
```

## Prevention
- Avoid using `*args` and `**kwargs` together with named parameters in wrappers unless you are strictly additive and careful about collision.
- Prefer explicit proxying of known parameters.
- Verify the signature of the `original` method being called.
