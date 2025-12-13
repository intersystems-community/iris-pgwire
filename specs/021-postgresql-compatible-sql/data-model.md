# Data Model: PostgreSQL-Compatible SQL Normalization

**Feature**: 021-postgresql-compatible-sql
**Date**: 2025-10-08

## Entity Definitions

### 1. SQL Query

**Description**: Complete SQL statement from PostgreSQL client requiring normalization before IRIS execution.

**Attributes**:
- `original_sql` (string): Raw SQL from PostgreSQL client
- `normalized_sql` (string): IRIS-compatible SQL after normalization
- `execution_path` (enum): "direct" | "vector" | "external"
- `normalization_time_ms` (float): Time spent in normalization layer
- `identifier_count` (int): Number of identifiers processed
- `date_literal_count` (int): Number of DATE literals translated

**States**:
- `Received`: Original SQL from client
- `Parsed`: Identifiers and DATE literals extracted
- `Normalized`: Identifiers uppercased, DATEs translated
- `Executed`: Sent to IRIS for execution

**Validation Rules**:
- `original_sql` MUST NOT be empty
- `normalization_time_ms` MUST be < 5ms for 50 identifiers (constitutional requirement)
- `execution_path` MUST be one of: "direct", "vector", "external"

**Relationships**:
- Contains multiple `Identifier` entities
- Contains zero or more `DATE Literal` entities
- Associated with one `Execution Context`

**Example**:
```python
SQLQuery(
    original_sql="INSERT INTO Patients (PatientID, FirstName, LastName, DateOfBirth) VALUES (1, 'John', 'Smith', '1985-03-15')",
    normalized_sql="INSERT INTO PATIENTS (PATIENTID, FIRSTNAME, LASTNAME, DATEOFBIRTH) VALUES (1, 'John', 'Smith', TO_DATE('1985-03-15', 'YYYY-MM-DD'))",
    execution_path="direct",
    normalization_time_ms=2.3,
    identifier_count=5,
    date_literal_count=1
)
```

---

### 2. Identifier

**Description**: Table name, column name, or alias in SQL query that may require case normalization.

**Attributes**:
- `text` (string): Identifier as it appears in SQL
- `normalized_text` (string): Identifier after normalization
- `is_quoted` (boolean): True if identifier is delimited with double quotes
- `identifier_type` (enum): "table" | "column" | "alias" | "schema"
- `position_in_sql` (int): Character offset in original SQL
- `clause_type` (enum): "SELECT" | "FROM" | "WHERE" | "JOIN" | "INSERT" | "UPDATE" | etc.

**States**:
- `Detected`: Identifier found in SQL via regex
- `Classified`: Determined if quoted or unquoted
- `Normalized`: Case transformation applied (or preserved)

**Normalization Rules**:
1. **Unquoted Identifier**: Convert to UPPERCASE
   - Input: `FirstName` → Output: `FIRSTNAME`
   - Input: `Patients` → Output: `PATIENTS`

2. **Quoted Identifier**: Preserve exact case
   - Input: `"FirstName"` → Output: `"FirstName"`
   - Input: `"camelCase"` → Output: `"camelCase"`

3. **Schema-Qualified**: Normalize each part separately
   - Input: `myschema.mytable` → Output: `MYSCHEMA.MYTABLE`
   - Input: `"mySchema".mytable` → Output: `"mySchema".MYTABLE`

**Example**:
```python
# Unquoted identifier
Identifier(
    text="FirstName",
    normalized_text="FIRSTNAME",
    is_quoted=False,
    identifier_type="column",
    position_in_sql=35,
    clause_type="INSERT"
)

# Quoted identifier (preserved)
Identifier(
    text='"FirstName"',
    normalized_text='"FirstName"',
    is_quoted=True,
    identifier_type="column",
    position_in_sql=35,
    clause_type="INSERT"
)
```

---

### 3. DATE Literal

**Description**: String literal in ISO-8601 format `'YYYY-MM-DD'` requiring translation to IRIS TO_DATE() function.

