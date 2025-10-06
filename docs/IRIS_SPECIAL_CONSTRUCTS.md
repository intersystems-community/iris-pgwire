# IRIS Special Constructs for PostgreSQL Wire Protocol Support

## Executive Summary

Beyond IntegratedML, IRIS has numerous special SQL constructs and functions that extend standard PostgreSQL. This document catalogues the high-priority features we need to implement for complete IRIS compatibility.

## 1. IRIS System Functions (%SYSTEM.*) - HIGH PRIORITY

### Critical System Functions to Implement
```sql
-- Most commonly used system functions
%SYSTEM.SQL.%GetStatement()         -- Get current SQL statement
%SYSTEM.Version.%GetNumber()        -- IRIS version info
%SYSTEM.Security.%GetUser()         -- Current user context
%SYSTEM.SQL.%PARALLEL()             -- Parallel query info
%SYSTEM.SQL.%QueryStats()           -- Query performance stats

-- Information Schema access
%SYSTEM.SQL.Schema.%ClassName()     -- Class metadata
%SYSTEM.SQL.Schema.%TableName()     -- Table metadata
```

### Implementation Strategy
```python
# Function mapping in our PostgreSQL wire protocol
IRIS_SYSTEM_FUNCTIONS = {
    '%SYSTEM.Version.%GetNumber': 'SELECT version()',
    '%SYSTEM.Security.%GetUser': 'SELECT current_user',
    '%SYSTEM.SQL.%GetStatement': 'SELECT current_query()',
    # Custom implementations for IRIS-specific functions
    '%SYSTEM.SQL.%PARALLEL': 'SELECT iris_parallel_info()',
    '%SYSTEM.SQL.%QueryStats': 'SELECT iris_query_stats()'
}
```

## 2. IRIS Data Types - HIGH PRIORITY

### IRIS-Specific Types Needing PostgreSQL Mapping
```sql
-- Auto-increment (different from PostgreSQL SERIAL)
SERIAL                  -- Table-level scope, not sequence-based

-- Version tracking
ROWVERSION             -- Namespace-wide versioning system

-- Compressed data types
%List                  -- Binary compressed lists
%Stream               -- Large binary objects

-- Specialized numeric
MONEY                 -- Currency with specific precision
POSIXTIME            -- Unix timestamp with microseconds

-- Date/time extensions
%TimeStamp           -- IRIS-specific timestamp format
%Date                -- IRIS date format
%Time                -- IRIS time format
```

### Required Type Mappings
```python
IRIS_TYPE_MAPPINGS = {
    'SERIAL': 'SERIAL',              # Need custom implementation
    'ROWVERSION': 'BIGINT',          # With version tracking metadata
    '%List': 'BYTEA',                # Binary data
    '%Stream': 'BYTEA',              # Large binary
    'MONEY': 'NUMERIC(19,4)',        # Currency precision
    'POSIXTIME': 'TIMESTAMP',        # Unix time conversion
    '%TimeStamp': 'TIMESTAMP',       # IRIS format conversion
    '%Date': 'DATE',                 # IRIS date conversion
    '%Time': 'TIME'                  # IRIS time conversion
}
```

## 3. IRIS SQL Extensions - MEDIUM-HIGH PRIORITY

### Query Syntax Extensions
```sql
-- TOP clause (SQL Server style, different from LIMIT)
SELECT TOP 10 * FROM table_name
SELECT TOP 10 PERCENT * FROM table_name

-- IRIS-specific joins
SELECT * FROM table1 %FULL OUTER JOIN table2 ON condition

-- IRIS FOR UPDATE options
SELECT * FROM table_name FOR UPDATE NOWAIT

-- IRIS-specific hints
SELECT /*+ INDEX(table_name, index_name) */ * FROM table_name
SELECT /*+ PARALLEL(4) */ * FROM large_table
```

