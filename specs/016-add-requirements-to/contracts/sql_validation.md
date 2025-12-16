# Contract: SQL Syntax Validation

**Requirement**: FR-002 - System MUST validate optimized SQL syntax before sending to IRIS to prevent compiler crashes

## Contract Definition

### Input
- Optimized SQL query (output from vector optimizer)

### Expected Output
- Validation result with boolean `is_valid` flag
- Detection of common syntax errors:
  - Missing brackets in TO_VECTOR literals
  - Malformed VECTOR_* function calls
  - Invalid IRIS SQL constructs

### Failure Modes
- ❌ Invalid SQL sent to IRIS → SQLCODE -400 compiler crash
- ❌ False positives (valid SQL rejected) → Queries blocked incorrectly
- ❌ False negatives (invalid SQL passed) → Compiler errors not prevented

## Test Cases

### Test 1: Valid SQL Passes Validation
```python
def test_valid_sql_passes_validation():
    """Valid IRIS SQL MUST pass validation"""
    sql = "SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]', FLOAT)) AS distance FROM vectors"

    result = validator.validate_sql(sql)

    assert result.is_valid is True
    assert result.has_brackets_in_vector_literals is True
    assert result.error_message is None
```

### Test 2: Missing Brackets Fails Validation
```python
def test_missing_brackets_fails_validation():
    """SQL with missing brackets MUST fail validation"""
    # Malformed: brackets stripped from vector literal
    sql = "SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('0.1,0.2,0.3', FLOAT)) AS distance FROM vectors"

    result = validator.validate_sql(sql)

    assert result.is_valid is False
    assert result.has_brackets_in_vector_literals is False
    assert "brackets missing" in result.error_message.lower()
```

### Test 3: Malformed TO_VECTOR Fails Validation
```python
def test_malformed_to_vector_fails_validation():
    """Malformed TO_VECTOR syntax MUST fail validation"""
    # Missing FLOAT parameter
    sql = "SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]')) AS distance FROM vectors"

    result = validator.validate_sql(sql)

    assert result.is_valid is False
    assert "to_vector" in result.error_message.lower()
```

### Test 4: Multiple Vector Literals Validated
```python
def test_multiple_vector_literals_validated():
    """SQL with multiple vector literals MUST validate all"""
    sql = """
    SELECT id,
           VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]', FLOAT)) AS dist1,
           VECTOR_L2(embedding, TO_VECTOR('[1.0,2.0,3.0]', FLOAT)) AS dist2
    FROM vectors
    """

    result = validator.validate_sql(sql)

    assert result.is_valid is True
    assert result.vector_literal_count == 2
    assert result.has_brackets_in_vector_literals is True
```

### Test 5: Non-Vector SQL Passes (No Validation Needed)
```python
def test_non_vector_sql_passes():
    """SQL without vector functions MUST pass validation"""
    sql = "SELECT id, label FROM vectors WHERE id = 1"

    result = validator.validate_sql(sql)

    assert result.is_valid is True
    assert result.vector_literal_count == 0
    # Validation skipped for non-vector queries
    assert result.validation_applied is False
```

## Validation Rules

1. **Bracket Detection**: Scan for `TO_VECTOR('...')` patterns
   - MUST find `[...]` inside quotes
   - MUST NOT find `0.1,0.2,...` without brackets

2. **Function Signature**: Validate `TO_VECTOR(literal, FLOAT)` syntax
   - MUST have 2 parameters
   - Second parameter MUST be `FLOAT` or `DOUBLE`

3. **Vector Function Usage**: Validate `VECTOR_*` function calls
   - `VECTOR_COSINE(column, TO_VECTOR(...))`
   - `VECTOR_L2(column, TO_VECTOR(...))`
   - `VECTOR_DOT_PRODUCT(column, TO_VECTOR(...))`

## Implementation Location

**Test File**: `tests/contract/test_vector_optimizer_validation.py`
**Implementation**: `src/iris_pgwire/vector_optimizer.py` (new `validate_sql()` method)

## Validation

Run contract tests:
```bash
pytest tests/contract/test_vector_optimizer_validation.py -v
```

Expected: All tests PASS after validation layer implemented.
