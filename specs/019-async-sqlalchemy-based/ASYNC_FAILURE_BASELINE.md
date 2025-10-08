# Async SQLAlchemy Failure Baseline

**Date**: 2025-10-08
**Status**: Pre-implementation failure documentation

## Expected Failure: AwaitRequired Exception

Based on research findings and current implementation state, async SQLAlchemy with IRIS via PGWire is expected to fail with the following error:

```
sqlalchemy.exc.AwaitRequired: The current operation requires an async execution env
```

## Root Cause

The `IRISDialect_psycopg` class currently:
1. Sets `is_async = True` (insufficient alone)
2. Does NOT implement `get_async_dialect_cls()` method
3. Therefore SQLAlchemy defaults to sync dialect resolution

## Test Command

```bash
python3 benchmarks/async_sqlalchemy_stress_test.py
```

## Expected Stack Trace

```
Traceback (most recent call last):
  File "benchmarks/async_sqlalchemy_stress_test.py", line X
    async with engine.connect() as conn:
  ...
sqlalchemy.exc.AwaitRequired: The current operation requires an async execution env
```

## Implementation Status

- [ ] `get_async_dialect_cls()` method (T010)
- [ ] `IRISDialectAsync_psycopg` class (T011-T017)

**Next Step**: Proceed to TDD phase (T003-T009) to write failing tests, then implement async dialect to make them pass.