### Implementation for PostgreSQL Wire Protocol
```python
def translate_iris_sql_extensions(sql: str) -> str:
    """Translate IRIS SQL extensions to PostgreSQL equivalents"""

    # TOP clause translation
    sql = re.sub(r'SELECT TOP (\d+)\s+', r'SELECT ', sql)
    sql = re.sub(r'LIMIT.*$', lambda m: f'LIMIT {top_value}', sql)

    # IRIS join syntax
    sql = sql.replace('%FULL OUTER JOIN', 'FULL OUTER JOIN')

    # FOR UPDATE options
    sql = sql.replace('FOR UPDATE NOWAIT', 'FOR UPDATE NOWAIT')

    return sql
```

## 4. IRIS-Specific Functions - MEDIUM PRIORITY

### String and Pattern Functions
```sql
-- IRIS string functions
%SQLUPPER(string)              -- SQL-safe upper case
%SQLLOWER(string)              -- SQL-safe lower case
%PATTERN.MATCH(string, pattern) -- Pattern matching
%EXACT(string)                 -- Exact case matching

-- IRIS conversion functions
%EXTERNAL(value)               -- External format conversion
%INTERNAL(value)               -- Internal format conversion
```

### Date/Time Functions
```sql
-- IRIS date/time extensions
DATEDIFF_MICROSECONDS(date1, date2)
DATEPART_TIMEZONE(datetime_value)
%HOROLOG                       -- IRIS date format
```

### JSON Functions (IRIS-specific implementations)
```sql
-- IRIS JSON functions
JSON_OBJECT(key1, value1, key2, value2)
JSON_ARRAY(value1, value2, value3)
JSON_SET(json_doc, path, value)
JSON_GET(json_doc, path)
```

## 5. Vector and AI Extensions - HIGH PRIORITY

### Vector Types (Already Implemented)
```sql
VECTOR(data_type, dimensions)  -- ✅ Already working
EMBEDDING                      -- ✅ Already working
```

### Vector Functions (Already Implemented)
```sql
TO_VECTOR('[1,2,3]')          -- ✅ Already working
VECTOR_COSINE(v1, v2)         -- ✅ Already working
VECTOR_DOT_PRODUCT(v1, v2)    -- ✅ Already working
```

### Advanced Vector Functions Needed
```sql
-- Additional vector functions to implement
VECTOR_NORMALIZE(vector)
VECTOR_DIMENSION(vector)
VECTOR_L2_DISTANCE(v1, v2)
VECTOR_MANHATTAN_DISTANCE(v1, v2)
```

## 6. IRIS Information Schema Extensions - MEDIUM PRIORITY

### IRIS-Specific System Tables
```sql
-- IntegratedML metadata (partially implemented)
INFORMATION_SCHEMA.ML_MODELS
INFORMATION_SCHEMA.ML_TRAINING_RUNS
INFORMATION_SCHEMA.ML_PREDICTIONS

-- IRIS system information
INFORMATION_SCHEMA.IRIS_CLASSES       -- ObjectScript classes
INFORMATION_SCHEMA.IRIS_NAMESPACES    -- Available namespaces
INFORMATION_SCHEMA.IRIS_MAPPINGS      -- Global mappings
INFORMATION_SCHEMA.IRIS_INDICES       -- IRIS-specific index types
```

## 7. ObjectScript Integration - LOW-MEDIUM PRIORITY

### Embedded SQL Syntax
```sql
-- Host variables (ObjectScript integration)
&sql(SELECT name INTO :name FROM person WHERE id = :id)

-- Cursor operations
&sql(DECLARE cursor_name CURSOR FOR SELECT * FROM table_name)
&sql(OPEN cursor_name)
&sql(FETCH cursor_name INTO :var1, :var2)
```

### SQL Preprocessor Directives
```sql
-- Compilation directives
#sqlcompile path=/path/to/file
#include <system_file>

-- Conditional compilation
#if defined(PRODUCTION)
    SELECT * FROM production_table
#else
    SELECT * FROM test_table
#endif
```

## 8. Performance and Optimization Features - LOW PRIORITY

### Query Hints and Optimization
```sql
-- IRIS query hints
%PLAN SELECT optimization hints
%NOPLAN                        -- Disable query optimization

-- Storage directives
%ODBCIN                        -- ODBC input mode
%ODBCOUT                       -- ODBC output mode
```

