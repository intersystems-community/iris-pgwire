# Vector Parameter Binding Implementation

> **Correction, 2026-10-17** — measured through pgwire with psycopg 3.3.6 against IRIS
> **2026.2.0.221.0com** (`iris-pgwire-db`), on both backends: embedded under `irispython`, and DBAPI
> with `intersystems_irispython` 5.3.2. Probes:
> `specs/051-unified-executor/spikes/probe_to_vector_binding.py` and `probe_to_vector_max_dims.py`.
>
> - **Binding into `TO_VECTOR(%s, DOUBLE, n)` works**, verified by value. INSERT, and ranking via
>   `ORDER BY VECTOR_COSINE(v, TO_VECTOR(%s, DOUBLE, n))`, give the locally computed order at 1,024 dims
>   (21.6 KB) and 4,096 dims (87.7 KB) on both backends.
> - **The maximum is 65,536 dimensions, not 188,962.** 65,537 fails with IRIS `-263` _"Failed to
>   convert input to logical vector value"_ on both backends. The limit is the dimension count, not
>   the byte count: 65,537 dims still fails when sent as 262 KB of short text. The 188,962 figure
>   below came from `SELECT 1 WHERE %s IS NOT NULL` with a Python list. psycopg sends a list as a
>   `float8[]` array, so that statement measured array transport, never reached `TO_VECTOR`, and does
>   not describe vector binding.
> - **"Fully functional on both paths" does not hold.** Measured gaps:
>   - **Embedded returns zero rows for any `SELECT` that projects a `VECTOR` column**, with no error.
>     IRIS raises `<OBJECT DISPATCH> *Invalid argument type` while fetching the row, and the
>     executor logged it as a warning and returned an empty result. _Fixed in the working tree the
>     same day, and not yet released: vectors now arrive as text, matching DBAPI. See
>     `tests/e2e/test_vector_projection.py`._
>   - **DBAPI does not translate pgvector `<=>`**: `ORDER BY v <=> %s` fails with `-25`. This is
>     tracked as feature 051.
>   - **Untyped `TO_VECTOR(%s)` fails against a `DOUBLE` column** with `-259`, because the optimizer
>     fills in `FLOAT`. **pgvector `<=>` fails against a `FLOAT` column**, because the optimizer
>     hard-codes `DOUBLE`. Neither path consults the column's element type.
>
> The tables and conclusion below are kept as originally written. Where they disagree with this note,
> this note is the measurement.

## Executive Summary

Successfully implemented full vector parameter binding support for the IRIS PostgreSQL wire protocol server, enabling pgvector-compatible queries with parameterized vector data across all supported dimensions (128D-1024D).

**Key Achievement**: Parameter binding provides **1,465× more capacity** than text literals for vector operations.

---

## Implementation Details

### 1. Vector Parameter Support

**Location**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/vector_optimizer.py`

#### Parameter Placeholder Detection

Modified cosine distance operator rewriting to detect and handle parameter placeholders:

```python
# Lines 372, 434 - Enhanced pattern matching
pattern = r"([\w\.]+|'[^']*'|\[[^\]]*\])\s*<=>\s*('[^']*'|\[[^\]]*\]|\?|%s|\$\d+)"
```

**Supported Parameter Formats**:

- `?` - Generic placeholder
- `%s` - Python DB-API format (psycopg)
- `$1`, `$2`, etc. - PostgreSQL numbered parameters

#### Automatic TO_VECTOR() Wrapping

When a parameter placeholder is detected on the right side of a pgvector operator, it's automatically wrapped:

```python
# Lines 377-386
if is_param_placeholder:
    result = f'VECTOR_COSINE({left}, TO_VECTOR({right}, DOUBLE))'
