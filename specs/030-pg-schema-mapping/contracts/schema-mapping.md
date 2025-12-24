# Contract: Schema Mapping Functions

**Feature**: 030-pg-schema-mapping
**Type**: Internal API (Python functions)

## translate_input_schema(sql: str) -> str

Transforms incoming SQL queries to replace PostgreSQL schema references with IRIS equivalents.

### Behavior

| Input Pattern | Output Pattern |
|---------------|----------------|
| `table_schema = 'public'` | `table_schema = 'SQLUser'` |
| `table_schema = 'PUBLIC'` | `table_schema = 'SQLUser'` |
| `FROM public.tablename` | `FROM SQLUser.tablename` |
| `table_schema = 'SQLUser'` | `table_schema = 'SQLUser'` (unchanged) |
| `table_schema = '%SYS'` | `table_schema = '%SYS'` (unchanged) |

### Contract Tests

```python
def test_where_clause_public():
    sql = "SELECT * FROM information_schema.tables WHERE table_schema = 'public'"
    result = translate_input_schema(sql)
    assert "table_schema = 'SQLUser'" in result

def test_schema_qualified_name():
    sql = "SELECT * FROM public.users"
    result = translate_input_schema(sql)
    assert "SQLUser.users" in result

def test_case_insensitive():
    sql = "WHERE table_schema = 'PUBLIC'"
    result = translate_input_schema(sql)
    assert "SQLUser" in result

def test_sqluser_unchanged():
    sql = "WHERE table_schema = 'SQLUser'"
    result = translate_input_schema(sql)
    assert result.count("SQLUser") == 1  # Not double-mapped

def test_system_schema_unchanged():
    sql = "WHERE table_schema = '%SYS'"
    result = translate_input_schema(sql)
    assert "%SYS" in result
```

---

## translate_output_schema(rows: list, columns: list) -> list

Transforms result sets to replace IRIS schema names with PostgreSQL equivalents in schema-related columns.

### Target Columns

Only these column names trigger translation:
- `table_schema`
- `schema_name`
- `nspname` (PostgreSQL system catalog name)

### Behavior

| Column | Input Value | Output Value |
|--------|-------------|--------------|
| `table_schema` | `SQLUser` | `public` |
| `table_schema` | `%SYS` | `%SYS` (unchanged) |
| `table_name` | `SQLUser` | `SQLUser` (not a schema column) |

### Contract Tests

```python
def test_table_schema_translation():
    rows = [("SQLUser", "users", "BASE TABLE")]
    columns = ["table_schema", "table_name", "table_type"]
    result = translate_output_schema(rows, columns)
    assert result[0][0] == "public"
    assert result[0][1] == "users"  # Unchanged

def test_system_schema_unchanged():
    rows = [("%SYS", "Config", "BASE TABLE")]
    columns = ["table_schema", "table_name", "table_type"]
    result = translate_output_schema(rows, columns)
    assert result[0][0] == "%SYS"

def test_non_schema_column_unchanged():
    rows = [("SQLUser",)]  # Value happens to match, but column isn't schema-related
    columns = ["some_column"]
    result = translate_output_schema(rows, columns)
    assert result[0][0] == "SQLUser"  # Not translated
```

---

## Performance Contract

- **NFR-001**: Each translation call MUST complete in < 1ms
- Measured via: `time.perf_counter()` around translation calls
- Test: Process 1000 typical queries, assert p99 < 1ms
