# Quickstart: IRIS SQL Constructs Translation

**Date**: 2025-01-19 | **Feature**: 004-iris-sql-constructs

## Overview
This quickstart validates the IRIS SQL Constructs Translation system by executing real PostgreSQL clients against translated IRIS SQL syntax.

## Prerequisites
- IRIS instance running with embedded Python
- IRIS PGWire server with translation module
- PostgreSQL clients: psql, psycopg
- Test data loaded in IRIS

## Test Scenario 1: IRIS System Functions

### Setup
```bash
# Start IRIS PGWire server with translation enabled
python -m iris_pgwire.server --debug --translation-enabled

# Verify IRIS connectivity
iris session -U _SYSTEM -P SYS
```

### Test Execution
```sql
-- Original IRIS query (would fail in PostgreSQL)
SELECT %SYSTEM.Version.GetNumber() AS iris_version;

-- Expected translation to PostgreSQL
SELECT version() AS iris_version;
```

### Validation Commands
```bash
# Test with psql client
psql -h localhost -p 5432 -c "SELECT %SYSTEM.Version.GetNumber()"

# Expected: Returns version information without error
# Verifies: IRIS function translation to PostgreSQL equivalent
```

### Success Criteria
- ✅ psql connects without protocol errors
- ✅ Query executes and returns version string
- ✅ Translation logged showing %SYSTEM.Version.GetNumber() → version()
- ✅ Response time < 50ms (per SLA)

## Test Scenario 2: IRIS SQL Syntax Extensions

### Test Execution
```sql
-- Original IRIS query with TOP syntax
SELECT TOP 5 name, age FROM users ORDER BY age DESC;

-- Expected translation to PostgreSQL
SELECT name, age FROM users ORDER BY age DESC LIMIT 5;
```

### Validation Commands
```bash
# Test with psycopg Python client
python3 << EOF
import psycopg
conn = psycopg.connect("host=localhost port=5432")
cur = conn.cursor()
cur.execute("SELECT TOP 5 name, age FROM users ORDER BY age DESC")
results = cur.fetchall()
print(f"Retrieved {len(results)} rows")
conn.close()
EOF
```

### Success Criteria
- ✅ Python client executes query successfully
- ✅ Returns exactly 5 rows (LIMIT translation working)
- ✅ Translation logged showing TOP → LIMIT conversion
- ✅ Results ordered correctly (ORDER BY preserved)

## Test Scenario 3: IRIS Functions with Parameters

### Test Execution
```sql
-- Original IRIS query with IRIS-specific functions
SELECT %SQLUPPER(name) AS upper_name,
       DATEDIFF_MICROSECONDS(created_date, CURRENT_TIMESTAMP) AS age_microseconds
FROM users WHERE id = ?;

-- Expected translation
SELECT UPPER(name) AS upper_name,
       EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_date)) * 1000000 AS age_microseconds
FROM users WHERE id = $1;
```

### Validation Commands
```bash
# Test with prepared statement
psql -h localhost -p 5432 << EOF
PREPARE test_query AS SELECT %SQLUPPER(name), DATEDIFF_MICROSECONDS(created_date, CURRENT_TIMESTAMP) FROM users WHERE id = \$1;
EXECUTE test_query(123);
DEALLOCATE test_query;
EOF
```

### Success Criteria
- ✅ Prepared statement creation succeeds
- ✅ Parameter binding works correctly ($1 mapping)
- ✅ IRIS functions translated to PostgreSQL equivalents
- ✅ Results match expected data types and values

## Test Scenario 4: Mixed IRIS and Standard SQL

### Test Execution
```sql
-- Complex query mixing IRIS constructs with standard SQL
SELECT u.name,
       %SQLUPPER(u.department) AS dept,
       COUNT(*) as order_count,
       AVG(o.total) as avg_order
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE u.created_date > DATEADD(DAY, -30, CURRENT_DATE)
GROUP BY u.id, u.name, u.department
ORDER BY avg_order DESC
LIMIT 10;
```

### Validation Commands
```bash
# Test complex translation
psql -h localhost -p 5432 --echo-all << EOF
\timing on
SELECT u.name,
       %SQLUPPER(u.department) AS dept,
       COUNT(*) as order_count,
       AVG(o.total) as avg_order
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE u.created_date > CURRENT_DATE - INTERVAL '30 days'
GROUP BY u.id, u.name, u.department
ORDER BY avg_order DESC
LIMIT 10;
EOF
```

### Success Criteria
- ✅ Complex query with joins executes successfully
- ✅ Only IRIS constructs translated, standard SQL preserved
- ✅ Aggregation and grouping work correctly
- ✅ Performance within acceptable limits

## Test Scenario 5: Error Handling for Unsupported Constructs

### Test Execution
```sql
-- IRIS administrative command (should fail gracefully)
VACUUM TABLE users;
```

### Validation Commands
```bash
# Test error handling
psql -h localhost -p 5432 -c "VACUUM TABLE users;" 2>&1 | grep -i "unsupported\|error"
```

### Success Criteria
- ✅ Returns clear error message about unsupported construct
- ✅ Error follows PostgreSQL error message format
- ✅ Connection remains stable after error
- ✅ Error logged for monitoring

## Performance Validation

### Load Testing
```bash
# Generate translation load
for i in {1..100}; do
  psql -h localhost -p 5432 -c "SELECT %SYSTEM.Version.GetNumber()" &
done
wait

# Check performance metrics
curl -s http://localhost:8080/cache/stats | jq '.'
```

### Success Criteria
- ✅ All 100 concurrent queries complete successfully
- ✅ Average translation time < 50ms
- ✅ Cache hit rate improves over multiple runs
- ✅ No memory leaks or connection issues

## Debug Mode Validation

### Test Execution
```bash
# Enable debug mode
export IRIS_PGWIRE_DEBUG=1
psql -h localhost -p 5432 -c "SELECT TOP 3 %SQLUPPER(name) FROM users"

# Check debug logs
tail -f /var/log/iris-pgwire.log | grep "translation_trace"
```

### Success Criteria
- ✅ Debug logs show detailed parsing steps
- ✅ Construct detection and mapping decisions logged
- ✅ Performance breakdown by operation recorded
- ✅ Before/after SQL logged for analysis

## Cleanup
```bash
# Stop PGWire server
pkill -f iris_pgwire.server

# Clear any test data
iris session -U _SYSTEM -P SYS -c "DELETE FROM test_users"
```

---

## Summary
This quickstart validates:
1. **Protocol Compatibility**: PostgreSQL clients work seamlessly
2. **Translation Accuracy**: IRIS constructs convert correctly
3. **Performance**: Sub-50ms translation latency
4. **Error Handling**: Graceful failure for unsupported constructs
5. **Debugging**: Comprehensive trace logging when enabled

**Success Definition**: All test scenarios pass with expected behavior and performance within constitutional requirements.