### Index and Storage Extensions
```sql
-- IRIS bitmap indices
CREATE BITMAP INDEX idx_name ON table_name (column_name)

-- Functional indices
CREATE INDEX idx_name ON table_name (UPPER(column_name))
```

## Implementation Priority Matrix

### Phase 1: Critical Features (Immediate)
| Feature | Priority | Effort | Impact |
|---------|----------|--------|---------|
| System Functions | HIGH | Medium | High |
| Data Type Mapping | HIGH | High | High |
| SQL Extensions | HIGH | Medium | Medium |
| Vector Functions | HIGH | Low | High |

### Phase 2: Important Features (Month 2)
| Feature | Priority | Effort | Impact |
|---------|----------|--------|---------|
| IRIS Functions | MEDIUM | Medium | Medium |
| Information Schema | MEDIUM | High | Medium |
| JSON Extensions | MEDIUM | Low | Low |

### Phase 3: Complete Parity (Month 3)
| Feature | Priority | Effort | Impact |
|---------|----------|--------|---------|
| ObjectScript Integration | LOW | High | Low |
| Performance Hints | LOW | Medium | Low |
| Index Extensions | LOW | Medium | Low |

## Implementation Architecture

### Enhanced Command Router
```python
class EnhancedIRISCommandRouter:
    """Extended command router for all IRIS constructs"""

    def __init__(self):
        self.ml_executor = IntegratedMLExecutor()
        self.system_function_translator = SystemFunctionTranslator()
        self.type_converter = IRISTypeConverter()
        self.sql_translator = IRISSQLTranslator()

    def route_sql(self, sql: str):
        # 1. Check for IntegratedML (already implemented)
        if self.ml_executor.is_ml_command(sql):
            return self.ml_executor.execute(sql)

        # 2. Check for system functions
        if self.has_system_functions(sql):
            sql = self.system_function_translator.translate(sql)

        # 3. Check for IRIS data types
        if self.has_iris_types(sql):
            sql = self.type_converter.convert_types(sql)

        # 4. Check for IRIS SQL extensions
        if self.has_iris_extensions(sql):
            sql = self.sql_translator.translate_extensions(sql)

        # 5. Execute via standard path
        return self.standard_executor.execute(sql)
```

### System Function Implementation
```python
class SystemFunctionTranslator:
    """Translate IRIS system functions to PostgreSQL equivalents"""

    def translate(self, sql: str) -> str:
        for iris_func, pg_equivalent in IRIS_SYSTEM_FUNCTIONS.items():
            sql = sql.replace(iris_func, pg_equivalent)
        return sql

    def create_custom_functions(self):
        """Create custom PostgreSQL functions for IRIS-specific features"""
        return {
            'iris_parallel_info': 'CREATE FUNCTION iris_parallel_info() RETURNS INTEGER...',
            'iris_query_stats': 'CREATE FUNCTION iris_query_stats() RETURNS TABLE...'
        }
```

## Testing Strategy

### Comprehensive Test Coverage
```python
# Test each category of IRIS constructs
def test_system_functions():
    """Test %SYSTEM.* function translation"""

def test_iris_data_types():
    """Test IRIS-specific data type handling"""

def test_sql_extensions():
    """Test TOP, hints, and other IRIS SQL extensions"""

def test_iris_functions():
    """Test IRIS-specific functions"""
```

## Conclusion

Beyond IntegratedML, IRIS has **50+ additional special constructs** that need implementation:

- **18 System Functions** requiring translation/implementation
- **12 Data Types** needing PostgreSQL mapping
- **8 SQL Extensions** for query syntax compatibility
- **15 IRIS Functions** for string, date, JSON operations
- **5 Information Schema** extensions for metadata access

**Implementation Strategy**: Prioritize high-impact features that provide immediate business value while building toward complete IRIS SQL compatibility through our PostgreSQL wire protocol.

**Result**: Full IRIS SQL feature set accessible via standard PostgreSQL drivers and tools.