```

**Result**: Queries like `SELECT * FROM table WHERE vec <=> %s` automatically become `VECTOR_COSINE(vec, TO_VECTOR(%s, DOUBLE))` with proper IRIS vector conversion.

### 3. Batch Operations (Fast Path)

**Location**: `src/iris_pgwire/protocol.py:3334-3530`

Implemented a high-performance "Fast Path" for bulk DML operations (INSERT/UPDATE/DELETE). This optimization addresses the standard PostgreSQL client behavior (e.g., `psycopg3`) of sending `Sync` messages every few rows, which typically limits throughput.

**Key Features**:

- **Protocol-Level Buffering**: Intercepts `Execute` messages for DML statements without `RETURNING` clauses.
- **Synthetic Completion**: Immediately returns a synthetic `CommandComplete` to the client, keeping the network pipeline full.
- **Deferred Database Flush**: Buffers parameters and defers the actual database call until 500 rows are accumulated or a non-DML message is received.
- **Efficient Execution**: Uses IRIS `executemany()` for the buffered batch, significantly reducing per-row overhead.

**Performance**: Achieved throughput of **3,778 rows/sec** for 128D vectors, exceeding the sim project requirements.

---

## Recursive JSON Path Support

The bridge now supports recursive PostgreSQL JSON operators (`->` and `->>`), translating them to IRIS `JSON_VALUE` or `JSON_QUERY` with dot-notation paths. This enables deep nesting support for JSONB-style workflows.

**Example**:

- `data->'user'->'profile'->>'name'` → `JSON_VALUE(data, '$.user.profile.name')`
- `data->'items'->0->>'id'` → `JSON_VALUE(data, '$.items[0].id')`

---

## DDL Idempotency

Full support for `IF NOT EXISTS` in `CREATE TABLE` and `CREATE INDEX` statements.

**Implementation**:

- **CREATE TABLE**: Directly supported by IRIS.
- **CREATE INDEX**: Translated using a comment marker `/* IF_NOT_EXISTS */` since IRIS does not natively support `IF NOT EXISTS` for indexes. The execution layer detects this marker and handles duplicate object errors (SQLCODE -324) gracefully by logging a warning instead of failing.

---

## Performance Characteristics

### Maximum Vector Dimensions

Tested using binary search across both PGWire paths:

| Metric                     | Value                    | Notes                                                                                                                 |
| -------------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| **Maximum Dimensions**     | ~~188,962D~~ **65,536D** | Corrected 2026-10-17: a dimension limit, measured through `TO_VECTOR`; 188,962 was array transport, not a vector bind |
| **Binary Vector Size**     | 1.44 MB                  | 188,962 × 8 bytes per DOUBLE                                                                                          |
| **JSON Text Size**         | 3.47 MB                  | Same vector in text format                                                                                            |
| **Capacity Improvement**   | **1,465×**               | vs. text literal limit (129D)                                                                                         |
| **Bulk Insert Throughput** | **3,778 rows/sec**       | Feature 026 "Fast Path"                                                                                               |

**Test Method**: Binary search between 1,024D (known working) and 262,144D (fails)

**Verification Command** (replaced 2026-10-17). The original ran
`SELECT 1 WHERE %s IS NOT NULL` with a Python list, which psycopg sends as a `float8[]` array. That
never reaches `TO_VECTOR`, so it measured array transport, not vector binding. This version binds a
vector string through `TO_VECTOR` and checks the result by value:

```python
# Bind through TO_VECTOR and check by value. A scalar result is used because projecting a
# VECTOR column through the embedded backend currently returns zero rows (see the note above).
random.seed(42)
n = 65536  # measured maximum; 65537 fails with -263 on IRIS 2026.2.0.221.0com
q = [round(random.random(), 6) for _ in range(n)]
text = "[" + ",".join(repr(x) for x in q) + "]"

with psycopg.connect("host=localhost port=5432 user=_SYSTEM password=SYS dbname=USER") as conn:
    got = conn.execute(
        f"SELECT VECTOR_DOT_PRODUCT(TO_VECTOR(%s, DOUBLE, {n}), TO_VECTOR(%s, DOUBLE, {n}))",
        (text, text),
    ).fetchone()[0]
    assert abs(float(got) - sum(x * x for x in q)) <= 1e-6 * float(got)