**Attributes**:
- `original_literal` (string): DATE literal as it appears in SQL (e.g., `'1985-03-15'`)
- `translated_literal` (string): IRIS-compatible TO_DATE() expression
- `year` (int): Extracted year value (validation)
- `month` (int): Extracted month value (validation: 1-12)
- `day` (int): Extracted day value (validation: 1-31)
- `position_in_sql` (int): Character offset in original SQL
- `clause_type` (enum): "INSERT" | "UPDATE" | "WHERE" | "SELECT"

**States**:
- `Detected`: Pattern `'YYYY-MM-DD'` found in SQL
- `Validated`: Date components parsed and validated
- `Translated`: Wrapped in TO_DATE() function

**Translation Rule**:
```python
# Pattern: 'YYYY-MM-DD'
original: "'1985-03-15'"
translated: "TO_DATE('1985-03-15', 'YYYY-MM-DD')"
```

**Validation Rules**:
- `year` MUST be 1000-9999 (4 digits)
- `month` MUST be 01-12
- `day` MUST be 01-31 (basic validation, not calendar-aware)
- Pattern MUST be exactly `'YYYY-MM-DD'` (no extra characters)

**False Positive Prevention**:
- NOT in comments: `-- '2024-01-01'`
- NOT in partial strings: `'Born 1985-03-15 in...'`
- NOT with extra characters: `'1985-03-15-extra'`

**Example**:
```python
DATELiteral(
    original_literal="'1985-03-15'",
    translated_literal="TO_DATE('1985-03-15', 'YYYY-MM-DD')",
    year=1985,
    month=3,
    day=15,
    position_in_sql=89,
    clause_type="INSERT"
)
```

---

### 4. Execution Context

**Description**: State tracking which execution path is being used for query normalization.

**Attributes**:
- `path_type` (enum): "direct" | "vector" | "external"
- `session_id` (string): Client session identifier
- `performance_tracker` (PerformanceTracker): Constitutional SLA monitoring
- `normalization_enabled` (boolean): Flag to disable normalization for testing

**Path Descriptions**:

1. **Direct Execution** (`path_type="direct"`):
   - Function: `iris_executor.py::_execute_embedded_async()`
   - Flow: Normalize SQL → iris.sql.exec() → Results
   - Use Case: Simple queries, DDL, DML

2. **Vector-Optimized** (`path_type="vector"`):
   - Function: `vector_optimizer.py::optimize_vector_query()`
   - Flow: Normalize SQL → Detect vectors → Convert params to literals → IRIS execution
   - Use Case: Vector similarity queries with ORDER BY

3. **External Connection** (`path_type="external"`):
   - Function: `iris_executor.py::_execute_external_async()`
   - Flow: Normalize SQL → External DBAPI cursor.execute() → Results
   - Use Case: Connection pooling, external deployments

**Validation Rules**:
- `path_type` MUST be one of the three defined paths
- `performance_tracker` MUST validate < 5ms normalization time
- Normalization MUST occur BEFORE vector optimization (FR-012)

**Example**:
```python
ExecutionContext(
    path_type="vector",
    session_id="session_abc123",
    performance_tracker=PerformanceTracker(...),
    normalization_enabled=True
)
```

---

## State Transitions

### SQL Query Lifecycle

```
┌─────────────┐
│  Received   │  Original SQL from PostgreSQL client
│ (original)  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Parsed    │  Identifiers and DATE literals extracted
│ (analyzing) │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Normalized  │  Identifiers uppercased, DATEs translated
│  (ready)    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Executed   │  Sent to IRIS for execution
│  (complete) │
└─────────────┘
```

### Identifier Processing

```
┌─────────────┐
│  Detected   │  Found via regex pattern
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Classified  │  Quoted vs unquoted determination
└──────┬──────┘
       │
       ├─ Quoted → Preserve case
       │
       └─ Unquoted → Convert to UPPERCASE
       │
       ▼
┌─────────────┐
│ Normalized  │  Case transformation complete
└─────────────┘
```

