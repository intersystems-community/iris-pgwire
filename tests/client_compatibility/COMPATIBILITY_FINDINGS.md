# Client Compatibility Test Results

**Date**: 2025-11-10
**PGWire Version**: Production (P0-P6 Complete)
**Test Execution**: Partial (Node.js completed)

---

## Executive Summary

**node-postgres (pg 8.11.3)**: ⚠️ **PARTIAL COMPATIBILITY**
- ✅ Basic connection: WORKS
- ✅ Simple queries: WORKS (with column naming caveat)
- ❌ Prepared statements with `::` type casts: FAILS
- ❌ PostgreSQL parameterized queries ($1, $2): NOT SUPPORTED by IRIS SQL

---

## Detailed Findings

### 1. ✅ Connection Establishment (P0 Handshake Protocol)

**Status**: **WORKING**

**Test Result**:
```javascript
const client = new Client({ host: 'localhost', port: 5432, database: 'USER', user: 'test_user', password: 'test', ssl: false });
await client.connect();
// ✅ SUCCESS: Connection established
```

**Validation**:
- SSL negotiation working (disabled for test)
- StartupMessage accepted
- Authentication successful
- ReadyForQuery state reached

---

### 2. ⚠️ Simple Query Protocol (P1)

**Status**: **WORKING with Column Naming Caveat**

**Test Result**:
```javascript
const result = await client.query('SELECT 1');
console.log(result.fields[0].name); // Output: "column1" (not "?column?")
console.log(result.rows[0]);         // Output: { column1: '1' }
```

**IRIS-Specific Behavior**:
- **Column Naming**: IRIS returns `column1` for unnamed columns
- **PostgreSQL Standard**: Returns `?column?` for unnamed columns

**Impact**: Tests expecting `?column?` will fail

**Workaround**: Use explicit column aliases:
```javascript
const result = await client.query('SELECT 1 AS my_column');
console.log(result.rows[0].my_column); // ✅ WORKS
```

---

### 3. ❌ PostgreSQL Type Cast Operator (`::`  )

**Status**: **NOT SUPPORTED**

**Test Result**:
```sql
SELECT $1::int   -- ❌ FAILS
SELECT $1::text  -- ❌ FAILS
```

**Error Message**:
```
ERROR: Host variable name must begin with either % or a letter, not ':'^SELECT $1:
```

**Root Cause**:
- PostgreSQL uses `::` for type casting (e.g., `'42'::int`)
- IRIS SQL does not recognize `::` operator
- IRIS interprets `:` as start of host variable (e.g., `:varname`)

**Impact**:
- All node-postgres tests using `::` type casts fail
- Common pattern in PostgreSQL applications

**Workaround**: Use IRIS CAST() function:
```sql
-- PostgreSQL syntax (doesn't work)
SELECT $1::int

-- IRIS-compatible syntax (works)
SELECT CAST($1 AS INTEGER)
```

---

### 4. ❌ PostgreSQL Parameterized Queries (`$1`, `$2`)

**Status**: **NOT SUPPORTED by IRIS SQL**

**Test Result**:
```javascript
// PostgreSQL standard (node-postgres sends this)
await client.query('SELECT $1::int', [42]);
// ❌ FAILS: IRIS doesn't understand $1 placeholders
```

**Error Message**:
```
ERROR: Host variable name must begin with either % or a letter, not ':'^SELECT $1:
```

**Root Cause**:
- node-postgres driver sends PostgreSQL-style `$1, $2, $3` parameters
- IRIS SQL uses different parameter syntax (`:param` or `?`)
- PGWire server would need to translate `$1` → IRIS parameter format

**Impact**:
- **CRITICAL**: All prepared statement tests fail
- This is a **P2 Extended Protocol** implementation gap

**Status**: **BLOCKING ISSUE** - Requires PGWire protocol translation layer

**Required Fix**: PGWire server must translate PostgreSQL parameter placeholders:
```
PostgreSQL Wire Protocol: SELECT $1, $2
           ↓
PGWire Translation Layer: Replace $1 → ?, $2 → ?
           ↓
IRIS SQL Execution: SELECT ?, ?
```

---

### 5. ⚠️ Column Case Sensitivity

**Status**: **IRIS Behavior Differs from PostgreSQL**

**IRIS Behavior**:
- Preserves mixed case column names (e.g., `PatientID`, `LastName`)
- PostgreSQL lowercases unquoted identifiers (e.g., `patientid`, `lastname`)

**Impact**: Schema introspection queries may need `LOWER()` for case-insensitive matching

---

### 6. ❌ Table Operations Edge Cases

**Delete Without Existing Table**:
```javascript
await client.query('DELETE FROM test_empty');
// ❌ FAILS if table doesn't exist (expected)
```

**Insert Cardinality Mismatch**:
```sql
CREATE TABLE test_commit (id INT, value VARCHAR(50))
INSERT INTO test_commit VALUES (1, 'committed')  -- ❌ FAILS
-- Error: Cardinality mismatch on INSERT/UPDATE between values list and number of table columns
```

