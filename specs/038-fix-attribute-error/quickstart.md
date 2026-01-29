# Quickstart: Verifying Fix for Connection Pool AttributeError

## Setup

1. Install the failing version (if you want to see it crash first): `pip install iris-pgwire==1.2.31`
2. Start the server: `python -m iris_pgwire.server`
3. Observe the crash: `AttributeError: 'DBAPIConnection' object has no attribute 'idle_seconds'`

## Verification Steps

### 1. Automated Unit Test
Run the new reproduction test case:

```bash
pytest tests/unit/test_dbapi_connection_stability.py
```

### 2. Manual Server Startup
Start the updated server and verify it reaches the ready state:

```bash
# Set debug logging to see recycling events
export PGWIRE_DEBUG=true
python -m iris_pgwire.server
```

**Expected Output**:
- "PGWire server started" message.
- No `AttributeError` tracebacks in the console.

### 3. Recycling Simulation
If the server is left running or the pool is stressed, recycling events will trigger. Verify the logs show:
- `Recycling old connection`
- `Removed connection from pool`
without crashing the background thread.
