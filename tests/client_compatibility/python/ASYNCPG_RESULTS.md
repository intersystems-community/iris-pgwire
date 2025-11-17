# asyncpg Compatibility Test Results

## Summary

**Test Results**: 1/21 passing (5%)
**Date**: 2025-11-12
**Driver**: asyncpg (pure async PostgreSQL driver)

## Critical Issue: Extended Query Protocol Describe Phase

**Root Cause**: asyncpg exclusively uses the Extended Query Protocol (Parse/Describe/Bind/Execute), which requires proper implementation of the Describe message. IRIS PGWire currently has issues with the Describe phase returning incorrect column metadata.

**Error Message**:
```
asyncpg.exceptions._base.ProtocolError: the number of columns in the result row (1) is different from what was described (0)
```

**Technical Details**:
- asyncpg sends Describe ('D') message after Parse to get column metadata
- PGWire returns RowDescription with 0 columns during Describe phase
- asyncpg then receives DataRow with 1 column during Execute phase
- Mismatch causes protocol error (expected 0 columns, got 1)

**PGWire Log Evidence**:
```
🔵 STEP 1 (SKIPPED): RowDescription already sent by Describe
```

This shows PGWire assumes RowDescription was sent correctly during Describe, but the metadata was incorrect.

## Test Breakdown

### ❌ Failing Tests (20/21)

**Connection Tests** (3/4):
- ❌ test_connection_establishment - Protocol error (column count mismatch)
- ❌ test_connection_pool - Protocol error (column count mismatch)
- ❌ test_server_version - Protocol error (column count mismatch)
- ❌ test_database_metadata - Protocol error (column count mismatch)

**Simple Query Protocol** (5/5):
- ❌ test_fetchval_constant - Protocol error (column count mismatch)
- ❌ test_fetchrow_multiple_columns - Protocol error (column count mismatch)
- ❌ test_fetch_all_rows - Protocol error (column count mismatch)
- ❌ test_select_current_timestamp - Protocol error (column count mismatch)
- ❌ test_select_with_null - Protocol error (column count mismatch)

**Column Metadata** (2/3):
- ❌ test_column_names - Protocol error (column count mismatch)
- ❌ test_column_types_from_prepared - Protocol error (column count mismatch)
- ✅ test_empty_result_set_metadata (only passing test!)

**Prepared Statements** (6/6):
- ❌ test_prepared_with_single_param - Protocol error (column count mismatch)
- ❌ test_prepared_with_multiple_params - Protocol error (column count mismatch)
- ❌ test_prepared_statement_reuse - Protocol error (column count mismatch)
- ❌ test_prepared_with_null_param - Protocol error (column count mismatch)
- ❌ test_prepared_with_string_escaping - Protocol error (column count mismatch)
- ❌ test_prepared_with_date_param - Protocol error (column count mismatch)

**Transaction Management** (3/3):
- ❌ test_basic_commit - Protocol error (column count mismatch)
- ❌ test_basic_rollback - Protocol error (column count mismatch)
- ❌ test_nested_transactions - Protocol error (column count mismatch)

### ✅ Passing Tests (1/21)

- ✅ test_empty_result_set_metadata - This test doesn't execute queries with result rows, avoiding the Describe phase issue

## Protocol Differences: asyncpg vs psycopg3

| Feature | psycopg3 | asyncpg | Impact |
|---------|----------|---------|--------|
| Query Protocol | Simple + Extended | Extended only | asyncpg always uses Parse/Describe/Bind/Execute |
| Describe Support | Optional | Required | asyncpg requires correct Describe implementation |
| Protocol Strictness | Moderate | High | asyncpg fails fast on protocol violations |
| Fallback Paths | Yes | No | psycopg3 can fallback to Simple Query Protocol |

**Key Difference**: psycopg3 can use Simple Query Protocol (`Query` message) which doesn't require the Describe phase. asyncpg ALWAYS uses Extended Query Protocol, making it more sensitive to Describe phase bugs.

## Required Fixes for asyncpg Compatibility

### 1. Fix Describe Message Handler (protocol.py)

**Location**: `src/iris_pgwire/protocol.py` - `handle_describe()` method

**Issue**: The Describe message handler is not correctly returning column metadata. It either:
- Returns empty RowDescription (0 columns)
- Returns incomplete metadata
- Doesn't execute metadata discovery queries

**Fix Required**:
```python
async def handle_describe(self, describe_type: bytes, describe_name: str):
    """Handle Describe message ('D')"""
    if describe_type == b'S':  # Statement
        # Get the prepared statement
        stmt = self.prepared_statements.get(describe_name)
        if stmt:
            # CRITICAL: Must execute metadata discovery here
            # Similar to execute_query but only for metadata
            metadata_result = await self._get_statement_metadata(stmt['query'])

            # Send RowDescription with CORRECT column count and types
            await self._send_row_description(metadata_result['columns'])
        else:
            # Send NoData if statement not found
            await self._send_no_data()
```