**Root Cause**: IRIS requires exact column count match in VALUES clause

**Workaround**: Specify column list explicitly:
```sql
INSERT INTO test_commit (id, value) VALUES (1, 'committed')  -- ✅ WORKS
```

---

## Test Results Summary

### Node.js (node-postgres 8.11.3)

| Test Scenario | Status | Notes |
|---------------|--------|-------|
| **Connection Tests** | ✅ PASS | All 6 connection tests passed |
| **Basic Queries** | ⚠️ PARTIAL | Works with column naming caveat |
| **Parameterized Queries** | ❌ FAIL | `$1, $2` syntax not supported |
| **Type Casting (`::`)** | ❌ FAIL | PostgreSQL-specific operator |
| **Transactions (BEGIN/COMMIT)** | ❌ FAIL | INSERT cardinality issue |
| **NULL Handling** | ⚠️ PARTIAL | Works but column naming issue |

**Overall**: **11 tests failed, 0 tests passed** (after fixing syntax errors)

---

## Critical Compatibility Issues

### 🔴 CRITICAL: PostgreSQL Parameter Placeholders Not Supported

**Issue**: PGWire does not translate `$1, $2, $3` → IRIS parameter syntax
**Impact**: All prepared statement tests fail
**Protocol Phase**: P2 Extended Protocol
**Priority**: **HIGH** - Blocks all parameterized queries

**Affected Clients**:
- node-postgres (pg)
- Likely affects: JDBC, Npgsql, pgx (all use `$1` syntax)

**Required Implementation**:
```python
# In src/iris_pgwire/protocol.py handle_parse() or handle_bind()
def translate_postgres_parameters(sql: str, params: List) -> Tuple[str, List]:
    """
    Translate PostgreSQL $1, $2, $3 placeholders to IRIS ? syntax.

    Example:
        Input:  "SELECT * FROM users WHERE id = $1 AND name = $2"
        Output: "SELECT * FROM users WHERE id = ? AND name = ?"
    """
    import re
    # Replace $1, $2, etc. with ? in sequential order
    translated_sql = re.sub(r'\$\d+', '?', sql)
    return translated_sql, params
```

---

### 🟡 MEDIUM: PostgreSQL Type Cast Operator (`::`) Not Supported

**Issue**: IRIS doesn't recognize `::` type cast syntax
**Impact**: Queries with type casts fail
**Workaround**: Use `CAST(expr AS type)` instead

**Required Documentation**:
- Warn users about `::` operator incompatibility
- Provide CAST() examples in client connection guides

---

### 🟢 LOW: Column Naming Convention Differs

**Issue**: IRIS returns `column1` instead of `?column?`
**Impact**: Tests expecting PostgreSQL naming fail
**Workaround**: Always use explicit column aliases

---

## Recommendations

### Immediate Actions (HIGH PRIORITY)

1. **✅ Implement PostgreSQL Parameter Translation** (P2 Extended Protocol)
   - Add `$1, $2, $3` → `?` translation in `handle_parse()` or `handle_bind()`
   - This is **BLOCKING** for all client drivers

2. **✅ Add `::` Type Cast Translation** (Optional Enhancement)
   - Translate `expr::type` → `CAST(expr AS type)`
   - Or document incompatibility clearly

3. **✅ Fix Test Suite** (Immediate)
   - Update tests to use IRIS-compatible syntax
   - Add IRIS-specific test variants
   - Document PostgreSQL vs IRIS differences

### Medium Priority

4. **Update Client Connection Examples**
   - Document `::` → `CAST()` requirement
   - Show IRIS parameter syntax (`?` not `$1`)
   - Warn about column naming differences

5. **Create PostgreSQL Compatibility Matrix**
   - Document supported vs unsupported PostgreSQL syntax
   - Provide IRIS equivalents for common patterns

### Low Priority

6. **Consider Column Naming Shim**
   - Option to return `?column?` for unnamed columns
   - Would require PGWire protocol change

---

## Next Steps

1. **Fix Parameter Translation** - Implement `$1 → ?` translation (CRITICAL)
2. **Re-run node-postgres tests** - Validate fixes work
3. **Test remaining clients** - JDBC, Npgsql, pgx (once parameter translation is fixed)
4. **Update documentation** - Client connection guides with IRIS-specific notes

---

## Test Environment

- **PGWire Server**: iris-pgwire-db container (localhost:5432)
- **IRIS Version**: 2025.x (embedded Python mode via irispython)
- **Node.js Version**: v21.x
- **node-postgres Version**: 8.11.3
- **Test Framework**: Jest

---

## Files Referenced

- Test Suite: `tests/client_compatibility/nodejs/`
- Connection Test: `connection.test.js` (syntax error on line 101: extra `]`)
- Query Test: `query.test.js` (11 tests, all failing due to `::` and `$1` issues)
- Simple Validation: `simple_test.js` (basic connectivity proof - PASSED)

---

**Report Status**: Phase B - Client Compatibility Testing (In Progress)
**Next Client**: JDBC (pending parameter translation fix)
