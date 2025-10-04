# Debugging Investigation - 2025-10-03

**Problem**: Code changes to `iris_executor.py` weren't taking effect despite clearing Python bytecode cache and restarting containers.

**Symptoms**:
- Debug logs added to `iris_executor.py` never appeared in output
- File content verified correct on disk (both local and in container)
- Container restarts, cache clearing, `importlib.reload()` all ineffective
- `print()` statements worked but `logger.info()` calls produced no output

## Root Cause: Structlog Configuration

The issue was **NOT** Python bytecode caching. The code was loading correctly all along.

### The Real Problem

```python
# ❌ WRONG CONFIGURATION (original)
structlog.configure(
    processors=[...],
    logger_factory=structlog.stdlib.LoggerFactory(),  # Creates stdlib loggers
    ...
)
```

**Why this fails**:
- `LoggerFactory()` creates loggers from Python's `logging` module
- Python's `logging` module requires handlers to be configured
- Without handlers, `logger.info()` calls execute successfully but produce **NO OUTPUT**
- This created the illusion that code wasn't loading

### The Fix

```python
# ✅ CORRECT CONFIGURATION
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),  # Writes directly to stdout
    cache_logger_on_first_use=True,
)
```

**Why this works**:
- `PrintLoggerFactory()` writes directly to stdout/stderr
- No handler configuration required
- Logs immediately appear in container output

## Evidence Timeline

### Initial Symptoms (Misleading)

```bash
# File verified correct
docker exec iris-pgwire-db grep "EXECUTING IN EMBEDDED MODE" /app/src/iris_pgwire/iris_executor.py
# Found at line 264 ✓

# But log never appeared
docker exec iris-pgwire-db tail /tmp/pgwire.log
# No "EXECUTING IN EMBEDDED MODE" message ✗
```

This led to assumption of bytecode caching issues.

### Attempted "Fixes" (All Red Herrings)

1. ❌ Cleared `__pycache__` directories - No effect
2. ❌ Deleted all `.pyc` files - No effect
3. ❌ Restarted container - No effect
4. ❌ Used `docker-compose down/up` (fresh container) - No effect
5. ❌ Cleared IRIS-specific Python cache - No effect
6. ❌ Added `importlib.reload()` - No effect (but kept for dev convenience)

### Breakthrough Discovery

Added `print()` statements alongside `logger.info()` calls:

```python
print("🔧 DEBUG: Module loading", flush=True)
logger.info("Module loading")
```

Result:
- `print()` appeared in logs ✅
- `logger.info()` did NOT appear ✗

This proved code WAS loading, but logging was broken.

### Verification

```python
logger = structlog.get_logger()
print(f"Logger type: {type(logger)}")
# Output: <class 'structlog._config.BoundLoggerLazyProxy'>

logger.info("Test")
# No exception raised
# No output produced

print("After logger.info() call", flush=True)
# This appeared in logs
```

Proved that `logger.info()` was executing silently without output.

## Lessons Learned

### 1. Silent Failures are Deceptive

The `LoggerFactory()` configuration caused silent failures:
- No exceptions raised
- No error messages
- Logs just vanished into the void

This is worse than a crash - it creates false debugging paths.

### 2. Verify Assumptions with print()

When debugging, use `print(flush=True)` alongside logging to verify:
- Code is actually executing
- The logging system is the problem, not code loading

### 3. Check Logger Configuration First

For containerized Python applications:
- Always use `PrintLoggerFactory()` unless you have specific handler configuration
- Test logging immediately after configuration
- Don't assume logging "just works"

### 4. Python Module Caching was NOT the Issue

Despite spending significant effort on:
- Clearing bytecode cache
- Using `importlib.reload()`
- Restarting containers
- Investigating IRIS-specific caching

None of these were the actual problem. The code was loading fine.

## Production Recommendations

### 1. Structured Logging Configuration

```python
import structlog
import logging

# ALWAYS use PrintLoggerFactory in containers
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

# Test immediately
logger = structlog.get_logger()
logger.info("Logging configured successfully")
```

### 2. Debugging Template

When code changes don't appear to load:

```python
# Step 1: Add print() alongside logging
print("🔧 DEBUG: Module loaded", flush=True)
logger.info("Module loaded")

# Step 2: If print() appears but logger.info() doesn't:
#   → Logging configuration issue, NOT code loading issue

# Step 3: Verify logger type
print(f"Logger: {type(logger)}", flush=True)

# Step 4: Fix logger factory
# Use PrintLoggerFactory(), not LoggerFactory()
```

### 3. Container Logging Best Practices

- ✅ Use `PrintLoggerFactory()` for stdout logging
- ✅ Test logging immediately after configuration
- ✅ Use `flush=True` in print() statements for unbuffered output
- ✅ Run Python with `-u` flag for unbuffered output: `/usr/irissys/bin/irispython -u`
- ✅ Set `PYTHONUNBUFFERED=1` environment variable

## Files Modified (Final State)

### `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/server.py`

**Changed**:
```python
# OLD (broken)
structlog.configure(
    logger_factory=structlog.stdlib.LoggerFactory(),
    ...
)

# NEW (working)
structlog.configure(
    logger_factory=structlog.PrintLoggerFactory(),
    ...
)
```

**Added**: `importlib.reload()` for development convenience (not required for the fix)

### `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/iris_executor.py`

**No configuration changes required** - worked once server.py logging was fixed.

**Evidence of working code**:
- Line 264: `logger.info("🔍 EXECUTING IN EMBEDDED MODE", ...)` - NOW APPEARS in logs ✅
- Lines 310-321: Semicolon removal code - NOW EXECUTES ✅
- Lines 330-334: `logger.info("About to execute iris.sql.exec", ...)` - NOW APPEARS in logs ✅

### `/Users/tdyar/ws/iris-pgwire/docs/EMBEDDED_PYTHON_SERVERS_HOWTO.md`

**Added**:
- Section 4: Critical warning about `PrintLoggerFactory()` vs `LoggerFactory()`
- Troubleshooting: "Logging Not Appearing" section with diagnostic steps

## Conclusion

**Time spent**: ~2 hours debugging bytecode caching (wrong path)
**Actual issue**: Single line configuration error (`LoggerFactory` → `PrintLoggerFactory`)
**Detection**: 5 minutes once `print()` statements were added

**Key Insight**: Silent failures are the hardest to debug. Always verify basic assumptions (like "is my logging working?") before investigating complex caching issues.

---

**Status**: ✅ RESOLVED
**Date**: 2025-10-03
**Impact**: All code changes now load correctly and logs appear as expected
