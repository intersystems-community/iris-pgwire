# Column Alias Preservation Investigation

**Date**: 2025-11-12
**Status**: In Progress
**Current Test Results**: 18/27 JDBC tests passing (67%)

---

## Executive Summary

Investigation into fixing column alias preservation for JDBC compatibility. Successfully fixed string literal uppercasing bug (+1 test), implemented 3-layer metadata discovery infrastructure, and fixed alias extractor regex. However, column aliases still showing as generic `column1`, `column2` names despite all component fixes working in isolation.

---

## Completed Work

### ✅ Fix #1: String Literal Uppercasing Bug

**Problem**: Identifier normalizer was uppercasing string literals
**Example**: `'hello'` → `'HELLO'`
**Impact**: 1 test failing (`testMultipleQueries`)

**Root Cause**:
```python
# src/iris_pgwire/sql_translator/identifier_normalizer.py:36
self._identifier_pattern = re.compile(r'"([^"]+)"|(\b[a-zA-Z_][a-zA-Z0-9_]*\b)')
```
Regex pattern matched words inside single-quoted string literals.

**Solution**:
Completely rewrote `normalize()` method to:
1. Detect string literals using pattern: `r"'(?:[^']|'')*'"`
2. Split SQL into chunks between string literals
3. Only normalize identifiers in non-string-literal chunks
4. Preserve string literals verbatim

**Result**: `testMultipleQueries` now PASSING ✅

**Files Modified**:
- `src/iris_pgwire/sql_translator/identifier_normalizer.py` (lines 56-115)

---

### ✅ Fix #2: Alias Extractor Regex Bug

**Problem**: Alias extractor failing on queries without FROM clause
**Example**: `SELECT 1 AS num, 'hello' AS text` → `[]` (empty aliases)
**Impact**: 9 tests failing due to column alias preservation

**Root Cause**:
```python
# src/iris_pgwire/sql_translator/alias_extractor.py:39
self._select_clause_pattern = re.compile(
    r'SELECT\s+(.*?)\s+(?:FROM|WHERE|GROUP|ORDER|LIMIT|$)',
    re.IGNORECASE | re.DOTALL
)
```
Regex required whitespace before end-of-string anchor (`\s+$`), but queries without FROM don't have trailing whitespace.

**Solution**:
Made whitespace optional before end-of-string:
```python
self._select_clause_pattern = re.compile(
    r'SELECT\s+(.*?)(?:\s+(?:FROM|WHERE|GROUP|ORDER|LIMIT)|$)',
    re.IGNORECASE | re.DOTALL
)
```

**Standalone Testing** (Confirmed Working):
```bash
docker exec iris-pgwire-db /usr/irissys/bin/irispython -c "
from iris_pgwire.sql_translator.alias_extractor import AliasExtractor
extractor = AliasExtractor()
print(extractor.extract_column_aliases(\"SELECT 1 AS NUM, 'hello' AS TEXT\"))
"
# Output: ['NUM', 'TEXT'] ✅
```

**Files Modified**:
- `src/iris_pgwire/sql_translator/alias_extractor.py` (lines 38-42)

---

### ✅ Fix #3: Use Normalized SQL for Alias Extraction

**Problem**: Alias extractor receiving original lowercase SQL instead of normalized uppercase SQL
**Evidence**: Logs show `SELECT 1 AS NUM, 'hello' AS TEXT` (uppercase) but code was passing original `sql` parameter

**Root Cause**:
```python
# src/iris_pgwire/iris_executor.py:914
extracted_aliases = self.alias_extractor.extract_column_aliases(sql)
```
Using original `sql` parameter instead of `optimized_sql` (which has been normalized/uppercased).

**Solution**:
Changed to use normalized SQL:
```python
# CRITICAL: Use optimized_sql (normalized/uppercased) not original sql
extracted_aliases = self.alias_extractor.extract_column_aliases(optimized_sql)
```

**Files Modified**:
- `src/iris_pgwire/iris_executor.py` (line 916)