### 2. Add Statement Metadata Discovery

**Location**: New method in `src/iris_pgwire/iris_executor.py`

**Purpose**: Execute query metadata discovery without fetching actual data.

**Implementation Pattern**:
```python
async def get_query_metadata(self, sql: str) -> Dict[str, Any]:
    """
    Discover query column metadata without executing query for data.

    Uses LIMIT 0 pattern or IRIS metadata introspection.
    """
    # Use Layer 1: LIMIT 0 metadata discovery
    metadata_sql = f"SELECT * FROM ({sql}) AS _meta LIMIT 0"
    result = await self.execute_query(metadata_sql)
    return {
        'columns': result['columns'],
        'column_count': len(result['columns'])
    }
```

### 3. Protocol Flow Testing

**Required Tests**: Validate complete Extended Query Protocol flow:
1. Parse → ParseComplete
2. Describe → RowDescription (with correct column metadata)
3. Bind → BindComplete
4. Execute → DataRow(s) → CommandComplete

**Test Pattern**:
```python
async def test_extended_protocol_flow():
    """Test complete Extended Query Protocol flow"""
    conn = await asyncpg.connect(...)

    # This implicitly tests Parse/Describe/Bind/Execute
    stmt = await conn.prepare("SELECT $1, $2")

    # Verify Describe returned correct metadata
    assert len(stmt.get_attributes()) == 2

    # Execute and verify data matches metadata
    row = await stmt.fetchrow(1, 'test')
    assert len(row) == 2
```

## Comparison with Other Drivers

| Feature | JDBC (27/27) | psycopg3 (18/20) | asyncpg (1/21) | Notes |
|---------|--------------|------------------|----------------|-------|
| Connection | ✅ | ✅ | ❌ | asyncpg requires Describe support |
| Simple Queries | ✅ | ✅ | ❌ | asyncpg uses Extended Protocol even for simple queries |
| Prepared Statements | ✅ | ⚠️ | ❌ | psycopg3 partial, asyncpg blocked by Describe |
| NULL Handling | ✅ | ✅ | ❌ (untestable) | Can't verify due to Describe issue |
| Column Metadata | ✅ | ✅ | ❌ | asyncpg requires Describe phase metadata |
| Transactions | ✅ | ✅ | ❌ (untestable) | Can't verify due to Describe issue |

**Overall Assessment**: asyncpg compatibility is **blocked** by Extended Query Protocol Describe phase implementation. This is a protocol-level issue, not a driver-specific quirk.

## Why asyncpg Fails Where Others Succeed

### Protocol Strictness Levels

1. **JDBC**: Uses Extended Query Protocol but has fallback mechanisms and tolerance for metadata inconsistencies
2. **psycopg3**: Can use Simple Query Protocol (no Describe phase), gracefully handles metadata issues
3. **asyncpg**: Pure Extended Query Protocol with strict validation - fails immediately on protocol violations

### asyncpg Design Philosophy

asyncpg is designed for **maximum performance** with **strict protocol compliance**:
- Pre-validates all metadata during Describe phase
- Allocates result buffers based on Describe metadata
- Zero-copy data parsing using pre-calculated column positions
- No fallback paths or workarounds

This design makes asyncpg **extremely sensitive** to Describe phase bugs that other drivers tolerate.

## Recommendations

### For Production Use

**DO NOT use asyncpg** with IRIS PGWire until Describe phase is fixed.

### For Development

1. **Fix Describe Handler First**: asyncpg compatibility requires correct Describe implementation
2. **Test Extended Protocol Flow**: Use asyncpg test suite to validate fixes
3. **Incremental Testing**: Fix one query type at a time (SELECT 1, SELECT *, etc.)

### Workarounds

None available - asyncpg has no fallback to Simple Query Protocol.

## Implementation Priority

**Priority**: HIGH (P1) - Extended Query Protocol Describe support is fundamental

**Rationale**:
- asyncpg is widely used in async Python applications (FastAPI, aiohttp)
- Describe phase is also required for full psycopg3 Extended Protocol support
- JDBC may also benefit from improved Describe implementation

**Estimated Effort**: Medium (2-3 days)
- Fix Describe handler in protocol.py
- Add metadata discovery to iris_executor.py
- Test with asyncpg test suite
- Validate across different query types

## References

- **Test file**: `/Users/tdyar/ws/iris-pgwire/tests/client_compatibility/python/test_asyncpg_basic.py`
- **PostgreSQL Protocol**: https://www.postgresql.org/docs/current/protocol-flow.html#PROTOCOL-FLOW-EXT-QUERY
- **asyncpg Documentation**: https://magicstack.github.io/asyncpg/current/
- **Describe Message Spec**: https://www.postgresql.org/docs/current/protocol-message-formats.html
