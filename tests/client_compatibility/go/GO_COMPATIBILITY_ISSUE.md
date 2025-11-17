# Critical Go Client Compatibility Issue - Binary Format Support

**Date**: 2025-11-13
**Status**: 🔴 **BLOCKING ISSUE** - 14/19 Go tests failing
**Severity**: HIGH - Breaks pgx v5 driver compatibility

## Executive Summary

The Go pgx v5 driver uses **binary format** (format code 1) for result data by default, but IRIS PGWire incorrectly sends **text format** (format code 0) data even though it claims binary format in the RowDescription message. This causes `strconv.ParseInt` errors when pgx tries to parse binary data as text.

## Test Results

**Go Client Tests**: 5/19 PASS (26% success rate) ❌

### Passing Tests (5)
- ✅ `TestServerInformation` - Uses TEXT type (works with binary)
- ✅ `TestConnectionErrorHandling` - No data transfer
- ✅ `TestEmptyResultSet` - No data rows
- ✅ `TestResultMetadata` - Only metadata, no data parsing
- ✅ `TestStringWithSpecialCharacters` - TEXT type (works with binary)

### Failing Tests (14)
All tests failing with same error pattern:
```
can't scan into dest[0]: strconv.ParseInt: parsing "\x00\x00\x00\x01": invalid syntax
```

**Root Cause**: pgx receives 4 bytes `\x00\x00\x00\x01` (binary INT4) but tries to parse as decimal string "1".

#### Failed Test List
- ❌ `TestBasicConnection` - SELECT 1
- ❌ `TestConnectionString` - SELECT 1
- ❌ `TestConnectionPooling` - SELECT 1, SELECT 2
- ❌ `TestMultipleSequentialConnections` - SELECT with parameters
- ❌ `TestConnectionTimeout` - SELECT 1
- ❌ `TestSelectConstant` - SELECT 1
- ❌ `TestMultiColumnSelect` - Multi-column query
- ❌ `TestNullValues` - NULL and integer columns
- ❌ `TestMultipleQueriesSequentially` - Sequential queries
- ❌ `TestParameterizedQueries` - Parameter binding
- ❌ `TestArrayResult` - UNION ALL query
- ❌ `TestTransactionCommit` - SELECT COUNT(*)
- ❌ `TestTransactionRollback` - SELECT COUNT(*)
- ❌ `TestBatchQueries` - Batch execution

## Technical Analysis

### PostgreSQL Wire Protocol Flow

1. **Parse** - Client sends SQL query
2. **Bind** - Client specifies `result_format_codes` (0=text, 1=binary)
   - pgx v5 sends: `result_format_codes=[1]` (binary for all columns)
3. **Describe** - Client requests column metadata
   - Server sends: **RowDescription** with `format_code=0` (text) ❌ WRONG
4. **Execute** - Server sends data
   - Server sends: Binary INT4 data `\x00\x00\x00\x01` (correct)
   - Client expects: Text format (because RowDescription said format_code=0)
   - Result: **Parse error** - pgx tries `strconv.ParseInt("\x00\x00\x00\x01")`

### Evidence from PGWire Logs

```
[info] Parsed result format codes    formats=[1] num_formats=1
[info] Bound portal                  statement_name=stmtcache_...
[info] 🔍🔍🔍 DESCRIBE PORTAL START

[info] 🔴 SEND_ROW_DESCRIPTION CALLED columns=[{'name': '?column?', 'type_oid': 23, 'type_size': -1, 'type_modifier': -1, 'format_code': 0}]
                                                                                                                                ^^^^^^^^
                                                                                                     BUG: Should be format_code=1 (binary)!

[info] Execute: Using result formats from portal    result_formats=[1]
```

**Key Observations**:
1. ✅ Bind correctly parses `result_formats=[1]` (binary)
2. ✅ Bind stores `result_formats=[1]` in portal
3. ❌ **Describe sends `format_code=0` (text) in RowDescription** ← BUG
4. ✅ Execute correctly uses `result_formats=[1]` for data encoding

### Root Cause in Code

**File**: `src/iris_pgwire/protocol.py`

#### Problem 1: Describe Portal Handler (Line 2437)
```python
# protocol.py:2437
result = await self.iris_executor.execute_query(query, params=portal.get('params', []))
if result.get('success') and result.get('columns'):
    await self.send_row_description(result['columns'])  # ❌ Missing result_formats!
```

**Issue**: `portal['result_formats']` exists but is NOT passed to `send_row_description()`

#### Problem 2: send_row_description() Function (Line 1311)
```python
# protocol.py:1311
async def send_row_description(self, columns: List[Dict[str, Any]]):
    # ❌ No result_formats parameter!
    ...
    format_code = col.get('format_code', 0)  # ❌ Always defaults to text (0)
```

**Issue**: Function doesn't accept `result_formats` parameter, so it can't set correct `format_code`

#### Problem 3: Column Metadata (Line 1340)
```python
# protocol.py:1340
format_code = col.get('format_code', 0)  # ❌ IRIS executor doesn't set format_code
```

**Issue**: IRIS executor returns columns without `format_code`, so it defaults to 0 (text)

### Why Node.js Works But Go Fails

**Node.js `pg` driver**:
- Uses **text format** (format_code=0) by default
- Sends `result_format_codes=[0]` in Bind message
- Server correctly sends text format data
- No parsing errors ✅

**Go `pgx` driver**:
- Uses **binary format** (format_code=1) for performance
- Sends `result_format_codes=[1]` in Bind message
- Server CLAIMS text format in RowDescription (format_code=0)
- Server SENDS binary format in DataRow (format_code=1)
- **Format mismatch** → parsing errors ❌

## Required Fix

### Solution: Propagate result_formats to RowDescription