---

### ✅ Infrastructure: 3-Layer Metadata Discovery

**Implementation**: Hybrid approach based on Perplexity research (2025-11-11)

**Layer 1: LIMIT 0 Metadata Discovery** (Protocol-native)
- Execute `SELECT * FROM (original_query) AS _metadata LIMIT 0` to discover column structure
- **Status**: Implemented but IRIS limitation confirmed - `iris.sql.exec()` doesn't expose column metadata
- **Testing**: Confirmed IRIS result object has no `_meta`, `description`, or metadata attributes
- **Conclusion**: This approach cannot work with IRIS embedded Python API

**Layer 2: SQL Parsing with Correlation** (Fallback)
- Parse SQL to extract aliases using `alias_extractor.py`
- Validate extracted aliases against actual result set column count
- **Status**: Implemented and working in standalone tests
- **Issue**: Not working when integrated (see "The Mystery" below)

**Layer 3: Generic Fallback** (Last resort)
- Use generic `column1`, `column2`, etc. names
- **Status**: Currently being used (indicates Layer 1 and 2 are failing)

**Files Modified**:
- `src/iris_pgwire/iris_executor.py` (lines 875-940, 1392-1478)

---

## The Mystery: Why Isn't Layer 2 Working?

### Evidence

1. **Alias extractor works standalone** ✅
   ```bash
   extractor.extract_column_aliases("SELECT 1 AS NUM, 'hello' AS TEXT")
   # Output: ['NUM', 'TEXT']
   ```

2. **Code is in the container** ✅
   ```bash
   docker exec iris-pgwire-db grep "Layer 2 SUCCESS" /app/src/iris_pgwire/iris_executor.py
   # Found: line 919
   ```

3. **Server is restarted** ✅
   - Python cache cleared
   - Process killed and restarted
   - File timestamp confirms modification

4. **But NO log messages appear** ❌
   ```bash
   docker exec iris-pgwire-db strings /tmp/pgwire.log | grep "Layer 2"
   # No output
   ```

5. **Still generating generic column names** ❌
   ```bash
   psql -c "SELECT 1 AS num"
   # Output: column1 | ...
   ```

### Possible Explanations

**Hypothesis 1**: Exception silently caught before logging
- Code may be throwing exception in Layer 2 logic
- Exception caught by outer try/except at line 1062
- But query succeeds (we get results), so exception would show in error logs

**Hypothesis 2**: Code path not being executed
- Different execution flow generating column metadata
- Our code path bypassed entirely
- But we ARE generating `column1`, `column2` (plural), which comes from line 941 (Layer 3)

**Hypothesis 3**: Logging being filtered/suppressed
- Log level too high to show INFO messages
- But other INFO messages DO appear in logs
- And diagnostic log at line 880 also missing

**Hypothesis 4**: Variable scope issue
- `optimized_sql` not in scope at line 916
- Would cause NameError exception
- But no exceptions in logs

### Diagnostic Attempts Made

1. ✅ Added diagnostic logging at line 880 - not appearing
2. ✅ Confirmed file changes in container
3. ✅ Cleared Python bytecode cache
4. ✅ Verified SQL normalization happens (logs show uppercase SQL)
5. ✅ Tested alias extractor standalone - works perfectly
6. ✅ Changed to use `optimized_sql` instead of `sql`
7. ❌ Still no log messages from metadata discovery code

---

## IRIS API Limitations Confirmed

**IRIS Embedded Python does NOT expose column metadata**:

```python
import iris
result = iris.sql.exec("SELECT 1 AS num, 'hello' AS text")

# Confirmed:
hasattr(result, '_meta')        # False
hasattr(result, 'description')  # False
result.ResultSet                # Object exists but no column info

# LIMIT 0 pattern:
result = iris.sql.exec("SELECT * FROM (SELECT 1 AS num) AS _m LIMIT 0")
# Returns 0 rows but still no metadata exposed
```