### DATE Literal Processing

```
┌─────────────┐
│  Detected   │  Pattern 'YYYY-MM-DD' found
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Validated   │  Date components parsed and validated
└──────┬──────┘
       │
       ├─ Valid → Translate to TO_DATE()
       │
       └─ Invalid → Log warning, skip translation
       │
       ▼
┌─────────────┐
│ Translated  │  Wrapped in TO_DATE() function
└─────────────┘
```

---

## Relationships

```
SQLQuery (1) ──┬─ contains ──> (N) Identifier
               │
               ├─ contains ──> (N) DATELiteral
               │
               └─ associated ──> (1) ExecutionContext


ExecutionContext (1) ──> (1) PerformanceTracker
```

**Cardinality Rules**:
- One `SQLQuery` contains 0-N `Identifier` entities
- One `SQLQuery` contains 0-N `DATELiteral` entities
- One `SQLQuery` associated with exactly one `ExecutionContext`
- One `ExecutionContext` associated with exactly one `PerformanceTracker`

---

## Performance Metrics

**Constitutional Requirements** (from data model perspective):

1. **Normalization Time**:
   - Target: < 5ms for 50 identifier references
   - Measured: `SQLQuery.normalization_time_ms`
   - Violation: Log warning via `PerformanceTracker`

2. **Total Execution Time**:
   - Target: < 10% increase vs baseline (no normalization)
   - Measured: Comparison between normalized and non-normalized execution
   - Validation: Performance benchmarks in test suite

3. **Translation SLA**:
   - Target: 5ms (constitutional Principle VI)
   - Scope: Entire normalization process (identifiers + DATEs)
   - Tracking: Via existing `performance_monitor` infrastructure

---

## Data Integrity Constraints

1. **Identifier Normalization Integrity**:
   - MUST preserve SQL semantics (same table/column references)
   - MUST NOT alter quoted identifier case
   - MUST convert all unquoted identifiers consistently

2. **DATE Literal Translation Integrity**:
   - MUST preserve date values exactly
   - MUST NOT translate non-DATE strings
   - MUST handle leap years correctly (via IRIS TO_DATE)

3. **Performance Constraint**:
   - Normalization MUST complete < 5ms for 50 identifiers
   - Total execution time MUST be < 110% of baseline

---

## Example End-to-End Data Flow

**Input SQL** (PostgreSQL client):
```sql
INSERT INTO Patients (PatientID, FirstName, LastName, DateOfBirth, Gender)
VALUES (1, 'John', 'Smith', '1985-03-15', 'M')
```

**Parsed Entities**:
```python
# SQLQuery
original_sql = "INSERT INTO Patients ..."
execution_path = "direct"

# Identifiers (unquoted → UPPERCASE)
Identifier("Patients" → "PATIENTS")
Identifier("PatientID" → "PATIENTID")
Identifier("FirstName" → "FIRSTNAME")
Identifier("LastName" → "LASTNAME")
Identifier("DateOfBirth" → "DATEOFBIRTH")
Identifier("Gender" → "GENDER")

# DATE Literal
DATELiteral("'1985-03-15'" → "TO_DATE('1985-03-15', 'YYYY-MM-DD')")
```

**Normalized SQL** (sent to IRIS):
```sql
INSERT INTO PATIENTS (PATIENTID, FIRSTNAME, LASTNAME, DATEOFBIRTH, GENDER)
VALUES (1, 'John', 'Smith', TO_DATE('1985-03-15', 'YYYY-MM-DD'), 'M')
```

**Performance Tracking**:
```python
SQLQuery.normalization_time_ms = 2.3  # < 5ms ✅
SQLQuery.identifier_count = 6
SQLQuery.date_literal_count = 1
```

---

**Data Model Status**: ✅ **COMPLETE**
**Entities Defined**: 4 (SQLQuery, Identifier, DATELiteral, ExecutionContext)
**State Transitions**: Fully specified
**Relationships**: Fully mapped
**Validation Rules**: All constraints documented