```

The full sweep is `specs/051-unified-executor/spikes/probe_to_vector_max_dims.py`.

### Dimension Testing Results

All tested dimensions work identically on both PGWire paths. _(Measured as array transport, not through `TO_VECTOR`. Through `TO_VECTOR`, rows above 65,536D fail: see the correction at the top.)_

| Dimensions   | Binary Size | Status     | Both Paths Match |
| ------------ | ----------- | ---------- | ---------------- |
| 128D         | 1 KB        | ✅         | Yes              |
| 256D         | 2 KB        | ✅         | Yes              |
| 512D         | 4 KB        | ✅         | Yes              |
| 1,024D       | 8 KB        | ✅         | Yes              |
| 2,048D       | 16 KB       | ✅         | Yes              |
| 4,096D       | 32 KB       | ✅         | Yes              |
| 8,192D       | 64 KB       | ✅         | Yes              |
| 16,384D      | 128 KB      | ✅         | Yes              |
| 32,768D      | 256 KB      | ✅         | Yes              |
| 65,536D      | 512 KB      | ✅         | Yes              |
| 131,072D     | 1 MB        | ✅         | Yes              |
| **188,962D** | **1.44 MB** | **✅ MAX** | **Yes**          |
| 262,144D     | 2 MB        | ❌         | -                |

---

## Test Suite

### Multi-Dimensional Test Data

**Location**: `benchmarks/setup_multidim_vectors.py`

Created persistent test data across all database instances:

```sql
CREATE TABLE benchmark_vectors (
    id INT PRIMARY KEY,
    embedding_128 VECTOR(DOUBLE, 128),
    embedding_256 VECTOR(DOUBLE, 256),
    embedding_512 VECTOR(DOUBLE, 512),
    embedding_1024 VECTOR(DOUBLE, 1024)
);
```

**Data Characteristics**:

- 1,000 rows per dimension
- Consistent random seed (42) for reproducibility
- Shared across PostgreSQL, IRIS-main, IRIS-embedded

**Usage**:

```bash
python3 benchmarks/setup_multidim_vectors.py
```

### Validation Tests

**test_all_vector_sizes.py** - Quick validation across all dimensions:

```bash
python3 test_all_vector_sizes.py

# Expected output:
🎉 SUCCESS: All vector sizes work with parameter binding!
```

**test_bulk_insert.py** - Performance benchmark for the Fast Path:

```bash
IRIS_PGWIRE_PERF_MONITOR=false PYTHONPATH=src pytest tests/integration/test_bulk_insert.py::test_bulk_insert_performance_simple -s

# Expected output:
🚀 BATCHED EXECUTEMANY PERFORMANCE: 3778.23 rows/sec (5000 rows in 1.32s)
```

---

## Conclusion

_(Superseded in part, 2026-10-17: see the correction at the top. Embedded drops rows that project a `VECTOR` column, and DBAPI does not translate `<=>`.)_ Vector parameter binding and high-performance bulk operations are **fully functional** across all supported dimensions (128D-1024D) on both PGWire-DBAPI and PGWire-embedded paths.

**Production Ready**:

- ✅ Parameter placeholders (?, %s, $1)
- ✅ Binary parameter encoding
- ✅ Automatic TO_VECTOR() injection
- ~~✅ Up to 188,962D vectors (1.44 MB)~~ — **65,536D** through `TO_VECTOR` (corrected 2026-10-17)
- ✅ pgvector operator compatibility
- ✅ **executemany() Fast Path (3,700+ rows/sec)**
- ✅ **HNSW Index Support (PostgreSQL syntax)**
- ✅ **Recursive JSON Path Support**
- ✅ **DDL Idempotency (IF NOT EXISTS)**

**Impact**: Enables high-performance, pgvector-compatible applications to work seamlessly with IRIS through the PostgreSQL wire protocol, with **1,465× more vector capacity** and industry-standard bulk loading speeds.

---

**Documentation Updated**: 2026-01-15
**Implementation Phase**: Feature 026 (IRIS Bridge Gaps) - COMPLETE
