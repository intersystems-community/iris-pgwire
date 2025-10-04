# Contract: Vector Optimizer Syntax Preservation

**Requirement**: FR-001 - System MUST preserve vector literal formatting (brackets) when optimizing pgvector operators to IRIS vector functions

## Contract Definition

### Input
- PostgreSQL query with pgvector operators (`<=>`, `<->`, `<#>`)
- Vector literal in standard pgvector format: `'[0.1,0.2,0.3]'`

### Expected Output
- IRIS-compatible query with VECTOR_* functions
- Vector literal MUST retain brackets: `TO_VECTOR('[0.1,0.2,0.3]', FLOAT)`

### Failure Modes
- ❌ Brackets stripped: `TO_VECTOR('0.1,0.2,0.3', FLOAT)` → IRIS SQLCODE -400
- ❌ Malformed literal: `TO_VECTOR([0.1,0.2,0.3], FLOAT)` → Syntax error
- ❌ Missing TO_VECTOR wrapper: `'[0.1,0.2,0.3]'` → Type mismatch

## Test Cases

### Test 1: Cosine Distance Operator (`<=>`)
```python
def test_cosine_operator_preserves_brackets():
    """Cosine distance operator MUST preserve brackets"""
    sql = "SELECT id, embedding <=> '[0.1,0.2,0.3]' AS distance FROM vectors"

    optimized = optimizer.optimize_query(sql)

    # MUST contain TO_VECTOR with brackets
    assert "TO_VECTOR('[0.1,0.2,0.3]', FLOAT)" in optimized
    # MUST use VECTOR_COSINE function
    assert "VECTOR_COSINE(embedding, TO_VECTOR" in optimized
```

### Test 2: L2 Distance Operator (`<->`)
```python
def test_l2_operator_preserves_brackets():
    """L2 distance operator MUST preserve brackets"""
    sql = "SELECT id, embedding <-> '[1.0,2.0,3.0]' AS distance FROM vectors"

    optimized = optimizer.optimize_query(sql)

    assert "TO_VECTOR('[1.0,2.0,3.0]', FLOAT)" in optimized
    assert "VECTOR_L2(embedding, TO_VECTOR" in optimized
```

### Test 3: Inner Product Operator (`<#>`)
```python
def test_inner_product_operator_preserves_brackets():
    """Inner product operator MUST preserve brackets"""
    sql = "SELECT id, (embedding <#> '[0.5,0.5,0.5]') * -1 AS similarity FROM vectors"

    optimized = optimizer.optimize_query(sql)

    assert "TO_VECTOR('[0.5,0.5,0.5]', FLOAT)" in optimized
    assert "VECTOR_DOT_PRODUCT(embedding, TO_VECTOR" in optimized
```

### Test 4: Large Vector (1024 dimensions)
```python
def test_large_vector_preserves_brackets():
    """Large vectors MUST preserve brackets"""
    vector_1024d = "[" + ",".join(["0.1"] * 1024) + "]"
    sql = f"SELECT id, embedding <=> '{vector_1024d}' AS distance FROM vectors"

    optimized = optimizer.optimize_query(sql)

    # Brackets MUST be preserved
    assert f"TO_VECTOR('{vector_1024d}', FLOAT)" in optimized
    # MUST NOT have brackets stripped
    assert f"TO_VECTOR('{vector_1024d[1:-1]}', FLOAT)" not in optimized
```

### Test 5: ORDER BY with Vector Operator
```python
def test_order_by_preserves_brackets():
    """ORDER BY with vector operator MUST preserve brackets"""
    sql = "SELECT id FROM vectors ORDER BY embedding <=> '[0.1,0.2,0.3]' LIMIT 5"

    optimized = optimizer.optimize_query(sql)

    # Brackets in ORDER BY clause
    assert "TO_VECTOR('[0.1,0.2,0.3]', FLOAT)" in optimized
    # ORDER BY aliasing handled correctly
    assert "ORDER BY" in optimized
```

## Implementation Location

**Test File**: `tests/contract/test_vector_optimizer_syntax.py`
**Implementation**: `src/iris_pgwire/vector_optimizer.py`

## Validation

Run contract tests:
```bash
pytest tests/contract/test_vector_optimizer_syntax.py -v
```

Expected: All tests PASS after vector optimizer fix.