**Step 1**: Modify `send_row_description()` signature
```python
# Add result_formats parameter
async def send_row_description(self, columns: List[Dict[str, Any]], result_formats: List[int] = None):
    if result_formats is None:
        result_formats = []  # Default to text for all columns
```

**Step 2**: Apply result_formats to column metadata
```python
# Inside send_row_description() loop over columns
for i, col in enumerate(columns):
    # Determine format code from result_formats
    if not result_formats:
        format_code = 0  # Default to text
    elif len(result_formats) == 1:
        format_code = result_formats[0]  # Single format for all columns
    elif i < len(result_formats):
        format_code = result_formats[i]  # Per-column format
    else:
        format_code = 0  # Fallback to text

    # Set format_code in column metadata (overrides col.get('format_code', 0))
    col['format_code'] = format_code
```

**Step 3**: Pass result_formats from Describe portal handler
```python
# protocol.py:2437
portal = self.portals[name]
result_formats = portal.get('result_formats', [])
result = await self.iris_executor.execute_query(query, params=portal.get('params', []))
if result.get('success') and result.get('columns'):
    await self.send_row_description(result['columns'], result_formats)  # ✅ Pass formats
```

**Step 4**: Verify binary encoding logic (already exists)
```python
# protocol.py:1443-1449 (already correct)
elif format_code == 1:
    # Binary format - encode based on PostgreSQL type OID
    type_oid = col.get('type_oid', 25)
    if type_oid == 23:  # INT4
        binary_data = struct.pack('!i', int(value))  # ✅ Binary encoding works
```

## Impact Assessment

### Current Impact
- ❌ **Go pgx v5 driver**: 26% success rate (5/19 tests)
- ❌ **Go lib/pq driver**: Likely similar failures (also uses binary format)
- ❌ **Rust postgres crate**: Likely similar failures (binary format)
- ❌ **Java JDBC**: May have similar issues depending on binary preference
- ✅ **Node.js pg driver**: 100% success rate (17/17 tests) - uses text format
- ✅ **Python psycopg**: Likely works (uses text format by default)

### After Fix Impact
- ✅ All client libraries should work (100% compatibility)
- ✅ Binary format provides 2-4× performance improvement for numeric types
- ✅ Proper PostgreSQL wire protocol compliance

## Performance Implications

### Binary Format Benefits
- **INT4**: 4 bytes binary vs 1-10 bytes text (60-75% reduction)
- **FLOAT8**: 8 bytes binary vs 5-20 bytes text (60-80% reduction)
- **No string parsing**: Direct memory copy vs strconv/atoi overhead
- **Network bandwidth**: 30-50% reduction for numeric-heavy workloads

### Why pgx Uses Binary Format
- **Performance**: 2-4× faster for numeric types
- **Precision**: No floating-point rounding errors from text conversion
- **Efficiency**: Less CPU and memory overhead
- **Standard**: PostgreSQL recommends binary format for performance

## Comparison with Node.js Results

| Test Category | Node.js (pg) | Go (pgx) | Status |
|---------------|--------------|----------|--------|
| Basic Connection | ✅ PASS | ❌ FAIL | Format mismatch |
| Connection Pooling | ✅ PASS | ❌ FAIL | Format mismatch |
| SELECT Constant | ✅ PASS | ❌ FAIL | Format mismatch |
| NULL Handling | ✅ PASS | ❌ FAIL | Format mismatch |
| UNION Queries | ✅ PASS | ❌ FAIL | Format mismatch |
| Transactions | ✅ PASS | ❌ FAIL | Format mismatch |
| Server Version | ✅ PASS | ✅ PASS | Text type |
| String Special Chars | ✅ PASS | ✅ PASS | Text type |
| Empty Result Set | ✅ PASS | ✅ PASS | No data |
| Result Metadata | ✅ PASS | ✅ PASS | No data parsing |
| **Total** | **17/17 (100%)** | **5/19 (26%)** | ❌ BLOCKING |

## Next Steps

1. ✅ **Document issue** - This document
2. ⏳ **Implement fix** - Modify `send_row_description()` to accept `result_formats`
3. ⏳ **Test fix** - Re-run Go tests (expect 19/19 PASS)
4. ⏳ **Verify regression** - Re-run Node.js tests (expect 17/17 PASS maintained)
5. ⏳ **Update CLAUDE.md** - Document binary format support in Section 11

## References

- **PostgreSQL Protocol Spec**: https://www.postgresql.org/docs/current/protocol-message-formats.html
- **Bind Message Format**: result_format_codes specify text (0) or binary (1)
- **RowDescription Format**: format_code field MUST match actual data format
- **DataRow Format**: Column values encoded per format_code from Bind
- **pgx v5 Documentation**: https://pkg.go.dev/github.com/jackc/pgx/v5
- **Node.js Test Results**: `tests/client_compatibility/nodejs/` (17/17 PASS)
- **IRIS PGWire Logs**: `/tmp/pgwire.log` in iris-pgwire-db container

## Error Message Example

```
=== RUN   TestBasicConnection
    connection_test.go:72:
        	Error Trace:	connection_test.go:72
        	Error:      	Received unexpected error:
        	            	can't scan into dest[0]: strconv.ParseInt: parsing "\x00\x00\x00\x01": invalid syntax
        	Test:       	TestBasicConnection
--- FAIL: TestBasicConnection (0.02s)
```

**Interpretation**:
- pgx receives 4 bytes: `\x00\x00\x00\x01` (binary INT4 value 1)
- pgx expects text format (because RowDescription said `format_code=0`)
- pgx calls `strconv.ParseInt("\x00\x00\x00\x01", 10, 64)`
- Error: Binary data is not valid decimal ASCII
