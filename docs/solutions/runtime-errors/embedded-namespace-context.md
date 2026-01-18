# Solution: Embedded Python Namespace Context

**Category:** Runtime Errors
**Date:** 2026-01-17
**Status:** Solved

## Problem Symptom
Intermittent "Class not found" errors when executing perfectly valid SQL (e.g., `SQLUser."USER"`) through `iris.sql.exec()` in the `iris-pgwire` executor. The same SQL works fine in a standalone `irispython` script.

## Investigation Steps
1. Verified SQL string formatting - correctly mapped to `SQLUser."USER"`.
2. Tested SQL in standalone script - successful.
3. Analyzed `IRISExecutor` context - found that `iris.sql.exec()` was being called within an `asyncio` thread pool (`concurrent.futures.ThreadPoolExecutor`).
4. Discovered that the IRIS process context (including the current namespace) is thread-local in Embedded Python.

## Root Cause
When running in a background thread, the IRIS context does not automatically inherit the namespace set in the main thread or during initialization. If the thread hasn't explicitly set its namespace, it may default to `%SYS` or stay in an undefined state, causing class lookups in `SQLUser` to fail.

## Working Solution
Added an explicit `SetNamespace` call inside the synchronous execution wrapper that runs in the thread pool.

```python
def _sync_execute():
    """Synchronous IRIS execution in thread pool"""
    import iris

    # CRITICAL: Ensure correct namespace context in background thread
    if hasattr(iris, "system") and hasattr(iris.system, "Process"):
        iris.system.Process.SetNamespace(self.iris_config.get("namespace", "USER"))
    
    # ... proceed with iris.sql.exec ...
```

## Prevention Strategies
- Always verify and explicitly set namespace context when crossing thread boundaries in Embedded Python.
- Add logging to verify the current namespace if "Class not found" errors persist despite correct SQL.

## Cross-References
- [iris_executor.py](../../src/iris_pgwire/iris_executor.py)
- Feature 036: DDL Compatibility