This is consistent with Perplexity research findings that IRIS embedded Python API lacks column metadata exposure, making SQL parsing the ONLY viable approach.

---

## Current Test Results

**Overall**: 18/27 tests passing (67%)

**By Category**:
- BasicConnectionTest: 6/6 (100%) ✅
- TransactionTest: 7/7 (100%) ✅
- SimpleQueryTest: 4/7 (57%)
- PreparedStatementTest: 2/7 (29%)

**Passing Tests** (18):
- All BasicConnectionTest tests
- All TransactionTest tests
- testMultipleQueries (string literal fix)
- testEmptyResultSet
- testSelectConstant
- testSelectCurrentTimestamp
- testPreparedStatementBatch (bonus fix from string literal)

**Failing Tests** (9) - All column alias related:
1. SimpleQueryTest.testResultSetMetadata()
2. SimpleQueryTest.testSelectMultipleColumns()
3. SimpleQueryTest.testSelectWithNullValue()
4. PreparedStatementTest.testPreparedStatementWithStringParameter()
5. PreparedStatementTest.testPreparedStatementWithNullParameter()
6. PreparedStatementTest.testPreparedStatementReuse()
7. PreparedStatementTest.testPreparedStatementWithDateParameter()
8. PreparedStatementTest.testPreparedStatementWithSingleParameter()
9. PreparedStatementTest.testPreparedStatementWithMultipleParameters()

**Error Pattern**:
```
org.postgresql.util.PSQLException: The column name num was not found in this ResultSet.
```
or
```
org.opentest4j.AssertionFailedError: expected: <id> but was: <column1>
```

---

## Next Steps

### Immediate Actions

1. **Debug logging mystery**:
   - Add explicit print() statements (not logger) to verify code execution
   - Check if exception being thrown and caught
   - Verify `optimized_sql` variable is in scope

2. **Alternative debugging approach**:
   - Instrument protocol.py to see what column names are being sent
   - Add logging in `send_row_description()` to see source of column names
   - Trace execution flow from protocol layer backwards

3. **Consider direct fix**:
   - If metadata discovery path is blocked, consider modifying protocol.py
   - Extract aliases at protocol layer where we know SQL is available
   - Bypass executor layer entirely for column name generation

### Research Questions

1. **Is there another code path generating columns?**
   - Check if protocol.py has its own column metadata generation
   - Search for other places `column1` might be generated
   - Verify our executor code is actually being called

2. **Why are log messages disappearing?**
   - Check if structlog configuration filtering messages
   - Verify log level settings
   - Test with print() statements instead of logger

3. **Variable scope verification**:
   - Confirm `optimized_sql` is in scope at line 916
   - Check if we're in a closure or nested function
   - Verify no shadowing of variable names

---

## Files Modified

**Core Implementation**:
- `src/iris_pgwire/sql_translator/identifier_normalizer.py` - String literal fix
- `src/iris_pgwire/sql_translator/alias_extractor.py` - Regex fix
- `src/iris_pgwire/iris_executor.py` - 3-layer metadata discovery + use optimized_sql

**Documentation**:
- This file

---

## References

- **Perplexity Research** (2025-11-11): PostgreSQL wire protocol metadata discovery patterns
- **IRIS Documentation**: Embedded Python API limitations
- **JDBC Test Suite**: `/Users/tdyar/ws/iris-pgwire/tests/client_compatibility/jdbc/`
- **PostgreSQL Protocol Spec**: Message format requirements for RowDescription

---

## Conclusion

We've made significant progress fixing underlying bugs:
- ✅ String literal uppercasing (18/27 → maintains progress)
- ✅ Alias extractor regex (confirmed working standalone)
- ✅ Infrastructure for systematic metadata discovery

However, the integration mystery remains unsolved. The alias extractor works perfectly in isolation but fails when integrated into the execution flow, with no diagnostic logs appearing despite explicit instrumentation.

**Recommendation**: Focus next session on tracing the actual execution flow from protocol layer backwards, using print() statements instead of structured logging to bypass any log filtering issues.
